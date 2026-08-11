"""Point-in-time access to fundamentals.

Every figure carries ``published_at``: the date it became publicly known.
Restatements arrive as new rows with a later published_at, never as updates.

Scoring for date D must see only what was knowable on D. This module is the
only sanctioned way to read the table, and every function here takes ``as_of``
as a required argument and applies ``published_at <= as_of`` itself — there is
no exported query builder that could be called without it. Do not add one:
a select() on Fundamental at a call site is exactly the bug this prevents.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Security(Base):
    __tablename__ = "securities"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sector: Mapped[str] = mapped_column(Text, nullable=False)


class Fundamental(Base):
    __tablename__ = "fundamentals"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    metric: Mapped[str] = mapped_column(Text, primary_key=True)
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    published_at: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric)
    source: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


async def metrics_as_of(
    session: AsyncSession, tickers: list[str], as_of: date
) -> dict[str, dict[str, float]]:
    """Latest known value of every metric for each ticker, as known on as_of.

    For each (ticker, metric) this takes the most recent period_end that had
    been published by as_of, and within that period the most recently
    published figure — so a restatement supersedes the original only from its
    own published_at onwards.
    """
    if not tickers:
        return {}

    rows = await session.execute(
        select(
            Fundamental.ticker,
            Fundamental.metric,
            Fundamental.value,
        )
        .where(
            Fundamental.published_at <= as_of,
            Fundamental.ticker.in_(tickers),
        )
        .distinct(Fundamental.ticker, Fundamental.metric)
        .order_by(
            Fundamental.ticker,
            Fundamental.metric,
            Fundamental.period_end.desc(),
            Fundamental.published_at.desc(),
        )
    )

    out: dict[str, dict[str, float]] = {t: {} for t in tickers}
    for ticker, metric, value in rows:
        if value is not None:
            out[ticker][metric] = float(value)
    return out


async def metric_history_as_of(
    session: AsyncSession, tickers: list[str], metrics: list[str], as_of: date
) -> dict[str, dict[str, list[tuple[date, float]]]]:
    """Every period of the named metrics that had been published by as_of.

    Same point-in-time contract as ``metrics_as_of``, but keeps the periods
    apart instead of collapsing to the latest one, so year-on-year changes can
    be derived. Within each period the most recently published figure wins, so
    a restatement supersedes the original only from its own published_at.

    Returned newest period first, per metric.
    """
    if not tickers or not metrics:
        return {}

    rows = await session.execute(
        select(
            Fundamental.ticker,
            Fundamental.metric,
            Fundamental.period_end,
            Fundamental.value,
        )
        .where(
            Fundamental.published_at <= as_of,
            Fundamental.ticker.in_(tickers),
            Fundamental.metric.in_(metrics),
        )
        .distinct(Fundamental.ticker, Fundamental.metric, Fundamental.period_end)
        .order_by(
            Fundamental.ticker,
            Fundamental.metric,
            Fundamental.period_end.desc(),
            Fundamental.published_at.desc(),
        )
    )

    out: dict[str, dict[str, list[tuple[date, float]]]] = {t: {} for t in tickers}
    for ticker, metric, period_end, value in rows:
        if value is not None:
            out[ticker].setdefault(metric, []).append((period_end, float(value)))
    return out


async def sector_of(session: AsyncSession, ticker: str) -> str | None:
    return (
        await session.execute(
            select(Security.sector).where(Security.ticker == ticker)
        )
    ).scalar_one_or_none()


async def tickers_in_sector(session: AsyncSession, sector: str) -> list[str]:
    return list(
        (
            await session.execute(
                select(Security.ticker)
                .where(Security.sector == sector)
                .order_by(Security.ticker)
            )
        ).scalars()
    )


async def all_securities(session: AsyncSession) -> list[Security]:
    return list(
        (await session.execute(select(Security).order_by(Security.ticker))).scalars()
    )
