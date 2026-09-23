"""A decision change row also carries the topic status it changed.

Restoring an idea the weekly selection run superseded, or one news discovery
marked stale, brings it back from `withdrawn` without any 'away' decision to
take back. The restore wrote no row, so it had no change id: the call could not
undo it, and a plain "undo" took back an earlier, unrelated change instead.

`candidate_status` (JSON, nullable) holds {"before", "after"} for such a write,
so its undo can set the topic back to withdrawn. Additive only; rows without it
read exactly as before.

Revision ID: 050
Revises: 049
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "topic_decision_changes",
        sa.Column("candidate_status", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("topic_decision_changes", "candidate_status")
