"""Universe screen data: every security with its lens scores, in one request.

The per-ticker endpoint is the wrong shape for a 526-row table — that would be
526 round trips. This assembles the whole grid in a single query.
"""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.fundamentals import Security
from app.lenses.base import SCORING_VERSION
from app.lenses.engine import DispersionDaily, LensScoreDaily

router = APIRouter(tags=["universe"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Market-cap buckets, in the reporting currency as stored. Rough by design:
# they exist to group a table, not to price anything.
SIZE_BANDS = (
    (200e9, "mega"),
    (10e9, "large"),
    (2e9, "mid"),
)


def size_band(market_cap: float | None) -> str:
    if market_cap is None:
        return "unknown"
    for threshold, label in SIZE_BANDS:
        if market_cap >= threshold:
            return label
    return "small"


class LensCell(BaseModel):
    # NULL is a real answer, not a zero: coverage says why.
    score: float | None
    score_absolute: float | None
    coverage: float
    applicable: bool


class UniverseRow(BaseModel):
    ticker: str
    name: str
    sector: str
    subsector: str | None
    size: str
    currency: str | None
    quote_currency: str | None
    market_cap: float | None
    dispersion: float | None
    usable_lenses: int | None
    lenses: dict[str, LensCell]


class UniverseOut(BaseModel):
    as_of: date | None
    scoring_version: str
    # Newest score-write time across the set, and its age in days, so the UI
    # can say out loud that it is showing yesterday's numbers.
    computed_at: datetime | None
    stale_days: int | None
    count: int
    rows: list[UniverseRow]


@router.get("/universe")
async def get_universe(session: SessionDep, as_of: date | None = None) -> UniverseOut:
    if as_of is None:
        as_of = (
            await session.execute(
                select(func.max(LensScoreDaily.as_of)).where(
                    LensScoreDaily.scoring_version == SCORING_VERSION
                )
            )
        ).scalar()

    securities = (
        await session.execute(select(Security).order_by(Security.ticker))
    ).scalars().all()

    scores: dict[str, dict[str, LensCell]] = {}
    newest: datetime | None = None
    if as_of is not None:
        rows = await session.execute(
            select(LensScoreDaily).where(
                LensScoreDaily.as_of == as_of,
                LensScoreDaily.scoring_version == SCORING_VERSION,
            )
        )
        for row in rows.scalars():
            scores.setdefault(row.ticker, {})[row.lens] = LensCell(
                score=None if row.score is None else float(row.score),
                score_absolute=(
                    None if row.score_absolute is None else float(row.score_absolute)
                ),
                coverage=float(row.coverage),
                applicable=row.applicable,
            )
            if row.computed_at and (newest is None or row.computed_at > newest):
                newest = row.computed_at

    spreads: dict[str, DispersionDaily] = {}
    if as_of is not None:
        spread_rows = await session.execute(
            select(DispersionDaily).where(
                DispersionDaily.as_of == as_of,
                DispersionDaily.scoring_version == SCORING_VERSION,
            )
        )
        spreads = {r.ticker: r for r in spread_rows.scalars()}

    out = []
    for security in securities:
        spread = spreads.get(security.ticker)
        out.append(
            UniverseRow(
                ticker=security.ticker,
                name=security.name,
                sector=security.sector,
                subsector=security.subsector,
                size=size_band(
                    float(security.market_cap) if security.market_cap else None
                ),
                currency=security.currency,
                quote_currency=security.quote_currency,
                market_cap=(
                    float(security.market_cap) if security.market_cap else None
                ),
                dispersion=(
                    float(spread.dispersion)
                    if spread and spread.dispersion is not None
                    else None
                ),
                usable_lenses=spread.usable_lenses if spread else None,
                lenses=scores.get(security.ticker, {}),
            )
        )

    return UniverseOut(
        as_of=as_of,
        scoring_version=SCORING_VERSION,
        computed_at=newest,
        stale_days=(
            None if newest is None else (datetime.now(UTC) - newest).days
        ),
        count=len(out),
        rows=out,
    )
