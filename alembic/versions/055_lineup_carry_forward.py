"""A new week keeps the topics he chose and has not recorded.

28-Sep: "tce is showing 0 scripts ready despite the fact that I has around 8
topics chosen for this week and didnt film them yet". The week key is Monday in
Israel time; at 00:00 on Monday the new week's list started empty and nothing
brought the unrecorded topics over. The first read of the current week now
copies them from the week before, once:

- `carried_at` (timestamp, nullable): when that copy ran. Null means it has not
  run yet, so a week created empty before this migration is still filled on its
  first read after it.
- `carried_from_lineup_id` (uuid, nullable): the week it copied from, or null
  when there was none.

Additive only.

Revision ID: 055
Revises: 054
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "weekly_lineups",
        sa.Column("carried_from_lineup_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("weekly_lineups", sa.Column("carried_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("weekly_lineups", "carried_at")
    op.drop_column("weekly_lineups", "carried_from_lineup_id")
