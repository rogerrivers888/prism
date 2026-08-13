"""add glossary terms and personal notes

Revision ID: 7c1a4e9d2b60
Revises: 55ac5def3899
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c1a4e9d2b60"
down_revision: Union[str, Sequence[str], None] = "55ac5def3899"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "glossary_terms",
        sa.Column("slug", sa.Text(), primary_key=True),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
            comment=(
                "Other ways the term is written. Drives auto-linking, so "
                "'P/E', 'price to earnings' and 'PE ratio' all reach one entry."
            ),
        ),
        sa.Column("short_definition", sa.Text(), nullable=False),
        sa.Column("full_explanation", sa.Text(), nullable=False),
        sa.Column("worked_example", sa.Text(), nullable=True),
        sa.Column("how_to_read_it", sa.Text(), nullable=True),
        sa.Column("common_mistakes", sa.Text(), nullable=True),
        sa.Column(
            "related_slugs", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column(
            "external_links",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
            comment="[{label, url, source_type}] - several sources, because they explain differently.",
        ),
        sa.Column("category", sa.Text(), nullable=False),
    )
    op.create_index("ix_glossary_terms_category", "glossary_terms", ["category"])

    # Roger's own words, kept in a separate table from the seeded content on
    # purpose: re-seeding the glossary must never be able to destroy a note he
    # wrote. A column on glossary_terms would put those two lifecycles in the
    # same row and one careless upsert would take the note with it.
    op.create_table(
        "glossary_notes",
        sa.Column("slug", sa.Text(), primary_key=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("glossary_notes")
    op.drop_index("ix_glossary_terms_category", table_name="glossary_terms")
    op.drop_table("glossary_terms")
