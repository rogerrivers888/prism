"""add index membership

Revision ID: c7d3e8f2a915
Revises: b4f8a2c91e57
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d3e8f2a915"
down_revision: Union[str, Sequence[str], None] = "b4f8a2c91e57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Who was in the index, when. The repair for survivorship bias: a backtest
    # at date D selects from membership AS OF D, so companies that later died
    # are eligible while they were alive and invisible after they left.
    op.create_table(
        "index_membership",
        sa.Column("index", sa.Text(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("joined_on", sa.Date(), nullable=False),
        sa.Column(
            "left_on",
            sa.Date(),
            nullable=True,
            comment="NULL while still a member.",
        ),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "joined_estimated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment=(
                "True when the source had no join date and inception was assumed. "
                "These are long-tenured members whose departure is known - "
                "dropping them would remove most of the survivorship repair."
            ),
        ),
        sa.Column(
            "is_delisted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Gone from the exchange entirely, not merely out of the index.",
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("index", "ticker", "joined_on", name="pk_index_membership"),
    )
    op.create_index("ix_index_membership_window", "index_membership",
                    ["index", "joined_on", "left_on"])


def downgrade() -> None:
    op.drop_index("ix_index_membership_window", table_name="index_membership")
    op.drop_table("index_membership")
