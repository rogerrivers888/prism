"""The rule vocabulary: what a strategy is allowed to say.

Deliberately a small declarative language, not code. A strategy is data —
validated at registration, hashed for the novelty gate, executed by an
interpreter that logs which rule fired. Arbitrary code could do more, and
could also do anything, which is exactly the problem: a rule-set you cannot
diff, hash or explain is a rule-set you cannot hold to account.

Features are namespaced strings resolved by the feature builder:

  lens:quality            relative lens score (0-100), most recent as-of date
  lens_abs:value          absolute lens score
  metric:price_to_book    a derived metric, point-in-time
  price:return_12_1       price-derived: returns, moving averages, 52w range
  special:piotroski_f     composites computed by the feature builder
  special:dispersion      lens disagreement, from the stored dispersion rows
  sector:cycle_median_delta   the ticker's sector-level feature

Every condition carries an ``id`` so an order can record exactly which rule
fired — "why did you buy this" must always have an answer.
"""

import hashlib
import json
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

FEATURE_NAMESPACES = ("lens", "lens_abs", "metric", "price", "special", "sector")

LENS_NAMES = {"trend", "growth", "quality", "value", "momentum", "cycle"}

PRICE_FEATURES = {
    "price",
    "return_1m",
    "return_3m",
    "return_6m",
    "return_12m",
    # Jegadeesh-Titman convention: twelve months back to one month back,
    # skipping the most recent month's reversal.
    "return_12_1",
    "ma50",
    "ma150",
    "ma200",
    "price_vs_ma50",
    "price_vs_ma150",
    "price_vs_ma200",
    "ma50_vs_ma200",
    "ma200_slope_3m",
    "pct_off_52w_high",
    "pct_above_52w_low",
    # Percentile of return_12m within the filtered universe: an IBD-style
    # relative strength rank.
    "rs_rank",
    "market_cap",
}

SPECIAL_FEATURES = {"piotroski_f", "dispersion", "earnings_yield_ebit", "roc_greenblatt"}

SECTOR_FEATURES = {"cycle_median_delta"}


def validate_feature(name: str) -> str:
    if ":" not in name:
        raise ValueError(f"feature '{name}' has no namespace")
    namespace, _, rest = name.partition(":")
    if namespace not in FEATURE_NAMESPACES:
        raise ValueError(f"unknown feature namespace '{namespace}'")
    if namespace in ("lens", "lens_abs") and rest not in LENS_NAMES:
        raise ValueError(f"unknown lens '{rest}'")
    if namespace == "price" and rest not in PRICE_FEATURES:
        raise ValueError(f"unknown price feature '{rest}'")
    if namespace == "special" and rest not in SPECIAL_FEATURES:
        raise ValueError(f"unknown special feature '{rest}'")
    if namespace == "sector" and rest not in SECTOR_FEATURES:
        raise ValueError(f"unknown sector feature '{rest}'")
    return name


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid")


Op = Literal["gt", "gte", "lt", "lte", "eq"]


class Compare(_Node):
    """feature <op> value. The workhorse."""

    kind: Literal["compare"] = "compare"
    id: str
    feature: str
    op: Op
    value: float

    _check = field_validator("feature")(validate_feature)


class Percentile(_Node):
    """feature's rank within the filtered universe, 0-100.

    'Cheapest fifth' is a percentile statement, not a threshold — the right
    cutoff for price-to-book in 2010 is not the right one in 2026.
    """

    kind: Literal["percentile"] = "percentile"
    id: str
    feature: str
    op: Op
    value: float = Field(ge=0, le=100)

    _check = field_validator("feature")(validate_feature)


class HeldDays(_Node):
    """Exit-side only: how long the position has been open."""

    kind: Literal["held_days"] = "held_days"
    id: str
    op: Op
    value: int = Field(gt=0)


class AllOf(_Node):
    kind: Literal["all"] = "all"
    conditions: list["Condition"] = Field(min_length=1)


class AnyOf(_Node):
    kind: Literal["any"] = "any"
    conditions: list["Condition"] = Field(min_length=1)


Condition = Annotated[
    Union[Compare, Percentile, HeldDays, AllOf, AnyOf], Field(discriminator="kind")
]

AllOf.model_rebuild()
AnyOf.model_rebuild()


class RankComponent(_Node):
    feature: str
    direction: Literal["asc", "desc"]

    _check = field_validator("feature")(validate_feature)


class Rank(_Node):
    """Order the candidates that passed entry, take the top N.

    rank_sum adds ordinal ranks across components — the Magic Formula shape,
    where a middling rank on both measures beats a top rank on one.
    """

    kind: Literal["single", "rank_sum"] = "single"
    components: list[RankComponent] = Field(min_length=1, max_length=4)
    top_n: int = Field(gt=0, le=100)


class Universe(_Node):
    sectors: list[str] | None = None
    exclude_sectors: list[str] | None = None
    min_market_cap: float | None = None
    max_market_cap: float | None = None
    quote_currencies: list[str] | None = None


class Rebalance(_Node):
    frequency: Literal["weekly", "monthly", "quarterly"]
    # reconstitute: the portfolio IS the rank output each time; dropping out
    #   of the ranking is the exit.
    # hold_until_exit: positions persist until an exit condition fires; new
    #   entries fill the freed slots.
    mode: Literal["reconstitute", "hold_until_exit"]


class Sizing(_Node):
    method: Literal["equal_weight"] = "equal_weight"
    max_positions: int = Field(gt=0, le=100)


class StrategyRules(_Node):
    """The whole executable definition."""

    universe: Universe
    entry: Condition
    rank: Rank
    exit: Condition | None = None
    rebalance: Rebalance
    sizing: Sizing

    @field_validator("exit")
    @classmethod
    def exit_required_for_hold_mode(cls, v, info):
        return v


def parse_rules(raw: dict) -> StrategyRules:
    rules = StrategyRules.model_validate(raw)
    if rules.rebalance.mode == "hold_until_exit" and rules.exit is None:
        raise ValueError("hold_until_exit requires exit conditions")
    return rules


def rule_signature(raw: dict) -> str:
    """Canonical hash of a rule-set. Two strategies with the same signature
    are the same strategy, whatever they are called."""
    canonical = json.dumps(
        StrategyRules.model_validate(raw).model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def features_used(rules: StrategyRules) -> set[str]:
    """Every feature a rule-set references, so the engine computes only what
    is needed."""
    out: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, (Compare, Percentile)):
            out.add(node.feature)
        elif isinstance(node, (AllOf, AnyOf)):
            for child in node.conditions:
                walk(child)

    walk(rules.entry)
    if rules.exit:
        walk(rules.exit)
    for component in rules.rank.components:
        out.add(component.feature)
    return out


def describe(rules: StrategyRules) -> list[str]:
    """The rule-set in plain English, generated from the same object the
    engine executes so the description cannot drift from the behaviour."""
    lines: list[str] = []
    u = rules.universe
    scope = []
    if u.sectors:
        scope.append(f"only {', '.join(u.sectors)}")
    if u.exclude_sectors:
        scope.append(f"excluding {', '.join(u.exclude_sectors)}")
    if u.min_market_cap:
        scope.append(f"market value at least £{u.min_market_cap / 1e9:.0f}bn"
                     if u.min_market_cap >= 1e9 else
                     f"market value at least £{u.min_market_cap / 1e6:.0f}m")
    if u.quote_currencies:
        scope.append(f"quoted in {', '.join(u.quote_currencies)}")
    lines.append("Universe: " + ("; ".join(scope) if scope else "everything Prism covers") + ".")

    def cond_text(node, depth=0) -> str:
        pad = "  " * depth
        if isinstance(node, Compare):
            return f"{pad}{node.feature} {OP_WORDS[node.op]} {node.value:g}"
        if isinstance(node, Percentile):
            return f"{pad}{node.feature} in the {ORDER[node.op]} {node.value:g}% of the universe"
        if isinstance(node, HeldDays):
            return f"{pad}held for {OP_WORDS[node.op]} {node.value} days"
        joiner = " AND " if isinstance(node, AllOf) else " OR "
        return joiner.join(cond_text(c, 0) for c in node.conditions)

    lines.append("Buy when: " + cond_text(rules.entry) + ".")
    parts = [f"{c.feature} ({'highest' if c.direction == 'desc' else 'lowest'} first)"
             for c in rules.rank.components]
    how = "combined rank of " + " + ".join(parts) if rules.rank.kind == "rank_sum" else parts[0]
    lines.append(f"Then keep the top {rules.rank.top_n} by {how}.")
    if rules.exit:
        lines.append("Sell when: " + cond_text(rules.exit) + ".")
    if rules.rebalance.mode == "reconstitute":
        lines.append(f"Rebuild the whole portfolio {rules.rebalance.frequency}; "
                     "falling out of the ranking is the exit.")
    else:
        lines.append(f"Check {rules.rebalance.frequency}; hold each position until an exit rule fires.")
    lines.append(f"Positions: equal weight, at most {rules.sizing.max_positions}.")
    return lines


OP_WORDS = {"gt": "above", "gte": "at least", "lt": "below", "lte": "at most", "eq": "exactly"}
ORDER = {"lte": "bottom", "lt": "bottom", "gte": "top", "gt": "top", "eq": "exact"}
