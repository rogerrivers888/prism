"""Glossary endpoints.

The whole glossary is served in one response. It is 64 terms and a few
kilobytes, the client needs all of it anyway to auto-link prose, and paginating
it would mean the linker could only recognise the terms it happened to have
fetched.
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import glossary as glossary_module
from app.db import get_session

router = APIRouter(prefix="/glossary", tags=["glossary"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class ExternalLink(BaseModel):
    label: str
    url: str
    source_type: str


class TermOut(BaseModel):
    slug: str
    term: str
    aliases: list[str]
    short_definition: str
    full_explanation: str
    worked_example: str | None
    how_to_read_it: str | None
    common_mistakes: str | None
    related_slugs: list[str]
    external_links: list[ExternalLink]
    category: str
    # Roger's own words, shown beside the seeded explanation rather than
    # replacing it.
    user_note: str | None = None
    user_note_updated_at: datetime | None = None


@router.get("")
async def list_terms(session: SessionDep) -> list[TermOut]:
    notes = await glossary_module.notes_by_slug(session)
    out = []
    for row in await glossary_module.all_terms(session):
        note = notes.get(row.slug)
        out.append(
            TermOut(
                slug=row.slug,
                term=row.term,
                aliases=row.aliases,
                short_definition=row.short_definition,
                full_explanation=row.full_explanation,
                worked_example=row.worked_example,
                how_to_read_it=row.how_to_read_it,
                common_mistakes=row.common_mistakes,
                related_slugs=row.related_slugs,
                external_links=[ExternalLink(**link) for link in row.external_links],
                category=row.category,
                user_note=note.note if note else None,
                user_note_updated_at=note.updated_at if note else None,
            )
        )
    return out


class NoteIn(BaseModel):
    note: str = Field(max_length=8000)


@router.put("/{slug}/note")
async def put_note(slug: str, body: NoteIn, session: SessionDep) -> dict:
    term = await session.get(glossary_module.GlossaryTerm, slug)
    if term is None:
        raise HTTPException(status_code=404, detail=f"unknown term {slug}")

    text = body.note.strip()
    if not text:
        # Clearing a note deletes the row rather than storing an empty string,
        # so "no note" has one representation.
        existing = await session.get(glossary_module.GlossaryNote, slug)
        if existing:
            await session.delete(existing)
        await session.commit()
        return {"slug": slug, "note": None}

    now = datetime.now(timezone.utc)
    await session.execute(
        insert(glossary_module.GlossaryNote)
        .values(slug=slug, note=text, updated_at=now)
        .on_conflict_do_update(
            index_elements=["slug"], set_={"note": text, "updated_at": now}
        )
    )
    await session.commit()
    return {"slug": slug, "note": text, "updated_at": now.isoformat()}


@router.post("/reseed")
async def reseed(session: SessionDep) -> dict:
    """Re-apply the seed content. Notes are in another table and survive."""
    count = await glossary_module.seed(session)
    await session.commit()
    return {"terms": count}
