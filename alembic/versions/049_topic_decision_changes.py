"""Each write to a topic's decision gets its own row and its own id.

`topic_decisions` keeps only where a topic stands now, one row per topic, so every
decision on a topic answered with the same id. The voice call undid decisions by
that id and reached whichever write came last: "undo the approval" took back a
later "save for later" instead and put the topic INTO the week.

Additive only: one new table. A row is written when a decision write changed
something (the decision, or the week with it); its id is the change id the call
undoes by, and the rows after it say whether anyone decided again since.

Revision ID: 049
Revises: 048
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_decision_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topic_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("before", sa.String(20), nullable=True),
        sa.Column("after", sa.String(20), nullable=True),
        sa.Column("decided_by", sa.String(100), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("week", postgresql.JSONB(), nullable=True),
        sa.Column("undone_at", sa.DateTime(), nullable=True),
        sa.Column("undone_by", sa.String(100), nullable=True),
        sa.UniqueConstraint(
            "workspace_id", "candidate_id", "seq", name="uq_topic_decision_change_seq"
        ),
    )
    op.create_index(
        "ix_topic_decision_changes_workspace_id", "topic_decision_changes", ["workspace_id"]
    )
    op.create_index(
        "ix_topic_decision_changes_candidate_id", "topic_decision_changes", ["candidate_id"]
    )
    op.create_index(
        "ix_topic_decision_changes_decided_at", "topic_decision_changes", ["decided_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_topic_decision_changes_decided_at", table_name="topic_decision_changes")
    op.drop_index("ix_topic_decision_changes_candidate_id", table_name="topic_decision_changes")
    op.drop_index("ix_topic_decision_changes_workspace_id", table_name="topic_decision_changes")
    op.drop_table("topic_decision_changes")
