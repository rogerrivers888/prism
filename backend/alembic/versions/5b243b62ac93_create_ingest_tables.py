"""create ingest tables

Revision ID: 5b243b62ac93
Revises: ff73b2212fd0
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5b243b62ac93"
down_revision: Union[str, Sequence[str], None] = "ff73b2212fd0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("securities", sa.Column("exchange", sa.Text(), nullable=True))
    op.add_column(
        "securities",
        sa.Column(
            "subsector",
            sa.Text(),
            nullable=True,
            comment=(
                "Finer classification than sector. Exists so biotech can "
                "eventually be separated from asset-heavy healthcare — the "
                "known limitation documented in ASSET_LIGHT_SECTORS."
            ),
        ),
    )
    op.add_column(
        "securities",
        sa.Column(
            "currency",
            sa.Text(),
            nullable=True,
            comment="Reporting/quote currency as given by the provider, e.g. GBX. Never converted at ingest.",
        ),
    )
    op.add_column("securities", sa.Column("market_cap", sa.Numeric(), nullable=True))
    op.add_column(
        "securities",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "securities",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Whether published_at is a real filing date from the provider or an
    # estimate derived from period_end. Backtests must be able to exclude
    # estimated rows, so this is never allowed to be ambiguous.
    op.add_column(
        "fundamentals",
        sa.Column(
            "published_at_estimated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_table(
        "prices_daily",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(), nullable=True),
        sa.Column("high", sa.Numeric(), nullable=True),
        sa.Column("low", sa.Numeric(), nullable=True),
        sa.Column("close", sa.Numeric(), nullable=True),
        sa.Column("adjusted_close", sa.Numeric(), nullable=True),
        sa.Column("volume", sa.Numeric(), nullable=True),
        # Stored, never converted: the book is GBP but holdings are mostly
        # USD, and FX handling comes later. Baking it in here would be
        # impossible to unpick.
        sa.Column("currency", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("ticker", "date", name="pk_prices_daily"),
    )

    # Raw provider responses, archived before anything is parsed. If the
    # parser turns out to be wrong we re-parse from here rather than
    # re-fetching, which costs nothing and preserves the original evidence.
    op.create_table(
        "raw_responses",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_raw_responses_lookup",
        "raw_responses",
        ["provider", "endpoint", "ticker", "fetched_at"],
    )

    # Per-UTC-day call accounting, so the budget survives restarts.
    op.create_table(
        "api_call_usage",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("call_date", sa.Date(), nullable=False),
        sa.Column("calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("provider", "call_date", name="pk_api_call_usage"),
    )


def downgrade() -> None:
    op.drop_table("api_call_usage")
    op.drop_index("ix_raw_responses_lookup", table_name="raw_responses")
    op.drop_table("raw_responses")
    op.drop_table("prices_daily")
    op.drop_column("fundamentals", "published_at_estimated")
    for column in (
        "updated_at",
        "is_active",
        "market_cap",
        "currency",
        "subsector",
        "exchange",
    ):
        op.drop_column("securities", column)
