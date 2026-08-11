"""Positions projection.

events is the source of truth; positions is a disposable read model derived
entirely from it. Nothing writes to positions except this projector, and
``rebuild`` can always TRUNCATE it and replay exactly from event 1.
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import BigInteger, DateTime, Numeric, Text, func, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.events import Event, read_all
from app.events.payloads import StopMoved, TradeExecuted, payload_adapter

logger = logging.getLogger(__name__)

PROJECTION_NAME = "positions"
_BATCH = 1000


class Position(Base):
    __tablename__ = "positions"

    stream_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    instrument_type: Mapped[str] = mapped_column(Text, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    current_stop: Mapped[Decimal | None] = mapped_column(Numeric)
    # R, fixed at entry. See _apply_trade for why this is never recalculated.
    initial_risk: Mapped[Decimal | None] = mapped_column(Numeric)
    # Live heat: abs(entry_price - current_stop) * size, tracks stop and size.
    current_risk: Mapped[Decimal | None] = mapped_column(Numeric)
    currency: Mapped[str] = mapped_column(
        Text, nullable=False, default="GBP", server_default="GBP"
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    last_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ProjectionState(Base):
    __tablename__ = "projection_state"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    last_event_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


async def apply(session: AsyncSession, event: Event) -> None:
    """Apply one event to the positions read model."""
    if event.event_type == "StreamVoided":
        await _apply_void(session, event)
    elif event.event_type in ("TradeExecuted", "StopMoved"):
        # A voided stream produces no position at all — checked against the
        # whole stream, not just events replayed so far, so an incremental
        # catch-up and a full rebuild always land on the same table.
        if await _is_voided(session, event.stream_id):
            return
        if event.event_type == "TradeExecuted":
            await _apply_trade(session, event)
        else:
            await _apply_stop(session, event)
    # Unknown event types are skipped, not errors: future event types will
    # appear in the log before this projector knows about them.


async def _is_voided(session: AsyncSession, stream_id: uuid.UUID) -> bool:
    return bool(
        (
            await session.execute(
                select(Event.id)
                .where(
                    Event.stream_id == stream_id,
                    Event.event_type == "StreamVoided",
                )
                .limit(1)
            )
        ).scalar()
    )


async def _apply_void(session: AsyncSession, event: Event) -> None:
    position = await session.get(Position, event.stream_id)
    if position is not None:
        await session.delete(position)
    logger.info("stream %s voided by event id=%s", event.stream_id, event.id)


def _validate(event: Event) -> TradeExecuted | StopMoved | None:
    try:
        return payload_adapter.validate_python(event.payload)
    except ValidationError:
        # Events written before a payload schema gained a field (e.g. early
        # dev events predating TradeExecuted.instrument_type) can't be
        # projected honestly — inferring the missing data would be guesswork.
        # Skip them loudly in the log rather than crash every replay forever.
        logger.warning(
            "skipping unprojectable %s event id=%s: payload failed validation",
            event.event_type,
            event.id,
        )
        return None


async def _apply_trade(session: AsyncSession, event: Event) -> None:
    payload = _validate(event)
    if payload is None:
        return

    position = await session.get(Position, event.stream_id)
    trade_direction = "long" if payload.side == "buy" else "short"

    if position is None or position.status == "closed":
        # First trade on the stream opens the position. (A trade on an
        # already-closed stream re-opens it as a fresh position.)
        #
        # initial_risk is set here, exactly once, and never recalculated by
        # any subsequent event. R is the risk accepted at entry — that is
        # the whole point of the unit, and it must not drift. NULL when the
        # opening trade carried no stop; never faked. Live heat lives in
        # current_risk instead, which does track the stop.
        initial_risk = (
            abs(payload.price - payload.stop) * payload.quantity
            if payload.stop is not None
            else None
        )
        session.add(
            Position(
                stream_id=event.stream_id,
                instrument_type=payload.instrument_type,
                ticker=payload.instrument,
                direction=trade_direction,
                size=payload.quantity,
                entry_price=payload.price,
                current_stop=payload.stop,
                initial_risk=initial_risk,
                current_risk=initial_risk,
                currency=payload.currency,
                opened_at=event.occurred_at,
                status="open",
                last_event_id=event.id,
            )
        )
        return

    if trade_direction == position.direction:
        # Adding to the position: entry_price becomes the weighted average.
        total = position.size + payload.quantity
        position.entry_price = (
            position.entry_price * position.size + payload.price * payload.quantity
        ) / total
        position.size = total
        if payload.stop is not None:
            position.current_stop = payload.stop
    else:
        # Opposite side reduces the position; at (or past) zero it closes.
        position.size = position.size - payload.quantity
        if position.size <= 0:
            position.size = Decimal(0)
            position.status = "closed"
            position.closed_at = event.occurred_at
    _refresh_current_risk(position)
    position.last_event_id = event.id


def _refresh_current_risk(position: Position) -> None:
    """Maintain current_risk = abs(entry_price - current_stop) * size.

    NULL when there is no stop or the position is closed. initial_risk is
    deliberately not touched anywhere near here.
    """
    if position.status == "closed" or position.current_stop is None:
        position.current_risk = None
    else:
        position.current_risk = (
            abs(position.entry_price - position.current_stop) * position.size
        )


async def _apply_stop(session: AsyncSession, event: Event) -> None:
    payload = _validate(event)
    if payload is None:
        return

    position = await session.get(Position, event.stream_id)
    if position is None:
        logger.warning(
            "skipping StopMoved event id=%s: no position for stream %s",
            event.id,
            event.stream_id,
        )
        return

    # Only current_stop and current_risk move. initial_risk was fixed by the
    # opening trade and no later event recalculates it.
    position.current_stop = payload.new_stop
    _refresh_current_risk(position)
    position.last_event_id = event.id


async def _get_state(session: AsyncSession) -> ProjectionState:
    state = await session.get(ProjectionState, PROJECTION_NAME)
    if state is None:
        state = ProjectionState(name=PROJECTION_NAME, last_event_id=0)
        session.add(state)
        await session.flush()
    return state


async def catch_up(session: AsyncSession) -> int:
    """Apply all events past the checkpoint, in id order. Idempotent.

    Returns the number of events processed (including deliberately skipped
    ones — the checkpoint advances past them either way).
    """
    state = await _get_state(session)
    processed = 0
    while True:
        batch = await read_all(session, after_id=state.last_event_id, limit=_BATCH)
        for event in batch:
            await apply(session, event)
            state.last_event_id = event.id
            processed += 1
        if len(batch) < _BATCH:
            break
    if processed:
        state.updated_at = func.now()
    await session.flush()
    return processed


async def rebuild(session: AsyncSession) -> int:
    """Throw the read model away and replay everything from event 1."""
    await session.execute(text("TRUNCATE positions"))
    state = await _get_state(session)
    state.last_event_id = 0
    await session.flush()
    session.expire_all()
    return await catch_up(session)


async def list_positions(
    session: AsyncSession, status: str | None = None
) -> list[Position]:
    query = select(Position).order_by(Position.opened_at)
    if status is not None:
        query = query.where(Position.status == status)
    return list((await session.execute(query)).scalars())


async def get_position(
    session: AsyncSession, stream_id: uuid.UUID
) -> Position | None:
    return await session.get(Position, stream_id)
