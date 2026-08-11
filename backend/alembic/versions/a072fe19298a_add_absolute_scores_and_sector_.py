"""add absolute scores and sector aggregates

Revision ID: a072fe19298a
Revises: 4872d8f8ccde
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a072fe19298a"
down_revision: Union[str, Sequence[str], None] = "4872d8f8ccde"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lens_scores_daily",
        sa.Column(
            "score_absolute",
            sa.Numeric(),
            nullable=True,
            comment=(
                "The lens scored purely against declared bands, ignoring "
                "peers. Secondary to `score`, which stays peer-relative."
            ),
        ),
    )
    op.add_column(
        "lens_scores_daily",
        sa.Column(
            "relative_premium",
            sa.Numeric(),
            nullable=True,
            comment=(
                "score - score_absolute. Large positive on value means "
                "cheap-within-an-expensive-sector: the cyclical-peak trap "
                "where a name screens well only because its peers screen "
                "worse. Large negative is the reverse."
            ),
        ),
    )

    # What tells us the sector itself is stretched, rather than the stock.
    op.create_table(
        "sector_lens_daily",
        sa.Column("sector", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("lens", sa.Text(), nullable=False),
        sa.Column("scoring_version", sa.Text(), nullable=False),
        sa.Column("median_score", sa.Numeric(), nullable=True),
        sa.Column(
            "median_score_absolute",
            sa.Numeric(),
            nullable=True,
            comment=(
                "The headline for a sector screen: a low median absolute "
                "value score means the whole sector is richly priced, which "
                "peer percentiles cannot show by construction."
            ),
        ),
        sa.Column("median_relative_premium", sa.Numeric(), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "sector", "as_of", "lens", "scoring_version", name="pk_sector_lens_daily"
        ),
    )
    op.create_index(
        "ix_sector_lens_daily_as_of", "sector_lens_daily", ["as_of", "lens"]
    )


def downgrade() -> None:
    op.drop_index("ix_sector_lens_daily_as_of", table_name="sector_lens_daily")
    op.drop_table("sector_lens_daily")
    op.drop_column("lens_scores_daily", "relative_premium")
    op.drop_column("lens_scores_daily", "score_absolute")
