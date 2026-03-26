"""Add buffer post fields to content_calendar.

Revision ID: 004
Revises: 003
Create Date: 2026-03-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "content_calendar",
        sa.Column("is_buffer", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "content_calendar",
        sa.Column("buffer_priority", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("content_calendar", "buffer_priority")
    op.drop_column("content_calendar", "is_buffer")
