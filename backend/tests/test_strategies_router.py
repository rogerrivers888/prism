"""Endpoint behaviour: ranking discipline and the promotion gate."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.strategies import registry

RULES = {
    "universe": {},
    "entry": {"kind": "compare", "id": "e", "feature": "lens:quality", "op": "gte", "value": 70},
    "rank": {"components": [{"feature": "lens:quality", "direction": "desc"}], "top_n": 5},
    "rebalance": {"frequency": "monthly", "mode": "reconstitute"},
    "sizing": {"max_positions": 5},
}


def variant(_seed=None):
    """A uniquely-signed rule-set.

    The test database persists between runs by design, and identical rules are
    rejected as duplicates by the registry — correctly. So each test builds a
    rule-set nothing else will collide with.
    """
    import copy
    import random

    out = copy.deepcopy(RULES)
    out["entry"]["value"] = round(random.uniform(1, 99), 6)
    return out


async def client(session):
    from app.db import get_session

    app.dependency_overrides[get_session] = lambda: session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_promotion_refuses_a_strategy_that_failed_the_gate(session):
    strategy_id = await registry.register(
        session, name="Failing", hypothesis="h", authority="a", rules=variant(),
        horizon="medium", expected_trade_frequency="f", expected_holding_period="p",
        predicted_performance="pp",
    )
    session.add(registry.StrategyBacktest(
        strategy_id=strategy_id,
        results={"gate": {"eligible_for_paper": False,
                          "blocking_reasons": ["expectancy after costs is not positive"]}},
        monthly_returns=[],
    ))
    await session.flush()

    async with await client(session) as c:
        response = await c.post(f"/strategies/{strategy_id}/promote", json={"stage": "paper"})
    assert response.status_code == 409
    assert "expectancy" in response.json()["detail"]

    fresh = await session.get(registry.Strategy, strategy_id)
    assert fresh.stage == "backtest"
    assert fresh.status == "registered"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_promotion_without_any_backtest_is_refused(session):
    strategy_id = await registry.register(
        session, name="Ungated", hypothesis="h", authority="a", rules=variant(),
        horizon="medium", expected_trade_frequency="f", expected_holding_period="p",
        predicted_performance="pp",
    )
    async with await client(session) as c:
        response = await c.post(f"/strategies/{strategy_id}/promote", json={"stage": "paper"})
    assert response.status_code == 409
    assert "no backtest" in response.json()["detail"]
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_passing_the_gate_promotes_and_activates(session):
    strategy_id = await registry.register(
        session, name="Passing", hypothesis="h", authority="a", rules=variant(),
        horizon="long", expected_trade_frequency="f", expected_holding_period="p",
        predicted_performance="pp",
    )
    session.add(registry.StrategyBacktest(
        strategy_id=strategy_id,
        results={"gate": {"eligible_for_paper": True, "blocking_reasons": []}},
        monthly_returns=[],
    ))
    await session.flush()

    async with await client(session) as c:
        response = await c.post(f"/strategies/{strategy_id}/promote",
                                json={"stage": "paper", "note": "Approved after review."})
    assert response.status_code == 200
    fresh = await session.get(registry.Strategy, strategy_id)
    assert fresh.stage == "paper"
    assert fresh.status == "active"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_leaderboard_splits_by_horizon_and_carries_a_verdict(session):
    # The test database persists across tests by design, so these assert on
    # their own rows rather than on an empty board.
    fast = f"Fast {uuid.uuid4().hex[:6]}"
    slow = f"Slow {uuid.uuid4().hex[:6]}"
    for name, horizon, rules in ((fast, "short", variant()), (slow, "long", variant())):
        await registry.register(
            session, name=name, hypothesis="h", authority="a", rules=rules,
            horizon=horizon, expected_trade_frequency="f", expected_holding_period="p",
            predicted_performance="pp",
        )
    async with await client(session) as c:
        response = await c.get("/strategies")
    body = response.json()
    assert response.status_code == 200
    assert {"short", "medium", "long"} <= set(body["boards"])

    short_names = [r["name"] for r in body["boards"]["short"]]
    long_names = [r["name"] for r in body["boards"]["long"]]
    assert fast in short_names and fast not in long_names
    assert slow in long_names and slow not in short_names

    # Never ranked on recent performance, and it says so.
    assert "last thirty days" in body["ranked_on"]
    row = next(r for r in body["boards"]["short"] if r["name"] == fast)
    assert row["track_record_verdict"] == "No trades yet — nothing to judge."
    assert "McLean" in row["decay_note"]
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_detail_exposes_rules_in_both_forms(session):
    strategy_id = await registry.register(
        session, name="Detailed", hypothesis="because", authority="Someone 1999",
        rules=variant(), horizon="medium", expected_trade_frequency="f",
        expected_holding_period="p", predicted_performance="pp",
        encoding_deviations="Dropped one component.",
    )
    async with await client(session) as c:
        response = await c.get(f"/strategies/{strategy_id}")
    body = response.json()
    assert response.status_code == 200
    assert body["rules_json"]["sizing"]["max_positions"] == 5
    assert any("Buy when" in line for line in body["rules_plain"])
    assert body["encoding_deviations"] == "Dropped one component."
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trades_today_is_empty_not_broken_before_any_trading(session):
    async with await client(session) as c:
        response = await c.get("/strategies/trades-today")
    assert response.status_code == 200
    assert response.json()["trades"] == []
    app.dependency_overrides.clear()
