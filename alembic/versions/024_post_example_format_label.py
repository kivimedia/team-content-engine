"""Add format_label column to post_examples for video-format creators (walking, talking-head).

Revision ID: 024
Revises: 023
Create Date: 2026-04-17
"""

from alembic import op
import sqlalchemy as sa


revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "post_examples",
        sa.Column(
            "format_label",
            sa.String(50),
            nullable=True,
            comment="Post format: walking_monologue | talking_head | photo_post | carousel | reel_text. Drives writer-agent style selection.",
        ),
    )
    op.create_index(
        "idx_post_examples_format_label",
        "post_examples",
        ["format_label"],
    )


def downgrade() -> None:
    op.drop_index("idx_post_examples_format_label", table_name="post_examples")
    op.drop_column("post_examples", "format_label")
