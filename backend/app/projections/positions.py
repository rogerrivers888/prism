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
    initial_risk: Mapped[Decimal | None] = mapped_column(Numeric)
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
    if event.event_type == "TradeExecuted":
        await _apply_trade(session, event)
    elif event.event_type == "StopMoved":
        await _apply_stop(session, event)
    # Unknown event types are skipped, not errors: future event types will
    # appear in the log before this projector knows about them.


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
        session.add(
            Position(
                stream_id=event.stream_id,
                instrument_type=payload.instrument_type,
                ticker=payload.instrument,
                direction=trade_direction,
                size=payload.quantity,
                entry_price=payload.price,
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
    else:
        # Opposite side reduces the position; at (or past) zero it closes.
        position.size = position.size - payload.quantity
        if position.size <= 0:
            position.size = Decimal(0)
            position.status = "closed"
            position.closed_at = event.occurred_at
    position.last_event_id = event.id


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

    new_stop = payload.new_stop
    position.current_stop = new_stop

    # initial_risk looks buggy at first sight; it isn't. R is defined at
    # entry: abs(entry_price - stop) * size, NULL while there is no stop.
    # While the stop still sits on the LOSING side of entry the trade hasn't
    # moved in our favour, so a stop change is a correction of what was at
    # risk from the start — recompute. Once the stop reaches breakeven or
    # better the trade has moved our way and the stop is trailing profit;
    # what was originally risked no longer changes, so initial_risk freezes
    # at its last computed value. (We don't store market prices, so "moved in
    # our favour" is observed through which side of entry the stop is on.)
    stop_on_losing_side = (
        new_stop < position.entry_price
        if position.direction == "long"
        else new_stop > position.entry_price
    )
    if stop_on_losing_side:
        position.initial_risk = abs(position.entry_price - new_stop) * position.size

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
