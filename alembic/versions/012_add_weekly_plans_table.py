"""Add weekly_plans table for persistent plan storage.

Revision ID: 012
Revises: 011
Create Date: 2026-03-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weekly_plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("plan_data", JSONB(), nullable=True),
        sa.Column("week_start", sa.Date(), nullable=True),
        sa.Column("progress_log", sa.Text(), nullable=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("weekly_plans")
