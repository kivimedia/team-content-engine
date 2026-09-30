"""Talk to the editor: which render he is watching.

30-Sep: Ziv gives all his notes on an edited video in one sitting, paused on the
second he means. A note has to point at the file he is watching, and nothing said
which render made that file: `_compute_plan` rewrites edit_plan.keep even when it
does not render (a blocked plan), and the video address carried no version.

- `recording_uploads.render_ref` (String 24, nullable): a short id of the last
  successful render, put on the player's video address.
- `recording_uploads.rendered_keep` (JSON, nullable): that render's keep on the
  file's own 30 fps frame clock.

Both are written only when a render succeeds. Additive only.

Revision ID: 056
Revises: 055
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None

# JSONB on the server, plain JSON where the tests build the tables (SQLite).
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("recording_uploads", sa.Column("render_ref", sa.String(24), nullable=True))
    op.add_column("recording_uploads", sa.Column("rendered_keep", JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("recording_uploads", "rendered_keep")
    op.drop_column("recording_uploads", "render_ref")
