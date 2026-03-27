"""Add plan_context and weekly_plan_id to content_calendar for deep planning.

Revision ID: 011
Revises: 010
Create Date: 2026-03-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "content_calendar",
        sa.Column("plan_context", JSONB(), nullable=True),
    )
    op.add_column(
        "content_calendar",
        sa.Column("weekly_plan_id", UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("content_calendar", "weekly_plan_id")
    op.drop_column("content_calendar", "plan_context")
