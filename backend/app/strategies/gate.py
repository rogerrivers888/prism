"""The backtest gate: what a strategy must survive before it can trade paper.

Runs automatically on registration, over all available history. Reuses the
existing harness's honesty machinery — full costs, bootstrap bands, a drift
control — and adds the one thing a strategy machine specifically needs:
deflation across the family tree.

On the choice of control. The strategy does two things: it picks stocks and it
times entries. A control drawn from the SAME ticker at random dates would
isolate timing while granting selection for free — and for Piotroski or the
Magic Formula, selection is the entire claim. So the control draws random
same-length holds on random tickers from the strategy's own filtered universe,
over the same calendar windows. If picking by F-score cannot beat picking at
random from the same pond over the same months, there is nothing there.
"""

import logging
import math
import random
import statistics
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest import bootstrap_returns
from app.strategies.features import FeatureService
from app.strategies.registry import Strategy, StrategyBacktest
from app.strategies.rules import StrategyRules, features_used, parse_rules
from app.strategies.simulator import (
    CostModel,
    SimResult,
    simulate,
    summarise,
)

logger = logging.getLogger(__name__)

CONTROL_SAMPLES_PER_TRADE = 20

# Euler-Mascheroni, for the expected-maximum approximation.
EULER = 0.5772156649


def _inverse_normal_cdf(p: float) -> float:
    """Acklam's inverse normal CDF — far more precision than a best-of-N
    approximation needs, and no SciPy dependency."""
    if not 0 < p < 1:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def expected_max_under_null(n_trials: int) -> float:
    """Expected maximum of N standard normal draws.

    Bailey & López de Prado's approximation. This is the number that turns
    "our best strategy scored X" into "our best strategy scored X, and pure
    noise across this many attempts would have scored Y".
    """
    if n_trials < 2:
        return 0.0
    return (1 - EULER) * _inverse_normal_cdf(1 - 1 / n_trials) + EULER * _inverse_normal_cdf(
        1 - 1 / (n_trials * math.e)
    )


def annualised_sharpe(monthly_returns: list[float]) -> float | None:
    if len(monthly_returns) < 12:
        return None
    sd = statistics.pstdev(monthly_returns)
    if sd == 0:
        return None
    return (statistics.fmean(monthly_returns) / sd) * math.sqrt(12)


def minimum_track_record_months(
    monthly_returns: list[float], confidence: float = 0.95
) -> float | None:
    """How long this strategy would have to run before its record could be
    told apart from luck (Bailey & López de Prado, benchmark zero).

    None when the observed edge is not positive: no length of track record
    establishes an edge that is not there.
    """
    if len(monthly_returns) < 6:
        return None
    sharpe = annualised_sharpe(monthly_returns)
    if sharpe is None or sharpe <= 0:
        return None
    monthly_sr = sharpe / math.sqrt(12)
    mean = statistics.fmean(monthly_returns)
    sd = statistics.pstdev(monthly_returns)
    if sd == 0:
        return None
    standardised = [(r - mean) / sd for r in monthly_returns]
    skew = statistics.fmean([s ** 3 for s in standardised])
    kurtosis = statistics.fmean([s ** 4 for s in standardised])
    z = _inverse_normal_cdf(confidence)
    numerator = 1 - skew * monthly_sr + (kurtosis - 1) / 4 * monthly_sr ** 2
    return round(1 + numerator * (z / monthly_sr) ** 2, 1)


def track_record_verdict(
    months_observed: float, trades: int, monthly_returns: list[float]
) -> str:
    """The sample-size sentence carried by every leaderboard row.

    Most rows will say "meaningless" for years. That is the honest answer, and
    hiding it would make the leaderboard an engine for over-confidence.
    """
    if trades == 0:
        return "No trades yet — nothing to judge."
    needed = minimum_track_record_months(monthly_returns)
    period = (
        f"{months_observed:.0f} months, {trades} trades"
        if months_observed >= 1
        else f"{trades} trades"
    )
    if needed is None:
        return (
            f"{period} — no positive edge to measure yet, so there is nothing "
            "for more data to confirm. Far too early to mean anything."
        )
    if months_observed >= needed:
        return (
            f"{period} — long enough to take seriously at this level of "
            f"consistency (about {needed:.0f} months were needed)."
        )
    return (
        f"{period} — statistically meaningless; at this consistency it would "
        f"need roughly {needed:.0f} months ({needed / 12:.1f} years) before "
        "the record could be told apart from luck."
    )


# ---------------------------------------------------------------- controls


def drift_control(
    service: FeatureService,
    rules: StrategyRules,
    result: SimResult,
    costs: CostModel,
    seed: int = 20260813,
) -> dict:
    """Random tickers from the same universe, held over the same windows.

    Matched on the calendar window each real trade occupied, so the control
    cannot be flattered or punished by being in the market at a different time.
    """
    if not result.round_trips:
        return {"samples": 0}

    eligible = [
        ticker for ticker, security in service.securities.items()
        if security.is_active
        and (not rules.universe.sectors or security.sector in rules.universe.sectors)
        and (not rules.universe.exclude_sectors
             or security.sector not in rules.universe.exclude_sectors)
        and len(service.bars.get(ticker, [])) > 260
    ]
    if not eligible:
        return {"samples": 0}

    rng = random.Random(seed)
    returns: list[float] = []
    for trip in result.round_trips:
        for _ in range(CONTROL_SAMPLES_PER_TRADE):
            ticker = eligible[rng.randrange(len(eligible))]
            bars = service.bars[ticker]
            entry_index = service._bar_index(ticker, trip.entry_date)
            exit_index = service._bar_index(ticker, trip.exit_date)
            if entry_index < 0 or exit_index <= entry_index:
                continue
            entry_price = bars[entry_index].adjusted_close
            if entry_price <= 0:
                continue
            gross = (bars[exit_index].adjusted_close / entry_price - 1.0) * 100.0
            security = service.securities[ticker]
            # Same friction both sides: the comparison is about selection, not
            # about who pays more to trade.
            friction = costs.spread_bps(security.quote_currency, None) * 2 / 100.0
            returns.append(gross - friction)

    if not returns:
        return {"samples": 0}
    return {
        "samples": len(returns),
        "mean_return_pct": round(statistics.fmean(returns), 4),
        "median_return_pct": round(statistics.median(returns), 4),
        "win_rate": round(sum(1 for r in returns if r > 0) / len(returns), 4),
        "_returns": returns,
    }


def regime_breakdown(result: SimResult) -> dict:
    """Trade outcomes split into three-year buckets.

    A strategy that worked in one stretch of one decade has not been shown to
    work; it has been shown to have coincided.
    """
    buckets: dict[str, list[float]] = {}
    for trip in result.round_trips:
        year = trip.exit_date.year
        base = year - (year % 3)
        buckets.setdefault(f"{base}-{base + 2}", []).append(trip.net_return_pct)
    out = {}
    for label, returns in sorted(buckets.items()):
        out[label] = {
            "trades": len(returns),
            "mean_return_pct": round(statistics.fmean(returns), 4),
            "win_rate": round(sum(1 for r in returns if r > 0) / len(returns), 4),
            # Shown, but not to be argued from.
            "underpowered": len(returns) < 30,
        }
    return out


# ---------------------------------------------------------------- family


async def family_of(session: AsyncSession, strategy_id: uuid.UUID) -> list[Strategy]:
    """Every strategy sharing a root ancestor, including this one.

    A tweak is a new strategy, and the whole family counts as trials: twelve
    variations on one idea are twelve chances for one to look good by luck.
    """
    all_rows = list((await session.execute(select(Strategy))).scalars())
    by_id = {row.strategy_id: row for row in all_rows}

    def root(row: Strategy) -> uuid.UUID:
        seen: set[uuid.UUID] = set()
        current = row
        while current.parent_strategy_id and current.parent_strategy_id in by_id:
            if current.strategy_id in seen:
                break  # lineage should be a tree, but never trust it
            seen.add(current.strategy_id)
            current = by_id[current.parent_strategy_id]
        return current.strategy_id

    target = by_id.get(strategy_id)
    if target is None:
        return []
    target_root = root(target)
    return [row for row in all_rows if root(row) == target_root]


def deflate(
    trade_returns: list[float], monthly_returns: list[float], n_trials: int
) -> dict:
    """What the best of N worthless strategies would have shown anyway.

    Two views. The per-trade one asks whether this trade population is
    distinguishable from zero given how many attempts the family made. The
    Sharpe one is the standard deflated-Sharpe comparison.
    """
    out: dict = {"n_trials": n_trials}
    z = expected_max_under_null(n_trials)
    out["expected_max_z"] = round(z, 4)

    if len(trade_returns) >= 30:
        standard_error = statistics.pstdev(trade_returns) / math.sqrt(len(trade_returns))
        observed = statistics.fmean(trade_returns)
        expected_best = standard_error * z
        out["per_trade"] = {
            "observed_mean_pct": round(observed, 4),
            "expected_best_of_n_under_null_pct": round(expected_best, 4),
            "survives": observed > expected_best,
            "margin_pct": round(observed - expected_best, 4),
        }

    sharpe = annualised_sharpe(monthly_returns)
    if sharpe is not None:
        n = len(monthly_returns)
        monthly_sr = sharpe / math.sqrt(12)
        se_monthly = math.sqrt((1 + 0.5 * monthly_sr ** 2) / n)
        expected_best_sharpe = se_monthly * z * math.sqrt(12)
        out["sharpe"] = {
            "observed": round(sharpe, 3),
            "expected_best_of_n_under_null": round(expected_best_sharpe, 3),
            "survives": sharpe > expected_best_sharpe,
        }
    return out


# ---------------------------------------------------------------- the gate


def caveats(results: dict, rules: StrategyRules, corrected_universe: bool = False) -> list[dict]:
    """What is wrong with these numbers, attached to them.

    The survivorship note leads either way — what changes is whether it
    describes a repaired problem or an open one.
    """
    if corrected_universe:
        out = [{
            "severity": "medium",
            "title": "Universe corrected for survivorship within the data window",
            "body": (
                "This backtest selects from the index membership as it stood on "
                "each date, including companies that later went bankrupt, were "
                "taken over, or dropped out — their data has been recovered and "
                "they are eligible while they were members. Residual gaps "
                "remain: membership records are thin before about 2012, a few "
                "departed companies have no retrievable data, and companies "
                "whose join dates were unrecorded are assumed to be members "
                "from the window start. Better than the survivor-only version; "
                "not perfect."
            ),
        }]
    else:
        out = [{
            "severity": "high",
            "title": "The absolute returns here are not real",
            "body": (
                "The universe is the index as it stands today. Companies that "
                "went bankrupt, were taken over, or fell out of the index are "
                "absent, so the backtest is choosing from a list of known "
                "survivors. This flatters every strategy, and it flatters "
                "momentum strategies most of all, because they buy whatever has "
                "risen furthest and the names that rose furthest before "
                "collapsing are the ones missing. Read the excess over the "
                "control, never the headline return."
            ),
        }]

    overall = results.get("overall", {})
    mean = overall.get("mean_trade_return_pct")
    median = overall.get("median_trade_return_pct")
    if mean is not None and median is not None and median != 0 and mean > 3 * median:
        out.append({
            "severity": "medium",
            "title": "A handful of trades produced most of the return",
            "body": (
                f"The average trade returned {mean:.1f}% while the typical one "
                f"returned {median:.1f}%. That gap means a few enormous winners "
                "carry the whole result, so the average describes those winners "
                "rather than what to expect from the next trade."
            ),
        })

    control = results.get("drift_control") or {}
    if control.get("samples"):
        out.append({
            "severity": "medium",
            "title": "What the control does and does not remove",
            "body": (
                "The control buys random companies from the same universe over "
                "the same weeks, so it removes the market's drift and part of the "
                "survivor effect. It cannot remove all of it: inside a list of "
                "survivors, 'has already risen' predicts 'rises further' partly "
                "because we already know none of them failed."
            ),
        })

    deflation = results.get("deflation", {})
    if deflation.get("n_trials", 1) > 1:
        out.append({
            "severity": "medium",
            "title": f"{deflation['n_trials']} related strategies were tried",
            "body": (
                "Variations on one idea are separate attempts, and the best of "
                "several attempts looks better than any of them deserves. The "
                "deflated figure is the one to read."
            ),
        })

    if rules.rebalance.frequency in ("weekly", "monthly"):
        out.append({
            "severity": "low",
            "title": "Costs are modelled, not observed",
            "body": (
                "Spread is assumed by size band and commission is flat. A "
                "strategy that rebalances this often is unusually sensitive to "
                "those assumptions being optimistic."
            ),
        })
    return out


@dataclass
class GateOutcome:
    passed: bool
    reasons: list[str]


def assess(results: dict) -> GateOutcome:
    """Promotion criteria, checked mechanically.

    Passing does not promote anything — it makes a strategy ELIGIBLE for Roger
    to promote. Nothing here ever promotes itself.
    """
    reasons: list[str] = []
    overall = results.get("overall", {})
    trades = overall.get("round_trips", 0)

    if trades < 30:
        reasons.append(f"only {trades} completed trades — too few to judge")
    expectancy = overall.get("mean_trade_return_pct")
    if expectancy is None or expectancy <= 0:
        reasons.append("expectancy after costs is not positive")

    control = results.get("drift_control") or {}
    excess = results.get("excess_over_drift_pct")
    if not control.get("samples"):
        reasons.append("no drift control could be computed")
    elif excess is None or excess <= 0:
        reasons.append(
            "does not beat picking at random from the same universe over the "
            "same windows"
        )

    return GateOutcome(passed=not reasons, reasons=reasons)


async def run_gate(
    session: AsyncSession,
    strategy_id: uuid.UUID,
    start: date,
    end: date,
    costs: CostModel | None = None,
    service: FeatureService | None = None,
    membership_index: str | None = "GSPC.INDX",
) -> dict:
    """Backtest a registered strategy and record the evidence.

    Uses the index membership as-of each date when the data exists, so the
    universe includes companies that later died. Never promotes.
    """
    costs = costs or CostModel()
    strategy = await session.get(Strategy, strategy_id)
    if strategy is None:
        raise ValueError(f"unknown strategy {strategy_id}")
    rules = parse_rules(strategy.rules)

    if service is None:
        needed = features_used(rules)
        if rules.universe.min_market_cap or rules.universe.max_market_cap:
            needed.add("price:market_cap")
        service = await FeatureService.build(
            session, start, end, needed, membership_index=membership_index
        )

    result = simulate(service, rules, start, end, costs=costs)
    overall = summarise(result)
    trade_returns = [t.net_return_pct for t in result.round_trips]
    monthly = result.monthly_returns()
    monthly_values = [row["return_pct"] for row in monthly]

    control = drift_control(service, rules, result, costs)
    control.pop("_returns", None)
    excess = (
        round(overall["mean_trade_return_pct"] - control["mean_return_pct"], 4)
        if control.get("samples") and "mean_trade_return_pct" in overall
        else None
    )

    boot = bootstrap_returns(trade_returns) if len(trade_returns) >= 30 else None
    family = await family_of(session, strategy_id)

    corrected = service.membership is not None and len(service.membership) > 0
    results = {
        "strategy_id": str(strategy_id),
        "name": strategy.name,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        # Which universe this ran on. "corrected" = membership-as-of-date,
        # departed companies included; "survivor_only" = today's list.
        "universe": "corrected" if corrected else "survivor_only",
        "costs": {
            "commission_per_order": costs.commission_per_order,
            "us_large_bps": costs.us_large_bps,
            "us_mid_bps": costs.us_mid_bps,
            "us_small_bps": costs.us_small_bps,
            "uk_bps": costs.uk_bps,
        },
        "overall": overall,
        "equity_curve": [[d.isoformat(), e] for d, e in result.equity_curve],
        "drift_control": control,
        "excess_over_drift_pct": excess,
        "bootstrap": None if boot is None else boot.__dict__,
        "regimes": regime_breakdown(result),
        "sharpe": annualised_sharpe(monthly_values),
        "minimum_track_record_months": minimum_track_record_months(monthly_values),
        "track_record_verdict": track_record_verdict(
            len(monthly_values), len(trade_returns), monthly_values
        ),
        "family": {
            "size": len(family),
            "members": [{"id": str(f.strategy_id), "name": f.name} for f in family],
        },
        "deflation": deflate(trade_returns, monthly_values, len(family)),
    }
    results["caveats"] = caveats(results, rules, corrected_universe=corrected)
    outcome = assess(results)
    results["gate"] = {
        "eligible_for_paper": outcome.passed,
        "blocking_reasons": outcome.reasons,
    }

    session.add(
        StrategyBacktest(strategy_id=strategy_id, results=results, monthly_returns=monthly)
    )
    await session.flush()
    return results
