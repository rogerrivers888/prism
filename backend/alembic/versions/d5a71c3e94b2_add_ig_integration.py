"""add IG integration

Revision ID: d5a71c3e94b2
Revises: c7d3e8f2a915
Create Date: 2026-08-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5a71c3e94b2"
down_revision: Union[str, Sequence[str], None] = "c7d3e8f2a915"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Two accounts under one login, and they are opposite risk regimes: a
    # pension that cannot be leveraged and a spread bet account that is
    # leveraged and funded nightly. Nothing downstream may total them
    # together, so the account is a first-class dimension everywhere.
    op.create_table(
        "ig_accounts",
        sa.Column("account_id", sa.Text(), primary_key=True),
        sa.Column(
            "type",
            sa.Text(),
            nullable=False,
            comment="IG's own accountType: SPREADBET, CFD, PHYSICAL (SIPP/ISA).",
        ),
        sa.Column(
            "regime",
            sa.Text(),
            nullable=False,
            comment=(
                "How Prism must treat it: 'leveraged' (funding accrues, margin "
                "matters) or 'unleveraged' (long-horizon, no funding). Derived "
                "from type, overridable by hand."
            ),
        ),
        sa.Column("label", sa.Text(), nullable=True, comment="Roger's own name for it."),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("is_preferred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    # Epic -> security. IG identifies markets by epic, not ticker, and an
    # unmappable epic is flagged rather than guessed: a wrong mapping would
    # silently attach one company's lens scores to another's position.
    op.create_table(
        "ig_epic_map",
        sa.Column("epic", sa.Text(), primary_key=True),
        sa.Column("ticker", sa.Text(), nullable=True,
                  comment="NULL until mapped. Never guessed."),
        sa.Column("instrument_name", sa.Text(), nullable=True),
        sa.Column("instrument_type", sa.Text(), nullable=True,
                  comment="IG's type: SHARES, INDICES, OPT_SHARES, BINARY, etc."),
        sa.Column("kind", sa.Text(), nullable=False, server_default="unknown",
                  comment="Prism's classification: equity, index, option, other."),
        # Option contract detail, parsed from the epic or the market payload.
        sa.Column("option_right", sa.Text(), nullable=True, comment="call | put"),
        sa.Column("option_strike", sa.Numeric(), nullable=True),
        sa.Column("option_expiry", sa.Date(), nullable=True),
        sa.Column("underlying_ticker", sa.Text(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.true(),
                  comment="True until a human confirms or corrects the mapping."),
        sa.Column("mapped_by", sa.Text(), nullable=True, comment="auto | roger"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_ig_epic_map_review", "ig_epic_map", ["needs_review"])

    # Projection of the IG position feed: what IG says we hold, right now.
    # Prism's own positions table stays separate — reconciliation links them
    # rather than merging, because a silent merge destroys the distinction
    # between what Roger recorded and what IG reports.
    op.create_table(
        "ig_positions",
        sa.Column("deal_id", sa.Text(), primary_key=True),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("epic", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("size", sa.Numeric(), nullable=False),
        sa.Column("open_level", sa.Numeric(), nullable=True),
        sa.Column("current_level", sa.Numeric(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("stop_level", sa.Numeric(), nullable=True),
        sa.Column("limit_level", sa.Numeric(), nullable=True),
        sa.Column("contract_size", sa.Numeric(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry", sa.Text(), nullable=True,
                  comment="IG's expiry string: '-' for cash, 'SEP-26' for dated."),
        sa.Column("instrument_type", sa.Text(), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Set when IG stops reporting it. Rows are never deleted."),
        sa.Column("last_event_id", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_ig_positions_account", "ig_positions", ["account_id", "closed_at"])

    # Option contracts, resolved. Separate from ig_positions because an option
    # needs its own vocabulary — strike, expiry, multiplier — and because
    # misparsing one as an equity bet is the specific failure to avoid.
    op.create_table(
        "option_positions",
        sa.Column("deal_id", sa.Text(), primary_key=True),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("epic", sa.Text(), nullable=False),
        sa.Column("underlying_ticker", sa.Text(), nullable=True),
        sa.Column("right", sa.Text(), nullable=False, comment="call | put"),
        sa.Column("strike", sa.Numeric(), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("contracts", sa.Numeric(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False, comment="long (bought) | short (written)"),
        sa.Column("multiplier", sa.Numeric(), nullable=False, server_default="100",
                  comment="Shares per contract. IG's contract size where given."),
        sa.Column("premium", sa.Numeric(), nullable=True,
                  comment="Paid if long, received if short, in position currency."),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("iv_at_entry", sa.Numeric(), nullable=True),
        sa.Column(
            "iv_estimated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            comment=(
                "True when IV was solved from the mark rather than supplied by "
                "IG. Shown to the user as estimated - an inferred number must "
                "never be presented as a quoted one."
            ),
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_option_positions_account", "option_positions",
                    ["account_id", "closed_at"])

    # Daily mark per contract, so decay is observed rather than only modelled.
    op.create_table(
        "option_marks",
        sa.Column("deal_id", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("mark", sa.Numeric(), nullable=False, comment="Contract value per unit."),
        sa.Column("underlying_price", sa.Numeric(), nullable=True),
        sa.Column("implied_vol", sa.Numeric(), nullable=True),
        sa.Column("iv_estimated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("delta", sa.Numeric(), nullable=True),
        sa.Column("theta_per_day", sa.Numeric(), nullable=True),
        sa.PrimaryKeyConstraint("deal_id", "as_of", name="pk_option_marks"),
    )

    # Balance and margin per account per day.
    op.create_table(
        "ig_balances",
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("balance", sa.Numeric(), nullable=True),
        sa.Column("deposit", sa.Numeric(), nullable=True, comment="Margin held."),
        sa.Column("profit_loss", sa.Numeric(), nullable=True),
        sa.Column("available", sa.Numeric(), nullable=True),
        sa.PrimaryKeyConstraint("account_id", "as_of", name="pk_ig_balances"),
    )

    # Funding accrual per leveraged position per night. Derived and
    # recomputable, but stored so "paid to date" is a sum rather than a
    # re-simulation every page load.
    op.create_table(
        "funding_accruals",
        sa.Column("deal_id", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("notional", sa.Numeric(), nullable=False,
                  comment="FULL notional, not margin. This is the point."),
        sa.Column("annual_rate_pct", sa.Numeric(), nullable=False),
        sa.Column("charge", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("estimated", sa.Boolean(), nullable=False, server_default=sa.true(),
                  comment="Prism's calculation, not IG's billed figure."),
        sa.PrimaryKeyConstraint("deal_id", "as_of", name="pk_funding_accruals"),
    )

    # First-sync reconciliation, reviewed rather than auto-applied.
    op.create_table(
        "ig_reconciliation",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            comment="matched | ig_only | prism_only — never auto-merged, never auto-deleted.",
        ),
        sa.Column("deal_id", sa.Text(), nullable=True),
        sa.Column("epic", sa.Text(), nullable=True),
        sa.Column("ticker", sa.Text(), nullable=True),
        sa.Column("prism_stream_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending",
                  comment="pending | accepted | rejected"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_ig_reconciliation_status", "ig_reconciliation", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ig_reconciliation_status", table_name="ig_reconciliation")
    op.drop_table("ig_reconciliation")
    op.drop_table("funding_accruals")
    op.drop_table("ig_balances")
    op.drop_table("option_marks")
    op.drop_index("ix_option_positions_account", table_name="option_positions")
    op.drop_table("option_positions")
    op.drop_index("ix_ig_positions_account", table_name="ig_positions")
    op.drop_table("ig_positions")
    op.drop_index("ix_ig_epic_map_review", table_name="ig_epic_map")
    op.drop_table("ig_epic_map")
    op.drop_table("ig_accounts")
