"""Talk to the editor: which render he is watching, and the sitting he gives notes in.

30-Sep: Ziv gives all his notes on an edited video in one sitting, paused on the
second he means, and one re-render comes at the end.

Part 1, which render made the file he is watching. Nothing said so before:
`_compute_plan` rewrites edit_plan.keep even when it does not render (a blocked
plan), and the video address carried no version.

- `recording_uploads.render_ref` (String 24, nullable): a short id of the last
  successful render, put on the player's video address.
- `recording_uploads.rendered_keep` (JSON, nullable): that render's keep on the
  file's own 30 fps frame clock.

Both are written only when a render succeeds.

Part 2, the sitting.

- New table `edit_sessions`: one sitting with one video. `state` open | thinking |
  rendering | done | needs_you | failed | closed, the render being watched
  (`render_ref`, `keep_snapshot`), the sheet's heartbeat (`last_seen`), what the
  batch changed (`before`), its job key, read-back and result. A partial unique
  index (`uq_edit_sessions_live_upload`) keeps one live sitting (open, thinking,
  rendering) per video, so two opens at once cannot each insert one.
- `editing_requests.session_id` (nullable FK to edit_sessions, indexed): the
  sitting a note was given in. `source_s` (Float): the paused second on the
  recording's clock. `understood` (Text): the editor's one-line reading of it.
- Scope `moment` and states `listening` and `held` need no DDL: scope and state
  are plain String(20) columns.

The editing_requests change runs in batch mode so the same file applies where the
tests build the tables (SQLite, which cannot ALTER a foreign key in place); on
Postgres batch mode emits the plain ALTER statements. Additive only.

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
# A live sitting takes notes or is making them; a video has at most one.
LIVE_WHERE = "state IN ('open', 'thinking', 'rendering')"


def upgrade() -> None:
    # ------------------------------------------------------------ part 1
    op.add_column("recording_uploads", sa.Column("render_ref", sa.String(24), nullable=True))
    op.add_column("recording_uploads", sa.Column("rendered_keep", JSON, nullable=True))

    # ------------------------------------------------------------ part 2
    op.create_table(
        "edit_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "upload_id",
            sa.Uuid(),
            sa.ForeignKey("recording_uploads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(20), nullable=False, server_default="open"),
        sa.Column("render_ref", sa.String(24), nullable=True),
        sa.Column("keep_snapshot", JSON, nullable=True),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.Column("before", JSON, nullable=True),
        sa.Column("llm_key", sa.String(120), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("result", JSON, nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_edit_sessions_workspace_id", "edit_sessions", ["workspace_id"])
    op.create_index("ix_edit_sessions_upload_id", "edit_sessions", ["upload_id"])
    op.create_index("ix_edit_sessions_state", "edit_sessions", ["state"])
    # One live sitting per video: two opens at once cannot both insert one.
    op.create_index(
        "uq_edit_sessions_live_upload",
        "edit_sessions",
        ["upload_id"],
        unique=True,
        postgresql_where=sa.text(LIVE_WHERE),
        sqlite_where=sa.text(LIVE_WHERE),
    )

    with op.batch_alter_table("editing_requests") as batch:
        batch.add_column(sa.Column("session_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("source_s", sa.Float(), nullable=True))
        batch.add_column(sa.Column("understood", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_editing_requests_session", "edit_sessions", ["session_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_editing_requests_session_id", ["session_id"])


def downgrade() -> None:
    with op.batch_alter_table("editing_requests") as batch:
        batch.drop_index("ix_editing_requests_session_id")
        batch.drop_constraint("fk_editing_requests_session", type_="foreignkey")
        batch.drop_column("understood")
        batch.drop_column("source_s")
        batch.drop_column("session_id")
    op.drop_index("uq_edit_sessions_live_upload", table_name="edit_sessions")
    op.drop_index("ix_edit_sessions_state", table_name="edit_sessions")
    op.drop_index("ix_edit_sessions_upload_id", table_name="edit_sessions")
    op.drop_index("ix_edit_sessions_workspace_id", table_name="edit_sessions")
    op.drop_table("edit_sessions")
    op.drop_column("recording_uploads", "rendered_keep")
    op.drop_column("recording_uploads", "render_ref")
