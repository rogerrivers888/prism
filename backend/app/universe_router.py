"""Universe screen data: every security with its lens scores, in one request.

The per-ticker endpoint is the wrong shape for a 526-row table — that would be
526 round trips. This assembles the whole grid in a single query.
"""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
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
        await session.execute(select(Security).where(Security.is_active.is_(True)).order_by(Security.ticker))
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


class PeerCount(BaseModel):
    sector: str
    members: int
    # Below 8, percentiles fall back to absolute bands — a silent degradation
    # worth surfacing rather than leaving to be discovered in the audit trail.
    ranks_on_peers: bool


class AddSecurityIn(BaseModel):
    tickers: list[str]


@router.get("/universe/health")
async def universe_health(session: SessionDep) -> dict:
    rows = (
        await session.execute(
            select(Security.sector, func.count())
            .where(Security.is_active.is_(True))
            .group_by(Security.sector)
            .order_by(func.count().desc())
        )
    ).all()
    counts = [
        PeerCount(sector=sector, members=n, ranks_on_peers=n >= 8) for sector, n in rows
    ]
    return {
        "total": sum(c.members for c in counts),
        "sectors": counts,
        "thin_sectors": [c.sector for c in counts if not c.ranks_on_peers],
    }


@router.get("/universe/search")
async def search_securities(q: str, session: SessionDep) -> list[dict]:
    """Look a company up by name or partial symbol before adding it."""
    from app.config import settings
    from app.ingest.eodhd import EODHDProvider

    if not settings.eodhd_api_key:
        raise HTTPException(status_code=503, detail="EODHD_API_KEY is not configured")
    if len(q.strip()) < 2:
        return []

    held = set(
        (await session.execute(select(Security.ticker))).scalars()
    )
    hits = await EODHDProvider(settings.eodhd_api_key).search(q.strip())
    return [{**hit, "already_held": hit["code"] in held} for hit in hits]


@router.post("/universe/securities")
async def add_securities(body: AddSecurityIn, session: SessionDep) -> dict:
    """Ingest new tickers: metadata, prices, fundamentals, then score them.

    Deliberately synchronous and slow — a first ingest is a few seconds per
    ticker — so the UI can report real progress rather than pretending.
    """
    from app.ingest.budget import BudgetExceeded, CallBudget
    from app.ingest.eodhd import EODHDProvider
    from app.ingest.mapping import UnmappedSector
    from app.ingest.runner import sync_universe
    from app.config import settings

    if not settings.eodhd_api_key:
        raise HTTPException(status_code=503, detail="EODHD_API_KEY is not configured")

    provider = EODHDProvider(settings.eodhd_api_key)
    budget = CallBudget(session, provider.name, settings.eodhd_daily_call_budget)
    tickers = [t.strip().upper() for t in body.tickers if t.strip()]
    tickers = [t if "." in t else f"{t}.US" for t in tickers]

    try:
        report = await sync_universe(
            session, provider, budget, tickers, concurrency=4, with_dividends=True
        )
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except UnmappedSector as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await session.commit()

    summary = report.as_dict()
    return {
        "requested": summary["requested"],
        "ingested": summary["ingested"],
        "already_held": summary["skipped_already_held"],
        "failed": summary["failed"],
        "unmapped_sectors": summary["unmapped_sectors"],
        "calls_spent": summary["calls_spent"],
    }


@router.delete("/universe/securities/{ticker}")
async def remove_security(ticker: str, session: SessionDep) -> dict:
    """Soft delete. History and any events referencing it survive untouched."""
    security = await session.get(Security, ticker.upper())
    if security is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")
    security.is_active = False
    await session.commit()
    return {"ticker": security.ticker, "is_active": False}
