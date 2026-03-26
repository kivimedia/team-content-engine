"""Add DM fulfillment, system versions, and audit log tables.

Revision ID: 003
Revises: 002
Create Date: 2026-03-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dm_fulfillment_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=True),
        sa.Column("cta_keyword", sa.String(100), nullable=False),
        sa.Column("promised_asset", sa.String(500), nullable=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("commenter_id", sa.String(200), nullable=True),
        sa.Column("comment_text", sa.Text(), nullable=True),
        sa.Column("comment_timestamp", sa.DateTime(), nullable=True),
        sa.Column("dm_sent", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("dm_sent_at", sa.DateTime(), nullable=True),
        sa.Column("dm_content", sa.Text(), nullable=True),
        sa.Column("delivery_method", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("whatsapp_joined", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("consent_given", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("opted_out", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["package_id"], ["post_packages.id"]),
    )

    op.create_table(
        "system_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("corpus_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("template_library_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("house_voice_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("scoring_config_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("change_type", sa.String(50), nullable=False),
        sa.Column("change_description", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(100), nullable=True),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("session_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("system_versions")
    op.drop_table("dm_fulfillment_logs")
