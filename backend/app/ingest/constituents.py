"""Index membership history: the survivorship repair.

The marketplace payload's HistoricalTickerComponents block carries one record
per membership spell — ticker, join date, leave date (null while current),
and whether the company is delisted outright. Stored point-in-time so a
backtest at date D can ask "who was in the index on D" and get the honest
answer, including the companies that later died.

Codes for recycled symbols arrive with an _old suffix (NYX_old is the departed
NYSE Euronext, not whatever trades as NYX today). Kept verbatim: the suffix is
what makes the dead company distinguishable from the ticker's next tenant.
"""

import logging
from datetime import date

from sqlalchemy import Boolean, Date, DateTime, Text, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.ingest import archive as archive_module

logger = logging.getLogger(__name__)


class IndexMembership(Base):
    __tablename__ = "index_membership"

    index: Mapped[str] = mapped_column(Text, primary_key=True)
    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    joined_on: Mapped[date] = mapped_column(Date, primary_key=True)
    left_on: Mapped[date | None] = mapped_column(Date)
    name: Mapped[str | None]
    joined_estimated: Mapped[bool] = mapped_column(Boolean)
    is_delisted: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str]


# Assumed join for records the source gives no StartDate. These are almost all
# long-tenured members whose DEPARTURE is recorded — Aetna, Altera, and the
# rest of exactly the survivorship problem. Treating them as members from
# index inception is accurate for any backtest window that starts later, and
# the flag preserves the fact that it is an assumption.
INCEPTION = date(1957, 3, 4)


def parse_membership(index: str, payload: dict, source: str) -> list[dict]:
    """HistoricalTickerComponents -> membership rows."""
    out = []
    assumed = 0
    for record in (payload.get("HistoricalTickerComponents") or {}).values():
        started = record.get("StartDate")
        ended = record.get("EndDate")
        estimated = False
        if not started:
            if not ended and not record.get("IsActiveNow"):
                # No dates at all and not current: nothing usable.
                continue
            started = INCEPTION.isoformat()
            estimated = True
            assumed += 1
        out.append({
            "index": index,
            "ticker": record["Code"],
            "joined_on": date.fromisoformat(started),
            "left_on": date.fromisoformat(ended) if ended else None,
            "name": record.get("Name"),
            "joined_estimated": estimated,
            "is_delisted": bool(record.get("IsDelisted")),
            "source": source,
        })
    if assumed:
        logger.info("%s: %d membership records had no join date; inception assumed",
                    index, assumed)
    return out


async def store(session: AsyncSession, rows: list[dict]) -> int:
    for row in rows:
        await session.execute(
            pg_insert(IndexMembership)
            .values(**row)
            .on_conflict_do_update(
                constraint="pk_index_membership",
                # A spell's end date becomes known later; the join date is the
                # identity and never changes.
                set_={"left_on": row["left_on"], "name": row["name"],
                      "joined_estimated": row["joined_estimated"],
                      "is_delisted": row["is_delisted"], "source": row["source"]},
            )
        )
    await session.flush()
    return len(rows)


async def sync_index(session: AsyncSession, provider, index: str = "GSPC.INDX") -> dict:
    """Fetch, archive verbatim, parse, upsert. The usual shape."""
    fetched = await provider.fetch_index_constituents(index)
    await archive_module.archive(
        session, provider.name, fetched.endpoint, index, fetched.payload
    )
    rows = parse_membership(index, fetched.payload, f"{provider.name}/unicornbay")
    written = await store(session, rows)
    spells_open = sum(1 for r in rows if r["left_on"] is None)
    return {"index": index, "rows": written, "current_members": spells_open}


async def members_as_of(
    session: AsyncSession, index: str, as_of: date
) -> set[str]:
    rows = (
        await session.execute(
            select(IndexMembership.ticker).where(
                IndexMembership.index == index,
                IndexMembership.joined_on <= as_of,
                (IndexMembership.left_on.is_(None)) | (IndexMembership.left_on > as_of),
            )
        )
    ).scalars()
    return set(rows)


async def membership_spells(
    session: AsyncSession, index: str
) -> dict[str, list[tuple[date, date | None]]]:
    """Every ticker's membership windows, for in-memory as-of checks."""
    out: dict[str, list[tuple[date, date | None]]] = {}
    for row in (
        await session.execute(
            select(IndexMembership).where(IndexMembership.index == index)
        )
    ).scalars():
        out.setdefault(row.ticker, []).append((row.joined_on, row.left_on))
    return out
