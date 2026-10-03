"""Agent talks: a filmed voice call with an agent becomes a library video (3-Oct).

Contract C4: the call's page records a selfie video of the conversation (his camera,
his microphone and the agent's voice) and sends it in pieces while the call runs. When
the call ends the pieces are joined into one video, which lands in the library as an
"Agent talk" and edits itself like a finished walk.

- New table `agent_talks`: one talk being recorded. Who it was with (`agent`), the
  call (`call_id`), when the recording started (`started_at`), the recorder's type
  (`mime_type`, `file_extension`), `status` recording | finished | failed with a
  sentence (`status_detail`), the last piece's arrival (`last_chunk_at`), how the call
  ended (`ended_at`, `duration_ms`), what the join found (`join_meta`) and the video it
  made (`upload_id`, FK to recording_uploads, SET NULL). A unique key on the workspace,
  agent, call and start makes a create sent twice the same talk.
- `recording_uploads.source` (String 30, nullable): NULL for a walk, "agent_talk" for
  a filmed call. `agent_name` (String 80): the agent as the library names it.
  `call_transcript` (JSON): the call's own lines, who said each one and when, which the
  edit reads to keep the agent's lines.

The pieces themselves are files beside each other on disk, not rows. Additive only.

Revision ID: 057
Revises: 056
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None

# JSONB on the server, plain JSON where the tests build the tables (SQLite).
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("recording_uploads", sa.Column("source", sa.String(30), nullable=True))
    op.add_column("recording_uploads", sa.Column("agent_name", sa.String(80), nullable=True))
    op.add_column("recording_uploads", sa.Column("call_transcript", JSON, nullable=True))

    op.create_table(
        "agent_talks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("agent", sa.String(80), nullable=False),
        sa.Column("call_id", sa.String(200), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("file_extension", sa.String(12), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="recording"),
        sa.Column("status_detail", sa.String(500), nullable=True),
        sa.Column("last_chunk_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("join_meta", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "upload_id",
            sa.Uuid(),
            sa.ForeignKey("recording_uploads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "workspace_id", "agent", "call_id", "started_at", name="uq_agent_talk_identity"
        ),
    )
    op.create_index("ix_agent_talks_workspace_id", "agent_talks", ["workspace_id"])
    op.create_index("ix_agent_talks_call_id", "agent_talks", ["call_id"])
    op.create_index("ix_agent_talks_status", "agent_talks", ["status"])
    op.create_index("ix_agent_talks_upload_id", "agent_talks", ["upload_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_talks_upload_id", table_name="agent_talks")
    op.drop_index("ix_agent_talks_status", table_name="agent_talks")
    op.drop_index("ix_agent_talks_call_id", table_name="agent_talks")
    op.drop_index("ix_agent_talks_workspace_id", table_name="agent_talks")
    op.drop_table("agent_talks")
    op.drop_column("recording_uploads", "call_transcript")
    op.drop_column("recording_uploads", "agent_name")
    op.drop_column("recording_uploads", "source")
