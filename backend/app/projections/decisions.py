"""Decisions projection.

The record is the point. A decision is entered before the outcome is known,
with a stated failure mode and a falsifier, and closed with both a decision
quality and an outcome quality — judged separately, because a good decision
can have a bad outcome and conflating them lets luck rewrite the process.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.events import Event


class Decision(Base):
    __tablename__ = "decisions"

    stream_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ticker: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    premortem: Mapped[str] = mapped_column(Text, nullable=False)
    falsifier: Mapped[str] = mapped_column(Text, nullable=False)
    sizing_note: Mapped[str | None] = mapped_column(Text)
    declined_reason: Mapped[str | None] = mapped_column(Text)
    decision_quality: Mapped[str | None] = mapped_column(Text)
    outcome_quality: Mapped[str | None] = mapped_column(Text)
    error_tag: Mapped[str | None] = mapped_column(Text)
    close_note: Mapped[str | None] = mapped_column(Text)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


async def apply(session: AsyncSession, event: Event) -> None:
    payload = event.payload

    if event.event_type == "DecisionRaised":
        session.add(
            Decision(
                stream_id=event.stream_id,
                ticker=payload.get("ticker"),
                kind=payload["kind"],
                status="raised",
                thesis=payload["thesis"],
                premortem=payload["premortem"],
                falsifier=payload["falsifier"],
                sizing_note=payload.get("sizing_note"),
                raised_at=event.occurred_at,
                last_event_id=event.id,
            )
        )
        return

    decision = await session.get(Decision, event.stream_id)
    if decision is None:
        return

    if event.event_type == "DecisionTaken":
        decision.status = "taken"
        decision.resolved_at = event.occurred_at
    elif event.event_type == "DecisionDeclined":
        decision.status = "declined"
        decision.declined_reason = payload.get("reason")
        decision.resolved_at = event.occurred_at
    elif event.event_type == "DecisionClosed":
        decision.status = "closed"
        decision.decision_quality = payload["decision_quality"]
        decision.outcome_quality = payload["outcome_quality"]
        decision.error_tag = payload.get("error_tag")
        decision.close_note = payload.get("note")
        decision.closed_at = event.occurred_at
    decision.last_event_id = event.id


async def all_decisions(session: AsyncSession) -> list[Decision]:
    return list(
        (await session.execute(select(Decision).order_by(Decision.raised_at.desc()))).scalars()
    )
