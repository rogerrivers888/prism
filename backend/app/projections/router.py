import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.projections import get_position, list_positions, rebuild

router = APIRouter(tags=["positions"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stream_id: uuid.UUID
    instrument_type: str
    ticker: str
    direction: str
    size: Decimal
    entry_price: Decimal
    current_stop: Decimal | None
    initial_risk: Decimal | None
    current_risk: Decimal | None
    currency: str
    opened_at: datetime
    closed_at: datetime | None
    status: str
    last_event_id: int


@router.get("/positions")
async def get_positions(
    session: SessionDep, status: Literal["open", "closed"] | None = None
) -> list[PositionOut]:
    positions = await list_positions(session, status=status)
    return [PositionOut.model_validate(p) for p in positions]


@router.get("/positions/{stream_id}")
async def get_one_position(stream_id: uuid.UUID, session: SessionDep) -> PositionOut:
    position = await get_position(session, stream_id)
    if position is None:
        raise HTTPException(status_code=404, detail="position not found")
    return PositionOut.model_validate(position)


# DEV-ONLY: remove once a real projection worker exists.
dev_router = APIRouter(prefix="/dev", tags=["dev (temporary)"])


@dev_router.post("/projections/rebuild")
async def rebuild_projections(session: SessionDep) -> dict[str, int]:
    applied = await rebuild(session)
    await session.commit()
    return {"applied": applied}
