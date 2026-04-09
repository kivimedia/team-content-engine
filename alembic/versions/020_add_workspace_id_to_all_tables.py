"""Add workspace_id column to all tables for multi-tenancy.

Revision ID: 020
Revises: 019
Create Date: 2026-04-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None

# All tables that inherit from Base and need workspace_id
TABLES = [
    "audit_logs",
    "brand_profiles",
    "content_calendar",
    "cost_events",
    "creator_profiles",
    "dm_fulfillment_logs",
    "founder_voice_profiles",
    "guide_options",
    "image_assets",
    "learning_events",
    "monthly_plans",
    "narration_scripts",
    "notifications",
    "operator_feedback",
    "pattern_templates",
    "pipeline_runs",
    "post_examples",
    "post_packages",
    "post_stack",
    "prompt_versions",
    "qa_scorecards",
    "render_queue",
    "research_briefs",
    "slot_options",
    "source_documents",
    "story_briefs",
    "system_versions",
    "trend_briefs",
    "video_assets",
    "video_lead_scripts",
    "weekly_guides",
    "weekly_plans",
]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])

    # Also add external_run_id to pipeline_runs for kmboards bridge
    op.add_column(
        "pipeline_runs",
        sa.Column("external_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_pipeline_runs_external_run_id", "pipeline_runs", ["external_run_id"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_external_run_id", table_name="pipeline_runs")
    op.drop_column("pipeline_runs", "external_run_id")

    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_column(table, "workspace_id")
