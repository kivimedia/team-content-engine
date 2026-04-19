"""Create weekly_walking_recordings table for the one-button weekly video pipeline.

One row per week: stores the single long recording, word-level transcript, alignment map,
and CutSense job IDs for all 5 per-clip edits. Status machine:
  uploaded -> transcribing -> aligning -> splitting -> editing -> done | failed

Revision ID: 031
Revises: 030
Create Date: 2026-04-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_walking_recordings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column(
            "weekly_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("weekly_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("long_video_path", sa.Text, nullable=True),
        sa.Column("status", sa.String(30), server_default="uploaded", nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("transcript_json", postgresql.JSONB, nullable=True),
        sa.Column("alignment_json", postgresql.JSONB, nullable=True),
        sa.Column("cutsense_jobs", postgresql.JSONB, nullable=True),
        sa.Column("transcribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aligned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("split_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("editing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "idx_weekly_walking_recordings_weekly_plan_id",
        "weekly_walking_recordings",
        ["weekly_plan_id"],
    )
    op.create_index(
        "idx_weekly_walking_recordings_status",
        "weekly_walking_recordings",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("idx_weekly_walking_recordings_status", table_name="weekly_walking_recordings")
    op.drop_index("idx_weekly_walking_recordings_weekly_plan_id", table_name="weekly_walking_recordings")
    op.drop_table("weekly_walking_recordings")
