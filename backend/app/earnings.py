"""Earnings dates, stored point-in-time.

A future report date is a forecast that moves. Storing only the latest view
would make a backtest cheat: it would enter trades timed against a date nobody
knew at the time. So every observation is kept, and "what date was expected on
day D" is a real query.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Numeric, Text, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EarningsDate(Base):
    __tablename__ = "earnings_dates"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    observed_on: Mapped[date] = mapped_column(Date, primary_key=True)
    report_date: Mapped[date | None] = mapped_column(Date)
    is_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    before_after_market: Mapped[str | None] = mapped_column(Text)
    eps_estimate: Mapped[Decimal | None] = mapped_column(Numeric)
    eps_actual: Mapped[Decimal | None] = mapped_column(Numeric)
    revenue_estimate: Mapped[Decimal | None] = mapped_column(Numeric)
    revenue_actual: Mapped[Decimal | None] = mapped_column(Numeric)
    surprise_percent: Mapped[Decimal | None] = mapped_column(Numeric)
    source: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


async def store(session: AsyncSession, rows: list[dict]) -> int:
    for row in rows:
        statement = insert(EarningsDate).values(**row)
        # Same day, same period: refresh. A different day is a new observation
        # and lands as a new row — that is the point of the table.
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["ticker", "period_end", "observed_on"],
                set_={
                    k: statement.excluded[k]
                    for k in row
                    if k not in ("ticker", "period_end", "observed_on")
                },
            )
        )
    await session.flush()
    return len(rows)


async def latest_view(
    session: AsyncSession, ticker: str, as_of: date | None = None
) -> list[EarningsDate]:
    """The most recent observation of each period, as known on ``as_of``.

    With no as_of this is simply today's view. With one, it reconstructs what
    was on file that day — including report dates that were still forecasts.
    """
    query = select(EarningsDate).where(EarningsDate.ticker == ticker)
    if as_of is not None:
        query = query.where(EarningsDate.observed_on <= as_of)
    query = query.distinct(EarningsDate.period_end).order_by(
        EarningsDate.period_end.desc(), EarningsDate.observed_on.desc()
    )
    return list((await session.execute(query)).scalars())


async def next_report(
    session: AsyncSession, ticker: str, as_of: date | None = None
) -> EarningsDate | None:
    reference = as_of or date.today()
    rows = [
        row
        for row in await latest_view(session, ticker, as_of)
        if row.report_date and row.report_date >= reference
    ]
    return min(rows, key=lambda r: r.report_date) if rows else None


async def days_to_earnings(
    session: AsyncSession, tickers: list[str], as_of: date | None = None
) -> dict[str, int]:
    """Days until each ticker's next expected report. Missing when unknown."""
    reference = as_of or date.today()
    if not tickers:
        return {}
    rows = (
        await session.execute(
            select(
                EarningsDate.ticker,
                func.min(EarningsDate.report_date),
            )
            .where(
                EarningsDate.ticker.in_(tickers),
                EarningsDate.report_date >= reference,
                EarningsDate.observed_on <= reference,
            )
            .group_by(EarningsDate.ticker)
        )
    ).all()
    return {ticker: (report - reference).days for ticker, report in rows if report}
