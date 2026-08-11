"""Pure scoring tests — no database, no session."""

from datetime import date

import pytest

from app.lenses.base import (
    LensScore,
    MetricSpec,
    band_score,
    dispersion,
    percentile_score,
    validate_bands,
)
from app.lenses.engine import LENSES, evaluate_lens
from app.lenses.guards import FLAG_FCF_NEEDS_CLASSIFICATION
from app.lenses import cycle, value

AS_OF = date(2026, 6, 30)
FULL = {
    "pe_ratio": 15.0,
    "ev_ebitda": 9.0,
    "fcf_yield": 4.0,
    "price_to_book": 2.5,
    "dividend_yield": 2.5,
    "ebitda": 500.0,
    "fcf": 200.0,
}


def _score(lens, sector, metrics, peers=None):
    return evaluate_lens(lens, "TEST", AS_OF, sector, metrics, peers)


def test_every_lens_band_table_matches_its_declared_direction():
    # The bands encode direction implicitly and higher_is_better encodes it
    # explicitly; if they ever disagree, scores silently invert.
    for lens in LENSES:
        for spec in lens.metrics:
            validate_bands(spec)


def test_band_score_interpolates_and_clamps():
    spec = MetricSpec("x", higher_is_better=True, bands=((0, 0), (10, 50), (20, 100)))
    assert band_score(spec, -5) == 0.0
    assert band_score(spec, 0) == 0.0
    assert band_score(spec, 5) == 25.0
    assert band_score(spec, 15) == 75.0
    assert band_score(spec, 99) == 100.0


def test_percentile_orients_by_direction():
    lower_better = MetricSpec("pe", higher_is_better=False, bands=((0, 100), (50, 0)))
    higher_better = MetricSpec("roic", higher_is_better=True, bands=((0, 0), (50, 100)))
    peers = [10.0, 20.0, 30.0, 40.0]

    # Cheapest of four peers scores well on a lower-is-better metric...
    assert percentile_score(lower_better, 10.0, peers) == pytest.approx(87.5)
    # ...and the same rank scores badly when higher is better.
    assert percentile_score(higher_better, 10.0, peers) == pytest.approx(12.5)


def test_ties_split_evenly():
    spec = MetricSpec("x", higher_is_better=True, bands=((0, 0), (10, 100)))
    assert percentile_score(spec, 5.0, [5.0, 5.0, 5.0, 5.0]) == pytest.approx(50.0)


def test_negative_ebitda_excludes_ev_ebitda_and_reduces_coverage():
    metrics = dict(FULL, ebitda=-50.0)
    result = _score(value.LENS, "industrials", metrics)

    entry = result.inputs["metrics"]["ev_ebitda"]
    assert entry["excluded"] == "ebitda_non_positive"
    assert entry["score"] is None  # excluded, not scored zero
    assert result.coverage == pytest.approx(0.8)  # 4 of 5 declared inputs
    assert result.score is not None


def test_asset_light_sector_excludes_price_to_book():
    result = _score(value.LENS, "software", FULL)
    assert result.inputs["metrics"]["price_to_book"]["excluded"] == "asset_light_sector"
    assert result.coverage == pytest.approx(0.8)


def test_negative_fcf_excludes_yield_and_flags_for_classification():
    # Structural or cyclical? The number alone cannot say, so we flag.
    result = _score(value.LENS, "industrials", dict(FULL, fcf=-100.0))
    assert result.inputs["metrics"]["fcf_yield"]["excluded"] == "fcf_negative_unclassified"
    assert FLAG_FCF_NEEDS_CLASSIFICATION in result.inputs["flags"]


def test_coverage_below_half_yields_null_score():
    # Two of five inputs: a score here would look exactly as confident as one
    # built on all five.
    thin = {"pe_ratio": 15.0, "fcf_yield": 4.0}
    result = _score(value.LENS, "industrials", thin)

    assert result.coverage == pytest.approx(0.4)
    assert result.score is None
    assert result.applicable is True
    assert result.inputs["withheld"] == "coverage_below_minimum"


def test_coverage_exactly_half_still_scores():
    metrics = {"roic": 12.0, "gross_margin": 40.0, "interest_cover": 8.0}
    from app.lenses import quality

    result = _score(quality.LENS, "industrials", metrics)
    assert result.coverage == pytest.approx(0.6)
    assert result.score is not None


def test_cycle_is_inapplicable_for_a_non_cyclical_sector():
    metrics = {
        "inventory_to_sales": 0.15,
        "days_inventory": 60.0,
        "capacity_utilisation": 80.0,
        "asp_change_yoy": 3.0,
        "book_to_bill": 1.05,
    }
    result = _score(cycle.LENS, "consumer_staples", metrics)

    assert result.applicable is False
    assert result.score is None  # never a number, even with every input present
    assert result.coverage == 0.0
    assert result.inputs["reason"] == "lens_not_applicable_to_sector"

    # ...but the same inputs do score for a sector that genuinely cycles.
    cyclical = _score(cycle.LENS, "semiconductors", metrics)
    assert cyclical.applicable is True
    assert cyclical.score is not None


def test_percentile_falls_back_to_bands_with_a_small_peer_set():
    seven = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0]
    small = _score(value.LENS, "industrials", FULL, {"pe_ratio": seven})
    assert small.inputs["metrics"]["pe_ratio"]["method"] == "absolute_bands"
    assert small.inputs["metrics"]["pe_ratio"]["peer_count"] == 7

    eight = seven + [24.0]
    big = _score(value.LENS, "industrials", FULL, {"pe_ratio": eight})
    assert big.inputs["metrics"]["pe_ratio"]["method"] == "peer_percentile"
    assert big.inputs["metrics"]["pe_ratio"]["peer_count"] == 8


def _fake(lens: str, score: float | None, applicable: bool = True) -> LensScore:
    return LensScore(
        ticker="X",
        as_of=AS_OF,
        lens=lens,
        score=score,
        coverage=1.0,
        applicable=applicable,
    )


def test_dispersion_needs_three_usable_lenses():
    two = [_fake("value", 20.0), _fake("growth", 80.0)]
    assert dispersion(two) is None

    three = two + [_fake("quality", 50.0)]
    assert dispersion(three) == pytest.approx(60.0)


def test_dispersion_ignores_inapplicable_and_null_scores():
    scores = [
        _fake("value", 20.0),
        _fake("growth", 80.0),
        _fake("cycle", None, applicable=False),  # inapplicable
        _fake("quality", None),  # applicable but coverage too thin
    ]
    # Only two usable readings, so no honest disagreement figure.
    assert dispersion(scores) is None

    scores.append(_fake("momentum", 55.0))
    assert dispersion(scores) == pytest.approx(60.0)
