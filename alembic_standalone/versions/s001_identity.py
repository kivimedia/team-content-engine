"""Standalone account, tenant and configuration foundation.

Revision ID: s001
Revises: none
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "s001"
down_revision = None
branch_labels = None
depends_on = None
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def common(workspace_nullable: bool = False):
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("workspace_id", sa.Uuid(), nullable=workspace_nullable),
    ]


def upgrade() -> None:
    op.create_table(
        "standalone_accounts",
        *common(True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "standalone_workspaces",
        *common(True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("timezone", sa.String(100), nullable=False, server_default="UTC"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "standalone_memberships",
        *common(),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("standalone_accounts.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="owner"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["workspace_id"], ["standalone_workspaces.id"]),
        sa.UniqueConstraint("account_id", "workspace_id"),
    )
    op.create_table(
        "standalone_sessions",
        *common(),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("standalone_accounts.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id"], ["standalone_workspaces.id"]),
    )
    op.create_table(
        "standalone_api_tokens",
        *common(),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("standalone_accounts.id"), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", JSON, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id"], ["standalone_workspaces.id"]),
    )
    op.create_table(
        "standalone_config_revisions",
        *common(),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", JSON, nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("standalone_accounts.id"), nullable=False),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["standalone_workspaces.id"]),
        sa.UniqueConstraint("workspace_id", "revision"),
    )
    op.create_table(
        "standalone_materials",
        *common(),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("lane_index", sa.Integer()),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text()),
        sa.ForeignKeyConstraint(["workspace_id"], ["standalone_workspaces.id"]),
        sa.UniqueConstraint("workspace_id", "kind", "sha256"),
    )
    op.create_table(
        "standalone_secrets",
        *common(),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("fingerprint", sa.String(16), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id"], ["standalone_workspaces.id"]),
        sa.UniqueConstraint("workspace_id", "kind"),
    )
    op.create_table(
        "standalone_deliveries",
        *common(),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("standalone_accounts.id"), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("render_id", sa.Uuid()),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_receipt", sa.String(250)),
        sa.Column("error_code", sa.String(80)),
        sa.ForeignKeyConstraint(["workspace_id"], ["standalone_workspaces.id"]),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
    )
    for name in (
        "standalone_accounts",
        "standalone_workspaces",
        "standalone_memberships",
        "standalone_sessions",
        "standalone_api_tokens",
        "standalone_config_revisions",
        "standalone_materials",
        "standalone_secrets",
        "standalone_deliveries",
    ):
        op.create_index(f"ix_{name}_workspace_id", name, ["workspace_id"])


def downgrade() -> None:
    for name in (
        "standalone_deliveries",
        "standalone_secrets",
        "standalone_materials",
        "standalone_config_revisions",
        "standalone_api_tokens",
        "standalone_sessions",
        "standalone_memberships",
        "standalone_workspaces",
        "standalone_accounts",
    ):
        op.drop_index(f"ix_{name}_workspace_id", table_name=name)
        op.drop_table(name)
