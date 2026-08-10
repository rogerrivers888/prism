"""DEV-ONLY endpoints for poking the event store by hand.

These exist to exercise the append/read paths before real domain endpoints
land. Remove this module (and its include in main.py) once they do.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.events import ConcurrencyError, append, read_stream

router = APIRouter(prefix="/dev", tags=["dev (temporary)"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class AppendEventRequest(BaseModel):
    stream_id: uuid.UUID
    stream_type: Literal["position", "thesis", "rule", "research"]
    event_type: str
    payload: dict
    # Must be timezone-aware: "when it happened in the world".
    occurred_at: AwareDatetime
    actor: Literal["roger", "ig-api", "rules-engine"]
    expected_seq: int | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stream_id: uuid.UUID
    stream_type: str
    seq: int
    event_type: str
    payload: dict
    occurred_at: AwareDatetime
    recorded_at: AwareDatetime
    actor: str


@router.post("/events", status_code=201)
async def append_event(body: AppendEventRequest, session: SessionDep) -> EventOut:
    try:
        event = await append(
            session,
            stream_id=body.stream_id,
            stream_type=body.stream_type,
            event_type=body.event_type,
            payload=body.payload,
            occurred_at=body.occurred_at,
            actor=body.actor,
            expected_seq=body.expected_seq,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False))
    except ConcurrencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await session.commit()
    return EventOut.model_validate(event)


@router.get("/streams/{stream_id}")
async def get_stream(stream_id: uuid.UUID, session: SessionDep) -> list[EventOut]:
    events = await read_stream(session, stream_id)
    return [EventOut.model_validate(e) for e in events]
