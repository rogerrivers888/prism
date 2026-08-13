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


def variant(_seed=None):
    """A uniquely-signed rule-set.

    The test database persists between runs by design and the registry
    correctly rejects identical rules as duplicates, so each registration
    needs a signature nothing else will collide with.
    """
    import copy
    import random

    out = copy.deepcopy(RULES)
    out["entry"]["value"] = round(random.uniform(1, 99), 6)
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
    root = await _register(session, "Root", variant())
    child = await _register(session, "Child", variant(), parent=root)
    grandchild = await _register(session, "Grandchild", variant(), parent=child)
    unrelated = await _register(session, "Unrelated", variant())

    family = await family_of(session, grandchild)
    ids = {f.strategy_id for f in family}
    assert ids == {root, child, grandchild}
    assert unrelated not in ids

    # Every member sees the same family, so the deflation bar is the same
    # whichever one you look at.
    assert {f.strategy_id for f in await family_of(session, root)} == ids


def test_drift_control_can_hold_the_corpses():
    """With membership data, the control must be allowed to hold dead names.

    A control drawn from today's survivors while the strategy carries the
    dead is a benchmark of known winners — every excess would be biased
    downward, the same survivorship error pointed the other way.
    """
    import datetime
    from datetime import date as date_type

    from app.fundamentals import Security
    from app.strategies.features import Bar, FeatureService
    from app.strategies.gate import drift_control
    from app.strategies.rules import parse_rules
    from app.strategies.simulator import CostModel, RoundTrip, SimResult

    start = date_type(2020, 1, 1)
    bars, securities = {}, {}
    # DEAD rises hard then its membership ends; is_active is False today.
    for ticker, is_active, step in (("ALIVE", True, 0.0), ("DEAD", False, 0.5)):
        series, day = [], start
        for i in range(300):
            while day.weekday() >= 5:
                day += datetime.timedelta(days=1)
            series.append(Bar(day, 100.0, 100.0, 100.0 + i * step))
            day += datetime.timedelta(days=1)
        bars[ticker] = series
        securities[ticker] = Security(ticker=ticker, name=ticker, sector="hardware",
                                      quote_currency="USD", currency="USD",
                                      is_active=is_active)
    calendar = sorted({b.date for s_ in bars.values() for b in s_})
    membership = {"ALIVE": [(calendar[0], None)], "DEAD": [(calendar[0], None)]}
    rules = parse_rules({
        "universe": {},
        "entry": {"kind": "compare", "id": "e", "feature": "price:return_1m",
                  "op": "gt", "value": -1000},
        "rank": {"components": [{"feature": "price:return_1m", "direction": "desc"}],
                 "top_n": 1},
        "rebalance": {"frequency": "monthly", "mode": "reconstitute"},
        "sizing": {"max_positions": 1},
    })
    trips = [RoundTrip("ALIVE", calendar[270], calendar[280], "e", "x", 1.0, 14)]
    result = SimResult(trades=[], round_trips=trips, equity_curve=[],
                       final_equity=0, total_costs=0, skipped_no_fill=0)

    def build(with_membership):
        return FeatureService(start=calendar[0], end=calendar[-1],
                              securities=securities, bars=bars, fundamentals={},
                              lens_scores={}, lens_scores_abs={}, dispersion={},
                              sector_cycle={}, calendar=calendar,
                              membership=membership if with_membership else None)

    corrected = drift_control(build(True), rules, result, CostModel(), seed=1)
    survivor = drift_control(build(False), rules, result, CostModel(), seed=1)
    assert corrected["samples"] > 0 and survivor["samples"] > 0
    # DEAD rises and ALIVE is flat, so a control allowed to hold DEAD returns
    # more than one that cannot. If these were equal, membership did not widen
    # the control's universe and the comparison is survivor-biased again.
    assert corrected["mean_return_pct"] > survivor["mean_return_pct"]
