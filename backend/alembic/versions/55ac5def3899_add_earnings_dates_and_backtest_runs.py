"""add earnings dates and backtest runs

Revision ID: 55ac5def3899
Revises: 90bafa98e506
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "55ac5def3899"
down_revision: Union[str, Sequence[str], None] = "90bafa98e506"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Point-in-time by construction. A future report date is an estimate that
    # moves, so each observation is its own row keyed by the day we saw it.
    # "What date was expected on 3 March?" is then a query, not a guess — and
    # the backtest depends on being able to ask it.
    op.create_table(
        "earnings_dates",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "observed_on",
            sa.Date(),
            nullable=False,
            comment="Date we saw this. Never overwritten by a later observation.",
        ),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column(
            "is_estimated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="True while the period has no actual EPS — the date is still a forecast.",
        ),
        sa.Column("before_after_market", sa.Text(), nullable=True),
        sa.Column("eps_estimate", sa.Numeric(), nullable=True),
        sa.Column("eps_actual", sa.Numeric(), nullable=True),
        sa.Column("revenue_estimate", sa.Numeric(), nullable=True),
        sa.Column("revenue_actual", sa.Numeric(), nullable=True),
        sa.Column("surprise_percent", sa.Numeric(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "ticker", "period_end", "observed_on", name="pk_earnings_dates"
        ),
    )
    op.create_index(
        "ix_earnings_dates_lookup", "earnings_dates", ["ticker", "report_date"]
    )

    # Every run is kept, including the bad ones. A harness that only stores
    # results worth keeping is a machine for finding false positives.
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("results", postgresql.JSONB(), nullable=False),
        sa.Column(
            "variants_tested",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment=(
                "How many parameter combinations were evaluated in the sweep this "
                "result came from. Without it, the best of twenty looks like one."
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("backtest_runs")
    op.drop_index("ix_earnings_dates_lookup", table_name="earnings_dates")
    op.drop_table("earnings_dates")
