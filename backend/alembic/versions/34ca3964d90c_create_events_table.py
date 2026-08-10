"""create events table

Revision ID: 34ca3964d90c
Revises: 6edc6af0a2ea
Create Date: 2026-08-10

The events table is the append-only ledger everything else derives from.
Immutability is enforced with a trigger that raises loudly — NOT a Postgres
RULE with DO INSTEAD NOTHING, which would silently discard writes while the
application believes they succeeded.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "34ca3964d90c"
down_revision: Union[str, Sequence[str], None] = "6edc6af0a2ea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("stream_id", postgresql.UUID(as_uuid=True), nullable=False),
        # 'position' | 'thesis' | 'rule' | 'research'
        sa.Column("stream_type", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        # occurred_at: when it happened in the world.
        # recorded_at: when we were told. A trade can fill on Monday and be
        # recorded on Thursday; keeping both lets us reconstruct what was
        # known at any point in time. Never collapse them into one.
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # 'roger' | 'ig-api' | 'rules-engine'
        sa.Column("actor", sa.Text(), nullable=False),
        sa.UniqueConstraint("stream_id", "seq", name="uq_events_stream_id_seq"),
    )

    # The unique constraint above already backs (stream_id, seq) lookups with
    # its index, so only the remaining two indexes are created explicitly.
    op.create_index(
        "ix_events_event_type_occurred_at", "events", ["event_type", "occurred_at"]
    )
    op.create_index(
        "ix_events_payload",
        "events",
        ["payload"],
        postgresql_using="gin",
    )

    # Immutability: fail loudly on any UPDATE or DELETE.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION events_immutable() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'events is append-only: % attempted on event id %',
            TG_OP, COALESCE(OLD.id, -1);
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER events_no_modify
          BEFORE UPDATE OR DELETE ON events
          FOR EACH ROW EXECUTE FUNCTION events_immutable();
        """
    )

    # Belt and braces. The table owner can still bypass grants, which is
    # exactly why the trigger above is the real protection.
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON events FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS events_no_modify ON events")
    op.execute("DROP FUNCTION IF EXISTS events_immutable()")
    op.drop_table("events")
