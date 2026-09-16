"""Evidence-first editorial records and the subscription LLM job queue.

Additive only: creates new tables, touches no existing table or row.

Revision ID: 037
Revises: 036
Create Date: 2026-09-16
"""

from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None

# Order matters for foreign keys.
_TABLES = (
    "llm_jobs",
    "evidence_sources",
    "evidence_collection_runs",
    "evidence_moments",
    "topic_candidates",
    "editorial_feedback",
    "recording_packets",
    "recording_uploads",
    "publication_receipts",
)


def _metadata():
    from tce.db.base import Base
    from tce.models import editorial, llm_job  # noqa: F401  (register tables)

    return Base.metadata


def upgrade() -> None:
    md = _metadata()
    bind = op.get_bind()
    for name in _TABLES:
        md.tables[name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    md = _metadata()
    bind = op.get_bind()
    for name in reversed(_TABLES):
        md.tables[name].drop(bind=bind, checkfirst=True)
