"""Registry invariants: pre-registration, immutability, lineage, the gates."""

import uuid

import pytest

from app.strategies import registry
from app.strategies.rules import parse_rules, rule_signature

RULES = {
    "universe": {"min_market_cap": 2e9},
    "entry": {
        "kind": "all",
        "conditions": [
            {"kind": "compare", "id": "quality_floor", "feature": "lens:quality", "op": "gte", "value": 70},
        ],
    },
    "rank": {"components": [{"feature": "lens:quality", "direction": "desc"}], "top_n": 20},
    "rebalance": {"frequency": "monthly", "mode": "reconstitute"},
    "sizing": {"max_positions": 20},
}


def other_rules(threshold: float) -> dict:
    import copy

    out = copy.deepcopy(RULES)
    out["entry"]["conditions"][0]["value"] = threshold
    return out


async def register_one(session, name="Test QARP", rules=None, **overrides):
    return await registry.register(
        session,
        name=name,
        hypothesis="Good businesses at sane prices drift up.",
        authority="Roger's idea, 2026-08-13",
        rules=rules or RULES,
        horizon="medium",
        expected_trade_frequency="~10 trades/month",
        expected_holding_period="months",
        predicted_performance="Modest excess over drift, low turnover.",
        **overrides,
    )


@pytest.mark.asyncio
async def test_registration_creates_the_projection_row(session):
    strategy_id = await register_one(session)
    row = await session.get(registry.Strategy, strategy_id)
    assert row is not None
    assert row.status == "registered"
    assert row.stage == "backtest"
    assert row.rule_signature == rule_signature(RULES)
    assert "McLean" in row.decay_note


@pytest.mark.asyncio
async def test_identical_rules_are_rejected_outright(session):
    """Same signature = same strategy. A rename is not a new idea."""
    await register_one(session, name="Original")
    with pytest.raises(registry.DuplicateStrategyError, match="Original"):
        await register_one(session, name="Totally Different Name")


@pytest.mark.asyncio
async def test_a_tweak_is_a_new_strategy_with_lineage(session):
    parent = await register_one(session, name="Parent")
    child = await register_one(
        session, name="Child", rules=other_rules(75), parent_strategy_id=parent
    )
    row = await session.get(registry.Strategy, child)
    assert row.parent_strategy_id == parent


@pytest.mark.asyncio
async def test_activation_blocked_while_flagged_duplicate(session):
    strategy_id = await register_one(session)
    row = await session.get(registry.Strategy, strategy_id)
    row.duplicate_of = uuid.uuid4()
    row.duplicate_correlation = 0.93
    await session.flush()

    with pytest.raises(registry.ActivationBlocked):
        await registry.activate(session, strategy_id)

    # The override works, and is recorded rather than silent.
    await registry.activate(session, strategy_id, override_note="Different exit logic matters here.")
    await session.refresh(row)
    assert row.status == "active"
    assert row.duplicate_override_note == "Different exit logic matters here."


@pytest.mark.asyncio
async def test_lifecycle_and_rebuild(session):
    """The projection is disposable: truncate, replay, identical state."""
    strategy_id = await register_one(session)
    await registry.activate(session, strategy_id)
    await registry.promote(session, strategy_id, "paper", note="Backtest passed the gate.")
    await registry.pause(session, strategy_id, reason="Reviewing after drawdown.")

    before = await session.get(registry.Strategy, strategy_id)
    assert (before.status, before.stage) == ("paused", "paper")

    await registry.rebuild(session)
    after = await session.get(registry.Strategy, strategy_id)
    assert (after.status, after.stage) == ("paused", "paper")
    assert after.name == before.name


def test_signature_is_order_insensitive():
    a = {"universe": {"min_market_cap": 2e9}, **{k: RULES[k] for k in ("entry", "rank", "rebalance", "sizing")}}
    b = dict(reversed(list(a.items())))
    assert rule_signature(a) == rule_signature(b)


def test_correlation_needs_two_years_of_overlap():
    a = {f"2020-{m:02d}": float(m) for m in range(1, 13)}
    assert registry.correlation(a, a) is None  # only 12 shared months
    b = {f"20{y:02d}-{m:02d}": float(m + y) for y in range(20, 23) for m in range(1, 13)}
    assert registry.correlation(b, b) == pytest.approx(1.0)


def test_rules_reject_unknown_features():
    import copy

    bad = copy.deepcopy(RULES)
    bad["entry"]["conditions"][0]["feature"] = "lens:vibes"
    with pytest.raises(Exception, match="unknown lens"):
        parse_rules(bad)


def test_hold_mode_requires_exit_rules():
    import copy

    bad = copy.deepcopy(RULES)
    bad["rebalance"]["mode"] = "hold_until_exit"
    with pytest.raises(ValueError, match="exit"):
        parse_rules(bad)
