"""Add research_brief_id FK to post_packages.

Revision ID: 016
Revises: 015
Create Date: 2026-03-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "post_packages",
        sa.Column("research_brief_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_post_packages_research_brief_id",
        "post_packages",
        "research_briefs",
        ["research_brief_id"],
        ["id"],
    )
    op.create_index(
        "ix_post_packages_research_brief_id",
        "post_packages",
        ["research_brief_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_post_packages_research_brief_id", table_name="post_packages")
    op.drop_constraint("fk_post_packages_research_brief_id", "post_packages", type_="foreignkey")
    op.drop_column("post_packages", "research_brief_id")
