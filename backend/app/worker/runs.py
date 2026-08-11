"""Job run bookkeeping.

A run records itself before it starts work and updates itself when it stops,
so a job that dies mid-flight leaves a row saying 'running' rather than no
trace at all. Silence is the failure mode we are guarding against: stale
scores that look current are worse than obviously missing ones.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Identity, Integer, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    job: Mapped[str] = mapped_column(Text, nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tickers_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tickers_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scores_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failures: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)


@dataclass
class RunTally:
    calls_used: int = 0
    tickers_updated: int = 0
    scores_written: int = 0
    failures: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(UTC)


async def start(session: AsyncSession, job: str, run_date: date) -> JobRun:
    run = JobRun(
        job=job, run_date=run_date, started_at=utc_now(), status=RUNNING
    )
    session.add(run)
    await session.flush()
    return run


async def finish(
    session: AsyncSession, run: JobRun, status: str, tally: RunTally
) -> None:
    run.finished_at = utc_now()
    run.status = status
    run.calls_used = tally.calls_used
    run.tickers_updated = tally.tickers_updated
    run.tickers_failed = len(tally.failures)
    run.scores_written = tally.scores_written
    run.failures = tally.failures or None
    run.notes = "; ".join(tally.notes) or None
    await session.flush()


async def latest(
    session: AsyncSession, job: str | None = None, limit: int = 10
) -> list[JobRun]:
    query = select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    if job is not None:
        query = query.where(JobRun.job == job)
    return list((await session.execute(query)).scalars())


async def succeeded_today(session: AsyncSession, job: str, run_date: date) -> bool:
    return bool(
        (
            await session.execute(
                select(JobRun.id)
                .where(
                    JobRun.job == job,
                    JobRun.run_date == run_date,
                    JobRun.status == SUCCEEDED,
                )
                .limit(1)
            )
        ).scalar()
    )
