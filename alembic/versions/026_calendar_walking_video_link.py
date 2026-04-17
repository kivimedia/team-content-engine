"""Link ContentCalendarEntry to walking_video_scripts so video-day cards
can show a READY status + "View Script" button after generation.

Revision ID: 026
Revises: 025
Create Date: 2026-04-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_calendar",
        sa.Column(
            "walking_video_script_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("walking_video_scripts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("content_calendar", "walking_video_script_id")
