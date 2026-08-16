"""Light intraday IG poll.

Separate entry point from the nightly job so it can be scheduled on its own
cron — a few times during UK market hours — without dragging the whole
pipeline along. Positions only.
"""

import asyncio
import logging
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.ig.jobs import run_intraday
from app.worker import runs
from app.worker.runs import FAILED, SUCCEEDED, RunTally

logger = logging.getLogger(__name__)

JOB_NAME = "ig_intraday"


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    engine = create_async_engine(settings.async_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            run_date = datetime.now(UTC).date()
            run = await runs.start(session, JOB_NAME, run_date)
            await session.commit()

            report = await run_intraday(session)
            await session.commit()

            tally = RunTally()
            tally.notes.append(str(report.as_dict()))
            if report.errors:
                # Fail loudly: a Book quietly showing yesterday's positions as
                # today's is worse than one that admits it could not refresh.
                tally.failures = {"ig": "; ".join(report.errors)}
                await runs.finish(session, run, FAILED, tally)
                await session.commit()
                logger.error("ig intraday failed: %s", report.errors)
                return 1

            await runs.finish(session, run, SUCCEEDED, tally)
            await session.commit()
            logger.info("ig intraday: %s", report.as_dict())
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
