"""add job runs and score computed at

Revision ID: 99cf399c401e
Revises: a072fe19298a
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "99cf399c401e"
down_revision: Union[str, Sequence[str], None] = "a072fe19298a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # So "did last night work?" is a query, not a log-reading exercise.
    op.create_table(
        "job_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("job", sa.Text(), nullable=False),
        sa.Column(
            "run_date",
            sa.Date(),
            nullable=False,
            comment="UTC date the run is for. One successful run per job per date.",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            comment="running | succeeded | failed. A run left as 'running' died mid-flight.",
        ),
        sa.Column("calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tickers_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tickers_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scores_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", postgresql.JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_job_runs_job_date", "job_runs", ["job", "run_date"])

    # Scores carry the wall-clock time they were computed, so a consumer can
    # tell stale numbers from current ones. as_of alone cannot: a score dated
    # today might have been written a week ago by a run that has since failed.
    op.add_column(
        "lens_scores_daily",
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lens_scores_daily", "computed_at")
    op.drop_index("ix_job_runs_job_date", table_name="job_runs")
    op.drop_table("job_runs")
