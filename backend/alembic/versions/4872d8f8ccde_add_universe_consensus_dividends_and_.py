"""add universe consensus dividends and quote currency

Revision ID: 4872d8f8ccde
Revises: 5b243b62ac93
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4872d8f8ccde"
down_revision: Union[str, Sequence[str], None] = "5b243b62ac93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "securities",
        sa.Column(
            "quote_currency",
            sa.Text(),
            nullable=True,
            comment=(
                "Currency prices are QUOTED in, which is not always the "
                "currency the accounts are REPORTED in. GBX (pence) is the "
                "trap: a GBX quote is 1/100 of a GBP figure, so treating the "
                "two as equal silently overstates by 100x. Never equate them; "
                "see app/currency.py."
            ),
        ),
    )

    # Earnings::Trend is a snapshot of today's consensus that cannot be
    # backfilled. Appending one row per observation date builds the history
    # forward instead, and costs nothing — the payload is already fetched.
    op.create_table(
        "consensus_estimates",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column(
            "observed_on",
            sa.Date(),
            nullable=False,
            comment="Date we saw this consensus. Never overwritten by a later observation.",
        ),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("period_label", sa.Text(), nullable=True),
        sa.Column("eps_avg", sa.Numeric(), nullable=True),
        sa.Column("eps_low", sa.Numeric(), nullable=True),
        sa.Column("eps_high", sa.Numeric(), nullable=True),
        sa.Column("eps_year_ago", sa.Numeric(), nullable=True),
        sa.Column("analysts", sa.Numeric(), nullable=True),
        sa.Column("eps_7d_ago", sa.Numeric(), nullable=True),
        sa.Column("eps_30d_ago", sa.Numeric(), nullable=True),
        sa.Column("eps_60d_ago", sa.Numeric(), nullable=True),
        sa.Column("eps_90d_ago", sa.Numeric(), nullable=True),
        sa.Column("revenue_avg", sa.Numeric(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint(
            "ticker", "observed_on", "period_end", name="pk_consensus_estimates"
        ),
    )
    op.create_index(
        "ix_consensus_estimates_ticker_period",
        "consensus_estimates",
        ["ticker", "period_end", "observed_on"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_consensus_estimates_ticker_period", table_name="consensus_estimates"
    )
    op.drop_table("consensus_estimates")
    op.drop_column("securities", "quote_currency")
