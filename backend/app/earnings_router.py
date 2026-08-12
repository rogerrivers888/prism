"""Earnings endpoints.

Reads always go through the point-in-time view, so what comes back is what was
known on the date asked for rather than what is known now.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import earnings as earnings_module
from app.db import get_session
from app.fundamentals import Security

router = APIRouter(prefix="/earnings", tags=["earnings"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class EarningsRow(BaseModel):
    period_end: date
    report_date: date | None
    is_estimated: bool
    before_after_market: str | None
    eps_estimate: float | None
    eps_actual: float | None
    surprise_percent: float | None
    observed_on: date


class EarningsOut(BaseModel):
    ticker: str
    as_of: date
    next_report_date: date | None
    next_is_estimated: bool | None
    days_to_earnings: int | None
    history: list[EarningsRow]


@router.get("/{ticker}")
async def get_earnings(
    ticker: str,
    session: SessionDep,
    as_of: date | None = None,
    limit: Annotated[int, Query(le=40)] = 8,
) -> EarningsOut:
    security = await session.get(Security, ticker.upper())
    if security is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")

    today = as_of or date.today()
    rows = await earnings_module.latest_view(session, security.ticker, today)
    upcoming = await earnings_module.next_report(session, security.ticker, today)

    reported = [r for r in rows if not r.is_estimated and r.report_date]
    reported.sort(key=lambda r: r.report_date, reverse=True)

    def as_float(value):
        return None if value is None else float(value)

    return EarningsOut(
        ticker=security.ticker,
        as_of=today,
        next_report_date=upcoming.report_date if upcoming else None,
        next_is_estimated=upcoming.is_estimated if upcoming else None,
        days_to_earnings=(
            (upcoming.report_date - today).days if upcoming and upcoming.report_date else None
        ),
        history=[
            EarningsRow(
                period_end=r.period_end,
                report_date=r.report_date,
                is_estimated=r.is_estimated,
                before_after_market=r.before_after_market,
                eps_estimate=as_float(r.eps_estimate),
                eps_actual=as_float(r.eps_actual),
                surprise_percent=as_float(r.surprise_percent),
                observed_on=r.observed_on,
            )
            for r in reported[:limit]
        ],
    )
