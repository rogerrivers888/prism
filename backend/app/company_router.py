"""Company detail: everything the deepest screen needs.

Most of this is already on disk. lens_scores_daily.inputs was built as an
audit trail — per-metric value, subscore, method, peer count and exclusion
reason — which turns out to be exactly the breakdown the UI wants, so the
drawer reads stored evidence rather than recomputing and risking a different
answer from the one that was published.
"""

from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.fundamentals import Security, metric_history_as_of, price_history_as_of
from app.lenses.base import SCORING_VERSION
from app.lenses.derived import SOURCE_METRICS, derive_all
from app.lenses.engine import (
    LENSES,
    DispersionDaily,
    LensScoreDaily,
    SectorLensDaily,
)

router = APIRouter(prefix="/company", tags=["company"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class LensDetail(BaseModel):
    lens: str
    score: float | None
    score_absolute: float | None
    relative_premium: float | None
    sector_median: float | None
    sector_median_absolute: float | None
    coverage: float
    applicable: bool
    inputs: dict


class CompanyOut(BaseModel):
    ticker: str
    name: str
    sector: str
    subsector: str | None
    exchange: str | None
    currency: str | None
    quote_currency: str | None
    market_cap: float | None
    is_active: bool
    as_of: date | None
    scoring_version: str
    dispersion: float | None
    usable_lenses: int | None
    # Which two lenses are pulling apart. 90 points of disagreement between
    # value and quality means something different from 90 between trend and
    # momentum, and the number alone cannot say which.
    highest_lens: str | None
    lowest_lens: str | None
    lenses: list[LensDetail]


@router.get("/{ticker}")
async def get_company(ticker: str, session: SessionDep, as_of: date | None = None) -> CompanyOut:
    security = await session.get(Security, ticker.upper())
    if security is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")

    if as_of is None:
        as_of = (
            await session.execute(
                select(func.max(LensScoreDaily.as_of)).where(
                    LensScoreDaily.scoring_version == SCORING_VERSION
                )
            )
        ).scalar()

    rows = {
        row.lens: row
        for row in (
            await session.execute(
                select(LensScoreDaily).where(
                    LensScoreDaily.ticker == security.ticker,
                    LensScoreDaily.as_of == as_of,
                    LensScoreDaily.scoring_version == SCORING_VERSION,
                )
            )
        ).scalars()
    }
    medians = {
        row.lens: row
        for row in (
            await session.execute(
                select(SectorLensDaily).where(
                    SectorLensDaily.sector == security.sector,
                    SectorLensDaily.as_of == as_of,
                    SectorLensDaily.scoring_version == SCORING_VERSION,
                )
            )
        ).scalars()
    }
    spread = (
        await session.execute(
            select(DispersionDaily).where(
                DispersionDaily.ticker == security.ticker,
                DispersionDaily.as_of == as_of,
                DispersionDaily.scoring_version == SCORING_VERSION,
            )
        )
    ).scalar_one_or_none()

    details: list[LensDetail] = []
    for lens in LENSES:
        row = rows.get(lens.name)
        median = medians.get(lens.name)
        details.append(
            LensDetail(
                lens=lens.name,
                score=None if row is None or row.score is None else float(row.score),
                score_absolute=(
                    None
                    if row is None or row.score_absolute is None
                    else float(row.score_absolute)
                ),
                relative_premium=(
                    None
                    if row is None or row.relative_premium is None
                    else float(row.relative_premium)
                ),
                sector_median=(
                    None
                    if median is None or median.median_score is None
                    else float(median.median_score)
                ),
                sector_median_absolute=(
                    None
                    if median is None or median.median_score_absolute is None
                    else float(median.median_score_absolute)
                ),
                coverage=0.0 if row is None else float(row.coverage),
                applicable=bool(row.applicable) if row else False,
                inputs=row.inputs if row else {},
            )
        )

    usable = [d for d in details if d.applicable and d.score is not None]
    highest = max(usable, key=lambda d: d.score).lens if usable else None
    lowest = min(usable, key=lambda d: d.score).lens if usable else None

    return CompanyOut(
        ticker=security.ticker,
        name=security.name,
        sector=security.sector,
        subsector=security.subsector,
        exchange=security.exchange,
        currency=security.currency,
        quote_currency=security.quote_currency,
        market_cap=float(security.market_cap) if security.market_cap else None,
        is_active=security.is_active,
        as_of=as_of,
        scoring_version=SCORING_VERSION,
        dispersion=(
            float(spread.dispersion)
            if spread and spread.dispersion is not None
            else None
        ),
        usable_lenses=spread.usable_lenses if spread else None,
        highest_lens=highest,
        lowest_lens=lowest,
        lenses=details,
    )


class PeerRow(BaseModel):
    ticker: str
    name: str
    is_self: bool
    score: float | None
    score_absolute: float | None
    metrics: dict


@router.get("/{ticker}/peers")
async def get_peers(
    ticker: str,
    session: SessionDep,
    lens: Annotated[str, Query()],
    as_of: date | None = None,
) -> list[PeerRow]:
    """Sector peers compared on one lens's metrics only.

    Deliberately scoped to a single lens: a table of every metric for every
    peer is a spreadsheet, not a comparison.
    """
    security = await session.get(Security, ticker.upper())
    if security is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")
    if lens not in {l.name for l in LENSES}:
        raise HTTPException(status_code=422, detail=f"unknown lens {lens}")

    if as_of is None:
        as_of = (
            await session.execute(
                select(func.max(LensScoreDaily.as_of)).where(
                    LensScoreDaily.scoring_version == SCORING_VERSION
                )
            )
        ).scalar()

    peers = (
        await session.execute(
            select(Security.ticker, Security.name).where(
                Security.sector == security.sector, Security.is_active.is_(True)
            )
        )
    ).all()
    names = {t: n for t, n in peers}

    rows = (
        await session.execute(
            select(LensScoreDaily).where(
                LensScoreDaily.ticker.in_(list(names)),
                LensScoreDaily.lens == lens,
                LensScoreDaily.as_of == as_of,
                LensScoreDaily.scoring_version == SCORING_VERSION,
            )
        )
    ).scalars()

    out = [
        PeerRow(
            ticker=row.ticker,
            name=names.get(row.ticker, row.ticker),
            is_self=row.ticker == security.ticker,
            score=None if row.score is None else float(row.score),
            score_absolute=(
                None if row.score_absolute is None else float(row.score_absolute)
            ),
            metrics=(row.inputs or {}).get("metrics", {}),
        )
        for row in rows
    ]
    out.sort(key=lambda r: (r.score is None, -(r.score or 0)))
    return out


class MetricSeries(BaseModel):
    metric: str
    points: list[tuple[str, float]]
    # Set when the metric is meaningless for this company rather than merely
    # missing, with what to look at instead.
    unavailable_reason: str | None = None
    suggested_alternative: str | None = None


RANGE_DAYS = {"12M": 400, "5Y": 1900, "MAX": 100_000}


@router.get("/{ticker}/metric-history")
async def get_metric_history(
    ticker: str,
    session: SessionDep,
    metrics: Annotated[str, Query(description="comma-separated metric names")],
    window: Annotated[Literal["12M", "5Y", "MAX"], Query(alias="range")] = "5Y",
) -> list[MetricSeries]:
    """Derived metrics recomputed at each historical reporting period.

    Ratios are not stored — they are formed at scoring time from raw line
    items — so a history is built by replaying the derivation over each
    period's trailing window. Slower than reading a stored series, but it can
    never disagree with the live score, and a formula change is reflected
    immediately without a backfill.
    """
    security = await session.get(Security, ticker.upper())
    if security is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")

    wanted = [m.strip() for m in metrics.split(",") if m.strip()][:4]
    today = date.today()
    cutoff = today - timedelta(days=RANGE_DAYS[window])

    history = (
        await metric_history_as_of(session, [security.ticker], list(SOURCE_METRICS), today)
    ).get(security.ticker, {})
    prices = (await price_history_as_of(session, [security.ticker], today, limit=20000)).get(
        security.ticker, []
    )

    periods = sorted({p for series in history.values() for p, _ in series})
    periods = [p for p in periods if p >= cutoff]

    series: dict[str, list[tuple[str, float]]] = {m: [] for m in wanted}
    for period in periods:
        sliced = {
            name: [(p, v) for p, v in values if p <= period]
            for name, values in history.items()
        }
        price_slice = [(d, c) for d, c in prices if d <= period]
        derived = derive_all(sliced, price_slice)
        for metric in wanted:
            value = derived.get(metric)
            if value is not None:
                series[metric].append((period.isoformat(), round(value, 6)))

    out = []
    for metric in wanted:
        reason = alternative = None
        if metric == "ev_ebitda" and not series[metric]:
            latest = derive_all(history, prices)
            if (latest.get("ebitda") or 0) <= 0:
                reason = (
                    "EV/EBITDA is undefined here: EBITDA is negative or zero, so the "
                    "multiple has no meaning rather than being merely high or low."
                )
                alternative = "ev_sales"
        out.append(
            MetricSeries(
                metric=metric,
                points=series[metric],
                unavailable_reason=reason,
                suggested_alternative=alternative,
            )
        )
    return out
