"""Bulk universe ingest: resumable, fault-tolerant, and honest about gaps.

Restarting after a failure at ticker 300 does not re-fetch the first 299 —
work already archived is skipped. A ticker that fails is recorded and the run
continues; an unmapped sector is collected rather than aborting the batch, so
one unknown industry string cannot cost hundreds of calls already spent.
"""

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.fundamentals import PriceDaily, Security
from app.ingest import archive as archive_module
from app.ingest import consensus as consensus_module
from app import earnings as earnings_module
from app.ingest.budget import BudgetExceeded, CallBudget
from app.ingest.jobs import _upsert_fundamentals, _upsert_security, bare
from app.ingest.mapping import UnmappedSector
from app.ingest.protocol import MarketDataProvider

logger = logging.getLogger(__name__)

# Fetch concurrently, persist sequentially: an AsyncSession is not safe to
# share across tasks, and the provider allows far more throughput than a
# single connection will absorb.
DEFAULT_CONCURRENCY = 8


@dataclass
class UniverseReport:
    requested: int = 0
    skipped_already_held: int = 0
    ingested: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    unmapped_sectors: Counter = field(default_factory=Counter)
    unmapped_examples: dict[str, str] = field(default_factory=dict)
    calls_spent: int = 0
    price_rows: int = 0
    fundamental_rows: int = 0
    dividend_rows: int = 0
    consensus_rows: int = 0

    def as_dict(self) -> dict:
        return {
            "requested": self.requested,
            "skipped_already_held": self.skipped_already_held,
            "ingested": self.ingested,
            "failed": self.failed,
            "unmapped_sectors": dict(self.unmapped_sectors.most_common()),
            "unmapped_examples": self.unmapped_examples,
            "calls_spent": self.calls_spent,
            "price_rows": self.price_rows,
            "fundamental_rows": self.fundamental_rows,
            "dividend_rows": self.dividend_rows,
            "consensus_rows": self.consensus_rows,
        }


async def already_held(session: AsyncSession, ticker: str, provider: str) -> bool:
    """True when this ticker has been fully ingested before.

    Keyed on the archive rather than on parsed rows: if the raw payload is
    held, a re-run can rebuild everything without spending a call.
    """
    symbol = bare(ticker)
    has_fundamentals = await archive_module.latest(
        session, provider, "fundamentals", ticker
    )
    if has_fundamentals is None:
        return False
    has_prices = (
        await session.execute(
            select(func.count()).select_from(PriceDaily).where(PriceDaily.ticker == symbol)
        )
    ).scalar() or 0
    return has_prices > 0


async def _fetch_one(
    provider: MarketDataProvider, ticker: str, want_dividends: bool
) -> dict:
    """All network work for one ticker. Runs concurrently; touches no session."""
    fundamentals = await provider.fetch_fundamentals(ticker)
    prices = await provider.fetch_prices(ticker)
    dividends = await provider.fetch_dividends(ticker) if want_dividends else None
    return {"fundamentals": fundamentals, "prices": prices, "dividends": dividends}


async def sync_universe(
    session: AsyncSession,
    provider: MarketDataProvider,
    budget: CallBudget,
    tickers: list[str],
    dry_run: bool = False,
    force: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
    with_dividends: bool = True,
) -> UniverseReport:
    report = UniverseReport(requested=len(tickers))

    outstanding = []
    for ticker in tickers:
        if not force and await already_held(session, ticker, provider.name):
            report.skipped_already_held += 1
            continue
        outstanding.append(ticker)

    calls_each = 3 if with_dividends else 2
    if dry_run:
        logger.info(
            "dry run: %d of %d tickers outstanding, %d calls",
            len(outstanding),
            len(tickers),
            len(outstanding) * calls_each,
        )
        report.calls_spent = 0
        report.failed["_dry_run"] = (
            f"would fetch {len(outstanding)} tickers at {calls_each} calls each "
            f"= {len(outstanding) * calls_each} calls"
        )
        return report

    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(ticker: str):
        async with semaphore:
            try:
                return ticker, await _fetch_one(provider, ticker, with_dividends), None
            except Exception as exc:  # noqa: BLE001 - one bad ticker must not stop the run
                return ticker, None, f"{type(exc).__name__}: {exc}"

    # Chunked so budget is checked as we go and a long run reports progress.
    chunk_size = max(concurrency, 1)
    for start in range(0, len(outstanding), chunk_size):
        chunk = outstanding[start : start + chunk_size]
        try:
            await budget.check(len(chunk) * calls_each)
        except BudgetExceeded as exc:
            report.failed["_budget"] = str(exc)
            logger.warning("stopping: %s", exc)
            break

        fetched = await asyncio.gather(*(guarded(t) for t in chunk))

        for ticker, payloads, error in fetched:
            if error is not None:
                report.failed[ticker] = error
                logger.warning("ingest failed for %s: %s", ticker, error)
                continue
            try:
                # Each ticker persists inside its own savepoint, so one
                # failure rolls back that ticker alone. A plain rollback here
                # would discard every sibling in the chunk that had already
                # been written but not yet committed.
                async with session.begin_nested():
                    await _persist(session, provider, ticker, payloads, report)
                await budget.spend(calls_each)
                report.calls_spent += calls_each
                report.ingested += 1
            except UnmappedSector as exc:
                # Collect and continue: the calls are already spent, and one
                # unknown industry string must not discard the whole batch.
                report.unmapped_sectors[str(exc)] += 1
                report.unmapped_examples.setdefault(str(exc), ticker)
                logger.warning("unmapped sector for %s: %s", ticker, exc)
            except Exception as exc:  # noqa: BLE001
                report.failed[ticker] = f"persist {type(exc).__name__}: {exc}"
                logger.warning("persist failed for %s: %s", ticker, exc)

        await session.commit()
        logger.info(
            "universe progress: %d ingested, %d failed, %d calls spent",
            report.ingested,
            len(report.failed),
            report.calls_spent,
        )

    return report


async def _persist(
    session: AsyncSession,
    provider: MarketDataProvider,
    ticker: str,
    payloads: dict,
    report: UniverseReport,
) -> None:
    symbol = bare(ticker)
    fundamentals = payloads["fundamentals"]
    prices = payloads["prices"]
    dividends = payloads["dividends"]

    # Archive every payload before a line of it is interpreted.
    await archive_module.archive(
        session, provider.name, "fundamentals", ticker, fundamentals.payload
    )
    await archive_module.archive(
        session, provider.name, "eod", ticker, prices.payload
    )
    if dividends is not None:
        await archive_module.archive(
            session, provider.name, "div", ticker, dividends.payload
        )

    # Sector mapping first: if it raises, nothing else has been written.
    record = provider.parse_security(symbol, fundamentals.payload)
    await _upsert_security(session, record)

    written, _ = await _upsert_fundamentals(
        session, provider.parse_fundamentals(symbol, fundamentals.payload)
    )
    report.fundamental_rows += written

    if dividends is not None:
        paid, _ = await _upsert_fundamentals(
            session, provider.parse_dividends(symbol, dividends.payload)
        )
        report.dividend_rows += paid

    report.consensus_rows += await consensus_module.store(
        session, provider.parse_consensus(symbol, fundamentals.payload, date.today())
    )
    await earnings_module.store(
        session, provider.parse_earnings(symbol, fundamentals.payload, date.today())
    )

    bars = provider.parse_prices(symbol, prices.payload)
    if bars:
        # Prices carry the QUOTE currency, which for LSE names is GBX and not
        # the reporting currency on the securities row.
        await _insert_prices(session, bars, record.quote_currency)
        report.price_rows += len(bars)
    await session.flush()


# Decades of daily bars per ticker, so they go in as one multi-row statement
# rather than ten thousand round trips.
PRICE_CHUNK = 2000


async def _insert_prices(session: AsyncSession, bars, currency: str | None) -> None:
    for start in range(0, len(bars), PRICE_CHUNK):
        window = bars[start : start + PRICE_CHUNK]
        statement = pg_insert(PriceDaily).values(
            [
                {
                    "ticker": bar.ticker,
                    "date": bar.date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "adjusted_close": bar.adjusted_close,
                    "volume": bar.volume,
                    "currency": currency,
                }
                for bar in window
            ]
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["ticker", "date"],
                set_={
                    "close": statement.excluded.close,
                    "adjusted_close": statement.excluded.adjusted_close,
                    "volume": statement.excluded.volume,
                    "currency": statement.excluded.currency,
                },
            )
        )
