"""The third lane: an outside change becomes a topic only when it lands on his work.

"News that excites Ziv" is not a feed. A story enters only when it connects to a
named thing - a repo he runs, a system Kivi Media runs for a client, or a
recurring problem the owners he coaches actually have - and the connection is a
row in `news_anchors`, not a model's opinion that something is relevant.

Two stages, and the split is the cost control. Stage A (`news_feeds` ->
`news_items` -> `news_matches`) is deterministic: fetch, filter by shape, match
against the anchor index. No LLM. An item matching nothing never becomes an
`EvidenceSource` and never costs a job, so a quiet day costs nothing and says so.
Stage B (`news_appraisals`) is one subscription job per matched item.

The lane reuses the evidence pipeline rather than paralleling it:
`evidence_sources.source_kind` gains `news_item` and `standing_fact`, so the four
settled gates, the invented-outcome check, coverage accounting, the global ranker
and the safety scan all apply unchanged. See
plans/21-Sep-26-tce-third-lane-news.md.

Privacy rule, same as editorial: raw fetched documents live only in `*_private`
columns, and standing facts are written in categories ("an AI receptionist
answering a shop's phone"), never with a client's name.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base
from tce.models.editorial import JSONType, _PrivateWorkspaceMixin

# How a feed is parsed. No search API and no scraping: deterministic documents only.
FEED_KINDS = ("atom", "rss", "json", "html")

# 1a: a vendor whose changelog describes something he actually runs. Citable.
# 1b: frontier releases. Citable.
# 2:  discovery only. May point at a primary source, may never be cited as one.
FEED_TIERS = ("1a", "1b", "2")

# Why an item was dropped before any model saw it. These are ledger reasons, not
# candidate rejections: the item never became evidence at all.
PREFILTER_REASONS = (
    "blocked_shape",  # funding, valuation, benchmark, exec move, earnings, survey
    "no_anchor",  # matched nothing in his work
    "stale",  # published outside the window
    "unverified_source",  # no primary document could be fetched and hashed
)

# What an anchor is. The last two are the routes opened by Ziv's 21-Sep
# correction: AI is in scope when it makes sense for the owners he coaches, or
# when it applies to Kivi Media's clients or solutions.
ANCHOR_KINDS = (
    "dependency",
    "vendor",
    "model_id",
    "capability",
    "client_solution",
    "problem_pattern",
)

# Where an anchor came from, so "why this is relevant to you" can name a real thing.
ANCHOR_ORIGINS = ("repo", "commit", "fathom", "env", "manual")

# The appraiser's verdict. "watch" is a real answer: something true that does not
# connect yet, parked on the Timely tab rather than forced into a script.
VERDICTS = ("publish", "watch", "reject")

# How fast it goes stale. "durable" is a confession that it was never news: the
# idea is converted to an ordinary evergreen candidate and consumes no news slot.
PERISHABILITY = ("hours", "days", "week", "month", "durable")

# Only a major story may take a second news slot in one week.
STORY_WEIGHTS = ("small", "major")

# The eight shapes a news-led script may take. Chosen by the appraiser with a
# reason, so the shape is a decision rather than something the writer drifts into.
NEWS_FORMATS = (
    "changes_my_product",
    "i_tested_it",
    "solves_a_client_problem",
    "coaches_will_misread_this",
    "impressive_but_not_the_problem",
    "changes_how_i_manage_agents",
    "three_things_id_test",
    "without_an_engineering_team",
)


class NewsFeed(_PrivateWorkspaceMixin, Base):
    """One source we poll. Mostly changelogs of things he already runs."""

    __tablename__ = "news_feeds"
    __table_args__ = (UniqueConstraint("workspace_id", "url", name="uq_news_feed_url"),)

    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(1000))
    kind: Mapped[str] = mapped_column(String(10), default="atom")  # FEED_KINDS
    tier: Mapped[str] = mapped_column(String(2), default="1a")  # FEED_TIERS
    vendor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Conditional requests, so a quiet feed costs a 304.
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_etag: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # An empty feed and a broken feed must never look the same. Three consecutive
    # failures surface in tce_health rather than reading as "no news today".
    last_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    items_seen_total: Mapped[int] = mapped_column(Integer, default=0)


class NewsItem(_PrivateWorkspaceMixin, Base):
    """One announcement, with the primary document that proves it."""

    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("workspace_id", "feed_id", "external_id", name="uq_news_item_identity"),
    )

    feed_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("news_feeds.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_id: Mapped[str] = mapped_column(String(400))
    url: Mapped[str] = mapped_column(String(1000))
    canonical_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # The announcement itself, which may differ from `url` when discovery came
    # through a tier-2 write-up. A claim may only cite this one.
    primary_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    title: Mapped[str] = mapped_column(String(600))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_tier: Mapped[str] = mapped_column(String(2), default="1a")

    # Provenance. `source_version` is a release tag, an ETag, a Last-Modified or
    # the hash prefix, in that order of preference. A changed hash is what makes
    # a stored claim stale, so it is not optional decoration.
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_private: Mapped[str | None] = mapped_column(Text, nullable=True)
    extract_private: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stage A outcome. `prefilter_reason` is set when the item never became
    # evidence, so the ledger can say what was read and why nothing happened.
    matched: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    prefilter_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Set once the item clears matching and becomes a `news_item` source.
    evidence_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # A correction supersedes rather than overwrites, so history stays readable.
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("news_items.id", ondelete="SET NULL"), nullable=True
    )


class NewsAnchor(_PrivateWorkspaceMixin, Base):
    """One named thing in his world that an announcement can land on.

    Rebuilt nightly from the repos, recent commits and evidence moments, plus the
    hand-written `client_solution` and seeded `problem_pattern` rows. The index is
    what makes the lane precise: a Databricks funding round matches nothing here,
    and that rejection costs no model call.
    """

    __tablename__ = "news_anchors"
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", "normalized_term", name="uq_news_anchor_term"),
    )

    kind: Mapped[str] = mapped_column(String(20), index=True)  # ANCHOR_KINDS
    term: Mapped[str] = mapped_column(String(300))
    # Unicode-aware fold. An ASCII-only normaliser deletes Hebrew outright, and
    # the evidence this is derived from is bilingual.
    normalized_term: Mapped[str] = mapped_column(String(300), index=True)

    origin_kind: Mapped[str] = mapped_column(String(20))  # ANCHOR_ORIGINS
    origin_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # A client_solution or a seeded problem_pattern is true all year and belongs
    # to no week, so it is not citable on its own. This points at the standing
    # fact that makes it citable. See the standing_fact source kind.
    standing_moment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_moments.id", ondelete="SET NULL"), nullable=True
    )

    weight: Mapped[float] = mapped_column(Float, default=1.0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class NewsMatch(_PrivateWorkspaceMixin, Base):
    """Why this item was let through, in a form a person can read back."""

    __tablename__ = "news_matches"
    __table_args__ = (
        UniqueConstraint("news_item_id", "anchor_id", name="uq_news_match_pair"),
    )

    news_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )
    anchor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_anchors.id", ondelete="CASCADE"), index=True
    )
    match_kind: Mapped[str] = mapped_column(String(20))  # mirrors the anchor kind
    matched_span: Mapped[str | None] = mapped_column(String(400), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=1.0)


class NewsAppraisal(_PrivateWorkspaceMixin, Base):
    """Stage B: the eight questions, answered once, stored whole.

    Facts, interpretation and prediction are three separate columns rather than
    three tones of voice, so a prediction cannot be written as a fact downstream.
    """

    __tablename__ = "news_appraisals"

    news_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)

    verdict: Mapped[str] = mapped_column(String(20), index=True)  # VERDICTS
    verdict_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    format: Mapped[str | None] = mapped_column(String(40), nullable=True)  # NEWS_FORMATS

    what_happened: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience_consequence: Mapped[str | None] = mapped_column(Text, nullable=True)
    distinct_claim: Mapped[str | None] = mapped_column(Text, nullable=True)
    do_differently: Mapped[list] = mapped_column(JSONType, default=list)

    # Kept apart on purpose. A test asserts no string appears in more than one.
    confirmed_facts: Mapped[list] = mapped_column(JSONType, default=list)
    ziv_interpretation: Mapped[list] = mapped_column(JSONType, default=list)
    predictions: Mapped[list] = mapped_column(JSONType, default=list)

    # Which moments carry the point of view. Private: the anchor earns the right
    # to speak, it never appears in a public draft.
    anchors: Mapped[list] = mapped_column(JSONType, default=list)
    scores: Mapped[dict] = mapped_column(JSONType, default=dict)

    perishability: Mapped[str | None] = mapped_column(String(20), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # "major" is the only thing that can open a second news slot in a week, and
    # it must name which of the three tests it passed.
    story_weight: Mapped[str] = mapped_column(String(10), default="small")
    weight_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class NewsWatchlist(_PrivateWorkspaceMixin, Base):
    """Real, but it does not connect yet.

    Browsable on the Timely tab and nowhere else: it is somewhere he goes, never
    something that arrives. A "bring it back" re-runs the appraisal against
    today's anchor index, which is the case that actually happens when he ships
    something touching the same vendor a fortnight later.
    """

    __tablename__ = "news_watchlist"
    __table_args__ = (
        UniqueConstraint("workspace_id", "news_item_id", name="uq_news_watch_item"),
    )

    news_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recheck_anchor_kinds: Mapped[list] = mapped_column(JSONType, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(40), nullable=True)
