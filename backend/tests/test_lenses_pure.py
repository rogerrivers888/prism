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


def test_healthcare_is_asset_heavy_and_keeps_price_to_book():
    # Pharma and devices carry plant, inventory and real book value. Biotech
    # is the known exception we cannot yet distinguish.
    result = _score(value.LENS, "healthcare", FULL)
    assert result.inputs["metrics"]["price_to_book"]["excluded"] is None
    assert result.coverage == pytest.approx(1.0)


@pytest.mark.parametrize("sector", ["financials", "banks", "insurance"])
def test_financials_exclude_ev_and_ebitda_metrics_but_keep_price_to_book(sector):
    from app.lenses import quality

    value_result = _score(value.LENS, sector, FULL)
    metrics = value_result.inputs["metrics"]
    # Undefined, not merely unflattering: deposits are funding, not leverage.
    assert metrics["ev_ebitda"]["excluded"] == "financials_ev_ebitda_undefined"
    assert metrics["ev_ebitda"]["score"] is None
    # P/B is the opposite case — one of the better value metrics here.
    assert metrics["price_to_book"]["excluded"] is None
    assert metrics["price_to_book"]["score"] is not None
    assert value_result.coverage == pytest.approx(0.8)

    quality_metrics = {
        "roic": 12.0,
        "gross_profitability": 0.28,
        "gross_margin": 40.0,  # display-only, not in the denominator
        "net_debt_to_ebitda": 1.5,
        "interest_cover": 8.0,
        "fcf_conversion": 85.0,
    }
    quality_result = _score(quality.LENS, sector, quality_metrics)
    assert (
        quality_result.inputs["metrics"]["net_debt_to_ebitda"]["excluded"]
        == "financials_ev_ebitda_undefined"
    )
    assert quality_result.coverage == pytest.approx(0.8)


def test_financials_guard_can_push_coverage_below_the_minimum():
    # A thin financial loses EV/EBITDA and lands under half coverage. A null
    # score is the correct outcome; the survivors are not reweighted to hide it.
    thin = {"pe_ratio": 11.0, "ev_ebitda": 9.0, "price_to_book": 0.9}
    result = _score(value.LENS, "banks", thin)

    assert result.coverage == pytest.approx(0.4)
    assert result.score is None
    assert result.inputs["withheld"] == "coverage_below_minimum"


def test_ev_ebitda_derived_metrics_are_declared_not_name_matched():
    # The guard keys off the metric's own declaration, so a future EV or
    # EBITDA ratio is covered by declaring itself rather than by a name list.
    derived = {
        (lens.name, spec.name)
        for lens in LENSES
        for spec in lens.metrics
        if spec.ev_or_ebitda_derived
    }
    assert derived == {("value", "ev_ebitda"), ("quality", "net_debt_to_ebitda")}


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


def test_coverage_above_the_minimum_still_scores():
    from app.lenses import quality

    metrics = {"roic": 12.0, "gross_profitability": 0.28, "interest_cover": 8.0}
    result = _score(quality.LENS, "industrials", metrics)
    assert result.coverage == pytest.approx(0.6)
    assert result.score is not None


def test_display_only_metric_is_returned_but_never_scored():
    from app.lenses import quality

    metrics = {
        "roic": 12.0,
        "gross_profitability": 0.28,
        "gross_margin": 82.0,  # display-only: a software-like margin
        "net_debt_to_ebitda": 1.5,
        "interest_cover": 8.0,
        "fcf_conversion": 85.0,
    }
    result = _score(quality.LENS, "software", metrics)

    entry = result.inputs["metrics"]["gross_margin"]
    assert entry["value"] == 82.0  # fetched and returned for the UI
    assert entry["scored"] is False
    assert entry["score"] is None  # takes no part in the score
    assert "gross_margin" not in result.inputs["declared"]
    assert result.inputs["display_only"] == ["gross_margin"]
    # Five scored inputs, all present.
    assert result.coverage == pytest.approx(1.0)


def test_display_only_metric_does_not_move_coverage_either_way():
    from app.lenses import quality

    scored_only = {
        "roic": 12.0,
        "gross_profitability": 0.28,
        "net_debt_to_ebitda": 1.5,
    }
    without = _score(quality.LENS, "industrials", scored_only)
    with_display = _score(quality.LENS, "industrials", dict(scored_only, gross_margin=40.0))

    # Absent, it cannot dilute coverage; present, it cannot inflate it.
    assert without.coverage == with_display.coverage == pytest.approx(0.6)
    assert without.score == with_display.score


def test_a_manufacturer_is_not_penalised_for_its_margin_structure():
    # The point of the demotion: two businesses identical on every scored
    # input but with structurally different gross margins must score the same.
    from app.lenses import quality

    base = {
        "roic": 12.0,
        "gross_profitability": 0.28,
        "net_debt_to_ebitda": 1.5,
        "interest_cover": 8.0,
        "fcf_conversion": 85.0,
    }
    manufacturer = _score(quality.LENS, "industrials", dict(base, gross_margin=38.0))
    software = _score(quality.LENS, "industrials", dict(base, gross_margin=81.0))

    assert manufacturer.score == software.score
    assert manufacturer.inputs["metrics"]["gross_margin"]["value"] == 38.0
    assert software.inputs["metrics"]["gross_margin"]["value"] == 81.0


def test_gross_profitability_bands_follow_the_novy_marx_thresholds():
    from app.lenses import quality

    spec = next(m for m in quality.LENS.metrics if m.name == "gross_profitability")
    assert spec.scored is True
    weak, average_low, strong = (
        band_score(spec, 0.12),
        band_score(spec, 0.22),
        band_score(spec, 0.40),
    )
    assert weak < average_low < strong
    assert band_score(spec, 0.15) < 50  # weak
    assert band_score(spec, 0.33) >= 70  # strong


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
