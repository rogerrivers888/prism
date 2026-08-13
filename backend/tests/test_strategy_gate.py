"""Gate arithmetic: deflation across the family, track-record honesty, and
the promotion criteria."""

import random
import uuid

import pytest

from app.strategies import registry
from app.strategies.gate import (
    annualised_sharpe,
    assess,
    deflate,
    expected_max_under_null,
    family_of,
    minimum_track_record_months,
    track_record_verdict,
)


def test_expected_max_grows_with_the_number_of_attempts():
    """The whole point: trying more things raises the bar for all of them."""
    assert expected_max_under_null(1) == 0.0
    values = [expected_max_under_null(n) for n in (2, 5, 12, 50, 200)]
    assert values == sorted(values)
    # Twelve strategies: the best would clear ~1.7 standard errors on luck alone.
    assert 1.5 < expected_max_under_null(12) < 1.9


def test_deflation_rejects_a_result_that_luck_would_have_produced():
    random.seed(7)
    # A worthless strategy: mean zero, plenty of noise.
    noise = [random.gauss(0.0, 5.0) for _ in range(200)]
    result = deflate(noise, [], n_trials=12)
    assert result["per_trade"]["survives"] is False


def test_deflation_accepts_a_result_far_beyond_luck():
    random.seed(7)
    strong = [random.gauss(3.0, 2.0) for _ in range(200)]
    result = deflate(strong, [], n_trials=12)
    assert result["per_trade"]["survives"] is True
    assert result["per_trade"]["margin_pct"] > 0


def test_a_single_trial_still_needs_a_positive_result():
    """With one attempt the deflation bar is zero, not negative."""
    random.seed(7)
    flat = [random.gauss(0.0, 3.0) for _ in range(200)]
    result = deflate(flat, [], n_trials=1)
    assert result["expected_max_z"] == 0.0
    assert result["per_trade"]["survives"] is (result["per_trade"]["observed_mean_pct"] > 0)


def test_track_record_refuses_to_certify_a_negative_edge():
    losing = [-1.0, -0.5, -2.0, 0.3, -1.2, -0.8, -1.5, 0.1] * 2
    assert minimum_track_record_months(losing) is None
    verdict = track_record_verdict(16, 40, losing)
    assert "nothing for more data to confirm" in verdict


def test_short_records_are_called_meaningless_in_plain_english():
    random.seed(3)
    noisy = [random.gauss(0.4, 6.0) for _ in range(8)]
    verdict = track_record_verdict(8, 11, noisy)
    assert "meaningless" in verdict or "too early" in verdict.lower()
    # No notation in a sentence meant for a non-statistician.
    assert "p=" not in verdict and "n=" not in verdict


def test_no_trades_says_so():
    assert track_record_verdict(0, 0, []) == "No trades yet — nothing to judge."


def test_sharpe_needs_a_year():
    assert annualised_sharpe([1.0] * 11) is None
    assert annualised_sharpe([1.0, -1.0] * 6) is not None


def test_gate_blocks_on_each_criterion_separately():
    too_few = assess({"overall": {"round_trips": 10, "mean_trade_return_pct": 2.0},
                      "drift_control": {"samples": 100}, "excess_over_drift_pct": 1.0})
    assert not too_few.passed and "too few" in too_few.reasons[0]

    negative = assess({"overall": {"round_trips": 100, "mean_trade_return_pct": -0.5},
                       "drift_control": {"samples": 100}, "excess_over_drift_pct": 1.0})
    assert not negative.passed
    assert any("expectancy" in r for r in negative.reasons)

    no_edge = assess({"overall": {"round_trips": 100, "mean_trade_return_pct": 0.5},
                      "drift_control": {"samples": 100}, "excess_over_drift_pct": -0.2})
    assert not no_edge.passed
    assert any("random" in r for r in no_edge.reasons)

    passes = assess({"overall": {"round_trips": 100, "mean_trade_return_pct": 0.5},
                     "drift_control": {"samples": 100}, "excess_over_drift_pct": 0.3})
    assert passes.passed and passes.reasons == []


RULES = {
    "universe": {},
    "entry": {"kind": "compare", "id": "e", "feature": "lens:quality", "op": "gte", "value": 70},
    "rank": {"components": [{"feature": "lens:quality", "direction": "desc"}], "top_n": 5},
    "rebalance": {"frequency": "monthly", "mode": "reconstitute"},
    "sizing": {"max_positions": 5},
}


def variant(threshold):
    import copy
    out = copy.deepcopy(RULES)
    out["entry"]["value"] = threshold
    return out


async def _register(session, name, rules, parent=None):
    return await registry.register(
        session, name=name, hypothesis="h", authority="a", rules=rules,
        horizon="medium", expected_trade_frequency="f", expected_holding_period="p",
        predicted_performance="pp", parent_strategy_id=parent,
    )


@pytest.mark.asyncio
async def test_family_counts_every_descendant_as_a_trial(session):
    """Three tweaks of one idea are four attempts, not one."""
    root = await _register(session, "Root", RULES)
    child = await _register(session, "Child", variant(71), parent=root)
    grandchild = await _register(session, "Grandchild", variant(72), parent=child)
    unrelated = await _register(session, "Unrelated", variant(90))

    family = await family_of(session, grandchild)
    ids = {f.strategy_id for f in family}
    assert ids == {root, child, grandchild}
    assert unrelated not in ids

    # Every member sees the same family, so the deflation bar is the same
    # whichever one you look at.
    assert {f.strategy_id for f in await family_of(session, root)} == ids
