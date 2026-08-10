"""Append-only event store.

``append`` is the only write path. The database enforces immutability with a
trigger (see the "create events table" migration), so even a bug here cannot
rewrite history.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Integer, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import UniqueConstraint

from app.db import Base
from app.events.payloads import payload_adapter


class ConcurrencyError(Exception):
    """Another writer advanced the stream past the sequence we expected."""


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("stream_id", "seq", name="uq_events_stream_id_seq"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    stream_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    stream_type: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # When it happened in the world vs. when we were told — never collapse.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)


async def append(
    session: AsyncSession,
    *,
    stream_id: uuid.UUID,
    stream_type: str,
    event_type: str,
    payload: dict,
    occurred_at: datetime,
    actor: str,
    expected_seq: int | None = None,
) -> Event:
    """Append one event to a stream and return it (flushed, not committed).

    Raises pydantic.ValidationError for an unknown event_type or malformed
    payload, and ConcurrencyError when ``expected_seq`` doesn't match the
    stream head (optimistic locking) or a concurrent writer claims the same
    sequence first.
    """
    validated = payload_adapter.validate_python({**payload, "event_type": event_type})

    head = (
        await session.execute(
            select(func.max(Event.seq)).where(Event.stream_id == stream_id)
        )
    ).scalar() or 0

    if expected_seq is not None and expected_seq != head:
        raise ConcurrencyError(
            f"stream {stream_id} is at seq {head}, expected {expected_seq}"
        )

    event = Event(
        stream_id=stream_id,
        stream_type=stream_type,
        seq=head + 1,
        event_type=event_type,
        payload=validated.model_dump(mode="json"),
        occurred_at=occurred_at,
        actor=actor,
    )
    session.add(event)
    try:
        await session.flush()
    except IntegrityError as exc:
        # The (stream_id, seq) unique constraint fired: a concurrent writer
        # appended between our head read and our insert.
        raise ConcurrencyError(
            f"concurrent append to stream {stream_id} at seq {head + 1}"
        ) from exc
    return event


async def read_stream(session: AsyncSession, stream_id: uuid.UUID) -> list[Event]:
    """All events in one stream, ordered by seq."""
    result = await session.execute(
        select(Event).where(Event.stream_id == stream_id).order_by(Event.seq)
    )
    return list(result.scalars())


async def read_all(
    session: AsyncSession, after_id: int = 0, limit: int = 1000
) -> list[Event]:
    """Global feed ordered by id, for projection catch-up."""
    result = await session.execute(
        select(Event).where(Event.id > after_id).order_by(Event.id).limit(limit)
    )
    return list(result.scalars())
