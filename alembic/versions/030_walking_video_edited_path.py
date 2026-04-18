"""Add edited_video_file_path column to walking_video_scripts so the CutSense
output URL can be stored alongside the raw recording (video_file_path).

Revision ID: 030
Revises: 029
Create Date: 2026-04-18
"""

from alembic import op
import sqlalchemy as sa


revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "walking_video_scripts",
        sa.Column(
            "edited_video_file_path",
            sa.Text,
            nullable=True,
            comment="CutSense output URL/path. Set when status flips to edited.",
        ),
    )


def downgrade() -> None:
    op.drop_column("walking_video_scripts", "edited_video_file_path")
