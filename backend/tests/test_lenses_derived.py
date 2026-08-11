"""Derived-metric tests. The derivation itself is pure — no database."""

from datetime import date

import pytest

from app.lenses import cycle
from app.lenses.base import band_score
from app.lenses.derived import days_inventory_change, derive_all
from app.lenses.engine import evaluate_lens

LATEST = date(2026, 3, 31)
PRIOR = date(2025, 3, 31)
AS_OF = date(2026, 6, 30)

SPEC = next(m for m in cycle.LENS.metrics if m.name == "days_inventory_change")


def test_falling_inventory_is_a_negative_change():
    history = {"days_inventory": [(LATEST, 94.0), (PRIOR, 120.0)]}
    assert days_inventory_change(history) == pytest.approx(-26.0)


def test_rising_inventory_is_a_positive_change():
    history = {"days_inventory": [(LATEST, 94.0), (PRIOR, 70.0)]}
    assert days_inventory_change(history) == pytest.approx(24.0)


def test_same_level_scores_differently_depending_on_direction():
    # The whole point: 94 days falling and 94 days rising are opposite
    # signals, and the level alone cannot tell them apart.
    falling = days_inventory_change({"days_inventory": [(LATEST, 94.0), (PRIOR, 120.0)]})
    rising = days_inventory_change({"days_inventory": [(LATEST, 94.0), (PRIOR, 70.0)]})

    assert band_score(SPEC, falling) > band_score(SPEC, rising)
    assert band_score(SPEC, falling) > 50 > band_score(SPEC, rising)


def test_derived_from_inventory_and_cogs_when_days_not_stored():
    # Both are stored by ingest anyway, so no separate series is needed.
    history = {
        "inventory": [(LATEST, 100.0), (PRIOR, 100.0)],
        "cogs": [(LATEST, 400.0), (PRIOR, 500.0)],
    }
    # 100/400*365 = 91.25 days now vs 100/500*365 = 73 days a year ago.
    assert days_inventory_change(history) == pytest.approx(18.25)


def test_stored_days_inventory_wins_over_recomputation():
    history = {
        "days_inventory": [(LATEST, 90.0), (PRIOR, 80.0)],
        "inventory": [(LATEST, 100.0), (PRIOR, 100.0)],
        "cogs": [(LATEST, 400.0), (PRIOR, 500.0)],
    }
    assert days_inventory_change(history) == pytest.approx(10.0)


def test_single_period_yields_no_change():
    assert days_inventory_change({"days_inventory": [(LATEST, 94.0)]}) is None
    assert days_inventory_change({}) is None


def test_history_that_is_not_a_year_back_is_refused():
    # Six months back is not a year-on-year comparison, and we decline to
    # pretend otherwise rather than quietly comparing the wrong periods.
    six_months = {"days_inventory": [(LATEST, 94.0), (date(2025, 9, 30), 120.0)]}
    assert days_inventory_change(six_months) is None

    # A shifted reporting calendar is still within tolerance.
    shifted = {"days_inventory": [(LATEST, 94.0), (date(2025, 4, 30), 120.0)]}
    assert days_inventory_change(shifted) == pytest.approx(-26.0)


def test_non_positive_cogs_leaves_the_period_without_a_reading():
    history = {
        "inventory": [(LATEST, 100.0), (PRIOR, 100.0)],
        "cogs": [(LATEST, 0.0), (PRIOR, 500.0)],
    }
    assert days_inventory_change(history) is None


def test_derive_all_omits_what_it_cannot_compute():
    assert derive_all({"days_inventory": [(LATEST, 94.0)]}) == {}
    assert "days_inventory_change" in derive_all(
        {"days_inventory": [(LATEST, 94.0), (PRIOR, 120.0)]}
    )


def test_missing_change_reduces_coverage_and_never_reuses_the_level():
    metrics = {
        "inventory_to_sales": 0.15,
        "days_inventory": 94.0,
        "capacity_utilisation": 80.0,
        "asp_change_yoy": 3.0,
        "book_to_bill": 1.05,
    }
    result = evaluate_lens(cycle.LENS, "CHIP", AS_OF, "semiconductors", metrics)

    entry = result.inputs["metrics"]["days_inventory_change"]
    assert entry["excluded"] == "not_available"
    assert entry["value"] is None
    assert entry["score"] is None  # the level is not scored twice in its place
    assert result.coverage == pytest.approx(5 / 6, abs=1e-4)
