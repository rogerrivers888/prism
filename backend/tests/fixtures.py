"""Fake companies for lens tests, so nothing depends on real market data.

The numbers are invented but internally consistent: a full metric set per
company, varied enough across a sector to make percentile ranking meaningful.
"""

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.fundamentals import Fundamental, Security

PERIOD_END = date(2026, 3, 31)
PUBLISHED = date(2026, 5, 1)

# A complete, unremarkable set of inputs. Tests vary individual metrics from
# this baseline so the thing under test is the only thing that differs.
BASELINE: dict[str, float] = {
    # value
    "pe_ratio": 15.0,
    "ev_ebitda": 9.0,
    "fcf_yield": 4.0,
    "price_to_book": 2.5,
    "dividend_yield": 2.5,
    # growth
    "revenue_growth_yoy": 10.0,
    "eps_growth_yoy": 12.0,
    "revenue_cagr_3y": 8.0,
    "eps_cagr_3y": 10.0,
    "fcf_growth_yoy": 9.0,
    # quality
    "roic": 12.0,
    "gross_margin": 40.0,
    "net_debt_to_ebitda": 1.5,
    "interest_cover": 8.0,
    "fcf_conversion": 85.0,
    # trend
    "price_vs_50dma": 2.0,
    "price_vs_200dma": 6.0,
    "ma50_vs_ma200": 3.0,
    "pct_above_52w_low": 35.0,
    # momentum
    "return_3m": 4.0,
    "return_6m": 9.0,
    "return_12m": 14.0,
    "earnings_revision_3m": 2.0,
    # cycle
    "inventory_to_sales": 0.15,
    "days_inventory": 60.0,
    "capacity_utilisation": 80.0,
    "asp_change_yoy": 3.0,
    "book_to_bill": 1.05,
    # context metrics: not scored directly, consulted by guards
    "ebitda": 500.0,
    "fcf": 200.0,
}


async def clean(session: AsyncSession) -> None:
    """Reset market data between tests.

    Safe to truncate: securities is reference data and both fundamentals and
    lens_scores_daily are rebuildable from ingest. The event ledger is never
    touched here.
    """
    await session.execute(
        text(
            "TRUNCATE securities, fundamentals, lens_scores_daily, dispersion_daily"
        )
    )


async def add_company(
    session: AsyncSession,
    ticker: str,
    sector: str,
    metrics: dict[str, float] | None = None,
    *,
    published_at: date = PUBLISHED,
    period_end: date = PERIOD_END,
    name: str | None = None,
) -> None:
    session.add(Security(ticker=ticker, name=name or f"{ticker} plc", sector=sector))
    await add_metrics(
        session,
        ticker,
        metrics if metrics is not None else BASELINE,
        published_at=published_at,
        period_end=period_end,
    )


async def add_metrics(
    session: AsyncSession,
    ticker: str,
    metrics: dict[str, float],
    *,
    published_at: date = PUBLISHED,
    period_end: date = PERIOD_END,
    source: str = "test-fixture",
) -> None:
    for metric, value in metrics.items():
        session.add(
            Fundamental(
                ticker=ticker,
                metric=metric,
                value=value,
                period_end=period_end,
                published_at=published_at,
                source=source,
            )
        )
    await session.flush()


async def add_sector(
    session: AsyncSession,
    sector: str,
    count: int,
    *,
    prefix: str = "PEER",
    spread: dict[str, float] | None = None,
) -> list[str]:
    """Create ``count`` companies in a sector, fanned out around the baseline.

    ``spread`` gives a per-metric step so peers hold genuinely different
    values — a percentile against identical peers would always be 50.
    """
    spread = spread or {"pe_ratio": 1.5, "roic": 1.0, "return_12m": 3.0}
    tickers = []
    for i in range(count):
        metrics = dict(BASELINE)
        for metric, step in spread.items():
            metrics[metric] = BASELINE[metric] + step * i
        ticker = f"{prefix}{i:02d}"
        await add_company(session, ticker, sector, metrics)
        tickers.append(ticker)
    return tickers
