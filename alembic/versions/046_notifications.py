"""Push notifications: one row per browser, one row per thing worth saying.

Additive only. Nothing sends until a VAPID key pair is configured and he has
granted permission, and with no subscribers the reconciler records the event and
moves on.

Revision ID: 046
Revises: 045
Create Date: 2026-09-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("endpoint_hash", sa.String(64), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(200), nullable=False),
        sa.Column("auth", sa.String(100), nullable=False),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("last_sent_at", sa.DateTime(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_notification_subscriptions_workspace_id",
        "notification_subscriptions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_notification_subscriptions_endpoint_hash",
        "notification_subscriptions",
        ["endpoint_hash"],
    )
    op.create_index(
        "ix_notification_subscriptions_status", "notification_subscriptions", ["status"]
    )
    op.create_unique_constraint(
        "uq_notification_endpoint",
        "notification_subscriptions",
        ["workspace_id", "endpoint_hash"],
    )

    op.create_table(
        "notification_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("path", sa.String(300), nullable=False, server_default="/today"),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("detail", sa.String(500), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_notification_events_workspace_id", "notification_events", ["workspace_id"]
    )
    op.create_index("ix_notification_events_kind", "notification_events", ["kind"])
    op.create_index("ix_notification_events_state", "notification_events", ["state"])
    # The reconciler runs every minute; without this it would re-send the same
    # "your script is ready" sixty times an hour.
    op.create_unique_constraint(
        "uq_notification_dedupe", "notification_events", ["workspace_id", "dedupe_key"]
    )


def downgrade() -> None:
    op.drop_table("notification_events")
    op.drop_table("notification_subscriptions")
