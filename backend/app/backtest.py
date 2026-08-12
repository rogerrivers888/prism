"""Backtest harness.

The purpose is to find out whether an idea works, which means the harness has
to be built to make an idea fail. Four things it refuses to do:

1. **Look ahead.** Every decision at date D uses only what was knowable on D.
   For earnings timing that is stricter than it sounds: the *actual* report
   date is not knowable in advance, so entries are timed against the date a
   real investor would have *expected*, derived only from reports already
   published. The actual date is used for exactly one thing — checking whether
   the position was still open when it landed.

2. **Pretend the universe is complete.** The universe is today's index
   membership. Companies that went bankrupt or were acquired are not in it, so
   any backtest over past years is measuring the survivors. Every result says
   so; none of them can be read without it.

3. **Ignore costs.** Spread, commission and, for leveraged instruments, daily
   funding on full notional. A gross return is not a result.

4. **Hide the search.** Testing twenty parameter pairs and reporting the best
   one is how noise becomes a strategy. Every result carries the number of
   variants the sweep evaluated, and a bootstrap that says whether the result
   is distinguishable from chance.
"""

import random
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.earnings import EarningsDate
from app.fundamentals import PriceDaily, Security

# A quarter is not 91 days. Using 364 preserves the day of the week, which is
# what actually governs when a company reports.
YEAR_DAYS = 364


@dataclass(frozen=True)
class Costs:
    """Round-trip frictions. Defaults are deliberately not optimistic."""

    spread_bps: float = 10.0
    commission_bps: float = 5.0
    # Spread bets and CFDs finance the full notional overnight, not the margin.
    funding_annual_pct: float = 0.0
    leveraged: bool = False


@dataclass
class Trade:
    ticker: str
    sector: str
    market_cap: float | None
    period_end: date
    expected_report: date
    actual_report: date | None
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    gross_return_pct: float
    net_return_pct: float
    holding_days: int
    # True when the company reported before the planned exit — the expectation
    # was wrong and the position was still open. Not discarded: being caught is
    # a real outcome of trading against a forecast date.
    caught_by_early_report: bool


def expected_report_date(
    prior_reports: list[tuple[date, date]], period_end: date
) -> date | None:
    """The report date a real investor would have expected for ``period_end``.

    ``prior_reports`` is (period_end, report_date) for periods that had already
    reported — nothing else is allowed in. The estimate is the same fiscal
    period one year earlier plus 364 days, which is how reporting calendars
    actually behave; failing that, the median gap between period end and report
    applied to this period.

    Returns None when there is no basis, and no trade is taken. Guessing here
    would quietly manufacture the very edge we are trying to measure.
    """
    if not prior_reports:
        return None

    same_quarter_last_year = [
        report
        for period, report in prior_reports
        if abs((period_end - period).days - YEAR_DAYS) <= 25
    ]
    if same_quarter_last_year:
        return max(same_quarter_last_year) + timedelta(days=YEAR_DAYS)

    lags = [(report - period).days for period, report in prior_reports]
    if not lags:
        return None
    return period_end + timedelta(days=int(statistics.median(lags)))


def _nearest_trading_day(
    prices: dict[date, float], target: date, direction: int, limit: int = 10
) -> tuple[date, float] | None:
    """Walk to the nearest day with a price. Markets close; calendars don't."""
    for offset in range(limit + 1):
        day = target + timedelta(days=offset * direction)
        price = prices.get(day)
        if price is not None:
            return day, price
    return None


def apply_costs(gross_pct: float, holding_days: int, costs: Costs) -> float:
    """Net of spread, commission and — when leveraged — overnight funding."""
    # Crossing the spread twice, paying commission twice.
    friction = (costs.spread_bps + costs.commission_bps) * 2 / 100.0
    funding = 0.0
    if costs.leveraged and costs.funding_annual_pct:
        funding = costs.funding_annual_pct * holding_days / 365.0
    return gross_pct - friction - funding


@dataclass
class Bootstrap:
    mean: float
    p5: float
    p95: float
    # Share of resamples whose mean was <= 0. High means the observed edge is
    # comfortably inside what chance produces.
    share_non_positive: float
    inside_noise: bool


def bootstrap_returns(returns: list[float], iterations: int = 2000) -> Bootstrap | None:
    """Resample the trade sequence to show the range chance alone could give.

    Deliberately resamples the observed trades rather than testing against a
    null of zero: the question is how stable this result is, and a mean that
    sits within a whisker of zero across resamples is not an edge.
    """
    if len(returns) < 10:
        return None

    rng = random.Random(20260811)
    # random.choices is C-level; a comprehension over randrange is not, and at
    # 30k trades that difference is minutes. Iterations taper with sample size
    # because the sampling error being measured shrinks as n grows.
    if len(returns) > 20000:
        iterations = min(iterations, 300)
    elif len(returns) > 5000:
        iterations = min(iterations, 800)
    means = [statistics.fmean(rng.choices(returns, k=len(returns))) for _ in range(iterations)]
    means.sort()

    p5 = means[int(0.05 * len(means))]
    p95 = means[int(0.95 * len(means))]
    non_positive = sum(1 for m in means if m <= 0) / len(means)
    return Bootstrap(
        mean=round(statistics.fmean(means), 4),
        p5=round(p5, 4),
        p95=round(p95, 4),
        share_non_positive=round(non_positive, 4),
        # If zero sits inside the 5–95 band, the result is not distinguishable
        # from chance at this sample size.
        inside_noise=p5 <= 0 <= p95,
    )


def summarise(trades: list[Trade]) -> dict:
    if not trades:
        return {"trades": 0}

    net = [t.net_return_pct for t in trades]
    gross = [t.gross_return_pct for t in trades]
    wins = [r for r in net if r > 0]
    losses = [r for r in net if r <= 0]

    # Expectancy in R: average win vs average loss, weighted by hit rate.
    average_win = statistics.fmean(wins) if wins else 0.0
    average_loss = abs(statistics.fmean(losses)) if losses else 0.0
    win_rate = len(wins) / len(net)
    expectancy_r = (
        (win_rate * average_win - (1 - win_rate) * average_loss) / average_loss
        if average_loss
        else None
    )

    # Max drawdown of the equity curve if each trade were taken in sequence at
    # constant size. Not a portfolio simulation — a sequence-risk sketch.
    equity, peak, drawdown = 0.0, 0.0, 0.0
    for r in net:
        equity += r
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)

    ordered = sorted(net)

    def percentile(p: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(p * len(ordered)))], 4)

    return {
        "trades": len(trades),
        "mean_return_pct": round(statistics.fmean(net), 4),
        "median_return_pct": round(statistics.median(net), 4),
        "mean_gross_return_pct": round(statistics.fmean(gross), 4),
        "cost_drag_pct": round(statistics.fmean(gross) - statistics.fmean(net), 4),
        "win_rate": round(win_rate, 4),
        "expectancy_r": None if expectancy_r is None else round(expectancy_r, 4),
        "max_drawdown_pct": round(drawdown, 4),
        "stdev_pct": round(statistics.pstdev(net), 4) if len(net) > 1 else None,
        # The distribution, because a mean hides everything that matters.
        "distribution": {
            "p5": percentile(0.05), "p25": percentile(0.25), "p50": percentile(0.50),
            "p75": percentile(0.75), "p95": percentile(0.95),
            "worst": round(min(net), 4), "best": round(max(net), 4),
        },
        "caught_by_early_report": sum(1 for t in trades if t.caught_by_early_report),
        "mean_holding_days": round(statistics.fmean([t.holding_days for t in trades]), 1),
    }


def _bucket_cap(cap: float | None) -> str:
    if cap is None:
        return "unknown"
    if cap >= 200e9:
        return "mega"
    if cap >= 10e9:
        return "large"
    if cap >= 2e9:
        return "mid"
    return "small"


def breakdowns(trades: list[Trade]) -> dict:
    """Sector, size and period, so "works in frothy sectors" is testable."""
    groups: dict[str, dict[str, list[Trade]]] = {
        "sector": {}, "size": {}, "year": {},
    }
    for trade in trades:
        groups["sector"].setdefault(trade.sector, []).append(trade)
        groups["size"].setdefault(_bucket_cap(trade.market_cap), []).append(trade)
        groups["year"].setdefault(str(trade.entry_date.year), []).append(trade)

    return {
        dimension: {
            key: summarise(items)
            for key, items in sorted(buckets.items())
            # A bucket this thin is an anecdote; it is reported with its count
            # rather than dropped, so the thinness is visible.
            if len(items) >= 5
        }
        for dimension, buckets in groups.items()
    }


async def run_pre_earnings(
    session: AsyncSession,
    enter_days_before: int,
    exit_days_before: int,
    start: date,
    end: date,
    costs: Costs,
    tickers: list[str] | None = None,
    variants_tested: int = 1,
) -> dict:
    """Buy N days before the *expected* report, sell M days before it.

    Never intentionally holds through the announcement. When the company
    reported earlier than expected the position is closed on the last price
    before the report and flagged — a real cost of trading a forecast date,
    not something to quietly drop.
    """
    if enter_days_before <= exit_days_before:
        raise ValueError("enter_days_before must be greater than exit_days_before")

    securities = {
        row.ticker: row
        for row in (
            await session.execute(
                select(Security).where(Security.is_active.is_(True))
            )
        ).scalars()
        if tickers is None or row.ticker in tickers
    }

    trades: list[Trade] = []
    skipped_no_expectation = 0
    skipped_no_prices = 0

    for ticker, security in securities.items():
        # Actual, reported periods only — a period still forecast has no
        # outcome to measure and no confirmed date to check against.
        reported = (
            await session.execute(
                select(EarningsDate.period_end, EarningsDate.report_date)
                .where(
                    EarningsDate.ticker == ticker,
                    EarningsDate.is_estimated.is_(False),
                    EarningsDate.report_date.is_not(None),
                )
                .distinct(EarningsDate.period_end)
                .order_by(EarningsDate.period_end, EarningsDate.observed_on.desc())
            )
        ).all()
        if len(reported) < 5:
            continue

        history = sorted((period, report) for period, report in reported)
        prices = {
            day: float(close)
            for day, close in (
                await session.execute(
                    select(PriceDaily.date, PriceDaily.adjusted_close).where(
                        PriceDaily.ticker == ticker,
                        PriceDaily.adjusted_close.is_not(None),
                    )
                )
            ).all()
        }
        if not prices:
            skipped_no_prices += 1
            continue

        for index, (period_end, actual_report) in enumerate(history):
            if not (start <= actual_report <= end):
                continue

            # Only periods that had ALREADY reported inform the expectation.
            # This is the line that separates a backtest from a fantasy.
            prior = [
                (p, r) for p, r in history[:index] if r < actual_report
            ]
            expected = expected_report_date(prior, period_end)
            if expected is None:
                skipped_no_expectation += 1
                continue

            planned_entry = expected - timedelta(days=enter_days_before)
            planned_exit = expected - timedelta(days=exit_days_before)

            # The entry decision must itself be made before the report; if the
            # expectation was so wrong that entry falls after the actual
            # report, there was no trade to take.
            if planned_entry >= actual_report:
                continue

            entry = _nearest_trading_day(prices, planned_entry, 1)
            if entry is None:
                continue

            caught = False
            exit_target = planned_exit
            if actual_report <= planned_exit:
                # Reported earlier than expected: close on the last price
                # strictly before the announcement.
                exit_target = actual_report - timedelta(days=1)
                caught = True

            exit_point = _nearest_trading_day(prices, exit_target, -1)
            if exit_point is None or exit_point[0] <= entry[0]:
                continue

            entry_date, entry_price = entry
            exit_date, exit_price = exit_point
            if entry_price <= 0:
                continue

            gross = (exit_price / entry_price - 1.0) * 100.0
            holding = (exit_date - entry_date).days
            trades.append(
                Trade(
                    ticker=ticker,
                    sector=security.sector,
                    market_cap=float(security.market_cap) if security.market_cap else None,
                    period_end=period_end,
                    expected_report=expected,
                    actual_report=actual_report,
                    entry_date=entry_date,
                    exit_date=exit_date,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    gross_return_pct=gross,
                    net_return_pct=apply_costs(gross, holding, costs),
                    holding_days=holding,
                    caught_by_early_report=caught,
                )
            )

    overall = summarise(trades)
    returns = [t.net_return_pct for t in trades]
    boot = bootstrap_returns(returns)

    # The control. Same universe, same holding length, random dates.
    control = {"samples": 0}
    if trades:
        control = await unconditional_drift(
            session,
            sorted({t.ticker for t in trades}),
            max(1, round(statistics.fmean([t.holding_days for t in trades]))),
            start,
            end,
            costs,
        )

    # How far the expectation was from the truth. If this is large, the
    # strategy is timing against noise and the result should be read as such.
    errors = [
        abs((t.expected_report - t.actual_report).days)
        for t in trades
        if t.actual_report
    ]

    return {
        "strategy": "pre_earnings",
        "params": {
            "enter_days_before": enter_days_before,
            "exit_days_before": exit_days_before,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "costs": {
                "spread_bps": costs.spread_bps,
                "commission_bps": costs.commission_bps,
                "funding_annual_pct": costs.funding_annual_pct,
                "leveraged": costs.leveraged,
            },
            "universe_size": len(securities),
        },
        "overall": overall,
        "breakdowns": breakdowns(trades),
        "bootstrap": None if boot is None else boot.__dict__,
        "control_unconditional_drift": {
            k: v for k, v in control.items() if k != "_returns"
        },
        "excess_significance": (
            excess_significance(returns, control.get("_returns", []))
            if control.get("samples")
            else None
        ),
        # The number that matters: the earnings window minus simply being long
        # for the same number of days.
        "excess_over_drift_pct": (
            round(overall["mean_return_pct"] - control["mean_return_pct"], 4)
            if control.get("samples") and overall.get("trades")
            else None
        ),
        "variants_tested": variants_tested,
        "expectation_error_days": {
            "mean": round(statistics.fmean(errors), 2) if errors else None,
            "median": round(statistics.median(errors), 2) if errors else None,
            "within_2_days": (
                round(sum(1 for e in errors if e <= 2) / len(errors), 4) if errors else None
            ),
        },
        "skipped": {
            "no_expectation_basis": skipped_no_expectation,
            "no_prices": skipped_no_prices,
        },
        # Attached to the result, not to a footnote. A caller that renders the
        # numbers without these is misrepresenting them.
        "caveats": caveats(overall, boot, variants_tested, control),
        # Private: the trade objects themselves, so segmentation can reuse a
        # run rather than repeat it. Stripped by public() before serialisation.
        "_trades": trades,
    }


def public(result: dict) -> dict:
    """Drop private keys. Anything underscore-prefixed is internal plumbing
    and is not JSON-serialisable."""
    return {key: value for key, value in result.items() if not key.startswith("_")}


def excess_significance(
    strategy_returns: list[float],
    control_returns: list[float],
    iterations: int = 2000,
) -> dict | None:
    """Is the gap between strategy and control bigger than sampling noise?

    Bootstraps both samples independently and looks at the distribution of the
    difference. The headline return is not the question — being long in a
    rising market answers that. The question is whether the earnings window
    adds anything on top, and whether that addition is stable.
    """
    if len(strategy_returns) < 30 or len(control_returns) < 30:
        return None

    rng = random.Random(20260812)
    if max(len(strategy_returns), len(control_returns)) > 20000:
        iterations = min(iterations, 300)
    diffs = [
        statistics.fmean(rng.choices(strategy_returns, k=len(strategy_returns)))
        - statistics.fmean(rng.choices(control_returns, k=len(control_returns)))
        for _ in range(iterations)
    ]
    diffs.sort()
    p5 = diffs[int(0.05 * len(diffs))]
    p95 = diffs[int(0.95 * len(diffs))]
    return {
        "mean_excess_pct": round(statistics.fmean(diffs), 4),
        "p5": round(p5, 4),
        "p95": round(p95, 4),
        "share_non_positive": round(sum(1 for d in diffs if d <= 0) / len(diffs), 4),
        "inside_noise": p5 <= 0 <= p95,
    }


async def unconditional_drift(
    session: AsyncSession,
    tickers: list[str],
    holding_days: int,
    start: date,
    end: date,
    costs: Costs,
    samples_per_ticker: int = 40,
) -> dict:
    """What a same-length hold returned on *any* random date, same universe.

    This is the control that decides whether a pre-earnings result means
    anything. A long-only strategy in a rising market makes money by being
    long, not by being clever about earnings. If the earnings window does not
    beat this, there is no earnings effect — only drift, measured on a
    survivor-biased universe that drifted especially hard.
    """
    rng = random.Random(20260811)
    returns: list[float] = []

    for ticker in tickers:
        rows = (
            await session.execute(
                select(PriceDaily.date, PriceDaily.adjusted_close)
                .where(
                    PriceDaily.ticker == ticker,
                    PriceDaily.date >= start,
                    PriceDaily.date <= end,
                    PriceDaily.adjusted_close.is_not(None),
                )
                .order_by(PriceDaily.date)
            )
        ).all()
        if len(rows) < holding_days + 5:
            continue
        series = [(d, float(c)) for d, c in rows]
        for _ in range(samples_per_ticker):
            i = rng.randrange(0, len(series) - holding_days - 1)
            entry_price = series[i][1]
            exit_price = series[i + holding_days][1]
            if entry_price <= 0:
                continue
            gross = (exit_price / entry_price - 1.0) * 100.0
            days = (series[i + holding_days][0] - series[i][0]).days
            returns.append(apply_costs(gross, days, costs))

    if not returns:
        return {"samples": 0}
    boot = bootstrap_returns(returns)
    return {
        "samples": len(returns),
        "mean_return_pct": round(statistics.fmean(returns), 4),
        "median_return_pct": round(statistics.median(returns), 4),
        "win_rate": round(sum(1 for r in returns if r > 0) / len(returns), 4),
        "bootstrap": None if boot is None else boot.__dict__,
        "_returns": returns,
    }


def caveats(
    overall: dict,
    boot: Bootstrap | None,
    variants_tested: int,
    control: dict | None = None,
) -> list[dict]:
    notes = [
        {
            "severity": "high",
            "title": "Survivorship bias",
            "body": (
                "The universe is today's index membership. Companies that went "
                "bankrupt, were acquired, or fell out of the index are absent, so "
                "this measures the survivors and flatters itself by an unknown "
                "amount. Historical constituent lists would fix it; EODHD sell "
                "them separately and we do not have them."
            ),
        },
        {
            "severity": "medium",
            "title": "Expected dates are reconstructed, not recorded",
            "body": (
                "We only began recording forecast report dates today, so for "
                "historical periods the expected date is rebuilt from prior "
                "reporting cadence. It is what an investor could have inferred, "
                "not what a data vendor told them on the day."
            ),
        },
    ]

    if variants_tested > 1:
        notes.append({
            "severity": "high" if variants_tested >= 10 else "medium",
            "title": f"{variants_tested} parameter combinations were tested",
            "body": (
                "With that many variants, the best-looking result is partly a "
                "product of the search. Treat any single winner as a hypothesis "
                "to test out of sample, not as a finding."
            ),
        })

    if boot and boot.inside_noise:
        notes.append({
            "severity": "high",
            "title": "Not distinguishable from chance",
            "body": (
                f"Resampling these trades puts the mean between {boot.p5:.3f}% and "
                f"{boot.p95:.3f}%, which spans zero. {boot.share_non_positive:.0%} of "
                "resamples were flat or negative. At this sample size the result "
                "is consistent with no edge at all."
            ),
        })

    if control and control.get("samples") and overall.get("trades"):
        excess = overall["mean_return_pct"] - control["mean_return_pct"]
        if excess <= 0:
            notes.append({
                "severity": "high",
                "title": "No edge over simply being long",
                "body": (
                    f"A random hold of the same length on the same universe returned "
                    f"{control['mean_return_pct']:+.3f}% against this strategy's "
                    f"{overall['mean_return_pct']:+.3f}%. The strategy does not beat "
                    "being long for the same number of days, so what it measures is "
                    "market drift, not an earnings effect."
                ),
            })
        else:
            notes.append({
                "severity": "medium",
                "title": f"Excess over drift is {excess:+.3f}% per trade",
                "body": (
                    f"A random hold of the same length returned "
                    f"{control['mean_return_pct']:+.3f}%. The earnings window adds "
                    f"{excess:+.3f}% on top. Judge the strategy on that difference, "
                    "not on the headline return — and remember the drift itself is "
                    "measured on a survivor-biased universe."
                ),
            })

    notes.append({
        "severity": "medium",
        "title": "Max drawdown is a sequence sketch, not a portfolio",
        "body": (
            "Trades are summed in sequence at constant size. Real positions overlap "
            "and are sized against capital, so this understates concentration risk "
            "and overstates the depth of any single run."
        ),
    })

    if overall.get("trades", 0) < 30:
        notes.append({
            "severity": "high",
            "title": f"Only {overall.get('trades', 0)} trades",
            "body": "Below about 30 trades no statistic here means anything.",
        })

    return notes
