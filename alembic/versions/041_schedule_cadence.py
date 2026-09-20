"""Schedule cadence, final stage and window; content-run final stage.

Additive only: existing rows read as weekly, full runs over seven days.

Revision ID: 041
Revises: 040
Create Date: 2026-09-20
"""

import sqlalchemy as sa

from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "editorial_schedules",
        sa.Column("cadence", sa.String(20), nullable=False, server_default="weekly"),
    )
    op.add_column(
        "editorial_schedules",
        sa.Column("final_stage", sa.String(30), nullable=False, server_default="exporting"),
    )
    op.add_column(
        "editorial_schedules",
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="7"),
    )
    op.add_column(
        "content_runs",
        sa.Column("final_stage", sa.String(30), nullable=False, server_default="exporting"),
    )


def downgrade() -> None:
    op.drop_column("content_runs", "final_stage")
    op.drop_column("editorial_schedules", "window_days")
    op.drop_column("editorial_schedules", "final_stage")
    op.drop_column("editorial_schedules", "cadence")
