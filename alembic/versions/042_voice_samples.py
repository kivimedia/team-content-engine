"""Voice samples: stretches of Ziv actually talking, mined from diarized call turns.

Additive only. Nothing reads this table until the corpus is built.

Revision ID: 042
Revises: 041
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_title", sa.String(500), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("first_turn_index", sa.Integer(), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("start_s", sa.Float(), nullable=True),
        sa.Column("end_s", sa.Float(), nullable=True),
        sa.Column("language", sa.String(20), nullable=False, server_default="en"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opening", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="teaching"),
        sa.Column("kind_reason", sa.String(300), nullable=True),
        sa.Column("keywords", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_voice_samples_workspace_id", "voice_samples", ["workspace_id"])
    op.create_index("ix_voice_samples_source_id", "voice_samples", ["source_id"])
    op.create_index("ix_voice_samples_occurred_at", "voice_samples", ["occurred_at"])
    op.create_index("ix_voice_samples_language", "voice_samples", ["language"])
    op.create_index("ix_voice_samples_word_count", "voice_samples", ["word_count"])
    op.create_index("ix_voice_samples_kind", "voice_samples", ["kind"])
    # One row per run, so rebuilding the corpus is idempotent.
    op.create_unique_constraint(
        "uq_voice_samples_source_turn", "voice_samples", ["source_id", "first_turn_index"]
    )


def downgrade() -> None:
    op.drop_table("voice_samples")
