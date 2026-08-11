"""Job visibility. Answers "did last night work?" without reading logs."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.worker import runs

router = APIRouter(prefix="/jobs", tags=["jobs"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class JobRunOut(BaseModel):
    job: str
    run_date: object
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: float | None
    calls_used: int
    tickers_updated: int
    tickers_failed: int
    scores_written: int
    failures: dict | None
    notes: str | None
    # True when a run started and never reported back — it died mid-flight.
    # Distinguished from an outright failure, which at least recorded itself.
    stalled: bool


def _as_out(row) -> JobRunOut:
    duration = (
        (row.finished_at - row.started_at).total_seconds()
        if row.finished_at
        else None
    )
    stalled = row.status == runs.RUNNING and (
        datetime.now(UTC) - row.started_at
    ).total_seconds() > 6 * 3600
    return JobRunOut(
        job=row.job,
        run_date=row.run_date,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        duration_seconds=duration,
        calls_used=row.calls_used,
        tickers_updated=row.tickers_updated,
        tickers_failed=row.tickers_failed,
        scores_written=row.scores_written,
        failures=row.failures,
        notes=row.notes,
        stalled=stalled,
    )


@router.get("")
async def list_runs(session: SessionDep, job: str | None = None, limit: int = 10) -> list[JobRunOut]:
    return [_as_out(r) for r in await runs.latest(session, job=job, limit=limit)]
