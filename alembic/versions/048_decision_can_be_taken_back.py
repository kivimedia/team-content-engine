"""A topic decision can be taken back without losing its note or its place.

Two small changes to topic_decisions:

- `decision` becomes nullable. Undoing a first approval, or restoring an idea
  that was never decided before it was put away, used to delete the whole row,
  and the note he wrote went with it. Now the row stays with decision NULL,
  which every reader already treats as undecided.
- `week_place` (JSON, nullable) keeps where the topic stood in this week's list
  when a decision took it off, so choosing it again puts it back at that place.

Revision ID: 048
Revises: 047
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("topic_decisions", "decision", existing_type=sa.String(20), nullable=True)
    op.add_column("topic_decisions", sa.Column("week_place", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("topic_decisions", "week_place")
    # Undecided rows cannot exist under NOT NULL; before 048 they had no row.
    op.execute("DELETE FROM topic_decisions WHERE decision IS NULL")
    op.alter_column("topic_decisions", "decision", existing_type=sa.String(20), nullable=False)
