import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text

from app.events import append
from app.projections import catch_up, get_position, rebuild

NOW = datetime(2026, 8, 11, 9, 0, 0, tzinfo=UTC)


async def _trade(session, stream_id, quantity, price, side="buy", **kw):
    return await append(
        session,
        stream_id=stream_id,
        stream_type="position",
        event_type="TradeExecuted",
        payload={
            "instrument": "GOLD",
            "instrument_type": "spreadbet",
            "side": side,
            "quantity": quantity,
            "price": price,
        },
        occurred_at=NOW,
        actor="roger",
        **kw,
    )


async def _stop(session, stream_id, new_stop):
    return await append(
        session,
        stream_id=stream_id,
        stream_type="position",
        event_type="StopMoved",
        payload={"instrument": "GOLD", "new_stop": new_stop},
        occurred_at=NOW,
        actor="roger",
    )


def _snapshot(position) -> dict:
    return {
        "stream_id": position.stream_id,
        "instrument_type": position.instrument_type,
        "ticker": position.ticker,
        "direction": position.direction,
        "size": position.size,
        "entry_price": position.entry_price,
        "current_stop": position.current_stop,
        "initial_risk": position.initial_risk,
        "currency": position.currency,
        "opened_at": position.opened_at,
        "closed_at": position.closed_at,
        "status": position.status,
        "last_event_id": position.last_event_id,
    }


async def test_two_trades_on_one_stream_aggregate(session):
    stream_id = uuid.uuid4()
    await _trade(session, stream_id, "10", "100")
    await _trade(session, stream_id, "10", "110")
    await catch_up(session)
    await session.commit()

    position = await get_position(session, stream_id)
    assert position is not None
    assert position.status == "open"
    assert position.direction == "long"
    assert position.instrument_type == "spreadbet"
    assert position.size == Decimal("20")
    assert position.entry_price == Decimal("105")  # weighted average


async def test_stop_moved_updates_stop_but_initial_risk_is_frozen(session):
    stream_id = uuid.uuid4()
    await _trade(session, stream_id, "10", "100")
    await _stop(session, stream_id, "90")  # sets R: |100-90| * 10 = 100
    await catch_up(session)
    await session.commit()

    position = await get_position(session, stream_id)
    assert position.current_stop == Decimal("90")
    assert position.initial_risk == Decimal("100")

    # Trailing the stop into profit updates current_stop only; R was
    # defined at entry and must not change.
    await _stop(session, stream_id, "105")
    await catch_up(session)
    await session.commit()
    session.expire_all()

    position = await get_position(session, stream_id)
    assert position.current_stop == Decimal("105")
    assert position.initial_risk == Decimal("100")


async def test_catch_up_is_idempotent(session):
    stream_id = uuid.uuid4()
    await _trade(session, stream_id, "10", "100")
    await _stop(session, stream_id, "95")
    first = await catch_up(session)
    await session.commit()
    assert first >= 2

    before = _snapshot(await get_position(session, stream_id))
    second = await catch_up(session)
    await session.commit()
    session.expire_all()

    assert second == 0
    assert _snapshot(await get_position(session, stream_id)) == before


async def test_rebuild_matches_incremental(session):
    stream_id = uuid.uuid4()
    await _trade(session, stream_id, "10", "100")
    await _stop(session, stream_id, "92")
    await _trade(session, stream_id, "5", "104")
    await catch_up(session)
    await session.commit()

    incremental = _snapshot(await get_position(session, stream_id))

    await rebuild(session)
    await session.commit()
    session.expire_all()

    assert _snapshot(await get_position(session, stream_id)) == incremental


async def test_unknown_event_type_is_skipped_without_error(session):
    stream_id = uuid.uuid4()
    # append() would reject an unknown type, so smuggle one in directly —
    # exactly what a newer writer will do before this projector is updated.
    await session.execute(
        text(
            """
            INSERT INTO events
              (stream_id, stream_type, seq, event_type, payload,
               occurred_at, actor)
            VALUES
              (:stream_id, 'position', 1, 'PositionReviewed', '{}'::jsonb,
               now(), 'roger')
            """
        ),
        {"stream_id": str(stream_id)},
    )
    processed = await catch_up(session)
    await session.commit()

    assert processed >= 1
    assert await get_position(session, stream_id) is None
