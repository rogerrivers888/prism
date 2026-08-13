"""Segmented backtesting, and an honest accounting of what segmenting costs.

The pooled pre-earnings result was null. The hypothesis this module tests is
narrower and more plausible: that speculative run-ups happen in high-attention
names rather than universally. Testing it means slicing the trades many ways,
and slicing many ways is how a null result gets talked into a finding.

Three things guard against that:

- Every segment gets its own drift control, drawn from the same names that
  produced its trades. A segment of volatile stocks will show larger returns
  than a segment of utilities whether or not earnings matter, so comparing
  segments to each other proves nothing. Each is compared to itself.
- The excess is bootstrapped as a *paired* statistic. Each resampled trade
  draws a matched random hold on the same ticker, so the band describes the
  difference rather than two independent quantities that happen to be
  subtracted.
- Every test is counted, and the p-values are corrected across all of them.
  Both corrected and uncorrected results are reported, because the gap between
  them is the point.

The lens readings used to define froth segments are recomputed at historical
dates from point-in-time fundamentals. Classifying a 2012 trade by today's
dispersion would be a lookahead, and a subtle one, because the classifier
would know which companies went on to disappoint.
"""

import logging
import random
from bisect import bisect_left
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest import Costs, Trade, apply_costs, run_pre_earnings
from app.earnings import EarningsDate
from app.fundamentals import PriceDaily
from app.lenses.base import SCORING_VERSION
from app.lenses.engine import DispersionDaily, LensScoreDaily

logger = logging.getLogger(__name__)

# Random holds drawn per ticker to form the control pool. Drawn once and
# reused across every segment that ticker appears in — the alternative is
# re-running the control thirty times over the same price series.
POOL_PER_TICKER = 120

BOOTSTRAP_ITERATIONS = 1000

# A segment below this cannot support a conclusion no matter how good the
# number looks, and is reported as underpowered rather than quietly ranked.
MIN_TRADES = 200

# Which sectors should agree with which. A real effect in semiconductors ought
# to show up, weaker, in hardware; one that exists in exactly one sector and
# nowhere adjacent to it is noise wearing a sector label.
SECTOR_NEIGHBOURS: dict[str, set[str]] = {
    "semiconductors": {"hardware", "software"},
    "hardware": {"semiconductors", "software", "industrials"},
    "software": {"hardware", "semiconductors", "communication_services"},
    "communication_services": {"software", "consumer_discretionary"},
    "consumer_discretionary": {"consumer_staples", "communication_services"},
    "consumer_staples": {"consumer_discretionary", "healthcare"},
    "healthcare": {"consumer_staples"},
    "banks": {"financials", "insurance"},
    "financials": {"banks", "insurance", "real_estate"},
    "insurance": {"financials", "banks"},
    "real_estate": {"financials", "utilities"},
    "energy": {"commodities", "materials", "utilities"},
    "commodities": {"energy", "materials"},
    "materials": {"commodities", "energy", "industrials"},
    "industrials": {"materials", "hardware"},
    "utilities": {"energy", "real_estate"},
}


@dataclass
class SegmentResult:
    family: str
    segment: str
    trades: int
    mean_return_pct: float
    median_return_pct: float
    win_rate: float
    drift_pct: float
    excess_pct: float
    p5: float
    p95: float
    p_value: float
    underpowered: bool

    def as_dict(self) -> dict:
        return {**self.__dict__}


async def price_series(
    session: AsyncSession, tickers: list[str], start: date, end: date
) -> dict[str, list[tuple[date, float]]]:
    """Adjusted closes per ticker, loaded once and reused for both the control
    pool and the realised-volatility classifier."""
    rows = (
        await session.execute(
            select(PriceDaily.ticker, PriceDaily.date, PriceDaily.adjusted_close)
            .where(
                PriceDaily.ticker.in_(tickers),
                PriceDaily.date >= start,
                PriceDaily.date <= end,
                PriceDaily.adjusted_close.is_not(None),
            )
            .order_by(PriceDaily.ticker, PriceDaily.date)
        )
    ).all()
    series: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for ticker, day, close in rows:
        series[ticker].append((day, float(close)))
    return dict(series)


def build_pool(
    series: dict[str, list[tuple[date, float]]], holding_days: int, costs: Costs
) -> dict[str, list[float]]:
    """Random same-length holds per ticker: the control, computed once.

    Every segment's control is drawn from this pool restricted to the names
    that segment actually traded, so the comparison is against the same
    universe rather than against the market as a whole.
    """
    rng = random.Random(20260813)
    pool: dict[str, list[float]] = {}
    for ticker, bars in series.items():
        if len(bars) < holding_days + 5:
            continue
        draws = []
        for _ in range(POOL_PER_TICKER):
            index = rng.randrange(0, len(bars) - holding_days - 1)
            entry = bars[index][1]
            if entry <= 0:
                continue
            gross = (bars[index + holding_days][1] / entry - 1.0) * 100.0
            days = (bars[index + holding_days][0] - bars[index][0]).days
            draws.append(apply_costs(gross, days, costs))
        if draws:
            pool[ticker] = draws
    return pool


def realised_vol(bars: list[tuple[date, float]], as_of: date, window: int = 60) -> float | None:
    """Annualised realised volatility over the trailing window, at as_of only.

    Computed from bars strictly before the entry date, so a volatile week that
    began after entry cannot classify the trade that preceded it.
    """
    # Bars are date-ordered, so bisect the cut point rather than scanning the
    # whole series once per trade.
    cut = bisect_left(bars, (as_of,))
    history = [close for _, close in bars[max(0, cut - window - 1) : cut]]
    if len(history) < window // 2:
        return None
    returns = [
        history[i] / history[i - 1] - 1.0
        for i in range(1, len(history))
        if history[i - 1] > 0
    ]
    if len(returns) < 5:
        return None
    return statistics.pstdev(returns) * (252 ** 0.5) * 100.0


async def lens_snapshots(
    session: AsyncSession, start: date, end: date
) -> tuple[list[date], dict[tuple[str, date], dict], dict[tuple[str, date], float]]:
    """Historical lens scores at the quarterly scoring dates.

    Returns the ordered date list plus lookups keyed by (ticker, as_of), so a
    trade can be matched to the most recent scoring date that preceded it.
    """
    rows = (
        await session.execute(
            select(
                LensScoreDaily.ticker,
                LensScoreDaily.as_of,
                LensScoreDaily.lens,
                LensScoreDaily.score,
                LensScoreDaily.relative_premium,
            ).where(
                LensScoreDaily.scoring_version == SCORING_VERSION,
                LensScoreDaily.as_of >= start,
                LensScoreDaily.as_of <= end,
            )
        )
    ).all()
    scores: dict[tuple[str, date], dict] = defaultdict(dict)
    for ticker, as_of, lens, score, premium in rows:
        scores[(ticker, as_of)][lens] = (
            None if score is None else float(score),
            None if premium is None else float(premium),
        )

    spread_rows = (
        await session.execute(
            select(DispersionDaily.ticker, DispersionDaily.as_of, DispersionDaily.dispersion).where(
                DispersionDaily.scoring_version == SCORING_VERSION,
                DispersionDaily.as_of >= start,
                DispersionDaily.as_of <= end,
            )
        )
    ).all()
    spreads = {
        (ticker, as_of): float(value)
        for ticker, as_of, value in spread_rows
        if value is not None
    }

    dates = sorted({as_of for _, as_of in scores} | {as_of for _, as_of in spreads})
    return dates, dict(scores), spreads


def most_recent(dates: list[date], target: date) -> date | None:
    """The latest scoring date at or before target. None means the trade
    predates any scoring run and cannot be classified."""
    candidates = [d for d in dates if d <= target]
    return candidates[-1] if candidates else None


def quintile_edges(values: list[float]) -> list[float]:
    ordered = sorted(values)
    return [ordered[int(len(ordered) * q / 5)] for q in range(1, 5)]


def bucket(value: float, edges: list[float]) -> int:
    return sum(1 for edge in edges if value >= edge)


def paired_bootstrap(
    pairs: list[tuple[float, str]],
    pool: dict[str, list[float]],
    iterations: int = BOOTSTRAP_ITERATIONS,
) -> tuple[float, float, float, float] | None:
    """Bootstrap the excess as a paired difference.

    Each resampled trade draws a matched random hold on the *same ticker*, so
    the band describes the earnings timing itself rather than the sum of two
    unrelated sampling errors. Returns (mean, p5, p95, two-sided p).
    """
    usable = [(ret, ticker) for ret, ticker in pairs if ticker in pool]
    if len(usable) < 30:
        return None

    rng = random.Random(20260814)
    if len(usable) > 20000:
        iterations = min(iterations, 300)
    diffs = []
    for _ in range(iterations):
        picks = [usable[rng.randrange(len(usable))] for _ in range(len(usable))]
        strategy = statistics.fmean([ret for ret, _ in picks])
        control = statistics.fmean(
            [pool[ticker][rng.randrange(len(pool[ticker]))] for _, ticker in picks]
        )
        diffs.append(strategy - control)
    diffs.sort()

    below = sum(1 for d in diffs if d <= 0) / len(diffs)
    # Two-sided, and floored at one over the resample count: a bootstrap of
    # 300 draws cannot evidence a p below 1/300, and reporting 0.0 would imply
    # a certainty the method does not have.
    p_value = max(2 * min(below, 1 - below), 1.0 / len(diffs))
    return (
        statistics.fmean(diffs),
        diffs[int(0.05 * len(diffs))],
        diffs[int(0.95 * len(diffs))],
        p_value,
    )


def evaluate_segment(
    family: str,
    name: str,
    trades: list[Trade],
    pool: dict[str, list[float]],
) -> SegmentResult | None:
    if len(trades) < 30:
        return None
    returns = [t.net_return_pct for t in trades]
    boot = paired_bootstrap([(t.net_return_pct, t.ticker) for t in trades], pool)
    if boot is None:
        return None
    mean_excess, p5, p95, p_value = boot

    drift_samples = [
        statistics.fmean(pool[t.ticker]) for t in trades if t.ticker in pool
    ]
    drift = statistics.fmean(drift_samples) if drift_samples else 0.0

    return SegmentResult(
        family=family,
        segment=name,
        trades=len(trades),
        mean_return_pct=round(statistics.fmean(returns), 4),
        median_return_pct=round(statistics.median(returns), 4),
        win_rate=round(sum(1 for r in returns if r > 0) / len(returns), 4),
        drift_pct=round(drift, 4),
        excess_pct=round(mean_excess, 4),
        p5=round(p5, 4),
        p95=round(p95, 4),
        p_value=round(p_value, 5),
        underpowered=len(trades) < MIN_TRADES,
    )


def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> list[bool]:
    """Which tests survive FDR control at alpha.

    Bonferroni is also reported alongside. BH is the more informative of the
    two here: with thirty-odd segments, Bonferroni is so severe that it would
    reject a real effect, and saying "nothing survives Bonferroni" would be
    true but uninformative on its own.
    """
    indexed = sorted(enumerate(p_values), key=lambda pair: pair[1])
    total = len(p_values)
    survives = [False] * total
    threshold_rank = 0
    for rank, (_, p) in enumerate(indexed, 1):
        if p <= alpha * rank / total:
            threshold_rank = rank
    for rank, (index, _) in enumerate(indexed, 1):
        if rank <= threshold_rank:
            survives[index] = True
    return survives


def neighbour_check(results: list[SegmentResult]) -> dict[str, dict]:
    """For each positive sector, do its adjacent sectors agree in sign?

    An effect confined to exactly one sector with no echo next door is the
    signature of noise, and this is the test that says so.
    """
    by_sector = {r.segment: r for r in results if r.family == "sector"}
    verdicts = {}
    for name, result in by_sector.items():
        if result.excess_pct <= 0:
            continue
        neighbours = SECTOR_NEIGHBOURS.get(name, set())
        present = [by_sector[n] for n in neighbours if n in by_sector]
        agreeing = [n for n in present if n.excess_pct > 0]
        verdicts[name] = {
            "excess_pct": result.excess_pct,
            "neighbours_checked": [n.segment for n in present],
            "neighbours_agreeing": [n.segment for n in agreeing],
            "neighbour_mean_excess_pct": (
                round(statistics.fmean([n.excess_pct for n in present]), 4)
                if present
                else None
            ),
            "isolated": bool(present) and not agreeing,
        }
    return verdicts


async def run_segmented(
    session: AsyncSession,
    enter_days_before: int,
    exit_days_before: int,
    start: date,
    end: date,
    costs: Costs,
    tickers: list[str] | None = None,
    families_only: set[str] | None = None,
) -> dict:
    """One pre-earnings run, sliced every way the hypothesis suggests.

    The strategy is run once and the trades reused, so every segment describes
    the same set of decisions rather than a slightly different backtest.
    """
    pooled = await run_pre_earnings(
        session, enter_days_before, exit_days_before, start, end, costs, tickers
    )
    trades: list[Trade] = pooled["_trades"]
    if not trades:
        return {"trades": 0, "segments": []}

    holding = max(1, round(statistics.fmean([t.holding_days for t in trades])))
    names = sorted({t.ticker for t in trades})
    series = await price_series(session, names, start, end)
    pool = build_pool(series, holding, costs)
    logger.info("control pool: %d tickers x %d draws", len(pool), POOL_PER_TICKER)

    dates, scores, spreads = await lens_snapshots(session, start, end)

    # ---- classify every trade, point-in-time -----------------------------
    unclassified = defaultdict(int)
    for trade in trades:
        as_of = most_recent(dates, trade.entry_date)
        trade.as_of = as_of  # type: ignore[attr-defined]
        trade.dispersion = spreads.get((trade.ticker, as_of)) if as_of else None  # type: ignore[attr-defined]
        lenses = scores.get((trade.ticker, as_of), {}) if as_of else {}
        value = lenses.get("value", (None, None))
        momentum = lenses.get("momentum", (None, None))
        trade.value_score = value[0]  # type: ignore[attr-defined]
        trade.value_premium = value[1]  # type: ignore[attr-defined]
        trade.momentum_score = momentum[0]  # type: ignore[attr-defined]
        trade.vol = realised_vol(series.get(trade.ticker, []), trade.entry_date)  # type: ignore[attr-defined]
        if as_of is None:
            unclassified["no_prior_scoring_date"] += 1
        if trade.dispersion is None:  # type: ignore[attr-defined]
            unclassified["no_dispersion"] += 1
        if trade.vol is None:  # type: ignore[attr-defined]
            unclassified["no_volatility"] += 1

    families: dict[str, dict[str, list[Trade]]] = defaultdict(lambda: defaultdict(list))

    for trade in trades:
        families["sector"][trade.sector].append(trade)

    caps = [t.market_cap for t in trades if t.market_cap]
    if caps:
        edges = quintile_edges(caps)
        for trade in trades:
            if trade.market_cap:
                families["market_cap_quintile"][f"Q{bucket(trade.market_cap, edges) + 1}"].append(trade)

    # Froth proxies. Each is measured against the cross-section as it stood on
    # the same scoring date, not against a fixed threshold — "high dispersion"
    # in 2011 is not the same number as in 2025.
    by_date_dispersion: dict[date, list[float]] = defaultdict(list)
    by_date_premium: dict[date, list[float]] = defaultdict(list)
    for trade in trades:
        as_of = trade.as_of  # type: ignore[attr-defined]
        if as_of and trade.dispersion is not None:  # type: ignore[attr-defined]
            by_date_dispersion[as_of].append(trade.dispersion)  # type: ignore[attr-defined]
        if as_of and trade.value_premium is not None:  # type: ignore[attr-defined]
            by_date_premium[as_of].append(trade.value_premium)  # type: ignore[attr-defined]
    median_dispersion = {d: statistics.median(v) for d, v in by_date_dispersion.items() if v}
    median_premium = {d: statistics.median(v) for d, v in by_date_premium.items() if v}

    for trade in trades:
        as_of = trade.as_of  # type: ignore[attr-defined]
        spread = trade.dispersion  # type: ignore[attr-defined]
        if as_of and spread is not None and as_of in median_dispersion:
            side = "high" if spread >= median_dispersion[as_of] else "low"
            families["lens_dispersion"][f"{side} disagreement"].append(trade)

        premium = trade.value_premium  # type: ignore[attr-defined]
        if as_of and premium is not None and as_of in median_premium:
            # High value premium is cheap-within-an-expensive-sector: the stock
            # screens well only because everything around it screens worse.
            side = "high" if premium >= median_premium[as_of] else "low"
            families["valuation_premium"][f"{side} premium vs sector"].append(trade)

        value = trade.value_score  # type: ignore[attr-defined]
        momentum = trade.momentum_score  # type: ignore[attr-defined]
        if value is not None and momentum is not None:
            # Low value score means expensive, not cheap: the lens scores the
            # value thesis, so 0 is priced for perfection and 100 is a bargain.
            perfection = value <= 35 and momentum >= 65
            families["priced_for_perfection"][
                "expensive + high momentum" if perfection else "everything else"
            ].append(trade)

    vols = [t.vol for t in trades if t.vol is not None]  # type: ignore[attr-defined]
    if vols:
        edges = quintile_edges(vols)
        for trade in trades:
            if trade.vol is not None:  # type: ignore[attr-defined]
                families["realised_vol_quintile"][f"Q{bucket(trade.vol, edges) + 1}"].append(trade)  # type: ignore[attr-defined]

    # ---- evaluate --------------------------------------------------------
    results: list[SegmentResult] = []
    for family, buckets in families.items():
        # When re-sweeping one segment there is no point bootstrapping the
        # other twenty-nine, and counting them as tests again would inflate
        # the correction for a question we are not asking.
        if families_only and family not in families_only:
            continue
        for name, members in sorted(buckets.items()):
            evaluated = evaluate_segment(family, name, members, pool)
            if evaluated:
                results.append(evaluated)

    p_values = [r.p_value for r in results]
    survives_fdr = benjamini_hochberg(p_values) if p_values else []
    bonferroni_alpha = 0.05 / len(p_values) if p_values else 0.05

    rows: list[dict] = []
    for result, fdr in zip(results, survives_fdr):
        rows.append(
            {
                **result.as_dict(),
                "significant_uncorrected": result.p_value <= 0.05,
                "significant_fdr": fdr,
                "significant_bonferroni": result.p_value <= bonferroni_alpha,
            }
        )

    positive = [r for r in rows if r["excess_pct"] > 0 and not r["underpowered"]]
    best = max(positive, key=lambda r: r["excess_pct"]) if positive else None

    payload = {
        "params": pooled["params"],
        "pooled": {
            "trades": pooled["overall"]["trades"],
            "mean_return_pct": pooled["overall"]["mean_return_pct"],
            "excess_over_drift_pct": pooled["excess_over_drift_pct"],
        },
        "holding_days": holding,
        "control_pool": {"tickers": len(pool), "draws_each": POOL_PER_TICKER},
        "unclassified": dict(unclassified),
        # The headline number of this whole exercise. Every result below has to
        # be read against it.
        "segment_tests_run": len(rows),
        "correction": {
            "uncorrected_alpha": 0.05,
            "bonferroni_alpha": round(bonferroni_alpha, 6),
            "method": "Benjamini-Hochberg FDR at 0.05, plus Bonferroni",
            "significant_uncorrected": sum(1 for r in rows if r["significant_uncorrected"]),
            "significant_fdr": sum(1 for r in rows if r["significant_fdr"]),
            "significant_bonferroni": sum(1 for r in rows if r["significant_bonferroni"]),
            # With 5% of tests expected to pass uncorrected by chance alone.
            "expected_false_positives_uncorrected": round(0.05 * len(rows), 1),
        },
        "segments": rows,
        "neighbour_agreement": neighbour_check(results),
        "best_positive_segment": best,
        "underpowered_segments": [r["segment"] for r in rows if r["underpowered"]],
    }
    payload["plain_verdict"] = plain_verdict(payload)
    return payload


async def report_dates_by_ticker(
    session: AsyncSession, tickers: list[str]
) -> dict[str, list[date]]:
    """Confirmed report dates, used to keep the control away from earnings."""
    rows = (
        await session.execute(
            select(EarningsDate.ticker, EarningsDate.report_date)
            .where(
                EarningsDate.ticker.in_(tickers),
                EarningsDate.is_estimated.is_(False),
                EarningsDate.report_date.is_not(None),
            )
            .distinct()
        )
    ).all()
    out: dict[str, list[date]] = defaultdict(list)
    for ticker, report in rows:
        out[ticker].append(report)
    return {t: sorted(v) for t, v in out.items()}


def rolling_vol(bars: list[tuple[date, float]], window: int = 60) -> list[float | None]:
    """Annualised trailing volatility at every index, using only prior bars.

    O(n) with running sums rather than O(n*window), because this is computed
    for every bar of every ticker.
    """
    closes = [c for _, c in bars]
    returns: list[float] = [0.0]
    for i in range(1, len(closes)):
        returns.append(closes[i] / closes[i - 1] - 1.0 if closes[i - 1] > 0 else 0.0)

    out: list[float | None] = [None] * len(bars)
    total = squared = 0.0
    for i in range(1, len(returns)):
        total += returns[i]
        squared += returns[i] * returns[i]
        if i > window:
            total -= returns[i - window]
            squared -= returns[i - window] * returns[i - window]
        if i >= window and i + 1 < len(out):
            mean = total / window
            variance = max(squared / window - mean * mean, 0.0)
            # Written to i+1, not i. The window ends at return i, so it is the
            # volatility known to someone entering on bar i+1 — matching
            # realised_vol, which excludes the entry day. Indexing it at i
            # instead would let the control see the entry-day close and would
            # filter the control on a different definition of "high volatility"
            # than the one that selected the trades.
            out[i + 1] = (variance ** 0.5) * (252 ** 0.5) * 100.0
    return out


def matched_pool(
    series: dict[str, list[tuple[date, float]]],
    holding_days: int,
    costs: Costs,
    vol_floor: float,
    reports: dict[str, list[date]],
    exclusion_before: int = 25,
    exclusion_after: int = 5,
) -> dict[str, list[float]]:
    """A control conditioned on the same volatility state, away from earnings.

    The unmatched control asks "what did these names return at a random time?"
    For a segment selected *on* high volatility that is the wrong question,
    because high trailing volatility usually follows a drawdown and the answer
    is contaminated by mean reversion that has nothing to do with earnings.

    This control asks the question that actually separates the hypotheses:
    what did these names return over the same holding period, when they were
    equally volatile, but *not* in the run-up to a report?
    """
    rng = random.Random(20260815)
    pool: dict[str, list[float]] = {}

    for ticker, bars in series.items():
        if len(bars) < holding_days + 70:
            continue
        vols = rolling_vol(bars)
        blocked = reports.get(ticker, [])

        eligible = []
        for i in range(len(bars) - holding_days - 1):
            if vols[i] is None or vols[i] < vol_floor:
                continue
            entry_day, exit_day = bars[i][0], bars[i + holding_days][0]
            near_earnings = any(
                entry_day <= report + timedelta(days=exclusion_after)
                and exit_day >= report - timedelta(days=exclusion_before)
                for report in blocked
            )
            if not near_earnings:
                eligible.append(i)

        if len(eligible) < 5:
            continue
        draws = []
        for _ in range(POOL_PER_TICKER):
            i = eligible[rng.randrange(len(eligible))]
            entry = bars[i][1]
            if entry <= 0:
                continue
            gross = (bars[i + holding_days][1] / entry - 1.0) * 100.0
            days = (bars[i + holding_days][0] - bars[i][0]).days
            draws.append(apply_costs(gross, days, costs))
        if draws:
            pool[ticker] = draws
    return pool


# Quintile labels read as "Q5" in a table, which is fine there and useless in
# a sentence. These are the sentence forms.
QUINTILE_WORDS = {
    "realised_vol_quintile": ("calmest", "most volatile", "by how much their share price jumps around"),
    "market_cap_quintile": ("smallest", "largest", "by company size"),
}


def friendly_segment(family: str, segment: str) -> str:
    """A segment name that can be dropped into a sentence."""
    if family in QUINTILE_WORDS and segment.startswith("Q"):
        low, high, _ = QUINTILE_WORDS[family]
        rank = segment[1:]
        if rank == "1":
            return f"the {low} fifth of companies"
        if rank == "5":
            return f"the {high} fifth of companies"
        return f"the {['', 'second', 'middle', 'fourth'][int(rank) - 1]} fifth of companies"
    return segment.replace("_", " ")


def and_list(names: list[str]) -> str:
    words = [n.replace("_", " ") for n in names]
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


def plain_verdict(result: dict) -> dict:
    """Plain-English summary of a segmented run.

    The thing a reader most needs to be told here is that thirty-odd tests
    were run, because a table of segments invites reading the best row as if
    it were the only one.
    """
    from app.backtest import ILLUSTRATIVE_POSITION

    rows = result.get("segments") or []
    if not rows:
        return {
            "headline": "No segment had enough trades to say anything about.",
            "body": "",
            "worth_acting_on": False,
        }

    correction = result.get("correction", {})
    tests = result.get("segment_tests_run", len(rows))
    expected = correction.get("expected_false_positives_uncorrected", 0)
    uncorrected = correction.get("significant_uncorrected", 0)
    survived = correction.get("significant_bonferroni", 0)

    strong = [r for r in rows if r.get("significant_bonferroni") and not r["underpowered"]]
    best = max(strong, key=lambda r: r["excess_pct"]) if strong else None

    pounds = lambda pct: f"£{pct / 100 * ILLUSTRATIVE_POSITION:,.0f}"

    if best is None:
        headline = (
            f"Nothing here is worth acting on. The trades were sliced {tests} different "
            f"ways, and once you allow for the fact that trying {tests} things will throw "
            f"up a few good-looking results by chance, none of them hold up."
        )
        worth = False
    else:
        name = friendly_segment(best["family"], best["segment"])
        sorted_by = QUINTILE_WORDS.get(best["family"], (None, None, f"by {best['family'].replace('_', ' ')}"))[2]
        headline = (
            f"One slice stands out and survives the checks: {name}, sorted {sorted_by}. "
            f"Within it, the earnings timing added about {best['excess_pct']:+.2f}% per "
            f"trade over simply owning the same shares for the same number of days — "
            f"roughly {pounds(best['excess_pct'])} on a {pounds(100)} position, across "
            f"{best['trades']:,} trades."
        )
        worth = True

    parts = [
        f"The trades were split {tests} ways. If none of the slices meant anything, about "
        f"{expected:.0f} would still look convincing purely by luck; {uncorrected} did. "
        f"After demanding stronger evidence to account for how many were tried, "
        f"{survived} survived."
    ]

    isolated = [name for name, v in (result.get("neighbour_agreement") or {}).items() if v.get("isolated")]
    if isolated:
        parts.append(
            f"{and_list(isolated).capitalize()} looked good but no similar industry did, which is "
            f"usually what a fluke looks like rather than a real pattern."
        )

    thin = result.get("underpowered_segments") or []
    if thin:
        parts.append(
            f"{len(thin)} slices had too few trades to conclude anything from, however "
            f"good the number looked, and are greyed out."
        )

    parts.append(
        "As everywhere, this uses the companies in the index today, so the ones that "
        "failed along the way are missing and every figure flatters the result."
    )

    return {"headline": headline, "body": " ".join(parts), "worth_acting_on": worth}
