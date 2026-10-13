"""Encrypted resumable onboarding and PDF coverage receipts.

Revision ID: s006
Revises: s005
"""

import sqlalchemy as sa

from alembic import op

revision = "s006"
down_revision = "s005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("standalone_materials", sa.Column("page_count", sa.Integer()))
    op.add_column("standalone_materials", sa.Column("readable_page_count", sa.Integer()))
    op.create_table(
        "standalone_onboarding_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "workspace_id", sa.Uuid(), sa.ForeignKey("standalone_workspaces.id"),
            nullable=False, unique=True,
        ),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("standalone_onboarding_drafts")
    op.drop_column("standalone_materials", "readable_page_count")
    op.drop_column("standalone_materials", "page_count")
