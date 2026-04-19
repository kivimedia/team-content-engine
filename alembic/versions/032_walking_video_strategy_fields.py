"""Add personal_anchor and strategic_justification to walking_video_scripts.

These fields store the writer agent's reasoning: why this topic was chosen,
what personal/first-person angle was used, and how it serves the strategy.
Visible in the Video Studio detail view so operators can judge script quality.

Revision ID: 032
Revises: 031
Create Date: 2026-04-19
"""

from alembic import op
import sqlalchemy as sa

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "walking_video_scripts",
        sa.Column("personal_anchor", sa.Text(), nullable=True),
    )
    op.add_column(
        "walking_video_scripts",
        sa.Column("strategic_justification", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("walking_video_scripts", "strategic_justification")
    op.drop_column("walking_video_scripts", "personal_anchor")
