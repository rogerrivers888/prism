"""Provider-agnostic contract for market data.

Nothing outside app/ingest/ imports provider-specific types. Swapping EODHD
for FMP, or adding SEC EDGAR as a second source of as-reported data, means
writing another implementation of this protocol and nothing else.

Fetching and parsing are deliberately separate methods: fetch spends a call
and returns raw JSON, parse is a pure function over that JSON. The archive
sits between them, so a wrong parser is re-run against stored payloads
instead of re-fetching.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FetchResult:
    """One raw provider response, before any interpretation."""

    endpoint: str
    payload: object
    calls: int = 1


@dataclass(frozen=True)
class SecurityRecord:
    ticker: str
    name: str
    exchange: str | None
    sector: str
    subsector: str | None
    # Currency the accounts are reported in.
    currency: str | None
    market_cap: float | None
    is_active: bool = True
    # Currency prices are quoted in, which is not always the reporting
    # currency: London quotes many shares in GBX (pence) while reporting in
    # GBP. Kept separate so the two can never be silently conflated.
    quote_currency: str | None = None


@dataclass(frozen=True)
class ConsensusRow:
    """One analyst-consensus observation, stamped with the date we saw it."""

    ticker: str
    observed_on: date
    period_end: date
    period_label: str | None
    eps_avg: float | None
    eps_low: float | None
    eps_high: float | None
    eps_year_ago: float | None
    analysts: float | None
    eps_7d_ago: float | None
    eps_30d_ago: float | None
    eps_60d_ago: float | None
    eps_90d_ago: float | None
    revenue_avg: float | None
    source: str


@dataclass(frozen=True)
class PriceBar:
    ticker: str
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    adjusted_close: float | None
    volume: float | None
    currency: str | None


@dataclass(frozen=True)
class FundamentalRow:
    """One metric observation, point-in-time.

    ``published_at_estimated`` is never guessed at a call site: the parser
    sets it when the provider gave no usable filing date.
    """

    ticker: str
    metric: str
    value: float
    period_end: date
    published_at: date
    published_at_estimated: bool
    source: str


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    async def fetch_security(self, ticker: str) -> FetchResult: ...

    async def fetch_prices(
        self, ticker: str, from_date: date | None = None
    ) -> FetchResult: ...

    async def fetch_fundamentals(self, ticker: str) -> FetchResult: ...

    async def fetch_dividends(self, ticker: str) -> FetchResult: ...

    def parse_security(self, ticker: str, payload: object) -> SecurityRecord: ...

    def parse_prices(self, ticker: str, payload: object) -> list[PriceBar]: ...

    def parse_fundamentals(
        self, ticker: str, payload: object
    ) -> list[FundamentalRow]: ...

    def parse_dividends(
        self, ticker: str, payload: object
    ) -> list[FundamentalRow]: ...

    def parse_consensus(
        self, ticker: str, payload: object, observed_on: date
    ) -> list[ConsensusRow]: ...
