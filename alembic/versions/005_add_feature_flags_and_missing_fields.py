"""Add feature flags table and missing PRD fields.

Revision ID: 005
Revises: 004
Create Date: 2026-03-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # GAP-08: Feature flags table
    op.create_table(
        "feature_flags",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )

    # GAP-13: actual_joins on learning_events (PRD 11.8)
    op.add_column(
        "learning_events",
        sa.Column("actual_joins", sa.Integer(), nullable=True),
    )

    # GAP-13: ingested_at on source_documents (PRD 11.1)
    op.add_column(
        "source_documents",
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
    )

    # GAP-13: image_prompts on post_packages (PRD 11.7)
    op.add_column(
        "post_packages",
        sa.Column("image_prompts", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("post_packages", "image_prompts")
    op.drop_column("source_documents", "ingested_at")
    op.drop_column("learning_events", "actual_joins")
    op.drop_table("feature_flags")
