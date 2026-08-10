"""create positions projection tables

Revision ID: c8a0d477e055
Revises: 34ca3964d90c
Create Date: 2026-08-11

positions is a disposable read model derived entirely from events. Nothing
writes to it except the projector, and it must always be possible to TRUNCATE
it and rebuild exactly from event 1.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c8a0d477e055"
down_revision: Union[str, Sequence[str], None] = "34ca3964d90c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "positions",
        # Same id as the event stream the position derives from.
        sa.Column("stream_id", postgresql.UUID(as_uuid=True), primary_key=True),
        # 'spreadbet' | 'option' | 'share' — captured on the opening event,
        # never inferred from ticker or size.
        sa.Column("instrument_type", sa.Text(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        # 'long' | 'short'
        sa.Column("direction", sa.Text(), nullable=False),
        # £/point, contracts, or share count depending on instrument_type.
        sa.Column("size", sa.Numeric(), nullable=False),
        sa.Column("entry_price", sa.Numeric(), nullable=False),
        sa.Column("current_stop", sa.Numeric(), nullable=True),
        sa.Column(
            "initial_risk",
            sa.Numeric(),
            nullable=True,
            comment=(
                "R in account currency: abs(entry_price - stop) * size. NULL when "
                "there is no stop — never faked. Recomputed while the stop is still "
                "on the losing side of entry (the trade hasn't moved in our favour, "
                "so the stop change corrects what was at risk from the start); "
                "frozen once the stop reaches breakeven or better, because R is "
                "defined at entry and trailing a stop into profit doesn't change "
                "what was originally risked. Not a bug."
            ),
        ),
        sa.Column("currency", sa.Text(), nullable=False, server_default="GBP"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        # 'open' | 'closed'
        sa.Column("status", sa.Text(), nullable=False),
        # Provenance: id of the last event applied to this row.
        sa.Column("last_event_id", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_positions_status_ticker", "positions", ["status", "ticker"])

    op.create_table(
        "projection_state",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column(
            "last_event_id", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute("INSERT INTO projection_state (name) VALUES ('positions')")


def downgrade() -> None:
    op.drop_table("projection_state")
    op.drop_index("ix_positions_status_ticker", table_name="positions")
    op.drop_table("positions")
