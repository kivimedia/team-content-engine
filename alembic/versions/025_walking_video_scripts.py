"""Create walking_video_scripts table for Video Studio walking-monologue flow.

Revision ID: 025
Revises: 024
Create Date: 2026-04-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "walking_video_scripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("title", sa.String(500), server_default="Untitled"),
        sa.Column("hook", sa.Text, nullable=True),
        sa.Column("hook_formula", sa.String(5), nullable=True),
        sa.Column("full_script", sa.Text, nullable=True),
        sa.Column("shot_notes", postgresql.JSONB, nullable=True),
        sa.Column("cutsense_prompt", sa.Text, nullable=True),
        sa.Column("format_label", sa.String(50), server_default="walking_monologue"),
        sa.Column("word_count", sa.Integer, nullable=True),
        sa.Column("estimated_duration_seconds", sa.Integer, nullable=True),
        sa.Column("duration_target_seconds", sa.Integer, nullable=True),
        sa.Column("topic", sa.Text, nullable=True),
        sa.Column("thesis", sa.Text, nullable=True),
        sa.Column("target_audience", sa.Text, nullable=True),
        sa.Column("niche", sa.String(50), server_default="general"),
        sa.Column(
            "creator_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("creator_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("seo_description", sa.Text, nullable=True),
        sa.Column("tags", postgresql.JSONB, nullable=True),
        sa.Column("repurpose", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(30), server_default="draft"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("video_file_path", sa.Text, nullable=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "idx_walking_video_scripts_status",
        "walking_video_scripts",
        ["status"],
    )
    op.create_index(
        "idx_walking_video_scripts_created_at",
        "walking_video_scripts",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_walking_video_scripts_created_at", table_name="walking_video_scripts")
    op.drop_index("idx_walking_video_scripts_status", table_name="walking_video_scripts")
    op.drop_table("walking_video_scripts")
