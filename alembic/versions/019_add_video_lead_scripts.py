"""Add video_lead_scripts table.

Revision ID: 019
Revises: 018
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_lead_scripts",
        sa.Column("id", sa.Uuid(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(500), nullable=False, server_default="Untitled"),
        sa.Column("title_pattern", sa.String(50), nullable=True),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("full_script", sa.Text(), nullable=True),
        sa.Column("sections", postgresql.JSONB(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("estimated_duration_minutes", sa.Float(), nullable=True),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("key_takeaway", sa.Text(), nullable=True),
        sa.Column("niche", sa.String(50), nullable=False, server_default="coaching"),
        sa.Column("seo_description", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("blog_repurpose_outline", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("pipeline_run_id", sa.Uuid(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("thesis", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("video_lead_scripts")
