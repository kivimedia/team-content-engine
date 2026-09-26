"""Post copy and publishing state for each edited video on each platform.

26-Sep: "I want tce to be able to do the full publishing and to show me the post in
the library". One row per (edited video, platform). Additive only.

Revision ID: 052
Revises: 051
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_publications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recording_uploads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("copy", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        sa.Column("external_id", sa.String(300), nullable=True),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("upload_id", "platform", name="uq_video_publication"),
    )
    op.create_index("ix_video_publications_workspace_id", "video_publications", ["workspace_id"])
    op.create_index("ix_video_publications_upload_id", "video_publications", ["upload_id"])


def downgrade() -> None:
    op.drop_index("ix_video_publications_upload_id", table_name="video_publications")
    op.drop_index("ix_video_publications_workspace_id", table_name="video_publications")
    op.drop_table("video_publications")
