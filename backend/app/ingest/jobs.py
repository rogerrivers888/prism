"""Ingest jobs. Each is idempotent and supports a dry run.

The shape of every job is the same: budget-check, fetch, archive the raw
response, then parse from the archive. Parsing never reads the wire directly,
so a parser fix is re-applied with reparse_* and costs no calls.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.fundamentals import Fundamental, PriceDaily, Security
from app.ingest import archive as archive_module
from app.ingest.budget import CallBudget
from app.ingest.protocol import MarketDataProvider

logger = logging.getLogger(__name__)

# Nine names: enough for real scores, small enough to stay legible.
SEED_UNIVERSE = (
    "MU.US",
    "SNDK.US",
    "NVDA.US",
    "AMD.US",
    "ARM.US",
    "TSM.US",
    "WDC.US",
    "MSFT.US",
    "AAPL.US",
)


@dataclass
class IngestResult:
    """What a job did, or would do when dry_run is set."""

    job: str
    ticker: str | None = None
    dry_run: bool = False
    calls_planned: int = 0
    calls_spent: int = 0
    rows_written: int = 0
    budget_remaining: int | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "job": self.job,
            "ticker": self.ticker,
            "dry_run": self.dry_run,
            "calls_planned": self.calls_planned,
            "calls_spent": self.calls_spent,
            "rows_written": self.rows_written,
            "budget_remaining": self.budget_remaining,
            "notes": self.notes,
        }


def bare(ticker: str) -> str:
    """MU.US -> MU. Storage keys on the plain symbol; the suffix is provider routing."""
    return ticker.split(".")[0]


async def _fetch_and_archive(
    session: AsyncSession,
    provider: MarketDataProvider,
    budget: CallBudget,
    result: IngestResult,
    coroutine_factory,
    ticker: str,
):
    """Spend budget, fetch, archive verbatim, and return the payload."""
    await budget.spend(1)
    fetched = await coroutine_factory()
    await archive_module.archive(
        session, provider.name, fetched.endpoint, ticker, fetched.payload
    )
    result.calls_spent += fetched.calls
    result.budget_remaining = await budget.remaining()
    return fetched.payload


async def sync_securities(
    session: AsyncSession,
    provider: MarketDataProvider,
    budget: CallBudget,
    tickers: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> list[IngestResult]:
    """Metadata and sector for a fixed list of tickers."""
    tickers = list(tickers or SEED_UNIVERSE)
    results: list[IngestResult] = []

    for ticker in tickers:
        result = IngestResult(job="sync_securities", ticker=ticker, dry_run=dry_run)
        symbol = bare(ticker)
        existing = await session.get(Security, symbol)

        # Metadata rarely changes and rides along with the fundamentals
        # payload, so an existing row is reused unless forced.
        cached = await archive_module.latest(session, provider.name, "fundamentals", ticker)
        needs_call = force or (existing is None and cached is None)
        result.calls_planned = 1 if needs_call else 0

        if dry_run:
            result.notes.append(
                "would fetch" if needs_call else "already held, would reparse from archive"
            )
            result.budget_remaining = await budget.remaining()
            results.append(result)
            continue

        if needs_call:
            payload = await _fetch_and_archive(
                session, provider, budget, result,
                lambda t=ticker: provider.fetch_security(t), ticker,
            )
        elif cached is not None:
            payload = cached.payload
            result.notes.append("parsed from archive, no call spent")
        else:
            result.notes.append("already held")
            results.append(result)
            continue

        record = provider.parse_security(symbol, payload)
        await session.execute(
            insert(Security)
            .values(
                ticker=record.ticker,
                name=record.name,
                sector=record.sector,
                exchange=record.exchange,
                subsector=record.subsector,
                currency=record.currency,
                market_cap=record.market_cap,
                is_active=record.is_active,
            )
            .on_conflict_do_update(
                index_elements=["ticker"],
                set_={
                    "name": record.name,
                    "sector": record.sector,
                    "exchange": record.exchange,
                    "subsector": record.subsector,
                    "currency": record.currency,
                    "market_cap": record.market_cap,
                    "is_active": record.is_active,
                },
            )
        )
        result.rows_written = 1
        results.append(result)

    await session.flush()
    return results


async def sync_prices(
    session: AsyncSession,
    provider: MarketDataProvider,
    budget: CallBudget,
    ticker: str,
    from_date: date | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> IngestResult:
    """EOD history, incremental after the first load.

    With no from_date and nothing held, this loads the full available history
    — backtesting needs it. Afterwards it resumes from the last stored bar.
    """
    result = IngestResult(job="sync_prices", ticker=ticker, dry_run=dry_run)
    symbol = bare(ticker)

    latest_held = (
        await session.execute(
            select(PriceDaily.date)
            .where(PriceDaily.ticker == symbol)
            .order_by(PriceDaily.date.desc())
            .limit(1)
        )
    ).scalar()

    if from_date is None and latest_held is not None and not force:
        from_date = latest_held
        result.notes.append(f"incremental from {from_date}")
    elif from_date is None:
        result.notes.append("full history")

    result.calls_planned = 1
    if dry_run:
        result.notes.append("would fetch EOD series")
        result.budget_remaining = await budget.remaining()
        return result

    payload = await _fetch_and_archive(
        session, provider, budget, result,
        lambda: provider.fetch_prices(ticker, from_date), ticker,
    )

    security = await session.get(Security, symbol)
    currency = security.currency if security else None

    bars = provider.parse_prices(symbol, payload)
    for bar in bars:
        await session.execute(
            insert(PriceDaily)
            .values(
                ticker=bar.ticker,
                date=bar.date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                adjusted_close=bar.adjusted_close,
                volume=bar.volume,
                currency=currency,
            )
            .on_conflict_do_update(
                index_elements=["ticker", "date"],
                set_={
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "adjusted_close": bar.adjusted_close,
                    "volume": bar.volume,
                    "currency": currency,
                },
            )
        )
    result.rows_written = len(bars)
    await session.flush()
    return result


async def sync_fundamentals(
    session: AsyncSession,
    provider: MarketDataProvider,
    budget: CallBudget,
    ticker: str,
    dry_run: bool = False,
    force: bool = False,
) -> IngestResult:
    """Statement line items into fundamentals, point-in-time."""
    result = IngestResult(job="sync_fundamentals", ticker=ticker, dry_run=dry_run)
    symbol = bare(ticker)

    cached = await archive_module.latest(session, provider.name, "fundamentals", ticker)
    needs_call = force or cached is None
    result.calls_planned = 1 if needs_call else 0

    if dry_run:
        result.notes.append(
            "would fetch" if needs_call else "would reparse from archive, no call"
        )
        result.budget_remaining = await budget.remaining()
        return result

    if needs_call:
        payload = await _fetch_and_archive(
            session, provider, budget, result,
            lambda: provider.fetch_fundamentals(ticker), ticker,
        )
    else:
        payload = cached.payload
        result.notes.append("reparsed from archive, no call spent")

    rows = provider.parse_fundamentals(symbol, payload)
    estimated = 0
    for row in rows:
        if row.published_at_estimated:
            estimated += 1
        await session.execute(
            insert(Fundamental)
            .values(
                ticker=row.ticker,
                metric=row.metric,
                value=row.value,
                period_end=row.period_end,
                published_at=row.published_at,
                published_at_estimated=row.published_at_estimated,
                source=row.source,
            )
            .on_conflict_do_update(
                index_elements=["ticker", "metric", "period_end", "published_at"],
                set_={
                    "value": row.value,
                    "published_at_estimated": row.published_at_estimated,
                    "source": row.source,
                },
            )
        )
    result.rows_written = len(rows)
    result.notes.append(f"{estimated} of {len(rows)} rows have an estimated published_at")
    await session.flush()
    return result
