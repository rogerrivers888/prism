"""Metrics derived from fundamentals history rather than ingested directly.

Pure: these take a period history in and return a number out, no database.
The engine injects the results alongside the ingested metrics before scoring,
so a derived metric behaves exactly like any other from then on — including
taking part in sector percentiles.

A derived metric that cannot be computed is simply absent, which reduces
coverage like any other missing input. It never falls back to a related
figure: substituting something we can measure for something we cannot is the
kind of quiet dishonesty the coverage rule exists to prevent.
"""

from collections.abc import Mapping, Sequence
from datetime import date

# Metrics read from history to compute the derived values below. Fetched as
# full history rather than latest-only, so keep this list tight.
SOURCE_METRICS = ("days_inventory", "inventory", "cogs")

DAYS_IN_YEAR = 365.0

# How far from exactly one year a comparison period may sit. Reporting
# calendars shift, so a quarter of slack either way; anything outside this is
# not a year-on-year comparison and we decline to pretend otherwise.
PRIOR_YEAR_MIN_DAYS = 300
PRIOR_YEAR_MAX_DAYS = 430

History = Mapping[str, Sequence[tuple[date, float]]]


def _days_inventory_by_period(history: History) -> dict[date, float]:
    """Days inventory at each period we can establish it for.

    Uses the ingested figure when present, otherwise computes it from
    inventory and COGS, which the ingest layer stores anyway — so no separate
    days-inventory series has to be maintained.
    """
    stored = dict(history.get("days_inventory", ()))
    inventory = dict(history.get("inventory", ()))
    cogs = dict(history.get("cogs", ()))

    by_period: dict[date, float] = {}
    for period in set(stored) | (set(inventory) & set(cogs)):
        if period in stored:
            by_period[period] = stored[period]
        elif cogs[period] > 0:
            # Zero or negative COGS makes the ratio meaningless, so the
            # period simply has no reading.
            by_period[period] = inventory[period] / cogs[period] * DAYS_IN_YEAR
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


DERIVATIONS = {"days_inventory_change": days_inventory_change}


def derive_all(history: History) -> dict[str, float]:
    """Every derived metric computable from this history."""
    derived = {}
    for name, derive in DERIVATIONS.items():
        computed = derive(history)
        if computed is not None:
            derived[name] = computed
    return derived
