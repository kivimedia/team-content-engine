"""Jennifer checks every edit, and learns rules from his notes (3-Oct).

- `recording_uploads.qc` (JSON, nullable): what Jennifer found on the render he would
  be watching: the verdict, one plain line, and the numbers (longest pause, dead air,
  loudness, captions, words heard).
- New table `render_checks`: one row per check of one render (`upload_id`,
  `render_ref`, `round` 0 or 1, `state`, `line`, `result`). The history behind `qc`.
- New table `editor_rules`: a note he gave on one video, distilled into a rule for
  every next video: `text`, where it came from (`source_upload_id`, `source_note_id`,
  both SET NULL), `active` (Delete on the rules page switches a rule off and keeps the
  row), `deactivated_at`, `times_applied` and the videos it was applied on
  (`applied_uploads`).

Additive only: one nullable column and two new tables. Nothing is rewritten.

Revision ID: 058
Revises: 057
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None

# JSONB on the server, plain JSON where the tests build the tables (SQLite).
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("recording_uploads", sa.Column("qc", JSON, nullable=True))

    op.create_table(
        "render_checks",
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
        sa.Column("render_ref", sa.String(24), nullable=True),
        sa.Column("round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(20), nullable=False, server_default="passed"),
        sa.Column("line", sa.String(500), nullable=True),
        sa.Column("result", JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_render_checks_workspace_id", "render_checks", ["workspace_id"])
    op.create_index("ix_render_checks_upload_id", "render_checks", ["upload_id"])
    op.create_index("ix_render_checks_render_ref", "render_checks", ["render_ref"])
    op.create_index("ix_render_checks_state", "render_checks", ["state"])

    op.create_table(
        "editor_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "source_upload_id",
            sa.Uuid(),
            sa.ForeignKey("recording_uploads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_note_id",
            sa.Uuid(),
            sa.ForeignKey("editing_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.Column("times_applied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applied_uploads", JSON, nullable=False, server_default=sa.text("'[]'")),
    )
    op.create_index("ix_editor_rules_workspace_id", "editor_rules", ["workspace_id"])
    op.create_index("ix_editor_rules_source_upload_id", "editor_rules", ["source_upload_id"])
    op.create_index("ix_editor_rules_source_note_id", "editor_rules", ["source_note_id"])
    op.create_index("ix_editor_rules_active", "editor_rules", ["active"])


def downgrade() -> None:
    op.drop_index("ix_editor_rules_active", table_name="editor_rules")
    op.drop_index("ix_editor_rules_source_note_id", table_name="editor_rules")
    op.drop_index("ix_editor_rules_source_upload_id", table_name="editor_rules")
    op.drop_index("ix_editor_rules_workspace_id", table_name="editor_rules")
    op.drop_table("editor_rules")
    op.drop_index("ix_render_checks_state", table_name="render_checks")
    op.drop_index("ix_render_checks_render_ref", table_name="render_checks")
    op.drop_index("ix_render_checks_upload_id", table_name="render_checks")
    op.drop_index("ix_render_checks_workspace_id", table_name="render_checks")
    op.drop_table("render_checks")
    op.drop_column("recording_uploads", "qc")
