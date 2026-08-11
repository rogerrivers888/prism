"""add current_risk to positions

Revision ID: 5c8c5fa9ccb5
Revises: c8a0d477e055
Create Date: 2026-08-11

Splits risk into two honest numbers: initial_risk (R, fixed at entry) and
current_risk (live heat, tracks the stop).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c8c5fa9ccb5"
down_revision: Union[str, Sequence[str], None] = "c8a0d477e055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INITIAL_RISK_COMMENT_OLD = (
    "R in account currency: abs(entry_price - stop) * size. NULL when "
    "there is no stop — never faked. Recomputed while the stop is still "
    "on the losing side of entry (the trade hasn't moved in our favour, "
    "so the stop change corrects what was at risk from the start); "
    "frozen once the stop reaches breakeven or better, because R is "
    "defined at entry and trailing a stop into profit doesn't change "
    "what was originally risked. Not a bug."
)
_INITIAL_RISK_COMMENT_NEW = (
    "R in account currency: abs(entry_price - stop) * size, set exactly once "
    "from the opening TradeExecuted event and never recalculated by any "
    "subsequent event — R is the risk accepted at entry and must not drift. "
    "NULL when the opening trade carried no stop; never faked."
)


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column(
            "current_risk",
            sa.Numeric(),
            nullable=True,
            comment=(
                "Live portfolio heat: abs(entry_price - current_stop) * size, "
                "recomputed whenever the stop or size changes. NULL when there "
                "is no stop, or once the position is closed."
            ),
        ),
    )
    op.alter_column("positions", "initial_risk", comment=_INITIAL_RISK_COMMENT_NEW)


def downgrade() -> None:
    op.alter_column("positions", "initial_risk", comment=_INITIAL_RISK_COMMENT_OLD)
    op.drop_column("positions", "current_risk")
