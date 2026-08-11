import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text

from app.events import append
from app.projections import catch_up, get_position, rebuild

NOW = datetime(2026, 8, 11, 9, 0, 0, tzinfo=UTC)


async def _trade(session, stream_id, quantity, price, side="buy", stop=None, **kw):
    payload = {
        "instrument": "GOLD",
        "instrument_type": "spreadbet",
        "side": side,
        "quantity": quantity,
        "price": price,
    }
    if stop is not None:
        payload["stop"] = stop
    return await append(
        session,
        stream_id=stream_id,
        stream_type="position",
        event_type="TradeExecuted",
        payload=payload,
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


async def _void(session, stream_id, reason="test void"):
    return await append(
        session,
        stream_id=stream_id,
        stream_type="position",
        event_type="StreamVoided",
        payload={"reason": reason},
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
        "current_risk": position.current_risk,
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


async def test_initial_risk_set_once_at_entry_and_never_recalculated(session):
    stream_id = uuid.uuid4()
    # Opening trade carries the stop: R = |100 - 90| * 10 = 100.
    await _trade(session, stream_id, "10", "100", stop="90")
    await catch_up(session)
    await session.commit()

    position = await get_position(session, stream_id)
    assert position.current_stop == Decimal("90")
    assert position.initial_risk == Decimal("100")
    assert position.current_risk == Decimal("100")

    # Any later stop move updates current_stop and current_risk only —
    # R was defined at entry and must not drift.
    await _stop(session, stream_id, "95")
    await catch_up(session)
    await session.commit()
    session.expire_all()

    position = await get_position(session, stream_id)
    assert position.current_stop == Decimal("95")
    assert position.current_risk == Decimal("50")
    assert position.initial_risk == Decimal("100")


async def test_no_stop_at_entry_means_initial_risk_stays_null(session):
    stream_id = uuid.uuid4()
    await _trade(session, stream_id, "10", "100")  # no stop: R is unknowable
    await _stop(session, stream_id, "90")
    await catch_up(session)
    await session.commit()

    position = await get_position(session, stream_id)
    assert position.initial_risk is None  # never faked after the fact
    assert position.current_stop == Decimal("90")
    assert position.current_risk == Decimal("100")


async def test_catch_up_is_idempotent(session):
    stream_id = uuid.uuid4()
    await _trade(session, stream_id, "10", "100", stop="92")
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
    await _trade(session, stream_id, "10", "100", stop="92")
    await _stop(session, stream_id, "96")
    await _trade(session, stream_id, "5", "104")
    await catch_up(session)
    await session.commit()

    incremental = _snapshot(await get_position(session, stream_id))

    await rebuild(session)
    await session.commit()
    session.expire_all()

    assert _snapshot(await get_position(session, stream_id)) == incremental


async def test_voided_stream_produces_no_position(session):
    # Void after projection: the position row is removed.
    voided_late = uuid.uuid4()
    await _trade(session, voided_late, "10", "100")
    await catch_up(session)
    await session.commit()
    assert await get_position(session, voided_late) is not None

    await _void(session, voided_late)
    await catch_up(session)
    await session.commit()
    session.expire_all()
    assert await get_position(session, voided_late) is None

    # Void already in the log before catch-up: the position never appears,
    # and a rebuild agrees.
    voided_early = uuid.uuid4()
    await _trade(session, voided_early, "10", "100")
    await _void(session, voided_early)
    await catch_up(session)
    await session.commit()
    assert await get_position(session, voided_early) is None

    await rebuild(session)
    await session.commit()
    session.expire_all()
    assert await get_position(session, voided_late) is None
    assert await get_position(session, voided_early) is None


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
