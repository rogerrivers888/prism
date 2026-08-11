"""create securities fundamentals and lens scores

Revision ID: 467d287cb726
Revises: 5c8c5fa9ccb5
Create Date: 2026-08-11

fundamentals is point-in-time: restatements arrive as new rows with a later
published_at, never as updates, so any scoring for date D can use only rows
where published_at <= D.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "467d287cb726"
down_revision: Union[str, Sequence[str], None] = "5c8c5fa9ccb5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sector membership drives peer percentiles, Cycle applicability and the
    # asset-light P/B guard, so it needs a home of its own — it is not a
    # point-in-time numeric fact and does not belong in fundamentals.
    op.create_table(
        "securities",
        sa.Column("ticker", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sector", sa.Text(), nullable=False),
    )
    op.create_index("ix_securities_sector", "securities", ["sector"])

    op.create_table(
        "fundamentals",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        # When this figure became publicly known. Mandatory: it is what makes
        # point-in-time scoring possible and lookahead bias detectable.
        sa.Column("published_at", sa.Date(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "ticker", "metric", "period_end", "published_at", name="pk_fundamentals"
        ),
    )
    # Every read filters published_at <= as_of and then takes the latest
    # period, so lead with the point-in-time predicate.
    op.create_index(
        "ix_fundamentals_pit",
        "fundamentals",
        ["published_at", "ticker", "metric", "period_end"],
    )

    op.create_table(
        "lens_scores_daily",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("lens", sa.Text(), nullable=False),
        # NULL is a real answer: coverage too thin, or lens inapplicable.
        sa.Column("score", sa.Numeric(), nullable=True),
        sa.Column("coverage", sa.Numeric(), nullable=False),
        sa.Column("applicable", sa.Boolean(), nullable=False),
        # Raw metrics, per-metric subscores and the method used, for audit.
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        # Part of the primary key: when a formula changes, old scores keep
        # their old version rather than being recomputed into a different
        # meaning under the same name.
        sa.Column("scoring_version", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "ticker", "as_of", "lens", "scoring_version", name="pk_lens_scores_daily"
        ),
    )
    op.create_index(
        "ix_lens_scores_daily_lens_as_of", "lens_scores_daily", ["lens", "as_of"]
    )


def downgrade() -> None:
    op.drop_index("ix_lens_scores_daily_lens_as_of", table_name="lens_scores_daily")
    op.drop_table("lens_scores_daily")
    op.drop_index("ix_fundamentals_pit", table_name="fundamentals")
    op.drop_table("fundamentals")
    op.drop_index("ix_securities_sector", table_name="securities")
    op.drop_table("securities")
