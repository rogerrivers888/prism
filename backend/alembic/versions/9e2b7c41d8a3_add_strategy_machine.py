"""add strategy machine tables

Revision ID: 9e2b7c41d8a3
Revises: 7c1a4e9d2b60
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9e2b7c41d8a3"
down_revision: Union[str, Sequence[str], None] = "7c1a4e9d2b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Read model over the strategy event streams. Disposable: TRUNCATE and
    # rebuild from event 1, like every other projection here. The events are
    # the record; this is the query surface.
    op.create_table(
        "strategies",
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False),
        sa.Column("citation", sa.Text(), nullable=True),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column(
            "rule_signature",
            sa.Text(),
            nullable=False,
            comment="sha256 of the canonicalised rules. Outright duplicates collide here.",
        ),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("expected_trade_frequency", sa.Text(), nullable=False),
        sa.Column("expected_holding_period", sa.Text(), nullable=False),
        sa.Column("predicted_performance", sa.Text(), nullable=False),
        sa.Column("parent_strategy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decay_note", sa.Text(), nullable=False),
        sa.Column("encoding_deviations", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="registered"),
        sa.Column("stage", sa.Text(), nullable=False, server_default="backtest"),
        sa.Column(
            "duplicate_of",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Set by the novelty gate: named sibling this duplicates. Blocks activation.",
        ),
        sa.Column("duplicate_correlation", sa.Numeric(), nullable=True),
        sa.Column("duplicate_override_note", sa.Text(), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_id", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_strategies_status", "strategies", ["status"])
    op.create_index("ix_strategies_parent", "strategies", ["parent_strategy_id"])

    # One row per gate run. monthly_returns is kept so the novelty gate can
    # correlate a new strategy against every existing one without re-running
    # their backtests.
    op.create_table(
        "strategy_backtests",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("results", postgresql.JSONB(), nullable=False),
        sa.Column(
            "monthly_returns",
            postgresql.JSONB(),
            nullable=False,
            comment='[{"month": "2015-03", "return_pct": 1.2}, ...] for correlation.',
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_strategy_backtests_strategy", "strategy_backtests", ["strategy_id"])

    # Paper book projections, rebuilt from PaperTradeExecuted events.
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("spread_cost", sa.Numeric(), nullable=False),
        sa.Column("commission", sa.Numeric(), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("fill_date", sa.Date(), nullable=False),
        sa.Column("rule_fired", sa.Text(), nullable=False),
        sa.Column("metric_values", postgresql.JSONB(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False, unique=True),
    )
    op.create_index("ix_paper_trades_strategy", "paper_trades", ["strategy_id", "fill_date"])

    op.create_table(
        "paper_positions",
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("avg_cost", sa.Numeric(), nullable=False),
        sa.Column("opened_at", sa.Date(), nullable=False),
        sa.Column("rule_fired", sa.Text(), nullable=False),
        sa.Column("metric_values", postgresql.JSONB(), nullable=False),
        sa.Column("last_event_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("strategy_id", "ticker", name="pk_paper_positions"),
    )

    # Derived, not event-sourced: recomputable from trades + prices at any
    # time. The nightly job appends one row per strategy per day.
    op.create_table(
        "paper_equity_daily",
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("equity", sa.Numeric(), nullable=False),
        sa.Column("cash", sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint("strategy_id", "date", name="pk_paper_equity_daily"),
    )


def downgrade() -> None:
    op.drop_table("paper_equity_daily")
    op.drop_table("paper_positions")
    op.drop_index("ix_paper_trades_strategy", table_name="paper_trades")
    op.drop_table("paper_trades")
    op.drop_index("ix_strategy_backtests_strategy", table_name="strategy_backtests")
    op.drop_table("strategy_backtests")
    op.drop_index("ix_strategies_parent", table_name="strategies")
    op.drop_index("ix_strategies_status", table_name="strategies")
    op.drop_table("strategies")
