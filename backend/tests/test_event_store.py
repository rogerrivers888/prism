import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.events import ConcurrencyError, append, read_stream

NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)

TRADE = {
    "instrument": "VUSA",
    "instrument_type": "share",
    "side": "buy",
    "quantity": "10",
    "price": "71.42",
}
STOP = {"instrument": "VUSA", "previous_stop": "65.00", "new_stop": "68.50"}


async def _append(session, stream_id, event_type="TradeExecuted", payload=TRADE, **kw):
    return await append(
        session,
        stream_id=stream_id,
        stream_type="position",
        event_type=event_type,
        payload=payload,
        occurred_at=NOW,
        actor="roger",
        **kw,
    )


async def test_append_then_read_returns_events_in_seq_order(session):
    stream_id = uuid.uuid4()
    await _append(session, stream_id)
    await _append(session, stream_id, event_type="StopMoved", payload=STOP)
    await _append(session, stream_id)
    await session.commit()

    events = await read_stream(session, stream_id)

    assert [e.seq for e in events] == [1, 2, 3]
    assert [e.event_type for e in events] == ["TradeExecuted", "StopMoved", "TradeExecuted"]
    assert events[0].payload["instrument"] == "VUSA"
    assert all(e.stream_id == stream_id for e in events)


async def test_update_on_events_raises(session):
    stream_id = uuid.uuid4()
    event = await _append(session, stream_id)
    await session.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(
            text("UPDATE events SET actor = 'mallory' WHERE id = :id"),
            {"id": event.id},
        )
    await session.rollback()


async def test_delete_on_events_raises(session):
    stream_id = uuid.uuid4()
    event = await _append(session, stream_id)
    await session.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(
            text("DELETE FROM events WHERE id = :id"), {"id": event.id}
        )
    await session.rollback()


async def test_stale_expected_seq_raises_concurrency_error(session):
    stream_id = uuid.uuid4()
    await _append(session, stream_id)
    await _append(session, stream_id, expected_seq=1)  # correct head: fine
    await session.commit()

    with pytest.raises(ConcurrencyError):
        await _append(session, stream_id, expected_seq=1)  # head is now 2
    await session.rollback()


async def test_duplicate_stream_id_seq_rejected(session):
    stream_id = uuid.uuid4()
    await _append(session, stream_id)
    await session.commit()

    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                """
                INSERT INTO events
                  (stream_id, stream_type, seq, event_type, payload,
                   occurred_at, actor)
                VALUES
                  (:stream_id, 'position', 1, 'TradeExecuted', '{}'::jsonb,
                   now(), 'roger')
                """
            ),
            {"stream_id": str(stream_id)},
        )
    await session.rollback()


async def test_unknown_event_type_rejected(session):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await _append(session, uuid.uuid4(), event_type="TimeTravelled")
    await session.rollback()
