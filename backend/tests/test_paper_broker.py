"""Paper broker invariants: next-day fills, event-sourced trades, honest cash."""

import datetime
import uuid
from datetime import date

import pytest

from app.fundamentals import Security
from app.strategies import registry
from app.strategies.features import Bar, FeatureService
from app.strategies.paper import (
    PaperEquityDaily,
    PaperPosition,
    PaperTrade,
    PendingPaperOrder,
    cash_balance,
    run_paper_day,
)
from app.strategies.simulator import STARTING_CAPITAL, CostModel

RULES = {
    "universe": {},
    "entry": {"kind": "compare", "id": "always", "feature": "price:return_1m",
              "op": "gt", "value": -1000},
    "rank": {"components": [{"feature": "price:return_1m", "direction": "desc"}],
             "top_n": 1},
    "rebalance": {"frequency": "weekly", "mode": "reconstitute"},
    "sizing": {"max_positions": 1},
}


def make_service(session_securities=None, days=80):
    bars = {}
    start = date(2026, 1, 5)
    path = [100 * (1.005 ** i) for i in range(days)]
    series = []
    day = start
    for price in path:
        while day.weekday() >= 5:
            day += datetime.timedelta(days=1)
        series.append(Bar(day, price, price, price))
        day += datetime.timedelta(days=1)
    bars["AAA"] = series
    securities = {"AAA": Security(ticker="AAA", name="AAA", sector="hardware",
                                  quote_currency="USD", currency="USD", is_active=True)}
    calendar = [b.date for b in series]
    return FeatureService(start=calendar[0], end=calendar[-1], securities=securities,
                          bars=bars, fundamentals={}, lens_scores={}, lens_scores_abs={},
                          dispersion={}, sector_cycle={}, calendar=calendar)


async def make_active_strategy(session) -> uuid.UUID:
    strategy_id = await registry.register(
        session,
        name=f"Paper test {uuid.uuid4().hex[:6]}",
        hypothesis="test", authority="test", rules=RULES, horizon="short",
        expected_trade_frequency="weekly", expected_holding_period="days",
        predicted_performance="n/a",
    )
    await registry.activate(session, strategy_id)
    return strategy_id


@pytest.mark.asyncio
async def test_signal_today_fill_next_session(session):
    service = make_service()
    strategy_id = await make_active_strategy(session)

    # Day 1 is a rebalance day (first trading day of the ISO week after
    # enough history): pick a Monday late in the series.
    mondays = [d for d in service.calendar if d.weekday() == 0 and
               service.calendar.index(d) > 30]
    signal_day = mondays[0]
    report = await run_paper_day(session, service, signal_day)
    assert report.orders_signalled == 1
    assert report.orders_filled == 0  # nothing to fill yet

    pending = list((await session.execute(
        __import__("sqlalchemy").select(PendingPaperOrder)
    )).scalars())
    assert len(pending) == 1

    next_day = service.next_trading_day(signal_day)
    report2 = await run_paper_day(session, service, next_day)
    assert report2.orders_filled == 1

    trades = list((await session.execute(
        __import__("sqlalchemy").select(PaperTrade).where(PaperTrade.strategy_id == strategy_id)
    )).scalars())
    assert len(trades) == 1
    assert trades[0].fill_date == next_day
    assert trades[0].signal_date == signal_day
    assert trades[0].fill_date > trades[0].signal_date


@pytest.mark.asyncio
async def test_fill_creates_position_and_reduces_cash(session):
    service = make_service()
    strategy_id = await make_active_strategy(session)
    mondays = [d for d in service.calendar if d.weekday() == 0 and
               service.calendar.index(d) > 30]
    await run_paper_day(session, service, mondays[0])
    await run_paper_day(session, service, service.next_trading_day(mondays[0]))

    position = await session.get(PaperPosition, (strategy_id, "AAA"))
    assert position is not None
    assert float(position.quantity) > 0
    assert position.rule_fired.startswith("rank_1_of_1")
    assert "price:return_1m" in position.metric_values

    cash = await cash_balance(session, strategy_id)
    assert cash < STARTING_CAPITAL
    # Equity row was written and is near starting capital (costs only).
    equity = await session.get(PaperEquityDaily,
                               (strategy_id, service.next_trading_day(mondays[0])))
    assert equity is not None
    assert float(equity.equity) == pytest.approx(STARTING_CAPITAL, rel=0.01)


@pytest.mark.asyncio
async def test_unfillable_order_is_dropped_after_max_attempts(session):
    service = make_service()
    strategy_id = await make_active_strategy(session)
    session.add(PendingPaperOrder(
        strategy_id=strategy_id, ticker="GONE", side="buy",
        signal_date=service.calendar[10], rule_fired="test", metric_values={},
        attempts=0,
    ))
    await session.flush()
    dropped = 0
    for day in service.calendar[11:18]:
        report = await run_paper_day(session, service, day)
        dropped += report.orders_dropped
    assert dropped == 1
    remaining = list((await session.execute(
        __import__("sqlalchemy").select(PendingPaperOrder)
        .where(PendingPaperOrder.ticker == "GONE")
    )).scalars())
    assert remaining == []


@pytest.mark.asyncio
async def test_paper_trades_are_events_first(session):
    """The projection can be wiped and rebuilt from the stream."""
    from sqlalchemy import select, text

    from app.events.store import read_stream
    from app.strategies.paper import apply_paper_event

    service = make_service()
    strategy_id = await make_active_strategy(session)
    mondays = [d for d in service.calendar if d.weekday() == 0 and
               service.calendar.index(d) > 30]
    await run_paper_day(session, service, mondays[0])
    await run_paper_day(session, service, service.next_trading_day(mondays[0]))

    before = list((await session.execute(
        select(PaperTrade).where(PaperTrade.strategy_id == strategy_id)
    )).scalars())
    assert before

    await session.execute(text("DELETE FROM paper_trades"))
    await session.execute(text("DELETE FROM paper_positions"))
    for event in await read_stream(session, strategy_id):
        await apply_paper_event(session, event)

    after = list((await session.execute(
        select(PaperTrade).where(PaperTrade.strategy_id == strategy_id)
    )).scalars())
    assert len(after) == len(before)
    position = await session.get(PaperPosition, (strategy_id, "AAA"))
    assert position is not None
