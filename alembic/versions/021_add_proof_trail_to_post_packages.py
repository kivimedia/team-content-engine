"""Add proof_trail and proof_status columns to post_packages.

Revision ID: 021
Revises: 020
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("post_packages", sa.Column("proof_trail", postgresql.JSONB(), nullable=True))
    op.add_column("post_packages", sa.Column("proof_status", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("post_packages", "proof_status")
    op.drop_column("post_packages", "proof_trail")
