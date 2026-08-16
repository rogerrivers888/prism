"""The nightly job.

Runs as its own Railway service on a cron schedule, not as a thread inside the
API process — a long ingest must not compete with request handling, and a
crash in one must not take down the other.

Order matters: data in, then scores derived from it, then the projection.
Every step is idempotent, so re-running the same day corrects rather than
duplicates. Resumability is keyed on the consensus observation: a ticker that
already has today's snapshot has been through the whole per-ticker path, so a
restart skips it instead of spending the calls again.

Failure is loud. The run is recorded as failed, the process exits non-zero so
Railway shows it red, and lens_scores_daily.computed_at lets any reader see
how old the numbers actually are.
"""

import asyncio
import logging
import os
import sys
from datetime import UTC, date, datetime

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.fundamentals import Security
from app.ingest import archive as archive_module
from app.ingest import consensus as consensus_module
from app import earnings as earnings_module
from app.ingest.budget import BudgetExceeded, CallBudget
from app.ingest.consensus import ConsensusEstimate
from app.ingest.eodhd import EODHDProvider
from app.ingest.jobs import _upsert_fundamentals, _upsert_security, bare
from app.ingest.mapping import UnmappedSector
from app.ingest.protocol import MarketDataProvider
from app.ingest.runner import _insert_prices
from app.ingest.universe import provider_ticker
from app.lenses.engine import score_universe
from app.projections import catch_up
from app.worker import runs

logger = logging.getLogger(__name__)

JOB_NAME = "daily"

# Fetch several tickers at once, persist one at a time: an AsyncSession is not
# safe to share across tasks.
CONCURRENCY = 6

# Above this share of the universe failing, the run is not "mostly fine" — it
# is broken, and should say so rather than quietly writing scores from
# half-updated data.
FAILURE_THRESHOLD = 0.10


async def tickers_done_today(session, run_date: date) -> set[str]:
    """Tickers already carrying today's consensus snapshot.

    That snapshot is written at the end of a ticker's per-ticker work, so its
    presence means the whole path completed. Cheap, and it makes a restart
    skip finished work without a separate progress table.
    """
    return set(
        (
            await session.execute(
                select(distinct(ConsensusEstimate.ticker)).where(
                    ConsensusEstimate.observed_on == run_date
                )
            )
        ).scalars()
    )


async def _fetch_one(provider: MarketDataProvider, ticker: str, since: date | None):
    """Network work for one ticker. Concurrent; touches no session."""
    fundamentals = await provider.fetch_fundamentals(ticker)
    prices = await provider.fetch_prices(ticker, since)
    return fundamentals, prices


async def _persist_one(
    session, provider: MarketDataProvider, ticker: str, payloads, run_date: date
) -> None:
    symbol = bare(ticker)
    fundamentals, prices = payloads

    await archive_module.archive(
        session, provider.name, "fundamentals", ticker, fundamentals.payload
    )
    await archive_module.archive(session, provider.name, "eod", ticker, prices.payload)

    record = provider.parse_security(symbol, fundamentals.payload)
    await _upsert_security(session, record)

    # A new filing simply appears here as new period rows; nothing needs to
    # detect it separately, because the payload is fetched anyway for the
    # consensus snapshot below.
    await _upsert_fundamentals(
        session, provider.parse_fundamentals(symbol, fundamentals.payload)
    )

    bars = provider.parse_prices(symbol, prices.payload)
    if bars:
        await _insert_prices(session, bars, record.quote_currency)

    # Last, and the reason the whole payload is refetched daily: Earnings
    # ::Trend is a snapshot that can never be reconstructed after the fact.
    # Its presence is also this ticker's done-marker for today.
    await consensus_module.store(
        session, provider.parse_consensus(symbol, fundamentals.payload, run_date)
    )
    # Re-observed nightly so the drift of a forecast date is itself recorded.
    await earnings_module.store(
        session, provider.parse_earnings(symbol, fundamentals.payload, run_date)
    )
    await session.flush()


async def run(session, provider: MarketDataProvider, run_date: date) -> runs.RunTally:
    tally = runs.RunTally()
    budget = CallBudget(session, provider.name, settings.eodhd_daily_call_budget)

    # Membership first: one call, and departures must keep arriving nightly or
    # the corrected universe silently reverts to a survivor list at the edge.
    try:
        from app.ingest import constituents as constituents_module

        await budget.spend(1)
        membership_report = await constituents_module.sync_index(session, provider)
        await session.commit()
        tally.notes.append(f"membership: {membership_report}")
    except Exception as exc:  # noqa: BLE001 - membership staleness must not stop prices
        await session.rollback()
        tally.notes.append(f"membership sync FAILED: {type(exc).__name__}: {exc}")
        logger.exception("membership sync failed")

    securities = list(
        (await session.execute(select(Security).order_by(Security.ticker))).scalars()
    )
    if not securities:
        raise RuntimeError(
            "no securities to update — run the backfill before the daily job"
        )

    done = await tickers_done_today(session, run_date)
    outstanding = [s for s in securities if s.ticker not in done]
    if done:
        tally.notes.append(f"resumed, {len(done)} tickers already done today")

    def routed(security: Security) -> str:
        return provider_ticker(security.ticker, security.exchange)

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def guarded(security: Security):
        async with semaphore:
            ticker = routed(security)
            try:
                # Incremental: resume from the last bar held rather than
                # refetching four decades every night.
                return security, await _fetch_one(provider, ticker, None), None
            except Exception as exc:  # noqa: BLE001
                return security, None, f"{type(exc).__name__}: {exc}"

    for start in range(0, len(outstanding), CONCURRENCY):
        chunk = outstanding[start : start + CONCURRENCY]
        try:
            await budget.check(len(chunk) * 2)
        except BudgetExceeded as exc:
            tally.failures["_budget"] = str(exc)
            break

        for security, payloads, error in await asyncio.gather(
            *(guarded(s) for s in chunk)
        ):
            ticker = routed(security)
            if error is not None:
                tally.failures[ticker] = error
                logger.warning("daily: fetch failed for %s: %s", ticker, error)
                continue
            try:
                # Savepoint per ticker: one bad payload must not discard the
                # siblings already written in this chunk.
                async with session.begin_nested():
                    await _persist_one(session, provider, ticker, payloads, run_date)
                await budget.spend(2)
                tally.calls_used += 2
                tally.tickers_updated += 1
            except UnmappedSector as exc:
                tally.failures[ticker] = f"unmapped sector: {exc}"
            except Exception as exc:  # noqa: BLE001
                tally.failures[ticker] = f"persist {type(exc).__name__}: {exc}"
                logger.warning("daily: persist failed for %s: %s", ticker, exc)
        await session.commit()
        logger.info(
            "daily: %d/%d updated, %d failed",
            tally.tickers_updated,
            len(outstanding),
            len(tally.failures),
        )

    failure_rate = len(tally.failures) / max(len(securities), 1)
    if failure_rate > FAILURE_THRESHOLD:
        raise RuntimeError(
            f"{len(tally.failures)} of {len(securities)} tickers failed "
            f"({failure_rate:.0%}) — refusing to publish scores from "
            "half-updated data"
        )

    # Scores, sector aggregates and dispersion are all written here, keyed on
    # (ticker, as_of, lens, version), so this overwrites in place.
    tally.scores_written = await score_universe(session, run_date)
    await session.commit()
    tally.notes.append(f"scored {tally.scores_written} lens rows")

    applied = await catch_up(session)
    await session.commit()
    tally.notes.append(f"projection applied {applied} events")

    # IG: observe the real book. Fenced like the paper run — a broker outage
    # must not unwind scores already committed above.
    try:
        from app.ig.jobs import run_nightly as ig_nightly

        ig_report = await ig_nightly(session, run_date)
        await session.commit()
        tally.notes.append(f"ig: {ig_report.as_dict()}")
        if ig_report.errors:
            logger.warning("ig sync reported errors: %s", ig_report.errors)
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        tally.notes.append(f"ig sync FAILED: {type(exc).__name__}: {exc}")
        logger.exception("ig sync failed")

    # Strategy machine: fill yesterday's paper orders at today's open, signal
    # tomorrow's from tonight's data. Runs after scoring so tonight's lens
    # scores exist for tonight's signals. A failure here must not unwind the
    # scores already committed above, so it is fenced and reported.
    try:
        from app.strategies.features import FeatureService
        from app.strategies.paper import run_paper_day
        from app.strategies.registry import Strategy, catch_up as strategies_catch_up
        from app.strategies.rules import features_used, parse_rules
        from sqlalchemy import select as sa_select

        await strategies_catch_up(session)
        active = list(
            (await session.execute(sa_select(Strategy).where(Strategy.status == "active"))).scalars()
        )
        if active:
            needed: set[str] = set()
            for strategy in active:
                rules = parse_rules(strategy.rules)
                needed |= features_used(rules)
                if rules.universe.min_market_cap or rules.universe.max_market_cap:
                    needed.add("price:market_cap")
            # Two years of window so 12-month features exist on day one.
            # Membership keeps live paper trading in the same universe the
            # backtests ran on: index members as of today, not everything the
            # database happens to hold.
            service = await FeatureService.build(
                session, run_date.replace(year=run_date.year - 2), run_date, needed,
                membership_index="GSPC.INDX",
            )
            paper = await run_paper_day(session, service, run_date)
            await session.commit()
            tally.notes.append(f"paper: {paper.as_dict()}")
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        tally.notes.append(f"paper run FAILED: {type(exc).__name__}: {exc}")
        logger.exception("paper run failed")

    return tally


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    run_date = datetime.now(UTC).date()
    engine = create_async_engine(settings.async_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        try:
            async with factory() as probe:
                await probe.execute(select(1))
        except Exception as exc:  # noqa: BLE001
            # Without this, an unset DATABASE_URL silently falls back to the
            # local development default and surfaces as a forty-line asyncpg
            # traceback about localhost — which says nothing about the actual
            # cause. Name the variable instead.
            if not os.environ.get("DATABASE_URL"):
                logger.error(
                    "DATABASE_URL is not set, so the local development default "
                    "was used and no database was reachable. On Railway, set "
                    "DATABASE_URL=${{Postgres.DATABASE_URL}} on this service."
                )
            else:
                logger.error("could not reach the database: %s", exc)
            return 1

        async with factory() as session:
            if await runs.succeeded_today(session, JOB_NAME, run_date):
                logger.info("daily: already succeeded for %s, nothing to do", run_date)
                return 0

            # Recorded before configuration is validated, so a missing API key
            # shows up in /jobs as a failed run rather than vanishing without
            # a trace — the earlier ordering raised before anything was written.
            record = await runs.start(session, JOB_NAME, run_date)
            await session.commit()

            try:
                if not settings.eodhd_api_key:
                    raise RuntimeError(
                        "EODHD_API_KEY is not set on this service"
                    )
                provider = EODHDProvider(settings.eodhd_api_key)
                tally = await run(session, provider, run_date)
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                tally = runs.RunTally(failures={"_fatal": f"{type(exc).__name__}: {exc}"})
                await runs.finish(session, record, runs.FAILED, tally)
                await session.commit()
                logger.exception("daily run failed")
                return 1

            await runs.finish(session, record, runs.SUCCEEDED, tally)
            await session.commit()
            logger.info(
                "daily run succeeded: %d tickers, %d calls, %d scores, %d failures",
                tally.tickers_updated,
                tally.calls_used,
                tally.scores_written,
                len(tally.failures),
            )
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    # Non-zero exit so a failed run shows red in Railway rather than being
    # mistaken for a quiet success.
    sys.exit(asyncio.run(main()))
