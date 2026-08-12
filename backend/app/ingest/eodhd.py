"""EODHD implementation of MarketDataProvider.

Everything EODHD-specific lives here. Fetching spends calls; parsing is pure
and runs against archived payloads, so a parser fix costs nothing to re-apply.

On published_at: EODHD carries ``filing_date`` on every statement period. It
is trusted only when it is strictly after period_end — for some tickers
(notably UK listings) the provider fills filing_date with period_end itself,
which would claim a figure was public on the day the period closed. That is a
lookahead, so those rows fall back to an estimated date and are flagged.
"""

import asyncio
import logging
from datetime import date, timedelta

import httpx

from app.ingest.mapping import map_sector
from app.ingest.protocol import (
    ConsensusRow,
    FetchResult,
    FundamentalRow,
    PriceBar,
    SecurityRecord,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://eodhd.com/api"
SOURCE = "eodhd"

# Documented fallback lag, used only when the provider gives no usable filing
# date. Chosen from observed US filing behaviour: the median gap between
# period_end and filing_date is ~36 days for quarters and ~45 for years. We
# round up so an estimate errs towards being late (data appears knowable
# later than it was), never towards a lookahead.
ESTIMATED_QUARTERLY_LAG = timedelta(days=45)
ESTIMATED_ANNUAL_LAG = timedelta(days=75)

# Statement line items copied through verbatim, before any ratio is formed.
# Kept raw so a ratio can be re-derived later without re-fetching.
INCOME_FIELDS = {
    "totalRevenue": "revenue",
    "costOfRevenue": "cogs",
    "grossProfit": "gross_profit",
    "ebitda": "ebitda_quarter",
    "ebit": "ebit_quarter",
    "netIncome": "net_income_quarter",
    "interestExpense": "interest_expense_quarter",
    "incomeBeforeTax": "income_before_tax_quarter",
    "taxProvision": "tax_provision_quarter",
}
BALANCE_FIELDS = {
    "inventory": "inventory",
    "totalAssets": "total_assets",
    "netDebt": "net_debt",
    "netInvestedCapital": "invested_capital",
    "totalStockholderEquity": "total_equity",
    "commonStockSharesOutstanding": "shares_outstanding",
}
CASHFLOW_FIELDS = {
    "freeCashFlow": "fcf_quarter",
}


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _day(value: object) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def resolve_published_at(
    period_end: date, filing_date: date | None, annual: bool
) -> tuple[date, bool]:
    """Return (published_at, estimated).

    A filing date is only meaningful if it falls after the period it reports
    on. Anything else — missing, equal to period_end, or before it — is not a
    real disclosure date, so we estimate instead and say so.
    """
    if filing_date is not None and filing_date > period_end:
        return filing_date, False
    lag = ESTIMATED_ANNUAL_LAG if annual else ESTIMATED_QUARTERLY_LAG
    return period_end + lag, True


class EODHDProvider:
    """Fetches from EODHD and parses its payloads. Implements MarketDataProvider."""

    name = "eodhd"

    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 5,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._max_retries = max_retries

    # ------------------------------------------------------------------ fetch

    def _redact(self, text: str) -> str:
        """Strip the API key out of anything that might be logged or raised.

        httpx puts the full request URL in its error messages, and the token
        is a query parameter — so an unhandled error would otherwise write the
        credential straight into the logs.
        """
        return text.replace(self._api_key, "***") if self._api_key else text

    async def _get(self, path: str, **params: object) -> object:
        """GET with exponential backoff on 429 and transient 5xx.

        The API key never appears in a log line or an exception message.
        """
        client = self._client or httpx.AsyncClient(timeout=120)
        owned = self._client is None
        query = {"api_token": self._api_key, "fmt": "json", **params}
        try:
            return await self._request(client, path, query)
        except Exception as exc:
            # Belt and braces over the targeted redaction below: any exception
            # escaping this call — httpx status errors, transport errors, JSON
            # decode failures, anything added later — is checked before it can
            # reach a log. The URL carries the token as a query parameter, so
            # leaking it is the default unless something stops it.
            message = str(exc)
            if self._api_key and self._api_key in message:
                raise RuntimeError(self._redact(message)) from None
            raise
        finally:
            if owned:
                await client.aclose()

    async def _request(
        self, client: httpx.AsyncClient, path: str, query: dict
    ) -> object:
        delay = 1.0
        for attempt in range(self._max_retries):
            response = await client.get(f"{BASE_URL}{path}", params=query)
            # 429 is rate limiting; 5xx from this provider is routinely a
            # transient gateway blip and succeeds on a retry.
            if response.status_code == 429 or response.status_code >= 500:
                logger.warning(
                    "eodhd %s on %s, backing off %.1fs (attempt %d/%d)",
                    response.status_code,
                    path,
                    delay,
                    attempt + 1,
                    self._max_retries,
                )
                await asyncio.sleep(delay)
                delay *= 2
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(
            f"eodhd did not recover on {path} after {self._max_retries} attempts"
        )

    async def fetch_security(self, ticker: str) -> FetchResult:
        # Security metadata lives inside the fundamentals payload, so this is
        # the same call — callers that need both should fetch once and parse
        # twice from the archive.
        return await self.fetch_fundamentals(ticker)

    async def fetch_fundamentals(self, ticker: str) -> FetchResult:
        payload = await self._get(f"/fundamentals/{ticker}")
        return FetchResult(endpoint="fundamentals", payload=payload, calls=1)

    async def search(self, query: str, limit: int = 8) -> list[dict]:
        """Resolve a company name or partial symbol to real tickers.

        Exists because the failure it prevents is indistinguishable from a
        bug: typing a company name gets a bare 404, which reads as "the app
        is broken" rather than "that isn't a ticker".
        """
        payload = await self._get(f"/search/{query}", limit=limit)
        if not isinstance(payload, list):
            return []
        return [
            {
                "ticker": f"{hit.get('Code')}.{'US' if hit.get('Exchange') in ('US', 'NYSE', 'NASDAQ', 'BATS', 'AMEX') else hit.get('Exchange')}",
                "code": hit.get("Code"),
                "exchange": hit.get("Exchange"),
                "name": hit.get("Name"),
                "type": hit.get("Type"),
                "currency": hit.get("Currency"),
            }
            for hit in payload
            if hit.get("Code")
        ]

    async def fetch_dividends(self, ticker: str) -> FetchResult:
        payload = await self._get(f"/div/{ticker}", **{"from": "1980-01-01"})
        return FetchResult(endpoint="div", payload=payload, calls=1)

    async def fetch_prices(
        self, ticker: str, from_date: date | None = None
    ) -> FetchResult:
        params: dict[str, object] = {}
        if from_date is not None:
            params["from"] = from_date.isoformat()
        payload = await self._get(f"/eod/{ticker}", **params)
        return FetchResult(endpoint="eod", payload=payload, calls=1)

    # ------------------------------------------------------------------ parse

    def parse_security(self, ticker: str, payload: object) -> SecurityRecord:
        if not isinstance(payload, dict):
            raise ValueError(f"unexpected fundamentals payload for {ticker}")
        general = payload.get("General", {})
        highlights = payload.get("Highlights", {})
        return SecurityRecord(
            ticker=ticker,
            name=general.get("Name") or ticker,
            exchange=general.get("Exchange"),
            sector=map_sector(general.get("Sector"), general.get("Industry")),
            # Provider's own industry string, kept verbatim so biotech can be
            # separated from asset-heavy healthcare once we act on it.
            subsector=general.get("Industry"),
            currency=self._reporting_currency(payload) or general.get("CurrencyCode"),
            market_cap=_number(highlights.get("MarketCapitalization")),
            is_active=not bool(general.get("IsDelisted")),
            # General.CurrencyCode is the QUOTE currency — GBX for most LSE
            # names — which differs from the currency the accounts are
            # reported in. Kept apart so nothing conflates pence with pounds.
            quote_currency=general.get("CurrencyCode"),
        )

    @staticmethod
    def _reporting_currency(payload: dict) -> str | None:
        """Currency the statements are denominated in, from the newest period."""
        periods = (
            payload.get("Financials", {})
            .get("Income_Statement", {})
            .get("quarterly", {})
        )
        if not isinstance(periods, dict) or not periods:
            return None
        newest = periods[max(periods)]
        return newest.get("currency_symbol") if isinstance(newest, dict) else None

    def parse_prices(self, ticker: str, payload: object) -> list[PriceBar]:
        if not isinstance(payload, list):
            raise ValueError(f"unexpected eod payload for {ticker}")
        bars = []
        for row in payload:
            day = _day(row.get("date"))
            if day is None:
                continue
            bars.append(
                PriceBar(
                    ticker=ticker,
                    date=day,
                    open=_number(row.get("open")),
                    high=_number(row.get("high")),
                    low=_number(row.get("low")),
                    close=_number(row.get("close")),
                    adjusted_close=_number(row.get("adjusted_close")),
                    volume=_number(row.get("volume")),
                    currency=None,  # set by the caller from securities
                )
            )
        return bars

    def parse_dividends(self, ticker: str, payload: object) -> list[FundamentalRow]:
        """Dividends per share, keyed on the ex-date.

        The ex-date is when the market prices the dividend out, and it is
        public from the declaration date. Where a declaration date is given we
        use it, so a dividend is not treated as known before it was announced.
        """
        if not isinstance(payload, list):
            return []
        rows = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            ex_date = _day(entry.get("date"))
            value = _number(entry.get("value"))
            if ex_date is None or value is None:
                continue
            declared = _day(entry.get("declarationDate"))
            published_at, estimated = (
                (declared, False) if declared and declared <= ex_date else (ex_date, True)
            )
            rows.append(
                FundamentalRow(
                    ticker=ticker,
                    metric="dividend_per_share",
                    value=value,
                    period_end=ex_date,
                    published_at=published_at,
                    published_at_estimated=estimated,
                    source=SOURCE,
                )
            )
        return rows

    def parse_consensus(
        self, ticker: str, payload: object, observed_on: date
    ) -> list[ConsensusRow]:
        """Every consensus period in the payload, stamped with today's date.

        All periods are kept, not just the current year: the value of this
        series is that it accumulates, and which period matters later is not
        knowable now.
        """
        if not isinstance(payload, dict):
            return []
        trend = payload.get("Earnings", {}).get("Trend", {})
        if not isinstance(trend, dict):
            return []

        rows = []
        for entry in trend.values():
            if not isinstance(entry, dict):
                continue
            period_end = _day(entry.get("date"))
            if period_end is None:
                continue
            rows.append(
                ConsensusRow(
                    ticker=ticker,
                    observed_on=observed_on,
                    period_end=period_end,
                    period_label=entry.get("period"),
                    eps_avg=_number(entry.get("earningsEstimateAvg")),
                    eps_low=_number(entry.get("earningsEstimateLow")),
                    eps_high=_number(entry.get("earningsEstimateHigh")),
                    eps_year_ago=_number(entry.get("earningsEstimateYearAgoEps")),
                    analysts=_number(entry.get("earningsEstimateNumberOfAnalysts")),
                    eps_7d_ago=_number(entry.get("epsTrend7daysAgo")),
                    eps_30d_ago=_number(entry.get("epsTrend30daysAgo")),
                    eps_60d_ago=_number(entry.get("epsTrend60daysAgo")),
                    eps_90d_ago=_number(entry.get("epsTrend90daysAgo")),
                    revenue_avg=_number(entry.get("revenueEstimateAvg")),
                    source=SOURCE,
                )
            )
        return rows

    def parse_earnings(
        self, ticker: str, payload: object, observed_on: date
    ) -> list[dict]:
        """Report dates from Earnings::History — actual and still-forecast.

        A period with no actual EPS has not reported yet, so its report_date is
        a forecast: flagged, and re-observed every night so the movement of the
        expectation is itself on the record.
        """
        if not isinstance(payload, dict):
            return []
        history = payload.get("Earnings", {}).get("History", {})
        if not isinstance(history, dict):
            return []

        rows = []
        for entry in history.values():
            if not isinstance(entry, dict):
                continue
            period_end = _day(entry.get("date"))
            if period_end is None:
                continue
            actual = _number(entry.get("epsActual"))
            rows.append(
                {
                    "ticker": ticker,
                    "period_end": period_end,
                    "observed_on": observed_on,
                    "report_date": _day(entry.get("reportDate")),
                    "is_estimated": actual is None,
                    "before_after_market": entry.get("beforeAfterMarket"),
                    "eps_estimate": _number(entry.get("epsEstimate")),
                    "eps_actual": actual,
                    "revenue_estimate": None,
                    "revenue_actual": None,
                    "surprise_percent": _number(entry.get("surprisePercent")),
                    "source": SOURCE,
                }
            )
        return rows

    def parse_fundamentals(
        self, ticker: str, payload: object
    ) -> list[FundamentalRow]:
        """Statement line items and consensus EPS, as point-in-time rows.

        Only raw line items are emitted here. Ratios are derived at scoring
        time from these, so a change to a formula never requires a re-fetch.
        """
        if not isinstance(payload, dict):
            raise ValueError(f"unexpected fundamentals payload for {ticker}")

        rows: list[FundamentalRow] = []
        financials = payload.get("Financials", {})

        for statement, fields in (
            ("Income_Statement", INCOME_FIELDS),
            ("Balance_Sheet", BALANCE_FIELDS),
            ("Cash_Flow", CASHFLOW_FIELDS),
        ):
            for frequency in ("quarterly", "yearly"):
                periods = financials.get(statement, {}).get(frequency, {})
                if not isinstance(periods, dict):
                    continue
                annual = frequency == "yearly"
                for row in periods.values():
                    period_end = _day(row.get("date"))
                    if period_end is None:
                        continue
                    published_at, estimated = resolve_published_at(
                        period_end, _day(row.get("filing_date")), annual
                    )
                    for source_field, metric in fields.items():
                        value = _number(row.get(source_field))
                        if value is None:
                            continue
                        rows.append(
                            FundamentalRow(
                                ticker=ticker,
                                # Annual figures are suffixed so they never
                                # collide with the quarterly series, which is
                                # what TTM aggregation reads.
                                metric=f"{metric}_annual" if annual else metric,
                                value=value,
                                period_end=period_end,
                                published_at=published_at,
                                published_at_estimated=estimated,
                                source=SOURCE,
                            )
                        )

        rows.extend(self._parse_eps_revisions(ticker, payload))
        return rows

    def _parse_eps_revisions(
        self, ticker: str, payload: object
    ) -> list[FundamentalRow]:
        """Consensus EPS drift over 90 days, for earnings_revision_3m.

        Earnings::Trend is a snapshot of today's consensus, not a history of
        past consensus, so this is only honest as of the fetch date. It is
        recorded with published_at = today and flagged estimated=False,
        because the consensus genuinely is public now — but it cannot be
        backfilled, and a backtest will simply find no rows before today.
        """
        trend = payload.get("Earnings", {}).get("Trend", {})
        if not isinstance(trend, dict) or not trend:
            return []

        # Trend carries one "0y" entry per fiscal year, including closed ones
        # whose 90-days-ago figures are long stale. Only the newest is a live
        # consensus, so select by date rather than by iteration order —
        # JSONB reorders object keys, so position is not stable across the
        # archive round-trip.
        current_year = [v for v in trend.values() if v.get("period") == "0y"]
        entry = max(
            (v for v in current_year if _day(v.get("date"))),
            key=lambda v: _day(v.get("date")),
            default=None,
        )
        if entry is None:
            return []

        current = _number(entry.get("epsTrendCurrent"))
        ninety = _number(entry.get("epsTrend90daysAgo"))
        if current is None or ninety is None or ninety == 0:
            return []

        as_of = _day(entry.get("date")) or date.today()
        change = (current - ninety) / abs(ninety) * 100.0
        today = date.today()
        return [
            FundamentalRow(
                ticker=ticker,
                metric="earnings_revision_3m",
                value=change,
                period_end=as_of,
                published_at=today,
                published_at_estimated=False,
                source=SOURCE,
            )
        ]
