"""DEV-ONLY ingest endpoints. Remove once a scheduler drives ingest."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.ingest.budget import BudgetExceeded, CallBudget
from app.ingest.eodhd import EODHDProvider
from app.ingest.jobs import (
    SEED_UNIVERSE,
    sync_dividends,
    sync_fundamentals,
    sync_prices,
    sync_securities,
)
from app.ingest.mapping import UnmappedSector

router = APIRouter(prefix="/dev/ingest", tags=["dev (temporary)"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
DryRun = Annotated[bool, Query(description="Show what would be fetched, spend nothing")]


def _provider() -> EODHDProvider:
    if not settings.eodhd_api_key:
        raise HTTPException(status_code=503, detail="EODHD_API_KEY is not configured")
    return EODHDProvider(settings.eodhd_api_key)


def _budget(session: AsyncSession) -> CallBudget:
    return CallBudget(session, "eodhd", settings.eodhd_daily_call_budget)


@router.get("/budget")
async def get_budget(session: SessionDep) -> dict:
    budget = _budget(session)
    return {
        "provider": "eodhd",
        "limit": budget.limit,
        "used_today": await budget.used(),
        "remaining": await budget.remaining(),
    }


@router.post("/securities")
async def ingest_securities(
    session: SessionDep,
    dry_run: DryRun = False,
    force: bool = False,
    tickers: Annotated[list[str] | None, Query()] = None,
) -> dict:
    try:
        results = await sync_securities(
            session, _provider(), _budget(session),
            tickers=tickers or list(SEED_UNIVERSE), dry_run=dry_run, force=force,
        )
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except UnmappedSector as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not dry_run:
        await session.commit()
    return {"results": [r.as_dict() for r in results]}


@router.post("/prices/{ticker}")
async def ingest_prices(
    ticker: str,
    session: SessionDep,
    dry_run: DryRun = False,
    force: bool = False,
    from_date: Annotated[date | None, Query(alias="from")] = None,
) -> dict:
    try:
        result = await sync_prices(
            session, _provider(), _budget(session), ticker,
            from_date=from_date, dry_run=dry_run, force=force,
        )
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    if not dry_run:
        await session.commit()
    return result.as_dict()


@router.post("/dividends/{ticker}")
async def ingest_dividends(
    ticker: str, session: SessionDep, dry_run: DryRun = False, force: bool = False
) -> dict:
    try:
        result = await sync_dividends(
            session, _provider(), _budget(session), ticker,
            dry_run=dry_run, force=force,
        )
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    if not dry_run:
        await session.commit()
    return result.as_dict()


@router.post("/fundamentals/{ticker}")
async def ingest_fundamentals(
    ticker: str, session: SessionDep, dry_run: DryRun = False, force: bool = False
) -> dict:
    try:
        result = await sync_fundamentals(
            session, _provider(), _budget(session), ticker,
            dry_run=dry_run, force=force,
        )
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    if not dry_run:
        await session.commit()
    return result.as_dict()
