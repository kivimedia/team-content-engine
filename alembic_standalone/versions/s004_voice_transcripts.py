"""Store explicitly requested transcripts for voice samples.

Revision ID: s004
Revises: s003
Create Date: 2026-10-11
"""

import sqlalchemy as sa

from alembic import op

revision = "s004"
down_revision = "s003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("standalone_materials", sa.Column("transcript_text", sa.Text()))


def downgrade() -> None:
    op.drop_column("standalone_materials", "transcript_text")
