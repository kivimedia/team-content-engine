"""His editorial settings: how many videos a week.

26-Sep: "I need a setting page that allows me to promote more than 3 videos a week
(choose how many videos)". One row per workspace; a workspace with no row keeps the
old default of three. Additive only.

Revision ID: 051
Revises: 050
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editorial_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("videos_per_week", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", name="uq_editorial_settings_workspace"),
    )
    op.create_index("ix_editorial_settings_workspace_id", "editorial_settings", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_editorial_settings_workspace_id", table_name="editorial_settings")
    op.drop_table("editorial_settings")
