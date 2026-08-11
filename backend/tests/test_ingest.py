"""Ingest tests. The HTTP layer is mocked — no live calls, ever."""

import json
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import select, text

from app.fundamentals import Fundamental, PriceDaily, Security
from app.ingest.archive import RawResponse, latest
from app.ingest.budget import BudgetExceeded, CallBudget
from app.ingest.eodhd import EODHDProvider, resolve_published_at
from app.ingest.jobs import sync_fundamentals, sync_prices, sync_securities
from app.ingest.mapping import UnmappedSector, map_sector

# A small but structurally faithful stand-in for the real payload.
FUNDAMENTALS = {
    "General": {
        "Code": "TEST",
        "Name": "Test Semiconductor Inc",
        "Exchange": "NASDAQ",
        "CurrencyCode": "USD",
        "Sector": "Technology",
        "Industry": "Semiconductors",
        "IsDelisted": False,
    },
    "Highlights": {"MarketCapitalization": 1_000_000_000},
    "Financials": {
        "Income_Statement": {
            "quarterly": {
                "2026-03-31": {
                    "date": "2026-03-31",
                    "filing_date": "2026-05-06",  # real: after period end
                    "totalRevenue": "1000",
                    "costOfRevenue": "600",
                    "grossProfit": "400",
                },
                "2025-12-31": {
                    "date": "2025-12-31",
                    "filing_date": "2025-12-31",  # placeholder: same day
                    "totalRevenue": "900",
                    "costOfRevenue": "560",
                    "grossProfit": "340",
                },
                "2025-09-30": {
                    "date": "2025-09-30",
                    "filing_date": None,  # missing entirely
                    "totalRevenue": "850",
                    "costOfRevenue": "540",
                    "grossProfit": "310",
                },
            }
        },
        "Balance_Sheet": {
            "quarterly": {
                "2026-03-31": {
                    "date": "2026-03-31",
                    "filing_date": "2026-05-06",
                    "inventory": "500",
                    "totalAssets": "5000",
                }
            }
        },
        "Cash_Flow": {"quarterly": {}},
    },
    # Several fiscal years carry a "0y" entry; only the newest is a live
    # consensus. Ordered oldest-first here on purpose, mirroring how JSONB
    # hands object keys back sorted.
    "Earnings": {
        "Trend": {
            "2017-08-31": {
                "date": "2017-08-31", "period": "0y",
                "epsTrendCurrent": "4.73", "epsTrend90daysAgo": "4.30",
            },
            "2026-08-31": {
                "date": "2026-08-31", "period": "0y",
                "epsTrendCurrent": "110.0", "epsTrend90daysAgo": "100.0",
            },
            "2027-08-31": {
                "date": "2027-08-31", "period": "+1y",
                "epsTrendCurrent": "150.0", "epsTrend90daysAgo": "90.0",
            },
        }
    },
}

EOD = [
    {"date": "2026-03-30", "open": 10, "high": 11, "low": 9, "close": 10.5,
     "adjusted_close": 10.5, "volume": 1000},
    {"date": "2026-03-31", "open": 10.5, "high": 12, "low": 10, "close": 11.5,
     "adjusted_close": 11.5, "volume": 1200},
]


class RecordingProvider(EODHDProvider):
    """EODHD provider over a mock transport, counting requests made."""

    def __init__(self):
        self.requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(str(request.url.path))
            if "/fundamentals/" in request.url.path:
                return httpx.Response(200, json=FUNDAMENTALS)
            return httpx.Response(200, json=EOD)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        super().__init__("test-key", client=client)


@pytest.fixture
async def clean_ingest(session):
    await session.execute(
        text(
            "TRUNCATE securities, fundamentals, prices_daily, raw_responses, "
            "api_call_usage, lens_scores_daily, dispersion_daily"
        )
    )
    yield
    await session.rollback()


@pytest.fixture
def provider():
    return RecordingProvider()


@pytest.fixture
def budget(session):
    return CallBudget(session, "eodhd", 100)


# ----------------------------------------------------------------- published_at


def test_real_filing_date_is_trusted():
    published, estimated = resolve_published_at(
        date(2026, 3, 31), date(2026, 5, 6), annual=False
    )
    assert published == date(2026, 5, 6)
    assert estimated is False


def test_filing_date_equal_to_period_end_is_not_a_filing_date():
    # Claiming a figure was public the day the period closed is a lookahead.
    published, estimated = resolve_published_at(
        date(2026, 3, 31), date(2026, 3, 31), annual=False
    )
    assert estimated is True
    assert published > date(2026, 3, 31)


def test_missing_filing_date_is_estimated_with_a_documented_lag():
    published, estimated = resolve_published_at(date(2026, 3, 31), None, annual=False)
    assert estimated is True
    assert (published - date(2026, 3, 31)).days == 45

    annual, annual_estimated = resolve_published_at(
        date(2026, 3, 31), None, annual=True
    )
    assert annual_estimated is True
    assert (annual - date(2026, 3, 31)).days == 75


def test_sector_mapping_prefers_industry_and_refuses_to_guess():
    assert map_sector("Technology", "Semiconductors") == "semiconductors"
    assert map_sector("Technology", "Computer Hardware") == "hardware"
    assert map_sector("Financial Services", "Banks—Regional") == "banks"
    # Unknown industry falls back to the coarse sector...
    assert map_sector("Utilities", "Something New") == "utilities"
    # ...but a wholly unknown pair raises rather than being bucketed.
    with pytest.raises(UnmappedSector):
        map_sector("Nonsense", "Nonsense")


# ----------------------------------------------------------------- archive


async def test_raw_response_is_archived_before_parsing(session, provider, budget, clean_ingest):
    await sync_fundamentals(session, provider, budget, "TEST.US")
    await session.commit()

    row = await latest(session, "eodhd", "fundamentals", "TEST.US")
    assert row is not None
    # Stored verbatim: the provider's own structure, not our interpretation.
    assert row.payload["General"]["Name"] == "Test Semiconductor Inc"
    assert "Financials" in row.payload


async def test_reparse_uses_the_archive_and_spends_no_call(session, provider, budget, clean_ingest):
    first = await sync_fundamentals(session, provider, budget, "TEST.US")
    await session.commit()
    assert first.calls_spent == 1
    assert len(provider.requests) == 1

    second = await sync_fundamentals(session, provider, budget, "TEST.US")
    await session.commit()

    assert second.calls_spent == 0
    assert len(provider.requests) == 1  # no second HTTP request
    assert second.rows_written == first.rows_written
    assert "reparsed from archive" in " ".join(second.notes)


async def test_forcing_a_refetch_spends_a_call(session, provider, budget, clean_ingest):
    await sync_fundamentals(session, provider, budget, "TEST.US")
    await session.commit()
    await sync_fundamentals(session, provider, budget, "TEST.US", force=True)
    await session.commit()
    assert len(provider.requests) == 2


# ----------------------------------------------------------------- parsing


async def test_published_at_estimated_set_per_period(session, provider, budget, clean_ingest):
    await sync_fundamentals(session, provider, budget, "TEST.US")
    await session.commit()

    rows = (
        await session.execute(
            select(Fundamental).where(
                Fundamental.ticker == "TEST", Fundamental.metric == "revenue"
            )
        )
    ).scalars().all()
    by_period = {r.period_end: r for r in rows}

    real = by_period[date(2026, 3, 31)]
    assert real.published_at == date(2026, 5, 6)
    assert real.published_at_estimated is False

    same_day = by_period[date(2025, 12, 31)]
    assert same_day.published_at_estimated is True
    assert same_day.published_at > date(2025, 12, 31)

    missing = by_period[date(2025, 9, 30)]
    assert missing.published_at_estimated is True


# ----------------------------------------------------------------- budget


async def test_eps_revision_uses_the_newest_fiscal_year_not_key_order(
    session, provider, budget, clean_ingest
):
    # Trend carries stale "0y" entries for closed years, and JSONB returns
    # object keys sorted, so picking by iteration order silently reads a
    # decade-old consensus.
    await sync_fundamentals(session, provider, budget, "TEST.US")
    await session.commit()

    row = (
        await session.execute(
            select(Fundamental).where(Fundamental.metric == "earnings_revision_3m")
        )
    ).scalar_one()
    # (110 - 100) / 100 = 10%, from the 2026 entry — not the 2017 one.
    assert row.value == pytest.approx(10.0)
    assert row.period_end == date(2026, 8, 31)


async def test_budget_refuses_calls_at_the_limit(session, provider, clean_ingest):
    tight = CallBudget(session, "eodhd", 1)
    await sync_fundamentals(session, provider, tight, "TEST.US")
    await session.commit()
    assert await tight.remaining() == 0

    with pytest.raises(BudgetExceeded, match="only 0 of 1 remain"):
        await sync_prices(session, provider, tight, "TEST.US")


async def test_dry_run_spends_nothing(session, provider, budget, clean_ingest):
    result = await sync_prices(session, provider, budget, "TEST.US", dry_run=True)

    assert result.dry_run is True
    assert result.calls_planned == 1
    assert result.calls_spent == 0
    assert result.rows_written == 0
    assert provider.requests == []
    assert await budget.used() == 0
    assert (await session.execute(select(PriceDaily))).first() is None


# ----------------------------------------------------------------- idempotence


async def test_prices_are_idempotent_and_then_incremental(session, provider, budget, clean_ingest):
    first = await sync_prices(session, provider, budget, "TEST.US")
    await session.commit()
    assert first.rows_written == 2

    stored = (await session.execute(select(PriceDaily))).scalars().all()
    assert len(stored) == 2

    second = await sync_prices(session, provider, budget, "TEST.US")
    await session.commit()

    # Re-running overwrites in place rather than duplicating...
    assert len((await session.execute(select(PriceDaily))).scalars().all()) == 2
    # ...and resumes from the last bar held rather than refetching everything.
    assert "incremental from 2026-03-31" in " ".join(second.notes)


async def test_securities_are_idempotent(session, provider, budget, clean_ingest):
    await sync_securities(session, provider, budget, tickers=["TEST.US"])
    await session.commit()
    assert len(provider.requests) == 1

    security = await session.get(Security, "TEST")
    assert security.sector == "semiconductors"
    assert security.subsector == "Semiconductors"
    assert security.currency == "USD"  # stored, not converted
    assert security.is_active is True

    await sync_securities(session, provider, budget, tickers=["TEST.US"])
    await session.commit()
    assert len(provider.requests) == 1  # nothing refetched

    count = (await session.execute(select(Security))).scalars().all()
    assert len(count) == 1


async def test_fundamentals_rerun_does_not_duplicate_rows(session, provider, budget, clean_ingest):
    await sync_fundamentals(session, provider, budget, "TEST.US")
    await session.commit()
    before = len((await session.execute(select(Fundamental))).scalars().all())

    await sync_fundamentals(session, provider, budget, "TEST.US", force=True)
    await session.commit()
    after = len((await session.execute(select(Fundamental))).scalars().all())

    assert before == after
