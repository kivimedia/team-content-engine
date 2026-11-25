"""Continue recording: a stopped take sent back to be finished, then joined.

Revision ID: 060
Revises: 059
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("recording_uploads", sa.Column(
        "continuation", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
        nullable=True,
    ))
    op.add_column("recording_sessions", sa.Column(
        "continues_upload_id", postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.create_index(
        "ix_recording_sessions_continues_upload_id", "recording_sessions", ["continues_upload_id"]
    )


def downgrade():
    op.drop_index("ix_recording_sessions_continues_upload_id", table_name="recording_sessions")
    op.drop_column("recording_sessions", "continues_upload_id")
    op.drop_column("recording_uploads", "continuation")
