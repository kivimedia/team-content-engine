"""Competitor velocity tracking — channel handles + post snapshot table.

Adds:
- creator_profiles.youtube_channel_id (nullable) so we can poll a creator
  when we know their channel; existing rows just stay null and skip polling.
- competitor_post_snapshots table — one row per (post_id, captured_at) pair.
  CompetitorVelocityService polls every 6h, computes views_per_hour vs the
  prior snapshot of the same post, and feeds high-acceleration posts back
  to trend_scout as a high-priority viral signal (peer acceleration is the
  cleanest leading indicator we can measure).

Revision ID: 036
Revises: 035
Create Date: 2026-05-05
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "creator_profiles",
        sa.Column("youtube_channel_id", sa.String(length=64), nullable=True),
    )

    op.create_table(
        "competitor_post_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "creator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("creator_profiles.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("post_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("post_url", sa.String(length=500), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("views", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("likes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("comments", sa.BigInteger(), nullable=False, server_default="0"),
        # Pre-computed at insert vs the most recent prior snapshot of the same
        # post, so trend_scout reads can sort cheaply without joining back.
        sa.Column("delta_views", sa.BigInteger(), nullable=True),
        sa.Column("delta_hours", sa.Float(), nullable=True),
        sa.Column("delta_views_per_hour", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_competitor_snapshots_captured_at",
        "competitor_post_snapshots",
        ["captured_at"],
    )
    op.create_index(
        "ix_competitor_snapshots_post_captured",
        "competitor_post_snapshots",
        ["post_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_competitor_snapshots_post_captured",
        table_name="competitor_post_snapshots",
    )
    op.drop_index(
        "ix_competitor_snapshots_captured_at",
        table_name="competitor_post_snapshots",
    )
    op.drop_table("competitor_post_snapshots")
    op.drop_column("creator_profiles", "youtube_channel_id")
