"""Durable news handoff and bounded editorial recovery.

Revision ID: 059
Revises: 058
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("news_items", sa.Column(
        "editorial_meta", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
        nullable=True,
    ))


def downgrade():
    op.drop_column("news_items", "editorial_meta")
