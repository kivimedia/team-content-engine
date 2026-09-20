"""Packet v2 hook metadata and restart-safe export intents.

Revision ID: 039
Revises: 038
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recording_packets", sa.Column("hook_options", postgresql.JSONB(), nullable=True))
    op.add_column("recording_packets", sa.Column("selected_hook_id", sa.String(80), nullable=True))
    op.add_column("recording_packets", sa.Column("beats", postgresql.JSONB(), nullable=True))
    op.create_unique_constraint(
        "uq_packet_version", "recording_packets", ["workspace_id", "candidate_id", "version"]
    )
    from tce.db.base import Base
    from tce.models import editorial  # noqa: F401

    Base.metadata.tables["export_intents"].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    from tce.db.base import Base
    from tce.models import editorial  # noqa: F401

    Base.metadata.tables["export_intents"].drop(bind=op.get_bind(), checkfirst=True)
    op.drop_constraint("uq_packet_version", "recording_packets", type_="unique")
    op.drop_column("recording_packets", "beats")
    op.drop_column("recording_packets", "selected_hook_id")
    op.drop_column("recording_packets", "hook_options")
