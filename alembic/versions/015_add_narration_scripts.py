"""Add narration_scripts table for voiceover-driven video pipeline.

Revision ID: 015
Revises: 014
Create Date: 2026-03-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narration_scripts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        # Reference
        sa.Column("package_id", UUID(as_uuid=True), sa.ForeignKey("post_packages.id"), nullable=True),
        # Script content
        sa.Column("template_style", sa.String(50), nullable=False),
        sa.Column("segments", JSONB, nullable=True),
        # Status
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        # Audio
        sa.Column("audio_file_path", sa.String(1000), nullable=True),
        sa.Column("audio_duration_sec", sa.Float, nullable=True),
        sa.Column("audio_format", sa.String(10), nullable=True),
        # Whisper alignment
        sa.Column("whisper_transcript", JSONB, nullable=True),
        sa.Column("alignment_method", sa.String(30), nullable=True),
        # Estimates
        sa.Column("estimated_duration_sec", sa.Float, nullable=True),
        sa.Column("word_count", sa.Integer, nullable=True),
        # Rendered output
        sa.Column("video_asset_id", UUID(as_uuid=True), sa.ForeignKey("video_assets.id"), nullable=True),
        # Pipeline
        sa.Column("pipeline_run_id", UUID(as_uuid=True), nullable=True),
    )

    op.create_index("ix_narration_scripts_package_id", "narration_scripts", ["package_id"])
    op.create_index("ix_narration_scripts_status", "narration_scripts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_narration_scripts_status")
    op.drop_index("ix_narration_scripts_package_id")
    op.drop_table("narration_scripts")
