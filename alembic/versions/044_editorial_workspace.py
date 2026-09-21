"""Editorial workspace: briefs, weekly lineups, conversation, change sets, editing requests.

Additive only. Nothing existing is altered and nothing reads these tables until the
`editorial_workspace_v2` flag is on, so this migration is safe to apply ahead of
the UI that uses it.

Ordered after 043 (the news lane) only because both were written the same day and
Alembic needs one line, not two heads. The two are independent: nothing here reads
a news column and nothing there reads a lineup.

Brief version 1 is NOT backfilled here. It is derived from the candidate's own
columns the first time a topic room is opened (and can be materialised early with
`scripts/backfill_candidate_briefs.py`), so this migration never rewrites content.

Revision ID: 044
Revises: 043
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def _base_columns() -> list[sa.Column]:
    """id / workspace_id / timestamps, the shape every private editorial table has."""
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    # ---------------------------------------------------------------- briefs
    op.create_table(
        "candidate_brief_versions",
        *_base_columns(),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topic_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parent_version", sa.Integer(), nullable=True),
        sa.Column("brief", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("origin", sa.String(20), nullable=False, server_default="seed"),
        sa.Column("change_set_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_candidate_brief_versions_workspace_id", "candidate_brief_versions", ["workspace_id"]
    )
    op.create_index(
        "ix_candidate_brief_versions_candidate_id", "candidate_brief_versions", ["candidate_id"]
    )
    op.create_index(
        "ix_candidate_brief_versions_change_set_id", "candidate_brief_versions", ["change_set_id"]
    )
    op.create_unique_constraint(
        "uq_candidate_brief_version",
        "candidate_brief_versions",
        ["workspace_id", "candidate_id", "version"],
    )

    # ------------------------------------------------------- topic decisions
    op.create_table(
        "topic_decisions",
        *_base_columns(),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topic_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(100), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("previous_decision", sa.String(20), nullable=True),
    )
    op.create_index("ix_topic_decisions_workspace_id", "topic_decisions", ["workspace_id"])
    op.create_index("ix_topic_decisions_candidate_id", "topic_decisions", ["candidate_id"])
    op.create_index("ix_topic_decisions_decision", "topic_decisions", ["decision"])
    op.create_unique_constraint(
        "uq_topic_decision", "topic_decisions", ["workspace_id", "candidate_id"]
    )

    # --------------------------------------------------------------- lineups
    op.create_table(
        "weekly_lineups",
        *_base_columns(),
        sa.Column("week_start", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("primary_slots", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(100), nullable=True),
    )
    op.create_index("ix_weekly_lineups_workspace_id", "weekly_lineups", ["workspace_id"])
    op.create_index("ix_weekly_lineups_week_start", "weekly_lineups", ["week_start"])
    op.create_unique_constraint(
        "uq_weekly_lineup_week", "weekly_lineups", ["workspace_id", "week_start"]
    )

    op.create_table(
        "weekly_lineup_items",
        *_base_columns(),
        sa.Column(
            "lineup_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("weekly_lineups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topic_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "packet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recording_packets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("slot", sa.String(20), nullable=False, server_default="primary"),
        sa.Column("lane", sa.String(20), nullable=False, server_default="other"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("added_by", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_weekly_lineup_items_workspace_id", "weekly_lineup_items", ["workspace_id"]
    )
    op.create_index("ix_weekly_lineup_items_lineup_id", "weekly_lineup_items", ["lineup_id"])
    op.create_index(
        "ix_weekly_lineup_items_candidate_id", "weekly_lineup_items", ["candidate_id"]
    )
    op.create_index("ix_weekly_lineup_items_slot", "weekly_lineup_items", ["slot"])
    op.create_unique_constraint(
        "uq_weekly_lineup_item",
        "weekly_lineup_items",
        ["workspace_id", "lineup_id", "candidate_id"],
    )

    # ---------------------------------------------------------- conversation
    op.create_table(
        "editorial_threads",
        *_base_columns(),
        sa.Column("context_type", sa.String(20), nullable=False),
        sa.Column("context_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_label", sa.String(300), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("last_mode", sa.String(20), nullable=False, server_default="discuss"),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_editorial_threads_workspace_id", "editorial_threads", ["workspace_id"])
    op.create_index("ix_editorial_threads_context_type", "editorial_threads", ["context_type"])
    op.create_index("ix_editorial_threads_context_id", "editorial_threads", ["context_id"])
    op.create_index(
        "ix_editorial_threads_last_message_at", "editorial_threads", ["last_message_at"]
    )
    op.create_unique_constraint(
        "uq_editorial_thread_context",
        "editorial_threads",
        ["workspace_id", "context_type", "context_id"],
    )

    op.create_table(
        "editorial_messages",
        *_base_columns(),
        sa.Column(
            "thread_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("editorial_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="discuss"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="complete"),
        sa.Column("status_detail", sa.String(500), nullable=True),
        sa.Column("change_set_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("citations", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("model_receipt", postgresql.JSONB(), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_editorial_messages_workspace_id", "editorial_messages", ["workspace_id"])
    op.create_index("ix_editorial_messages_thread_id", "editorial_messages", ["thread_id"])
    op.create_index("ix_editorial_messages_status", "editorial_messages", ["status"])
    op.create_index("ix_editorial_messages_job_id", "editorial_messages", ["job_id"])
    op.create_index(
        "ix_editorial_messages_change_set_id", "editorial_messages", ["change_set_id"]
    )

    # ----------------------------------------------------------- change sets
    op.create_table(
        "editorial_change_sets",
        *_base_columns(),
        sa.Column(
            "thread_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("editorial_threads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("validation", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("origin", sa.String(20), nullable=False, server_default="conversation"),
        sa.Column("applied_version", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.String(100), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_editorial_change_sets_workspace_id", "editorial_change_sets", ["workspace_id"]
    )
    op.create_index("ix_editorial_change_sets_thread_id", "editorial_change_sets", ["thread_id"])
    op.create_index(
        "ix_editorial_change_sets_target_type", "editorial_change_sets", ["target_type"]
    )
    op.create_index("ix_editorial_change_sets_target_id", "editorial_change_sets", ["target_id"])
    op.create_index("ix_editorial_change_sets_state", "editorial_change_sets", ["state"])
    op.create_unique_constraint(
        "uq_editorial_change_set_idem",
        "editorial_change_sets",
        ["workspace_id", "idempotency_key"],
    )

    op.create_table(
        "editorial_change_operations",
        *_base_columns(),
        sa.Column(
            "change_set_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("editorial_change_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("op", sa.String(30), nullable=False),
        sa.Column("field", sa.String(120), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("depends_on", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.create_index(
        "ix_editorial_change_operations_workspace_id",
        "editorial_change_operations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_editorial_change_operations_change_set_id",
        "editorial_change_operations",
        ["change_set_id"],
    )
    op.create_unique_constraint(
        "uq_editorial_change_op_seq",
        "editorial_change_operations",
        ["workspace_id", "change_set_id", "seq"],
    )

    # ------------------------------------------------------- editing requests
    op.create_table(
        "editing_requests",
        *_base_columns(),
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recording_uploads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topic_candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("packet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("packet_version", sa.Integer(), nullable=True),
        sa.Column("scope", sa.String(20), nullable=False, server_default="whole"),
        sa.Column("start_s", sa.Float(), nullable=True),
        sa.Column("end_s", sa.Float(), nullable=True),
        sa.Column("section_ref", sa.String(120), nullable=True),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="open"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_editing_requests_workspace_id", "editing_requests", ["workspace_id"])
    op.create_index("ix_editing_requests_upload_id", "editing_requests", ["upload_id"])
    op.create_index("ix_editing_requests_candidate_id", "editing_requests", ["candidate_id"])
    op.create_index("ix_editing_requests_state", "editing_requests", ["state"])


def downgrade() -> None:
    op.drop_table("editing_requests")
    op.drop_table("editorial_change_operations")
    op.drop_table("editorial_change_sets")
    op.drop_table("editorial_messages")
    op.drop_table("editorial_threads")
    op.drop_table("weekly_lineup_items")
    op.drop_table("weekly_lineups")
    op.drop_table("topic_decisions")
    op.drop_table("candidate_brief_versions")
