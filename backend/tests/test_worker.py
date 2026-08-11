"""Daily job: resumability, idempotence and loud failure."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select, text

from app.ingest.consensus import ConsensusEstimate
from app.worker import runs
from app.worker.daily import JOB_NAME, tickers_done_today

RUN_DATE = date(2026, 8, 12)


@pytest.fixture(autouse=True)
async def clean_jobs(session):
    await session.execute(text("TRUNCATE job_runs, consensus_estimates"))
    yield
    await session.rollback()


async def test_a_successful_run_is_recorded_and_makes_the_day_a_no_op(session):
    assert await runs.succeeded_today(session, JOB_NAME, RUN_DATE) is False

    record = await runs.start(session, JOB_NAME, RUN_DATE)
    assert record.status == runs.RUNNING
    # A run that dies here leaves 'running' behind rather than no trace.

    tally = runs.RunTally(calls_used=1054, tickers_updated=527, scores_written=3162)
    await runs.finish(session, record, runs.SUCCEEDED, tally)
    await session.commit()

    assert await runs.succeeded_today(session, JOB_NAME, RUN_DATE) is True
    # A different day is still outstanding.
    assert await runs.succeeded_today(session, JOB_NAME, date(2026, 8, 13)) is False


async def test_a_failed_run_does_not_mark_the_day_done(session):
    record = await runs.start(session, JOB_NAME, RUN_DATE)
    await runs.finish(
        session, record, runs.FAILED, runs.RunTally(failures={"MU.US": "boom"})
    )
    await session.commit()

    # Must not be treated as complete, or the failure would be papered over
    # by the next run declining to do anything.
    assert await runs.succeeded_today(session, JOB_NAME, RUN_DATE) is False
    latest = (await runs.latest(session, job=JOB_NAME))[0]
    assert latest.status == runs.FAILED
    assert latest.tickers_failed == 1
    assert latest.failures == {"MU.US": "boom"}


async def test_resume_skips_tickers_that_already_have_todays_snapshot(session):
    assert await tickers_done_today(session, RUN_DATE) == set()

    session.add(
        ConsensusEstimate(
            ticker="MU",
            observed_on=RUN_DATE,
            period_end=date(2026, 8, 31),
            period_label="0y",
            eps_avg=100.0,
        )
    )
    # Yesterday's snapshot for another ticker must not count as done today.
    session.add(
        ConsensusEstimate(
            ticker="NVDA",
            observed_on=date(2026, 8, 11),
            period_end=date(2026, 8, 31),
            period_label="0y",
            eps_avg=50.0,
        )
    )
    await session.flush()

    done = await tickers_done_today(session, RUN_DATE)
    assert done == {"MU"}


async def test_run_history_is_ordered_newest_first(session):
    for day in (date(2026, 8, 10), date(2026, 8, 11), RUN_DATE):
        record = await runs.start(session, JOB_NAME, day)
        await runs.finish(session, record, runs.SUCCEEDED, runs.RunTally())
    await session.commit()

    history = await runs.latest(session, job=JOB_NAME, limit=3)
    assert [r.run_date for r in history] == [RUN_DATE, date(2026, 8, 11), date(2026, 8, 10)]
