"""Mobile recording sessions, clips, chunks and canonical upload relation.

Revision ID: 040
Revises: 039
Create Date: 2026-09-20
"""

import sqlalchemy as sa

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None

TABLES = ("recording_sessions", "recording_clips", "recording_chunks")


def upgrade() -> None:
    from tce.db.base import Base
    from tce.models import recording_session  # noqa: F401

    md = Base.metadata
    bind = op.get_bind()
    for name in TABLES:
        md.tables[name].create(bind=bind, checkfirst=True)
    op.add_column("recording_uploads", sa.Column("recording_session_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_recording_upload_session", "recording_uploads", "recording_sessions",
        ["recording_session_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "ix_recording_uploads_recording_session_id", "recording_uploads", ["recording_session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_recording_uploads_recording_session_id", table_name="recording_uploads")
    op.drop_constraint("fk_recording_upload_session", "recording_uploads", type_="foreignkey")
    op.drop_column("recording_uploads", "recording_session_id")
    from tce.db.base import Base
    from tce.models import recording_session  # noqa: F401

    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind=op.get_bind(), checkfirst=True)
