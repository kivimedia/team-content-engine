"""Add operator_feedback column to walking_video_scripts so operators can
capture revision notes, approval rationale, or "what to tune next time"
directly on the script row (mirrors the OperatorFeedback pattern on post
packages).

Revision ID: 029
Revises: 028
Create Date: 2026-04-18
"""

from alembic import op
import sqlalchemy as sa


revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "walking_video_scripts",
        sa.Column(
            "operator_feedback",
            sa.Text,
            nullable=True,
            comment="Operator notes on the generated script: what to tune, revision rationale, approval context.",
        ),
    )


def downgrade() -> None:
    op.drop_column("walking_video_scripts", "operator_feedback")
