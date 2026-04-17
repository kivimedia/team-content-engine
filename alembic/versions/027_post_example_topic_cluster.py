"""Add topic_cluster column to post_examples so the LLM corpus classifier
(Layer 1 of TJ grounding) can tag each post with its high-level content
zone (e.g. "AI competition", "website strategy", "SaaS disruption"). Used
by trend_scout + writer RAG to bias toward TJ's proven topic clusters.

Revision ID: 027
Revises: 026
Create Date: 2026-04-17
"""

from alembic import op
import sqlalchemy as sa


revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "post_examples",
        sa.Column(
            "topic_cluster",
            sa.String(100),
            nullable=True,
            comment="High-level topic zone from creator's analysis (e.g. 'AI competition', 'website strategy for AI agents'). Populated by enrich_post_examples LLM classifier.",
        ),
    )
    op.create_index(
        "idx_post_examples_topic_cluster",
        "post_examples",
        ["creator_id", "topic_cluster"],
    )


def downgrade() -> None:
    op.drop_index("idx_post_examples_topic_cluster", table_name="post_examples")
    op.drop_column("post_examples", "topic_cluster")
