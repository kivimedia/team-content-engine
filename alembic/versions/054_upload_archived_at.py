"""Archive a recording: out of the Library list, kept on the server.

27-Sep: "need to be able to archive" in the Library. Nullable timestamp on
recording_uploads; null means shown. Additive only.

Revision ID: 054
Revises: 053
Create Date: 2026-09-27
"""

import sqlalchemy as sa

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recording_uploads", sa.Column("archived_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("recording_uploads", "archived_at")
