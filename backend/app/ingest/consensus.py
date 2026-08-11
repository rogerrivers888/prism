"""Accumulated consensus estimates.

The provider gives today's consensus and no history of it. Rather than lose
that, every observation is appended with the date it was seen. A row is never
overwritten by a later observation, so in twelve months this is a revision
history nobody sold us.
"""

from datetime import date

from sqlalchemy import Date, Numeric, Text, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.ingest.protocol import ConsensusRow


class ConsensusEstimate(Base):
    __tablename__ = "consensus_estimates"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    observed_on: Mapped[date] = mapped_column(Date, primary_key=True)
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    period_label: Mapped[str | None] = mapped_column(Text)
    eps_avg: Mapped[float | None] = mapped_column(Numeric)
    eps_low: Mapped[float | None] = mapped_column(Numeric)
    eps_high: Mapped[float | None] = mapped_column(Numeric)
    eps_year_ago: Mapped[float | None] = mapped_column(Numeric)
    analysts: Mapped[float | None] = mapped_column(Numeric)
    eps_7d_ago: Mapped[float | None] = mapped_column(Numeric)
    eps_30d_ago: Mapped[float | None] = mapped_column(Numeric)
    eps_60d_ago: Mapped[float | None] = mapped_column(Numeric)
    eps_90d_ago: Mapped[float | None] = mapped_column(Numeric)
    revenue_avg: Mapped[float | None] = mapped_column(Numeric)
    source: Mapped[str | None] = mapped_column(Text)


async def store(session: AsyncSession, rows: list[ConsensusRow]) -> int:
    """Append observations. Re-running on the same day is a no-op, not a wipe."""
    for row in rows:
        statement = insert(ConsensusEstimate).values(
            ticker=row.ticker,
            observed_on=row.observed_on,
            period_end=row.period_end,
            period_label=row.period_label,
            eps_avg=row.eps_avg,
            eps_low=row.eps_low,
            eps_high=row.eps_high,
            eps_year_ago=row.eps_year_ago,
            analysts=row.analysts,
            eps_7d_ago=row.eps_7d_ago,
            eps_30d_ago=row.eps_30d_ago,
            eps_60d_ago=row.eps_60d_ago,
            eps_90d_ago=row.eps_90d_ago,
            revenue_avg=row.revenue_avg,
            source=row.source,
        )
        # Same day, same period: refresh in place. A different day is a new
        # observation and lands as a new row, which is the whole point.
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["ticker", "observed_on", "period_end"],
                set_={
                    "eps_avg": statement.excluded.eps_avg,
                    "eps_low": statement.excluded.eps_low,
                    "eps_high": statement.excluded.eps_high,
                    "eps_year_ago": statement.excluded.eps_year_ago,
                    "analysts": statement.excluded.analysts,
                    "eps_7d_ago": statement.excluded.eps_7d_ago,
                    "eps_30d_ago": statement.excluded.eps_30d_ago,
                    "eps_60d_ago": statement.excluded.eps_60d_ago,
                    "eps_90d_ago": statement.excluded.eps_90d_ago,
                    "revenue_avg": statement.excluded.revenue_avg,
                },
            )
        )
    await session.flush()
    return len(rows)


async def observation_dates(session: AsyncSession, ticker: str) -> list[date]:
    return list(
        (
            await session.execute(
                select(ConsensusEstimate.observed_on)
                .where(ConsensusEstimate.ticker == ticker)
                .distinct()
                .order_by(ConsensusEstimate.observed_on)
            )
        ).scalars()
    )
