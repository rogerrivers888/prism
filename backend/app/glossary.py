"""The glossary: one place that explains every term the app uses.

Seed content lives in content/glossary_seed.json and is the single source of
truth — the 32 metric explainers that used to live in the frontend were moved
here rather than copied, so there is no second version to drift.

Notes Roger writes are kept in a separate table. Re-seeding must be safe to run
at any time, and it would not be if his words shared a row with the seed.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, Text, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

logger = logging.getLogger(__name__)

SEED_PATH = Path(__file__).parent / "content" / "glossary_seed.json"


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    slug: Mapped[str] = mapped_column(primary_key=True)
    term: Mapped[str]
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text))
    short_definition: Mapped[str]
    full_explanation: Mapped[str]
    worked_example: Mapped[str | None]
    how_to_read_it: Mapped[str | None]
    common_mistakes: Mapped[str | None]
    related_slugs: Mapped[list[str]] = mapped_column(ARRAY(Text))
    external_links: Mapped[list] = mapped_column(JSONB)
    category: Mapped[str]


class GlossaryNote(Base):
    __tablename__ = "glossary_notes"

    slug: Mapped[str] = mapped_column(primary_key=True)
    note: Mapped[str]
    # Explicitly tz-aware: the default mapping for datetime is TIMESTAMP
    # WITHOUT TIME ZONE, which disagrees with the migration and fails on write.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def seed_rows() -> list[dict]:
    return json.loads(SEED_PATH.read_text())


async def seed(session: AsyncSession) -> int:
    """Upsert every seeded term. Idempotent, and safe to re-run on deploy.

    Notes are untouched because they live in their own table.
    """
    rows = seed_rows()
    for row in rows:
        columns = {k: v for k, v in row.items() if k != "slug"}
        await session.execute(
            insert(GlossaryTerm)
            .values(slug=row["slug"], **columns)
            .on_conflict_do_update(index_elements=["slug"], set_=columns)
        )
    await session.flush()
    return len(rows)


async def all_terms(session: AsyncSession) -> list[GlossaryTerm]:
    return list(
        (
            await session.execute(select(GlossaryTerm).order_by(GlossaryTerm.term))
        ).scalars()
    )


async def notes_by_slug(session: AsyncSession) -> dict[str, GlossaryNote]:
    rows = (await session.execute(select(GlossaryNote))).scalars()
    return {row.slug: row for row in rows}
