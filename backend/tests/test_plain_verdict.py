"""The plain-English rules, asserted rather than hoped for.

Roger said the backtest output was written for someone who already understood
it. These pin the parts of the fix that a later edit could quietly undo.
"""

import re

from app.backtest import plain_verdict

BASE = {
    "overall": {"trades": 31654, "mean_return_pct": 0.239, "cost_drag_pct": 0.300, "win_rate": 0.533},
    "control_unconditional_drift": {"samples": 20960, "mean_return_pct": 0.173},
    "variants_tested": 1,
}

# Notation that must never appear in the plain-English part.
NOTATION = re.compile(r"\bp\s*=|\bp-value|confidence interval|\bn\s*=|statistically significant", re.I)


def verdict(**overrides):
    payload = {**BASE, **overrides}
    return plain_verdict(payload)


def test_leads_with_not_worth_it_when_there_is_no_edge():
    result = verdict(excess_over_drift_pct=-0.05, excess_significance={"inside_noise": False})
    assert result["worth_acting_on"] is False
    # The judgement is in the first sentence, not buried after the numbers.
    assert result["headline"].startswith("This is not worth acting on")


def test_says_could_be_a_coincidence_rather_than_quoting_a_p_value():
    result = verdict(excess_over_drift_pct=0.066, excess_significance={"inside_noise": True})
    assert "coincidence" in result["headline"]
    assert result["worth_acting_on"] is False


def test_translates_a_percentage_into_money():
    """A per-trade percentage means nothing until it is pounds on a position
    someone might actually take."""
    result = verdict(excess_over_drift_pct=0.58, excess_significance={"inside_noise": False})
    assert "£58" in result["headline"]
    assert "£10,000" in result["headline"]
    assert result["worth_acting_on"] is True


def test_no_statistical_notation_anywhere_in_the_verdict():
    for overrides in (
        {"excess_over_drift_pct": 0.58, "excess_significance": {"inside_noise": False}},
        {"excess_over_drift_pct": 0.066, "excess_significance": {"inside_noise": True}},
        {"excess_over_drift_pct": -0.1, "excess_significance": {"inside_noise": False}},
    ):
        result = verdict(**overrides)
        blob = result["headline"] + " " + result["body"]
        assert not NOTATION.search(blob), f"notation leaked into: {blob}"


def test_always_states_the_survivorship_caveat():
    result = verdict(excess_over_drift_pct=0.58, excess_significance={"inside_noise": False})
    assert "went bust" in result["body"]


def test_mentions_how_many_variants_were_tried():
    result = verdict(
        excess_over_drift_pct=0.58, excess_significance={"inside_noise": False}, variants_tested=6
    )
    assert "6 different combinations" in result["body"]


def test_handles_a_run_with_no_trades():
    assert plain_verdict({"overall": {"trades": 0}})["worth_acting_on"] is False
