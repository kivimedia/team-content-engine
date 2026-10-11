"""One-time client invitations.

Revision ID: 061
Revises: 060
Create Date: 2026-10-11
"""

import sqlalchemy as sa

from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "standalone_invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "workspace_id", sa.Uuid(), sa.ForeignKey("standalone_workspaces.id"), nullable=False
        ),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("standalone_accounts.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_standalone_invites_workspace_id", "standalone_invites", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_standalone_invites_workspace_id", table_name="standalone_invites")
    op.drop_table("standalone_invites")
