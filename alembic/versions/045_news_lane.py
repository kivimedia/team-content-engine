"""The third lane: news that connects to his work, plus the standing facts that let it.

Additive only. Nothing reads any of this until TCE_NEWS_LANE is on, and the
daily-news schedule ships disabled.

Numbered 045 rather than 043: this was written the same evening as the editorial
workspace migration and both started from 042. That one landed first, so this one
moves behind it to keep a single head. The two are independent - nothing here
reads a lineup column and nothing there reads a news column.

Two columns on existing tables carry the lane into the editorial pipeline rather
than beside it: topic_candidates.news_item_id (present = news-led) and
evidence_moments.news_ref (the lane's locator, beside span_start_s for meetings
and code_refs for commits). SOURCE_KINDS gains news_item and standing_fact, which
needs no schema change because source_kind is already a String(40).

Revision ID: 045
Revises: 044
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "news_feeds",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False, server_default="atom"),
        sa.Column("tier", sa.String(2), nullable=False, server_default="1a"),
        sa.Column("vendor", sa.String(120), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("last_etag", sa.String(300), nullable=True),
        sa.Column("last_modified", sa.String(120), nullable=True),
        sa.Column("last_status", sa.String(40), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_seen_total", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("workspace_id", "url", name="uq_news_feed_url"),
    )
    op.create_index("ix_news_feeds_workspace_id", "news_feeds", ["workspace_id"])

    op.create_table(
        "news_items",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "feed_id",
            UUID,
            sa.ForeignKey("news_feeds.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_id", sa.String(400), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("canonical_url", sa.String(1000), nullable=True),
        sa.Column("primary_url", sa.String(1000), nullable=True),
        sa.Column("title", sa.String(600), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("publisher", sa.String(200), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column("language", sa.String(20), nullable=True),
        sa.Column("source_tier", sa.String(2), nullable=False, server_default="1a"),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("source_version", sa.String(200), nullable=True),
        sa.Column("raw_private", sa.Text(), nullable=True),
        sa.Column("extract_private", sa.Text(), nullable=True),
        sa.Column("matched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("prefilter_reason", sa.String(40), nullable=True),
        sa.Column(
            "evidence_source_id",
            UUID,
            sa.ForeignKey("evidence_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "superseded_by",
            UUID,
            sa.ForeignKey("news_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "workspace_id", "feed_id", "external_id", name="uq_news_item_identity"
        ),
    )
    op.create_index("ix_news_items_workspace_id", "news_items", ["workspace_id"])
    op.create_index("ix_news_items_feed_id", "news_items", ["feed_id"])
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"])
    op.create_index("ix_news_items_matched", "news_items", ["matched"])
    op.create_index("ix_news_items_evidence_source_id", "news_items", ["evidence_source_id"])

    op.create_table(
        "news_anchors",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("term", sa.String(300), nullable=False),
        sa.Column("normalized_term", sa.String(300), nullable=False),
        sa.Column("origin_kind", sa.String(20), nullable=False),
        sa.Column("origin_ref", sa.String(500), nullable=True),
        sa.Column(
            "standing_moment_id",
            UUID,
            sa.ForeignKey("evidence_moments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint(
            "workspace_id", "kind", "normalized_term", name="uq_news_anchor_term"
        ),
    )
    op.create_index("ix_news_anchors_workspace_id", "news_anchors", ["workspace_id"])
    op.create_index("ix_news_anchors_kind", "news_anchors", ["kind"])
    op.create_index("ix_news_anchors_normalized_term", "news_anchors", ["normalized_term"])
    op.create_index("ix_news_anchors_active", "news_anchors", ["active"])

    op.create_table(
        "news_matches",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "news_item_id",
            UUID,
            sa.ForeignKey("news_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "anchor_id",
            UUID,
            sa.ForeignKey("news_anchors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("match_kind", sa.String(20), nullable=False),
        sa.Column("matched_span", sa.String(400), nullable=True),
        sa.Column("score", sa.Float(), nullable=False, server_default="1.0"),
        sa.UniqueConstraint("news_item_id", "anchor_id", name="uq_news_match_pair"),
    )
    op.create_index("ix_news_matches_workspace_id", "news_matches", ["workspace_id"])
    op.create_index("ix_news_matches_news_item_id", "news_matches", ["news_item_id"])
    op.create_index("ix_news_matches_anchor_id", "news_matches", ["anchor_id"])

    op.create_table(
        "news_appraisals",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "news_item_id",
            UUID,
            sa.ForeignKey("news_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_id", UUID, nullable=True),
        sa.Column("prompt_version", sa.String(80), nullable=True),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("verdict_reason", sa.Text(), nullable=True),
        sa.Column("format", sa.String(40), nullable=True),
        sa.Column("what_happened", sa.Text(), nullable=True),
        sa.Column("audience_consequence", sa.Text(), nullable=True),
        sa.Column("distinct_claim", sa.Text(), nullable=True),
        sa.Column("do_differently", JSONB, nullable=False, server_default="[]"),
        sa.Column("confirmed_facts", JSONB, nullable=False, server_default="[]"),
        sa.Column("ziv_interpretation", JSONB, nullable=False, server_default="[]"),
        sa.Column("predictions", JSONB, nullable=False, server_default="[]"),
        sa.Column("anchors", JSONB, nullable=False, server_default="[]"),
        sa.Column("scores", JSONB, nullable=False, server_default="{}"),
        sa.Column("perishability", sa.String(20), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("story_weight", sa.String(10), nullable=False, server_default="small"),
        sa.Column("weight_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_news_appraisals_workspace_id", "news_appraisals", ["workspace_id"])
    op.create_index("ix_news_appraisals_news_item_id", "news_appraisals", ["news_item_id"])
    op.create_index("ix_news_appraisals_verdict", "news_appraisals", ["verdict"])
    op.create_index("ix_news_appraisals_expires_at", "news_appraisals", ["expires_at"])

    op.create_table(
        "news_watchlist",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "news_item_id",
            UUID,
            sa.ForeignKey("news_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("recheck_anchor_kinds", JSONB, nullable=False, server_default="[]"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution", sa.String(40), nullable=True),
        sa.UniqueConstraint("workspace_id", "news_item_id", name="uq_news_watch_item"),
    )
    op.create_index("ix_news_watchlist_workspace_id", "news_watchlist", ["workspace_id"])
    op.create_index("ix_news_watchlist_news_item_id", "news_watchlist", ["news_item_id"])

    # The two columns that carry the lane into the existing editorial pipeline.
    op.add_column("evidence_moments", sa.Column("news_ref", JSONB, nullable=True))
    op.add_column(
        "topic_candidates",
        sa.Column(
            "news_item_id",
            UUID,
            sa.ForeignKey("news_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("topic_candidates", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_topic_candidates_news_item_id", "topic_candidates", ["news_item_id"]
    )

    # Packet additions: the confirmed/interpretation/prediction block, and which
    # of the eight shapes the script takes.
    op.add_column("recording_packets", sa.Column("news_block", JSONB, nullable=True))
    op.add_column("recording_packets", sa.Column("format", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("recording_packets", "format")
    op.drop_column("recording_packets", "news_block")
    op.drop_index("ix_topic_candidates_news_item_id", table_name="topic_candidates")
    op.drop_column("topic_candidates", "expires_at")
    op.drop_column("topic_candidates", "news_item_id")
    op.drop_column("evidence_moments", "news_ref")
    op.drop_table("news_watchlist")
    op.drop_table("news_appraisals")
    op.drop_table("news_matches")
    op.drop_table("news_anchors")
    op.drop_table("news_items")
    op.drop_table("news_feeds")
