"""The strategy engine: evaluates rule-sets against point-in-time features.

One code path serves both the backtest gate and the nightly paper run — the
simulator IS the evaluator replayed over history, so the backtest cannot
behave differently from the live engine except through data availability.

Every order carries which rule fired and the metric values behind it. "Why
did you buy this" must always have an answer, forever.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from app.strategies.features import FeatureService
from app.strategies.rules import (
    AllOf,
    AnyOf,
    Compare,
    HeldDays,
    Percentile,
    StrategyRules,
    features_used,
)

logger = logging.getLogger(__name__)

OPS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
}


@dataclass
class Holding:
    ticker: str
    opened: date
    quantity: float
    avg_cost: float
    rule_fired: str
    metric_values: dict


@dataclass
class Order:
    ticker: str
    side: str  # buy | sell
    rule_fired: str
    metric_values: dict
    signal_date: date


@dataclass
class Evaluation:
    orders: list[Order]
    target: list[str]
    candidates_considered: int
    passed_entry: int


def _percentile_rank(values: dict[str, float], ticker: str) -> float | None:
    value = values.get(ticker)
    if value is None or len(values) < 2:
        return None
    below = sum(1 for v in values.values() if v < value)
    return below / (len(values) - 1) * 100.0


def _passes(
    node,
    ticker: str,
    features: dict[str, dict[str, float]],
    percentiles: dict[str, dict[str, float]],
    held_days: int | None,
) -> tuple[bool, str | None]:
    """Evaluate a condition tree. Returns (passed, failing_or_firing_id).

    A feature that is missing FAILS the condition rather than passing it: a
    rule that cannot be checked has not been satisfied. For exits the id
    returned is the condition that FIRED, so it can be recorded on the order.
    """
    if isinstance(node, Compare):
        value = features.get(ticker, {}).get(node.feature)
        if value is None:
            return False, node.id
        return OPS[node.op](value, node.value), node.id
    if isinstance(node, Percentile):
        rank = percentiles.get(node.feature, {}).get(ticker)
        if rank is None:
            return False, node.id
        return OPS[node.op](rank, node.value), node.id
    if isinstance(node, HeldDays):
        if held_days is None:
            return False, node.id
        return OPS[node.op](held_days, node.value), node.id
    if isinstance(node, AllOf):
        for child in node.conditions:
            ok, why = _passes(child, ticker, features, percentiles, held_days)
            if not ok:
                return False, why
        return True, None
    if isinstance(node, AnyOf):
        for child in node.conditions:
            ok, why = _passes(child, ticker, features, percentiles, held_days)
            if ok:
                return True, why
        return False, None
    raise TypeError(f"unknown condition node {type(node)}")


def _percentile_features(node, out: set[str]) -> None:
    if isinstance(node, Percentile):
        out.add(node.feature)
    elif isinstance(node, (AllOf, AnyOf)):
        for child in node.conditions:
            _percentile_features(child, out)


def evaluate(
    service: FeatureService,
    rules: StrategyRules,
    as_of: date,
    holdings: dict[str, Holding],
) -> Evaluation:
    """One rebalance decision: who to sell, who to buy, and why."""
    needed = features_used(rules)
    if rules.universe.min_market_cap or rules.universe.max_market_cap:
        needed = needed | {"price:market_cap"}

    # ---- universe filter ------------------------------------------------
    candidates: list[str] = []
    for ticker, security in service.securities.items():
        if not security.is_active:
            continue
        if rules.universe.sectors and security.sector not in rules.universe.sectors:
            continue
        if rules.universe.exclude_sectors and security.sector in rules.universe.exclude_sectors:
            continue
        if rules.universe.quote_currencies and security.quote_currency not in rules.universe.quote_currencies:
            continue
        candidates.append(ticker)

    features = service.features_for(as_of, needed, candidates)

    if rules.universe.min_market_cap or rules.universe.max_market_cap:
        lo = rules.universe.min_market_cap or 0.0
        hi = rules.universe.max_market_cap or float("inf")
        candidates = [
            t for t in candidates
            if lo <= features.get(t, {}).get("price:market_cap", -1.0) <= hi
        ]

    # ---- cross-sectional percentiles, within the filtered universe ------
    wanted_percentiles: set[str] = set()
    _percentile_features(rules.entry, wanted_percentiles)
    if rules.exit:
        _percentile_features(rules.exit, wanted_percentiles)
    percentiles: dict[str, dict[str, float]] = {}
    for feature in wanted_percentiles:
        values = {t: features[t][feature] for t in candidates
                  if feature in features.get(t, {})}
        percentiles[feature] = {
            t: rank for t in values
            if (rank := _percentile_rank(values, t)) is not None
        }

    # ---- entry ----------------------------------------------------------
    passed = [t for t in candidates
              if _passes(rules.entry, t, features, percentiles, None)[0]]

    # ---- rank -----------------------------------------------------------
    def rank_key(ticker: str):
        total = 0.0
        for component in rules.rank.components:
            value = features.get(ticker, {}).get(component.feature)
            if value is None:
                return None
            total += -value if component.direction == "desc" else value
        return total

    if rules.rank.kind == "rank_sum":
        # Ordinal ranks per component, summed - the Magic Formula shape.
        totals: dict[str, float] = {}
        for component in rules.rank.components:
            values = [(features[t][component.feature], t) for t in passed
                      if component.feature in features.get(t, {})]
            values.sort(reverse=(component.direction == "desc"))
            for position, (_, ticker) in enumerate(values, 1):
                totals[ticker] = totals.get(ticker, 0.0) + position
        complete = {t for t in passed
                    if all(c.feature in features.get(t, {}) for c in rules.rank.components)}
        ranked = sorted((t for t in complete), key=lambda t: totals[t])
    else:
        keyed = [(rank_key(t), t) for t in passed]
        ranked = [t for k, t in sorted((pair for pair in keyed if pair[0] is not None))]

    rank_label = "+".join(c.feature for c in rules.rank.components)

    # ---- diff against holdings -----------------------------------------
    orders: list[Order] = []
    metric_of = lambda t: {f: round(v, 6) for f, v in features.get(t, {}).items()}

    if rules.rebalance.mode == "reconstitute":
        target = ranked[: rules.rank.top_n]
        for ticker, holding in holdings.items():
            if ticker not in target:
                orders.append(Order(ticker, "sell", f"dropped_out_of_ranking({rank_label})",
                                    metric_of(ticker), as_of))
        for position, ticker in enumerate(target, 1):
            if ticker not in holdings:
                orders.append(Order(ticker, "buy",
                                    f"rank_{position}_of_{rules.rank.top_n}({rank_label})",
                                    metric_of(ticker), as_of))
    else:
        target = list(holdings)
        for ticker, holding in holdings.items():
            held = (as_of - holding.opened).days
            fired, which = _passes(rules.exit, ticker, features, percentiles, held)
            if fired:
                orders.append(Order(ticker, "sell", f"exit:{which}", metric_of(ticker), as_of))
                target.remove(ticker)
        slots = rules.sizing.max_positions - len(target)
        for ticker in ranked:
            if slots <= 0:
                break
            if ticker in holdings or ticker in target:
                continue
            target.append(ticker)
            orders.append(Order(ticker, "buy", f"entry+rank({rank_label})",
                                metric_of(ticker), as_of))
            slots -= 1

    return Evaluation(
        orders=orders,
        target=target,
        candidates_considered=len(candidates),
        passed_entry=len(passed),
    )
