"""One receipt per workspace and local routine date.

Revision ID: s005
Revises: s004
Create Date: 2026-10-11
"""

import sqlalchemy as sa

from alembic import op

revision = "s005"
down_revision = "s004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "standalone_routine_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "workspace_id", sa.Uuid(), sa.ForeignKey("standalone_workspaces.id"), nullable=False
        ),
        sa.Column("routine_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("standalone_jobs.id")),
        sa.Column("error_code", sa.String(80)),
        sa.UniqueConstraint("workspace_id", "routine_date"),
    )
    op.create_index(
        "ix_standalone_routine_runs_workspace_id",
        "standalone_routine_runs",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_standalone_routine_runs_workspace_id",
        table_name="standalone_routine_runs",
    )
    op.drop_table("standalone_routine_runs")
