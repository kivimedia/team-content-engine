"""Add brand_profiles table.

Revision ID: 018_add_brand_profiles
Revises: 017_add_4week_planner_tables
Create Date: 2026-04-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "018_add_brand_profiles"
down_revision = "017_add_4week_planner_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brand_profiles",
        sa.Column("id", sa.Uuid(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("creator_profile_id", sa.Uuid(), sa.ForeignKey("creator_profiles.id"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("colors", postgresql.JSONB(), nullable=True),
        sa.Column("fonts", postgresql.JSONB(), nullable=True),
        sa.Column("logo_url", sa.String(1000), nullable=True),
        sa.Column("voice_config", postgresql.JSONB(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_profiles_creator", "brand_profiles", ["creator_profile_id"])


def downgrade() -> None:
    op.drop_index("ix_brand_profiles_creator")
    op.drop_table("brand_profiles")
