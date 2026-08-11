"""create dispersion daily

Revision ID: ff73b2212fd0
Revises: 467d287cb726
Create Date: 2026-08-11

Dispersion is one figure per ticker per day, not per lens, so it gets its own
table. A column on lens_scores_daily would repeat the same value across all
six lens rows and invite them to drift apart.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ff73b2212fd0"
down_revision: Union[str, Sequence[str], None] = "467d287cb726"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dispersion_daily",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        # Same versioning contract as the scores it is derived from.
        sa.Column("scoring_version", sa.Text(), nullable=False),
        sa.Column(
            "dispersion",
            sa.Numeric(),
            nullable=True,
            comment=(
                "Max minus min score across lenses that are both applicable "
                "and non-null. NULL below three such lenses: a gap between "
                "two readings is a coin toss, not a disagreement."
            ),
        ),
        sa.Column(
            "usable_lenses",
            sa.Integer(),
            nullable=False,
            comment="How many lenses contributed, so a NULL can be explained.",
        ),
        sa.PrimaryKeyConstraint(
            "ticker", "as_of", "scoring_version", name="pk_dispersion_daily"
        ),
    )
    op.create_index("ix_dispersion_daily_as_of", "dispersion_daily", ["as_of"])


def downgrade() -> None:
    op.drop_index("ix_dispersion_daily_as_of", table_name="dispersion_daily")
    op.drop_table("dispersion_daily")
