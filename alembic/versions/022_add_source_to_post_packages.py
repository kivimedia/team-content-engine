"""Add source column to post_packages for tracking origin (pipeline/topic/copy).

Revision ID: 022
Revises: 021
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("post_packages", sa.Column("source", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("post_packages", "source")
