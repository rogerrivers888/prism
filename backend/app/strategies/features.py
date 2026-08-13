"""Point-in-time features for the strategy engine.

Everything routes through the same discipline as the lens engine: a value is
usable on date D only if it had been published by D. Prices are public the day
they print; fundamentals carry ``published_at``; lens scores are used from
their as-of date onwards.

Loaded once for a whole run and sliced per date in memory, because a gate
backtest touches two hundred rebalance dates and the alternative is two
hundred full-universe queries per strategy.
"""

import logging
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.fundamentals import Fundamental, PriceDaily, Security
from app.lenses.base import SCORING_VERSION
from app.lenses.derived import derive_all, SOURCE_METRICS
from app.lenses.engine import DispersionDaily, LensScoreDaily, SectorLensDaily

logger = logging.getLogger(__name__)

TRADING_DAYS = {"return_1m": 21, "return_3m": 63, "return_6m": 126, "return_12m": 252}

# Fundamentals needed by the composite features, over and above SOURCE_METRICS.
COMPOSITE_METRICS = (
    "net_income_quarter",
    "ebit_quarter",
    "fcf_quarter",
    "revenue",
    "gross_profit",
    "total_assets",
    "net_debt",
    "invested_capital",
    "shares_outstanding",
)


@dataclass
class Bar:
    date: date
    open: float | None
    close: float | None
    adjusted_close: float


@dataclass
class FeatureService:
    """All data for a window, held in memory, sliced per date."""

    start: date
    end: date
    securities: dict[str, Security]
    # ticker -> ascending bars
    bars: dict[str, list[Bar]]
    # ticker -> metric -> [(period_end, published_at, value)] period desc, published desc
    fundamentals: dict[str, dict[str, list[tuple[date, date, float]]]]
    # (ticker, lens) -> ascending [(as_of, score)]
    lens_scores: dict[tuple[str, str], list[tuple[date, float]]]
    lens_scores_abs: dict[tuple[str, str], list[tuple[date, float]]]
    dispersion: dict[str, list[tuple[date, float]]]
    # sector -> ascending [(as_of, cycle_median)]
    sector_cycle: dict[str, list[tuple[date, float]]]
    calendar: list[date]
    # ticker -> membership spells [(joined, left|None)]. When set, the engine
    # selects from the index AS IT WAS on each date: departed companies are
    # eligible while they were members and invisible after they left. None
    # means no membership data - the old survivor-only behaviour.
    membership: dict[str, list[tuple[date, date | None]]] | None = None
    _cache: dict = field(default_factory=dict)

    # ------------------------------------------------------------- loading

    @classmethod
    async def build(
        cls,
        session: AsyncSession,
        start: date,
        end: date,
        needed: set[str],
        tickers: list[str] | None = None,
        membership_index: str | None = None,
    ) -> "FeatureService":
        namespaces = {feature.split(":", 1)[0] for feature in needed}
        want_fundamentals = bool(
            namespaces & {"metric"}
            or {"special:piotroski_f", "special:earnings_yield_ebit",
                "special:roc_greenblatt", "price:market_cap"} & needed
        )
        want_lens = bool(namespaces & {"lens", "lens_abs"})
        want_dispersion = "special:dispersion" in needed
        want_sector_cycle = "sector:cycle_median_delta" in needed

        securities = {
            s.ticker: s
            for s in (await session.execute(select(Security))).scalars()
            if tickers is None or s.ticker in tickers
        }
        universe = list(securities)

        bars: dict[str, list[Bar]] = defaultdict(list)
        # One bulk load; the window extends a year back so 12-month returns
        # exist from the first rebalance date.
        price_rows = await session.stream(
            select(
                PriceDaily.ticker, PriceDaily.date, PriceDaily.open,
                PriceDaily.close, PriceDaily.adjusted_close,
            )
            .where(
                PriceDaily.ticker.in_(universe),
                PriceDaily.date >= start.replace(year=start.year - 2),
                PriceDaily.date <= end,
                PriceDaily.adjusted_close.is_not(None),
            )
            .order_by(PriceDaily.ticker, PriceDaily.date)
        )
        async for ticker, day, op, close, adj in price_rows:
            bars[ticker].append(Bar(day, float(op) if op else None,
                                    float(close) if close else None, float(adj)))

        fundamentals: dict[str, dict[str, list[tuple[date, date, float]]]] = {}
        if want_fundamentals:
            metrics = sorted(set(SOURCE_METRICS) | set(COMPOSITE_METRICS))
            rows = await session.stream(
                select(
                    Fundamental.ticker, Fundamental.metric, Fundamental.period_end,
                    Fundamental.published_at, Fundamental.value,
                )
                .where(
                    Fundamental.ticker.in_(universe),
                    Fundamental.metric.in_(metrics),
                    Fundamental.published_at <= end,
                )
                .order_by(
                    Fundamental.ticker, Fundamental.metric,
                    Fundamental.period_end.desc(), Fundamental.published_at.desc(),
                )
            )
            async for ticker, metric, period_end, published, value in rows:
                if value is not None:
                    fundamentals.setdefault(ticker, {}).setdefault(metric, []).append(
                        (period_end, published, float(value))
                    )

        lens_scores: dict[tuple[str, str], list[tuple[date, float]]] = defaultdict(list)
        lens_abs: dict[tuple[str, str], list[tuple[date, float]]] = defaultdict(list)
        if want_lens:
            rows = await session.stream(
                select(
                    LensScoreDaily.ticker, LensScoreDaily.lens, LensScoreDaily.as_of,
                    LensScoreDaily.score, LensScoreDaily.score_absolute,
                )
                .where(
                    LensScoreDaily.scoring_version == SCORING_VERSION,
                    LensScoreDaily.as_of <= end,
                    LensScoreDaily.applicable.is_(True),
                )
                .order_by(LensScoreDaily.as_of)
            )
            async for ticker, lens, as_of, score, score_abs in rows:
                if score is not None:
                    lens_scores[(ticker, lens)].append((as_of, float(score)))
                if score_abs is not None:
                    lens_abs[(ticker, lens)].append((as_of, float(score_abs)))

        dispersion: dict[str, list[tuple[date, float]]] = defaultdict(list)
        if want_dispersion:
            rows = await session.stream(
                select(DispersionDaily.ticker, DispersionDaily.as_of, DispersionDaily.dispersion)
                .where(
                    DispersionDaily.scoring_version == SCORING_VERSION,
                    DispersionDaily.as_of <= end,
                    DispersionDaily.dispersion.is_not(None),
                )
                .order_by(DispersionDaily.as_of)
            )
            async for ticker, as_of, value in rows:
                dispersion[ticker].append((as_of, float(value)))

        sector_cycle: dict[str, list[tuple[date, float]]] = defaultdict(list)
        if want_sector_cycle:
            # The ABSOLUTE median, necessarily: relative scores are
            # percentiles within the sector, so their sector median is ~50 by
            # construction and its change is noise around zero.
            rows = await session.stream(
                select(
                    SectorLensDaily.sector,
                    SectorLensDaily.as_of,
                    SectorLensDaily.median_score_absolute,
                )
                .where(
                    SectorLensDaily.scoring_version == SCORING_VERSION,
                    SectorLensDaily.lens == "cycle",
                    SectorLensDaily.as_of <= end,
                    SectorLensDaily.median_score_absolute.is_not(None),
                )
                .order_by(SectorLensDaily.as_of)
            )
            async for sector, as_of, value in rows:
                sector_cycle[sector].append((as_of, float(value)))

        calendar = sorted({bar.date for series in bars.values() for bar in series
                           if start <= bar.date <= end})

        membership = None
        if membership_index is not None:
            from app.ingest.constituents import membership_spells

            membership = await membership_spells(session, membership_index)

        return cls(
            start=start, end=end, securities=securities, bars=dict(bars),
            fundamentals=fundamentals, lens_scores=dict(lens_scores),
            lens_scores_abs=dict(lens_abs), dispersion=dict(dispersion),
            sector_cycle=dict(sector_cycle), calendar=calendar,
            membership=membership,
        )

    def is_member(self, ticker: str, as_of: date) -> bool:
        """Was this ticker in the index on this date? True for everything when
        no membership data is loaded."""
        if self.membership is None:
            return True
        return any(
            joined <= as_of and (left is None or left > as_of)
            for joined, left in self.membership.get(ticker, [])
        )

    # ------------------------------------------------------------- slicing

    def _bar_index(self, ticker: str, as_of: date) -> int:
        """Index of the last bar dated <= as_of, or -1."""
        series = self.bars.get(ticker, [])
        dates = self._dates_of(ticker)
        return bisect_right(dates, as_of) - 1

    def _dates_of(self, ticker: str) -> list[date]:
        key = ("dates", ticker)
        if key not in self._cache:
            self._cache[key] = [bar.date for bar in self.bars.get(ticker, [])]
        return self._cache[key]

    def fundamentals_at(self, ticker: str, as_of: date) -> dict[str, list[tuple[date, float]]]:
        """Latest-published value per period, published on or before as_of.
        Period-descending, matching metric_history_as_of."""
        out: dict[str, list[tuple[date, float]]] = {}
        for metric, rows in self.fundamentals.get(ticker, {}).items():
            series: list[tuple[date, float]] = []
            current_period: date | None = None
            for period_end, published, value in rows:
                if period_end != current_period:
                    # First row for this period is the most recently published;
                    # take the first one visible at as_of.
                    current_period = period_end
                    taken = False
                if not taken and published <= as_of:
                    series.append((period_end, value))
                    taken = True
            out[metric] = series
        return out

    @staticmethod
    def _latest(series: list[tuple[date, float]] | None) -> float | None:
        return series[0][1] if series else None

    @staticmethod
    def _ttm(series: list[tuple[date, float]] | None, offset: int = 0) -> float | None:
        """Sum of four quarters starting ``offset`` quarters back. Period-desc input."""
        if not series or len(series) < offset + 4:
            return None
        window = series[offset : offset + 4]
        return sum(v for _, v in window)

    @staticmethod
    def _asof_value(series: list[tuple[date, float]], as_of: date) -> float | None:
        """Most recent value at or before as_of from an ascending series."""
        if not series:
            return None
        index = bisect_right([d for d, _ in series], as_of) - 1
        return series[index][1] if index >= 0 else None

    # ------------------------------------------------------------- features

    def price_features(self, ticker: str, as_of: date) -> dict[str, float]:
        index = self._bar_index(ticker, as_of)
        if index < 0:
            return {}
        series = self.bars[ticker]
        closes = self._cache.setdefault(("adj", ticker),
                                        [bar.adjusted_close for bar in series])
        price = closes[index]
        out: dict[str, float] = {"price": price}

        for name, days in TRADING_DAYS.items():
            if index >= days and closes[index - days] > 0:
                out[name] = (price / closes[index - days] - 1.0) * 100.0
        # 12-1: skip the most recent month's reversal.
        if index >= 252 and closes[index - 252] > 0 and index >= 21:
            out["return_12_1"] = (closes[index - 21] / closes[index - 252] - 1.0) * 100.0

        for window, name in ((50, "ma50"), (150, "ma150"), (200, "ma200")):
            if index + 1 >= window:
                out[name] = sum(closes[index + 1 - window : index + 1]) / window
        if "ma50" in out:
            out["price_vs_ma50"] = (price / out["ma50"] - 1.0) * 100.0
        if "ma150" in out:
            out["price_vs_ma150"] = (price / out["ma150"] - 1.0) * 100.0
        if "ma200" in out:
            out["price_vs_ma200"] = (price / out["ma200"] - 1.0) * 100.0
        if "ma50" in out and "ma200" in out:
            out["ma50_vs_ma200"] = (out["ma50"] / out["ma200"] - 1.0) * 100.0
        if index + 1 >= 200 + 63:
            past = sum(closes[index + 1 - 63 - 200 : index + 1 - 63]) / 200
            if past > 0:
                out["ma200_slope_3m"] = (out["ma200"] / past - 1.0) * 100.0
        if index + 1 >= 252:
            window = closes[index + 1 - 252 : index + 1]
            high, low = max(window), min(window)
            if high > 0:
                out["pct_off_52w_high"] = (price / high - 1.0) * 100.0
            if low > 0:
                out["pct_above_52w_low"] = (price / low - 1.0) * 100.0
        return out

    def composite_features(
        self, ticker: str, as_of: date, price: float | None
    ) -> dict[str, float]:
        history = self.fundamentals_at(ticker, as_of)
        out: dict[str, float] = {}

        shares = self._latest(history.get("shares_outstanding"))
        market_cap = shares * price if (shares and price) else None
        if market_cap:
            out["market_cap"] = market_cap

        ebit = self._ttm(history.get("ebit_quarter"))
        net_debt = self._latest(history.get("net_debt"))
        if ebit is not None and market_cap:
            enterprise = market_cap + (net_debt or 0.0)
            if enterprise > 0:
                out["earnings_yield_ebit"] = ebit / enterprise * 100.0
        invested = self._latest(history.get("invested_capital"))
        if ebit is not None and invested and invested > 0:
            out["roc_greenblatt"] = ebit / invested * 100.0

        f_score = self._piotroski(history)
        if f_score is not None:
            out["piotroski_f"] = f_score
        return out

    def _piotroski(self, history) -> float | None:
        """Piotroski F-score, 8 of 9 components.

        Deviations from Piotroski (2000), stated rather than hidden: the
        current-ratio test is dropped (no current asset/liability data) and
        CFO is proxied by free cash flow, which is stricter. Scored only when
        at least six components are computable.
        """
        ni = self._ttm(history.get("net_income_quarter"))
        ni_prior = self._ttm(history.get("net_income_quarter"), offset=4)
        fcf = self._ttm(history.get("fcf_quarter"))
        assets = self._latest(history.get("total_assets"))
        assets_series = history.get("total_assets") or []
        assets_prior = assets_series[4][1] if len(assets_series) > 4 else None
        revenue = self._ttm(history.get("revenue"))
        revenue_prior = self._ttm(history.get("revenue"), offset=4)
        gross = self._ttm(history.get("gross_profit"))
        gross_prior = self._ttm(history.get("gross_profit"), offset=4)
        net_debt_series = history.get("net_debt") or []
        net_debt = self._latest(net_debt_series)
        net_debt_prior = net_debt_series[4][1] if len(net_debt_series) > 4 else None
        shares_series = history.get("shares_outstanding") or []
        shares = self._latest(shares_series)
        shares_prior = shares_series[4][1] if len(shares_series) > 4 else None

        components: list[bool] = []
        if ni is not None and assets:
            components.append(ni > 0)
        if fcf is not None:
            components.append(fcf > 0)
        if None not in (ni, ni_prior) and assets and assets_prior:
            components.append(ni / assets > ni_prior / assets_prior)
        if None not in (fcf, ni):
            components.append(fcf > ni)
        if None not in (net_debt, net_debt_prior) and assets and assets_prior:
            components.append(net_debt / assets < net_debt_prior / assets_prior)
        if None not in (gross, gross_prior, revenue, revenue_prior) and revenue and revenue_prior:
            components.append(gross / revenue > gross_prior / revenue_prior)
        if None not in (revenue, revenue_prior) and assets and assets_prior:
            components.append(revenue / assets > revenue_prior / assets_prior)
        if None not in (shares, shares_prior) and shares_prior:
            # No meaningful issuance: a 1% buffer for rounding and SBC noise.
            components.append(shares <= shares_prior * 1.01)

        if len(components) < 6:
            return None
        return float(sum(components))

    def features_for(
        self, as_of: date, needed: set[str], tickers: list[str]
    ) -> dict[str, dict[str, float]]:
        """Feature map for every ticker, at one date. Cached per (date, needs)."""
        key = (as_of, frozenset(needed))
        if key in self._cache:
            return self._cache[key]

        namespaces = {f.split(":", 1)[0] for f in needed}
        metric_names = {f.split(":", 1)[1] for f in needed if f.startswith("metric:")}
        want_composites = bool(
            {"special:piotroski_f", "special:earnings_yield_ebit",
             "special:roc_greenblatt", "price:market_cap"} & needed
        )

        out: dict[str, dict[str, float]] = {}
        for ticker in tickers:
            row: dict[str, float] = {}
            prices = self.price_features(ticker, as_of)
            if not prices:
                continue
            for feature in needed:
                namespace, _, name = feature.partition(":")
                if namespace == "price" and name in prices:
                    row[feature] = prices[name]
                elif namespace in ("lens", "lens_abs"):
                    table = self.lens_scores if namespace == "lens" else self.lens_scores_abs
                    value = self._asof_value(table.get((ticker, name), []), as_of)
                    if value is not None:
                        row[feature] = value
                elif feature == "special:dispersion":
                    value = self._asof_value(self.dispersion.get(ticker, []), as_of)
                    if value is not None:
                        row[feature] = value
                elif feature == "sector:cycle_median_delta":
                    sector = self.securities[ticker].sector
                    series = self.sector_cycle.get(sector, [])
                    dates = [d for d, _ in series]
                    idx = bisect_right(dates, as_of) - 1
                    if idx >= 1:
                        row[feature] = series[idx][1] - series[idx - 1][1]

            if metric_names:
                history = self.fundamentals_at(ticker, as_of)
                index = self._bar_index(ticker, as_of)
                closes = self._cache.get(("adj", ticker)) or [b.adjusted_close for b in self.bars[ticker]]
                dates = self._dates_of(ticker)
                price_slice = list(zip(dates[max(0, index - 399) : index + 1],
                                       closes[max(0, index - 399) : index + 1]))[::-1]
                derived = derive_all(history, price_slice)
                for name in metric_names:
                    if derived.get(name) is not None:
                        row[f"metric:{name}"] = derived[name]

            if want_composites:
                composites = self.composite_features(ticker, as_of, prices.get("price"))
                for name, value in composites.items():
                    feature = "price:market_cap" if name == "market_cap" else f"special:{name}"
                    if feature in needed:
                        row[feature] = value

            out[ticker] = row

        # rs_rank: percentile of return_12m across everything with the number.
        if "price:rs_rank" in needed:
            twelve = {t: r["price:return_12m"] if "price:return_12m" in r
                      else self.price_features(t, as_of).get("return_12m")
                      for t, r in out.items()}
            twelve = {t: v for t, v in twelve.items() if v is not None}
            ordered = sorted(twelve.values())
            n = len(ordered)
            if n > 1:
                for ticker, value in twelve.items():
                    rank = bisect_right(ordered, value)
                    out[ticker]["price:rs_rank"] = rank / n * 100.0

        self._cache[key] = out
        return out

    # ------------------------------------------------------------- calendar

    def next_trading_day(self, after: date) -> date | None:
        index = bisect_right(self.calendar, after)
        return self.calendar[index] if index < len(self.calendar) else None

    def rebalance_dates(self, frequency: str) -> list[date]:
        """First trading day of each week / month / quarter in the window."""
        out: list[date] = []
        seen: set[tuple] = set()
        for day in self.calendar:
            if frequency == "weekly":
                key = day.isocalendar()[:2]
            elif frequency == "monthly":
                key = (day.year, day.month)
            else:
                key = (day.year, (day.month - 1) // 3)
            if key not in seen:
                seen.add(key)
                out.append(day)
        return out

    def open_price(self, ticker: str, day: date) -> float | None:
        """Adjusted open for fills: raw open scaled by the day's adjustment
        factor, so fills live in the same total-return space as the equity
        curve."""
        index = self._bar_index(ticker, day)
        if index < 0:
            return None
        bar = self.bars[ticker][index]
        if bar.date != day:
            return None
        if bar.open and bar.close and bar.close > 0:
            return bar.open * (bar.adjusted_close / bar.close)
        return bar.adjusted_close
