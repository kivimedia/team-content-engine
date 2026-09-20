"""Durable content runs, stage cache, editorial schedule and worker-group state.

Revision ID: 038
Revises: 037
Create Date: 2026-09-20
"""

from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None

TABLES = (
    "content_runs",
    "content_run_stages",
    "stage_result_cache",
    "editorial_schedules",
    "editorial_schedule_occurrences",
    "worker_group_states",
)


def _metadata():
    from tce.db.base import Base
    from tce.models import content_run  # noqa: F401

    return Base.metadata


def upgrade() -> None:
    md = _metadata()
    bind = op.get_bind()
    for name in TABLES:
        md.tables[name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    md = _metadata()
    bind = op.get_bind()
    for name in reversed(TABLES):
        md.tables[name].drop(bind=bind, checkfirst=True)

