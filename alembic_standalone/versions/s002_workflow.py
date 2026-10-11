"""Private idea, script, recording and conversation records.

Revision ID: s002
Revises: s001
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "s002"
down_revision = "s001"
branch_labels = None
depends_on = None
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def common():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "workspace_id", sa.Uuid(), sa.ForeignKey("standalone_workspaces.id"), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "standalone_source_items",
        *common(),
        sa.Column("lane_index", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(300), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(1000)),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("workspace_id", "lane_index", "external_id", "sha256"),
    )
    op.create_table(
        "standalone_ideas",
        *common(),
        sa.Column("source_item_id", sa.Uuid(), sa.ForeignKey("standalone_source_items.id")),
        sa.Column("lane_index", sa.Integer()),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("why_now", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(30), nullable=False, server_default="inbox"),
        sa.Column("week_start", sa.String(10)),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "standalone_script_versions",
        *common(),
        sa.Column("idea_id", sa.Uuid(), sa.ForeignKey("standalone_ideas.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("script", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("origin", sa.String(24), nullable=False, server_default="generated"),
        sa.UniqueConstraint("workspace_id", "idea_id", "version"),
    )
    op.create_table(
        "standalone_recordings",
        *common(),
        sa.Column("idea_id", sa.Uuid(), sa.ForeignKey("standalone_ideas.id"), nullable=False),
        sa.Column("script_version", sa.Integer()),
        sa.Column("original_key", sa.String(500), nullable=False),
        sa.Column("edited_key", sa.String(500)),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="uploaded"),
        sa.Column("qc", JSON),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "standalone_chat_messages",
        *common(),
        sa.Column("context", sa.String(30), nullable=False),
        sa.Column("context_id", sa.Uuid()),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
    )
    op.create_table(
        "standalone_jobs",
        *common(),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("phase", sa.String(160), nullable=False, server_default="Queued"),
        sa.Column("input", JSON, nullable=False),
        sa.Column("result", JSON),
        sa.Column("error_code", sa.String(80)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_hash", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "standalone_live_sessions",
        *common(),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("standalone_accounts.id"), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("context_id", sa.Uuid()),
        sa.Column("provider_session_id", sa.String(150), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="started"),
    )
    op.create_table(
        "standalone_renders",
        *common(),
        sa.Column(
            "recording_id", sa.Uuid(), sa.ForeignKey("standalone_recordings.id"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("start_s", sa.Integer(), nullable=False),
        sa.Column("end_s", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("workspace_id", "recording_id", "version"),
    )
    for name in (
        "standalone_source_items",
        "standalone_ideas",
        "standalone_script_versions",
        "standalone_recordings",
        "standalone_chat_messages",
        "standalone_jobs",
        "standalone_live_sessions",
        "standalone_renders",
    ):
        op.create_index(f"ix_{name}_workspace_id", name, ["workspace_id"])


def downgrade() -> None:
    for name in (
        "standalone_renders",
        "standalone_live_sessions",
        "standalone_jobs",
        "standalone_chat_messages",
        "standalone_recordings",
        "standalone_script_versions",
        "standalone_ideas",
        "standalone_source_items",
    ):
        op.drop_index(f"ix_{name}_workspace_id", table_name=name)
        op.drop_table(name)
