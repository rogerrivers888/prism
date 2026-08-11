"""Metrics derived from stored history rather than ingested pre-computed.

Pure: history in, numbers out, no database. The engine injects the results
alongside ingested metrics before scoring, so a derived metric behaves like
any other from then on — including taking part in sector percentiles.

Ingest stores raw statement line items and raw prices; every ratio is formed
here. That means changing a formula costs a re-score, never a re-fetch, and
the point-in-time rule is inherited for free: the history handed in has
already been filtered to what was published by the scoring date.

A derived metric that cannot be computed is simply absent, which reduces
coverage like any other missing input. It never falls back to a related
figure: substituting something we can measure for something we cannot is the
kind of quiet dishonesty the coverage rule exists to prevent.
"""

from collections.abc import Mapping, Sequence
from datetime import date

DAYS_IN_YEAR = 365.0

# Statement line items read from history. Quarterly flows are summed to a
# trailing twelve months; balance items are point-in-time.
FLOW_METRICS = (
    "revenue",
    "cogs",
    "gross_profit",
    "ebitda_quarter",
    "ebit_quarter",
    "net_income_quarter",
    "interest_expense_quarter",
    "income_before_tax_quarter",
    "tax_provision_quarter",
    "fcf_quarter",
)
STOCK_METRICS = (
    "inventory",
    "total_assets",
    "net_debt",
    "invested_capital",
    "total_equity",
    "shares_outstanding",
)
SOURCE_METRICS = FLOW_METRICS + STOCK_METRICS + ("days_inventory",)

# Trading-day offsets for trailing returns.
TRADING_DAYS = {"return_3m": 63, "return_6m": 126, "return_12m": 252}

# How far from exactly one year a comparison period may sit. Reporting
# calendars shift, so a quarter of slack either way; anything outside this is
# not a year-on-year comparison and we decline to pretend otherwise.
PRIOR_YEAR_MIN_DAYS = 300
PRIOR_YEAR_MAX_DAYS = 430

History = Mapping[str, Sequence[tuple[date, float]]]
Prices = Sequence[tuple[date, float]]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _periods(history: History, metric: str) -> list[tuple[date, float]]:
    """Observations newest first."""
    return sorted(history.get(metric, ()), key=lambda pair: pair[0], reverse=True)


def _ttm(history: History, metric: str, skip: int = 0) -> float | None:
    """Sum of four consecutive quarters, skipping the newest ``skip`` of them."""
    series = _periods(history, metric)
    window = series[skip : skip + 4]
    if len(window) < 4:
        return None
    return sum(value for _, value in window)


def _latest(history: History, metric: str) -> float | None:
    series = _periods(history, metric)
    return series[0][1] if series else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _growth(current: float | None, prior: float | None) -> float | None:
    """Percentage change. None when the base is non-positive.

    Growth off a negative or zero base is not a meaningful percentage — a
    swing from -100 to +50 is not "150% growth" — so we decline it rather
    than emit a number that would rank.
    """
    if current is None or prior is None or prior <= 0:
        return None
    return (current / prior - 1.0) * 100.0


def _cagr(current: float | None, prior: float | None, years: int) -> float | None:
    if current is None or prior is None or prior <= 0 or current <= 0:
        return None
    return ((current / prior) ** (1.0 / years) - 1.0) * 100.0


# --------------------------------------------------------------------------
# statement-derived metrics
# --------------------------------------------------------------------------


def _eps_ttm(history: History, skip: int = 0) -> float | None:
    """Trailing EPS using the share count reported alongside the period."""
    net_income = _ttm(history, "net_income_quarter", skip)
    shares = _periods(history, "shares_outstanding")
    if net_income is None or len(shares) <= skip:
        return None
    return _ratio(net_income, shares[skip][1])


def from_statements(history: History) -> dict[str, float]:
    """Every ratio computable from trailing statement history."""
    derived: dict[str, float] = {}

    revenue = _ttm(history, "revenue")
    cogs = _ttm(history, "cogs")
    gross_profit = _ttm(history, "gross_profit")
    ebitda = _ttm(history, "ebitda_quarter")
    ebit = _ttm(history, "ebit_quarter")
    net_income = _ttm(history, "net_income_quarter")
    interest = _ttm(history, "interest_expense_quarter")
    pre_tax = _ttm(history, "income_before_tax_quarter")
    tax = _ttm(history, "tax_provision_quarter")
    fcf = _ttm(history, "fcf_quarter")

    total_assets = _latest(history, "total_assets")
    net_debt = _latest(history, "net_debt")
    invested_capital = _latest(history, "invested_capital")
    inventory = _latest(history, "inventory")

    # Context metrics the guards consult. Named to match what guards expect.
    if ebitda is not None:
        derived["ebitda"] = ebitda
    if fcf is not None:
        derived["fcf"] = fcf

    # --- quality ---
    if ebit is not None and invested_capital not in (None, 0):
        tax_rate = _ratio(tax, pre_tax)
        # An implausible effective rate means the inputs disagree; fall back
        # to no adjustment rather than inventing one.
        if tax_rate is None or not 0.0 <= tax_rate <= 0.6:
            tax_rate = 0.0
        nopat = ebit * (1.0 - tax_rate)
        derived["roic"] = nopat / invested_capital * 100.0

    gross_profitability = _ratio(gross_profit, total_assets)
    if gross_profitability is not None:
        derived["gross_profitability"] = gross_profitability

    gross_margin = _ratio(gross_profit, revenue)
    if gross_margin is not None:
        derived["gross_margin"] = gross_margin * 100.0

    net_debt_to_ebitda = _ratio(net_debt, ebitda)
    if net_debt_to_ebitda is not None and ebitda > 0:
        derived["net_debt_to_ebitda"] = net_debt_to_ebitda

    # Zero reported interest is not infinite cover — it usually means the
    # expense was capitalised or netted off. Absent beats a fabricated 100.
    if ebit is not None and interest is not None and interest > 0:
        derived["interest_cover"] = ebit / interest

    fcf_conversion = _ratio(fcf, net_income)
    if fcf_conversion is not None and net_income > 0:
        derived["fcf_conversion"] = fcf_conversion * 100.0

    # --- growth ---
    revenue_prior = _ttm(history, "revenue", skip=4)
    revenue_3y = _ttm(history, "revenue", skip=12)
    fcf_prior = _ttm(history, "fcf_quarter", skip=4)

    for metric, value in (
        ("revenue_growth_yoy", _growth(revenue, revenue_prior)),
        ("revenue_cagr_3y", _cagr(revenue, revenue_3y, 3)),
        ("eps_growth_yoy", _growth(_eps_ttm(history), _eps_ttm(history, skip=4))),
        ("eps_cagr_3y", _cagr(_eps_ttm(history), _eps_ttm(history, skip=12), 3)),
        ("fcf_growth_yoy", _growth(fcf, fcf_prior)),
    ):
        if value is not None:
            derived[metric] = value

    # --- cycle ---
    inventory_to_sales = _ratio(inventory, revenue)
    if inventory_to_sales is not None:
        derived["inventory_to_sales"] = inventory_to_sales

    days_inventory = _ratio(inventory, cogs)
    if days_inventory is not None:
        derived["days_inventory"] = days_inventory * DAYS_IN_YEAR

    return derived


def _days_inventory_by_period(history: History) -> dict[date, float]:
    """Days inventory at each period we can establish it for.

    Uses an ingested figure when present, otherwise computes it from
    inventory and trailing COGS, which ingest stores anyway — so no separate
    days-inventory series has to be maintained.
    """
    stored = dict(history.get("days_inventory", ()))
    inventory = dict(history.get("inventory", ()))

    cogs_series = _periods(history, "cogs")
    by_period: dict[date, float] = dict(stored)
    for index, (period, _) in enumerate(cogs_series):
        if period in by_period or period not in inventory:
            continue
        trailing = _ttm({"cogs": cogs_series}, "cogs", skip=index)
        if trailing and trailing > 0:
            by_period[period] = inventory[period] / trailing * DAYS_IN_YEAR
    return by_period


def days_inventory_change(history: History) -> float | None:
    """Year-on-year change in days inventory, in days. None without history.

    Direction carries more information than level in a cyclical business:
    94 days falling alongside rising prices signals a tightening cycle, while
    94 days rising signals a glut forming. The level alone cannot tell them
    apart, which is why this sits beside days_inventory rather than
    replacing it.
    """
    by_period = _days_inventory_by_period(history)
    if len(by_period) < 2:
        return None

    latest = max(by_period)
    candidates = [
        period
        for period in by_period
        if PRIOR_YEAR_MIN_DAYS <= (latest - period).days <= PRIOR_YEAR_MAX_DAYS
    ]
    if not candidates:
        # History exists but nothing sits a year back — not enough to compute
        # a change, so the metric is unavailable rather than approximated.
        return None

    prior = min(candidates, key=lambda p: abs((latest - p).days - DAYS_IN_YEAR))
    return round(by_period[latest] - by_period[prior], 6)


# --------------------------------------------------------------------------
# price-derived metrics
# --------------------------------------------------------------------------


def from_prices(prices: Prices) -> dict[str, float]:
    """Trend and momentum metrics from a price series (newest first)."""
    series = sorted(prices, key=lambda pair: pair[0], reverse=True)
    if not series:
        return {}

    closes = [value for _, value in series]
    latest = closes[0]
    derived: dict[str, float] = {}

    ma50 = sum(closes[:50]) / 50 if len(closes) >= 50 else None
    ma200 = sum(closes[:200]) / 200 if len(closes) >= 200 else None

    if ma50:
        derived["price_vs_50dma"] = (latest / ma50 - 1.0) * 100.0
    if ma200:
        derived["price_vs_200dma"] = (latest / ma200 - 1.0) * 100.0
    if ma50 and ma200:
        derived["ma50_vs_ma200"] = (ma50 / ma200 - 1.0) * 100.0

    if len(closes) >= 252:
        low_52w = min(closes[:252])
        if low_52w > 0:
            derived["pct_above_52w_low"] = (latest / low_52w - 1.0) * 100.0

    for metric, offset in TRADING_DAYS.items():
        if len(closes) > offset and closes[offset] > 0:
            derived[metric] = (latest / closes[offset] - 1.0) * 100.0

    return derived


def from_prices_and_statements(
    prices: Prices, history: History, statements: Mapping[str, float]
) -> dict[str, float]:
    """Valuation metrics, which need a price and a set of trailing figures."""
    series = sorted(prices, key=lambda pair: pair[0], reverse=True)
    shares = _latest(history, "shares_outstanding")
    if not series or not shares:
        return {}

    market_cap = series[0][1] * shares
    if market_cap <= 0:
        return {}

    derived: dict[str, float] = {}
    net_income = _ttm(history, "net_income_quarter")
    ebitda = statements.get("ebitda")
    fcf = statements.get("fcf")
    equity = _latest(history, "total_equity")
    net_debt = _latest(history, "net_debt")

    if net_income is not None and net_income > 0:
        # A negative P/E is not "cheap"; it is not a multiple at all.
        derived["pe_ratio"] = market_cap / net_income
    if ebitda is not None and ebitda > 0 and net_debt is not None:
        derived["ev_ebitda"] = (market_cap + net_debt) / ebitda
    if fcf is not None:
        derived["fcf_yield"] = fcf / market_cap * 100.0
    if equity is not None and equity > 0:
        derived["price_to_book"] = market_cap / equity

    return derived


DERIVATIONS = {"days_inventory_change": days_inventory_change}


def derive_all(
    history: History, prices: Prices = ()
) -> dict[str, float]:
    """Every derived metric computable from this history and price series."""
    derived = from_statements(history)
    derived.update(from_prices(prices))
    derived.update(from_prices_and_statements(prices, history, derived))
    for name, derive in DERIVATIONS.items():
        computed = derive(history)
        if computed is not None:
            derived[name] = computed
    return derived
