"""add watchlist research decisions and sleeves

Revision ID: 90bafa98e506
Revises: 99cf399c401e
Create Date: 2026-08-11

Read models and user-authored content for the remaining screens. The events
table is untouched: watchlist and decisions are projections over new event
types, not new sources of truth.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "90bafa98e506"
down_revision: Union[str, Sequence[str], None] = "99cf399c401e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sleeve is assigned on the opening trade and carried here by the
    # projection. It is a decision the operator makes, never inferred from
    # the numbers — a position is in a sleeve because it was bought for that
    # sleeve's reason, and each sleeve has its own exit discipline.
    op.add_column(
        "positions",
        sa.Column(
            "sleeve",
            sa.Text(),
            nullable=True,
            comment="high_growth | deeply_undervalued. From the opening event, never derived.",
        ),
    )

    # --- watchlist: projection over WatchlistAdded / WatchlistRemoved -------
    op.create_table(
        "watchlist",
        sa.Column("ticker", sa.Text(), primary_key=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("last_event_id", sa.BigInteger(), nullable=False),
    )

    # --- research ----------------------------------------------------------
    op.create_table(
        "research_points",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "scope_type",
            sa.Text(),
            nullable=False,
            comment="sector | ticker — the thing this point is an argument about.",
        ),
        sa.Column("scope_value", sa.Text(), nullable=False),
        sa.Column("stance", sa.Text(), nullable=False, comment="for | against"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "stress_test",
            sa.Text(),
            nullable=True,
            comment="Claude's attempt to break the argument. Advisory, not a verdict.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_research_points_scope", "research_points", ["scope_type", "scope_value"]
    )

    op.create_table(
        "research_clips",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "tickers",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Tickers Claude matched against the universe. Advisory tags.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Full-text search over title, summary and body.
    op.execute(
        """
        ALTER TABLE research_clips
        ADD COLUMN search tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english',
                coalesce(title,'') || ' ' || coalesce(summary,'') || ' ' || coalesce(body,''))
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_research_clips_search ON research_clips USING GIN (search)")

    # --- decisions: projection over Decision* events ------------------------
    op.create_table(
        "decisions",
        sa.Column("stream_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False, comment="buy | sell | trim | add | hold"),
        sa.Column("status", sa.Text(), nullable=False, comment="raised | taken | declined | closed"),
        # Required at entry: a decision without these is not a decision, it is
        # an impulse with a ticker attached.
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("premortem", sa.Text(), nullable=False),
        sa.Column("falsifier", sa.Text(), nullable=False),
        sa.Column("sizing_note", sa.Text(), nullable=True),
        sa.Column("declined_reason", sa.Text(), nullable=True),
        # Judged separately on purpose: a good decision can have a bad
        # outcome, and conflating them is how process gets rewritten by luck.
        sa.Column("decision_quality", sa.Text(), nullable=True, comment="good | bad"),
        sa.Column("outcome_quality", sa.Text(), nullable=True, comment="good | bad | neutral"),
        sa.Column(
            "error_tag",
            sa.Text(),
            nullable=True,
            comment="analytical | informational | behavioural | sizing | timing | none",
        ),
        sa.Column("close_note", sa.Text(), nullable=True),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_id", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_decisions_status", "decisions", ["status"])

    # --- saved screener filter sets ----------------------------------------
    op.create_table(
        "saved_screens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("filters", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("saved_screens")
    op.drop_index("ix_decisions_status", table_name="decisions")
    op.drop_table("decisions")
    op.execute("DROP INDEX IF EXISTS ix_research_clips_search")
    op.drop_table("research_clips")
    op.drop_index("ix_research_points_scope", table_name="research_points")
    op.drop_table("research_points")
    op.drop_table("watchlist")
    op.drop_column("positions", "sleeve")
