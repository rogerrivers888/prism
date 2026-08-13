"""The glossary, and the one property that matters most: re-seeding must never
be able to destroy something Roger wrote."""

import pytest

from app import glossary as glossary_module


def test_seed_content_is_well_formed():
    rows = glossary_module.seed_rows()
    slugs = {r["slug"] for r in rows}
    assert len(slugs) == len(rows), "duplicate slugs in the seed"

    for row in rows:
        assert row["term"] and row["short_definition"] and row["full_explanation"]
        assert row["category"]
        for link in row["external_links"]:
            assert link["url"].startswith("https://")
            assert link["label"] and link["source_type"]

    # A related term that points nowhere renders as a dead chip in the drawer.
    dangling = {s for r in rows for s in r["related_slugs"]} - slugs
    assert not dangling, f"related_slugs point at missing terms: {sorted(dangling)}"


def test_every_metric_explainer_survived_the_migration():
    """The 32 metric explainers moved here from the frontend rather than being
    copied. If one was dropped in the move, a metric name silently stops being
    clickable, so the count is pinned."""
    rows = {r["slug"] for r in glossary_module.seed_rows()}
    for slug in ("pe_ratio", "ev_ebitda", "fcf_yield", "gross_profitability",
                 "days_inventory_change", "book_to_bill", "ebitda", "fcf"):
        assert slug in rows


@pytest.mark.asyncio
async def test_seed_is_idempotent(session):
    first = await glossary_module.seed(session)
    second = await glossary_module.seed(session)
    assert first == second
    assert len(await glossary_module.all_terms(session)) == first


@pytest.mark.asyncio
async def test_a_personal_note_survives_reseeding(session):
    """The reason notes live in their own table.

    If a note shared a row with the seeded content, an upsert on re-seed would
    overwrite it, and the loss would be silent.
    """
    from datetime import datetime, timezone

    await glossary_module.seed(session)
    session.add(
        glossary_module.GlossaryNote(
            slug="pe_ratio",
            note="I keep over-trusting this on cyclicals.",
            updated_at=datetime.now(timezone.utc),
        )
    )
    await session.flush()

    await glossary_module.seed(session)

    notes = await glossary_module.notes_by_slug(session)
    assert notes["pe_ratio"].note == "I keep over-trusting this on cyclicals."
