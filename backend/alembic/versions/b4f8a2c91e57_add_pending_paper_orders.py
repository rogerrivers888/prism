"""add pending paper orders

Revision ID: b4f8a2c91e57
Revises: 9e2b7c41d8a3
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4f8a2c91e57"
down_revision: Union[str, Sequence[str], None] = "9e2b7c41d8a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A signal computed tonight fills at TOMORROW's open, which does not exist
    # yet. The order waits here; when the next nightly run sees the open, it
    # writes the PaperTradeExecuted event and deletes the row. Operational
    # state, not history — the events are the history.
    op.create_table(
        "pending_paper_orders",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("rule_fired", sa.Text(), nullable=False),
        sa.Column("metric_values", postgresql.JSONB(), nullable=False),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Fill attempts. After 5 sessions with no print, dropped with a log.",
        ),
        sa.UniqueConstraint("strategy_id", "ticker", "side", "signal_date",
                            name="uq_pending_order"),
    )
    op.create_index("ix_pending_orders_strategy", "pending_paper_orders", ["strategy_id"])


def downgrade() -> None:
    op.drop_index("ix_pending_orders_strategy", table_name="pending_paper_orders")
    op.drop_table("pending_paper_orders")
