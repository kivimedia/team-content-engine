"""Add video_assets table for Remotion-rendered video output.

Revision ID: 013
Revises: 012
Create Date: 2026-03-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "video_assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("package_id", UUID(as_uuid=True), sa.ForeignKey("post_packages.id"), nullable=True),
        sa.Column("guide_id", UUID(as_uuid=True), sa.ForeignKey("weekly_guides.id"), nullable=True),
        # Template
        sa.Column("template_name", sa.String(100), nullable=False),
        sa.Column("composition_id", sa.String(100), nullable=True),
        sa.Column("composition_props", JSONB(), nullable=True),
        # Output
        sa.Column("video_url", sa.String(2000), nullable=True),
        sa.Column("video_s3_path", sa.String(1000), nullable=True),
        sa.Column("thumbnail_url", sa.String(2000), nullable=True),
        # Specs
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("resolution", sa.String(20), nullable=True),
        sa.Column("codec", sa.String(20), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        # Rendering
        sa.Column("render_time_seconds", sa.Float(), nullable=True),
        sa.Column("render_cost_usd", sa.Float(), nullable=True),
        # Review
        sa.Column("operator_selected", sa.Boolean(), server_default="false"),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        # Pipeline
        sa.Column("pipeline_run_id", UUID(as_uuid=True), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_video_assets_package_id", "video_assets", ["package_id"])
    op.create_index("ix_video_assets_guide_id", "video_assets", ["guide_id"])


def downgrade() -> None:
    op.drop_index("ix_video_assets_guide_id", "video_assets")
    op.drop_index("ix_video_assets_package_id", "video_assets")
    op.drop_table("video_assets")
