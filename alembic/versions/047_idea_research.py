"""Research on one idea, run in the background for the voice agent.

Additive only: one new table. Nothing reads it until research is asked for.

Revision ID: 047
Revises: 046
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idea_research",
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
        sa.Column("state", sa.String(20), nullable=False, server_default="running"),
        sa.Column("requested_by", sa.String(100), nullable=True),
        sa.Column("query", sa.String(500), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("web", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("web_status", sa.String(20), nullable=False, server_default="skipped"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_idea_research_workspace_id", "idea_research", ["workspace_id"])
    op.create_index("ix_idea_research_candidate_id", "idea_research", ["candidate_id"])
    op.create_index("ix_idea_research_state", "idea_research", ["state"])


def downgrade() -> None:
    op.drop_index("ix_idea_research_state", table_name="idea_research")
    op.drop_index("ix_idea_research_candidate_id", table_name="idea_research")
    op.drop_index("ix_idea_research_workspace_id", table_name="idea_research")
    op.drop_table("idea_research")
