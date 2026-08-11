"""One-off universe backfill: `python -m app.ingest.backfill`.

Run inside the deployed container so it uses the internal database URL and
does not depend on anyone's laptop staying connected. Resumable — rerunning
skips tickers whose raw payload is already archived, so an interrupted
backfill continues rather than restarting.
"""

import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.ingest.budget import CallBudget
from app.ingest.eodhd import EODHDProvider
from app.ingest.runner import sync_universe
from app.ingest.universe import (
    NASDAQ100_INDEX,
    SEMICONDUCTOR_PEERS,
    SP500_INDEX,
    UK_HOLDINGS,
    combine,
    components_from_index,
)

logger = logging.getLogger(__name__)


async def resolve_universe(session, provider: EODHDProvider, budget: CallBudget):
    """Index membership from the provider, so it stays current."""
    await budget.spend(2)
    sp500 = await provider.fetch_fundamentals(SP500_INDEX)
    nasdaq = await provider.fetch_fundamentals(NASDAQ100_INDEX)
    await session.commit()
    return combine(
        components_from_index(sp500.payload),
        components_from_index(nasdaq.payload),
        UK_HOLDINGS,
        SEMICONDUCTOR_PEERS,
    )


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not settings.eodhd_api_key:
        print("EODHD_API_KEY is not configured", file=sys.stderr)
        return 1

    engine = create_async_engine(settings.async_database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            provider = EODHDProvider(settings.eodhd_api_key)
            budget = CallBudget(
                session, provider.name, settings.eodhd_daily_call_budget
            )
            tickers = await resolve_universe(session, provider, budget)
            logger.info("universe resolved: %d tickers", len(tickers))

            report = await sync_universe(
                session, provider, budget, tickers, concurrency=6, with_dividends=True
            )
            await session.commit()

            summary = report.as_dict()
            logger.info("BACKFILL COMPLETE %s", {
                k: summary[k]
                for k in (
                    "requested", "skipped_already_held", "ingested", "calls_spent",
                    "price_rows", "fundamental_rows", "dividend_rows", "consensus_rows",
                )
            })
            if summary["failed"]:
                logger.warning("failures: %s", summary["failed"])
            if summary["unmapped_sectors"]:
                logger.warning("unmapped sectors: %s", summary["unmapped_sectors"])
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
