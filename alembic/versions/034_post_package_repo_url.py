"""Add repo_url column to post_packages.

Lets a Library card link to the actual GitHub repo even when no TrackedRepo
row exists (e.g. user pasted a raw URL into Start from Repo).

Revision ID: 034
Revises: 033
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa


revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "post_packages",
        sa.Column("repo_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("post_packages", "repo_url")
