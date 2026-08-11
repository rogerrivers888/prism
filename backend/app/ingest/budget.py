"""Per-day API call budgeting, persisted so it survives restarts."""

import logging
from datetime import UTC, date, datetime

from sqlalchemy import Date, Integer, Text, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Refusing to spend a call that would breach the daily budget."""


class ApiCallUsage(Base):
    __tablename__ = "api_call_usage"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    call_date: Mapped[date] = mapped_column(Date, primary_key=True)
    calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def utc_today() -> date:
    return datetime.now(UTC).date()


class CallBudget:
    """Tracks and enforces call spend for one provider on one UTC day."""

    def __init__(self, session: AsyncSession, provider: str, limit: int) -> None:
        self.session = session
        self.provider = provider
        self.limit = limit

    async def used(self, on: date | None = None) -> int:
        return (
            await self.session.execute(
                select(ApiCallUsage.calls_used).where(
                    ApiCallUsage.provider == self.provider,
                    ApiCallUsage.call_date == (on or utc_today()),
                )
            )
        ).scalar() or 0

    async def remaining(self) -> int:
        return max(0, self.limit - await self.used())

    async def check(self, calls: int) -> None:
        """Raise if spending ``calls`` would breach the budget, without spending."""
        remaining = await self.remaining()
        if calls > remaining:
            raise BudgetExceeded(
                f"{self.provider}: {calls} call(s) requested but only "
                f"{remaining} of {self.limit} remain today"
            )

    async def spend(self, calls: int = 1) -> int:
        """Record ``calls`` against today's budget, refusing to overspend.

        Checked and recorded in one place so a caller cannot fetch first and
        account for it afterwards. Returns the remaining budget.
        """
        await self.check(calls)
        statement = insert(ApiCallUsage).values(
            provider=self.provider, call_date=utc_today(), calls_used=calls
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["provider", "call_date"],
                set_={"calls_used": ApiCallUsage.calls_used + calls},
            )
        )
        await self.session.flush()
        remaining = await self.remaining()
        logger.info(
            "%s: spent %d call(s), %d of %d remaining today",
            self.provider,
            calls,
            remaining,
            self.limit,
        )
        return remaining
