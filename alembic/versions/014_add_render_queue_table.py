"""Add render_queue table for tracking video render jobs.

Revision ID: 014
Revises: 013
Create Date: 2026-03-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "render_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pipeline_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("package_id", UUID(as_uuid=True), sa.ForeignKey("post_packages.id"), nullable=True),
        sa.Column("guide_id", UUID(as_uuid=True), sa.ForeignKey("weekly_guides.id"), nullable=True),
        # Job spec
        sa.Column("template_name", sa.String(100), nullable=False),
        sa.Column("composition_id", sa.String(100), nullable=True),
        sa.Column("composition_props", JSONB(), nullable=True),
        # Status: queued, rendering, completed, failed
        sa.Column("status", sa.String(20), server_default="queued"),
        sa.Column("progress_pct", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Output
        sa.Column("video_asset_id", UUID(as_uuid=True), sa.ForeignKey("video_assets.id"), nullable=True),
        sa.Column("output_path", sa.String(1000), nullable=True),
        sa.Column("thumbnail_path", sa.String(1000), nullable=True),
        # Timing
        sa.Column("queued_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("render_time_seconds", sa.Float(), nullable=True),
    )
    op.create_index("ix_render_queue_status", "render_queue", ["status"])
    op.create_index("ix_render_queue_package_id", "render_queue", ["package_id"])

    # Add thumbnail_path to video_assets
    op.add_column("video_assets", sa.Column("thumbnail_path", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("video_assets", "thumbnail_path")
    op.drop_index("ix_render_queue_package_id", "render_queue")
    op.drop_index("ix_render_queue_status", "render_queue")
    op.drop_table("render_queue")
