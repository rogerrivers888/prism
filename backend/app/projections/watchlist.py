"""Watchlist projection.

Curation lives here, not in the universe. The universe should stay large —
peer percentiles need eight members in a sector before they beat absolute
bands — so narrowing attention is a separate concern with its own list.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.events import Event

# One stream for the whole watchlist: the order of adds and removals is the
# thing worth preserving, and a single user cannot contend with themselves.
WATCHLIST_STREAM = uuid.UUID("00000000-0000-5000-a000-000000000001")


class WatchlistEntry(Base):
    __tablename__ = "watchlist"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    last_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


async def apply(session: AsyncSession, event: Event) -> None:
    if event.event_type == "WatchlistAdded":
        ticker = event.payload["ticker"]
        statement = insert(WatchlistEntry).values(
            ticker=ticker,
            added_at=event.occurred_at,
            note=event.payload.get("note"),
            last_event_id=event.id,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["ticker"],
                set_={
                    "note": statement.excluded.note,
                    "last_event_id": statement.excluded.last_event_id,
                },
            )
        )
    elif event.event_type == "WatchlistRemoved":
        entry = await session.get(WatchlistEntry, event.payload["ticker"])
        if entry is not None:
            await session.delete(entry)


async def entries(session: AsyncSession) -> list[WatchlistEntry]:
    return list(
        (
            await session.execute(
                select(WatchlistEntry).order_by(WatchlistEntry.added_at.desc())
            )
        ).scalars()
    )
