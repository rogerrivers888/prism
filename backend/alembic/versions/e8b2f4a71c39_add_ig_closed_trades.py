"""add IG closed trades

Revision ID: e8b2f4a71c39
Revises: d5a71c3e94b2
Create Date: 2026-08-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8b2f4a71c39"
down_revision: Union[str, Sequence[str], None] = "d5a71c3e94b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Trades that have already closed, projected from IG's transaction
    # history. The open-position feed cannot see these — it only reports what
    # is live — so without this the closed tab would stay empty forever even
    # though IG has years of record.
    op.create_table(
        "ig_closed_trades",
        sa.Column("reference", sa.Text(), primary_key=True),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("instrument_name", sa.Text(), nullable=True),
        sa.Column("ticker", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("direction", sa.Text(), nullable=True),
        sa.Column("size", sa.Numeric(), nullable=True),
        sa.Column("open_level", sa.Numeric(), nullable=True),
        sa.Column("close_level", sa.Numeric(), nullable=True),
        sa.Column(
            "profit_loss",
            sa.Numeric(),
            nullable=True,
            comment="IG's own realised figure, in the account currency.",
        ),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("days_held", sa.Integer(), nullable=True),
        # Option contract detail, where the name yields it.
        sa.Column("option_right", sa.Text(), nullable=True),
        sa.Column("option_strike", sa.Numeric(), nullable=True),
    )
    op.create_index("ix_ig_closed_trades_closed", "ig_closed_trades", ["closed_at"])
    op.create_index("ix_ig_closed_trades_account", "ig_closed_trades", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_ig_closed_trades_account", table_name="ig_closed_trades")
    op.drop_index("ix_ig_closed_trades_closed", table_name="ig_closed_trades")
    op.drop_table("ig_closed_trades")
