"""The news lane inside the real selector, not beside it.

The rules module is tested on its own. These tests drive the selector's actual
functions with a news moment in the pool, because the failures that matter here
live in the seams: a news shard that cannot see its anchor, a resumed run that
counts anchors as accountable, a durable idea still taking a news slot.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from tce.editorial.common import parse_selection_header
from tce.editorial.selector import (
    PoolMoment,
    anchor_ids_for,
    build_selection_prompt,
    enforce_candidates,
    load_context,
    split_news,
)
from tce.models.editorial import EvidenceMoment, EvidenceSource
from tce.models.news import NewsAppraisal, NewsItem, NewsWatchlist
from tce.news.record import record_appraisal

WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
NOW = datetime(2026, 9, 22, 12, 0, 0)
GATES = {
    g: {"pass": True, "reason": "ok"}
    for g in (
        "small_service_business",
        "coach_or_event_owner_relevance",
        "concrete_supported_substance",
        "connects_to_ziv_work",
    )
}


def _source(kind: str, **kw) -> EvidenceSource:
    return EvidenceSource(
        id=kw.pop("id", uuid.uuid4()),
        workspace_id=WS,
        source_kind=kind,
        external_id=kw.pop("external_id", f"{kind}-{uuid.uuid4()}"),
        version_hash=kw.pop("version_hash", "v1"),
        occurred_at=kw.pop("occurred_at", NOW - timedelta(days=1)),
        fetch_status="ok",
        payload_private={},
        **kw,
    )


def _moment(source: EvidenceSource, claim: str = "demonstrated", **kw) -> EvidenceMoment:
    return EvidenceMoment(
        id=kw.pop("id", uuid.uuid4()),
        workspace_id=WS,
        source_id=source.id,
        source_version_hash=source.version_hash,
        excerpt_private=kw.pop("excerpt", "an excerpt"),
        lesson_summary=kw.pop("lesson", "a lesson"),
        claim_type=claim,
        speaker_confidence="high",
        status="active",
        sensitivity_flags=[],
        **kw,
    )


def _pm(kind: str, claim: str = "demonstrated", **kw) -> PoolMoment:
    src = _source(kind)
    return PoolMoment(moment=_moment(src, claim, **kw), source=src, in_week=True)


def _news_pm(anchor_ids: list[str], **ref) -> PoolMoment:
    base_ref = {
        "news_item_id": str(uuid.uuid4()),
        "published_at": (NOW - timedelta(days=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=9)).isoformat(),
        "story_weight": "small",
        "perishability": "week",
        "scores": {"owner_relevance": 5, "consequence_specificity": 5, "distinctiveness": 5},
        "anchor_moment_ids": anchor_ids,
    }
    base_ref.update(ref)
    return _pm("news_item", "quoted", news_ref=base_ref)


def _candidate(ids: list[str], **over) -> dict:
    base = {
        "moment_ids": ids,
        "title": "A title",
        "lesson": "A lesson for owners",
        "audience": "both",
        "public_angle": "An angle",
        "gates": dict(GATES),
        "scores": {"owner_relevance": 4, "useful_lesson": 4, "support_strength": 4},
        "freshness_role": "news",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Splitting the pool
# ---------------------------------------------------------------------------


def test_news_goes_to_its_own_group_and_standing_facts_to_neither():
    call, commit = _pm("fathom_meeting"), _pm("github_commit_group")
    news, standing = _news_pm([]), _pm("standing_fact")
    rest, news_out = split_news([call, news, commit, standing])
    assert {pm.source.source_kind for pm in rest} == {"fathom_meeting", "github_commit_group"}
    assert news_out == [news]
    assert standing not in rest and standing not in news_out, (
        "a standing fact reached the ordinary pool; it would be judged as a "
        "candidate in its own right every single week"
    )


def test_a_week_with_no_news_splits_to_exactly_what_it_was():
    pool = [_pm("fathom_meeting"), _pm("github_commit_group")]
    rest, news = split_news(pool)
    assert rest == pool and news == []


def test_anchor_ids_are_collected_in_order_without_duplicates():
    a, b, c = (str(uuid.uuid4()) for _ in range(3))
    ids = anchor_ids_for([_news_pm([a, b]), _news_pm([b, c])])
    assert ids == [a, b, c]


# ---------------------------------------------------------------------------
# The resume trap: context is citable, never accountable
# ---------------------------------------------------------------------------


def test_a_resumed_run_does_not_count_anchors_as_accountable():
    """If anchors and news shared a key, resume would demand the model account for
    moments it was only shown so it could cite them."""
    anchor = _pm("github_commit_group")
    news = _news_pm([anchor.id])
    prompt = build_selection_prompt(
        "strategy", "feedback", [news], 3, NOW, shard=2, shards=2, context=[anchor]
    )
    header = parse_selection_header(prompt)
    assert header["moment_ids"] == [news.id], "an anchor leaked into the accountable ids"
    assert header["context_ids"] == [anchor.id], "the anchor was not recoverable on resume"


def test_a_shard_with_no_context_is_byte_identical_to_before():
    """The lane must not change a single prompt when it has nothing to say."""
    pm = _pm("fathom_meeting")
    with_none = build_selection_prompt("s", "f", [pm], 3, NOW)
    with_empty = build_selection_prompt("s", "f", [pm], 3, NOW, context=[])
    assert with_none == with_empty
    assert "ANCHOR CONTEXT" not in with_none
    assert parse_selection_header(with_none)["context_ids"] == []


def test_the_news_shard_tells_the_model_the_rule():
    anchor = _pm("fathom_meeting")
    prompt = build_selection_prompt("s", "f", [_news_pm([anchor.id])], 3, NOW, context=[anchor])
    assert "ANCHOR CONTEXT" in prompt
    assert "MUST also cite at least one anchor" in prompt


# ---------------------------------------------------------------------------
# enforce_candidates with real news in the pool
# ---------------------------------------------------------------------------


def test_news_plus_an_anchor_is_accepted_and_scored_as_news():
    anchor = _pm("github_commit_group")
    news = _news_pm([anchor.id])
    pool = [news, anchor]
    ids = {pm.id for pm in pool}
    accepted, rejected = enforce_candidates([_candidate([news.id, anchor.id])], pool, ids)
    assert rejected == []
    assert len(accepted) == 1
    cand = accepted[0]
    assert cand["freshness_role"] == "news"
    assert cand["news"] is not None
    assert cand["news"]["story_weight"] == "small"
    assert "News score:" in (cand["public_safety_notes"] or ""), "the card cannot show its working"


def test_news_alone_is_rejected_under_his_own_gate():
    news = _news_pm([])
    accepted, rejected = enforce_candidates([_candidate([news.id])], [news], {news.id})
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0]["gate"] == "connects_to_ziv_work"
    assert rejected[0]["code"] == "news_needs_anchor"


def test_an_ordinary_candidate_is_scored_exactly_as_before():
    """The evergreen path must not move by a single point."""
    call = _pm("fathom_meeting", "paraphrased")
    accepted, _ = enforce_candidates(
        [_candidate([call.id], freshness_role="evergreen")], [call], {call.id}
    )
    assert accepted[0]["news"] is None
    assert accepted[0]["freshness_role"] == "evergreen"


def test_a_durable_news_idea_becomes_evergreen_and_takes_no_slot():
    anchor = _pm("github_commit_group")
    news = _news_pm([anchor.id], perishability="durable", expires_at=None)
    pool = [news, anchor]
    accepted, _ = enforce_candidates(
        [_candidate([news.id, anchor.id])], pool, {pm.id for pm in pool}
    )
    assert accepted[0]["freshness_role"] == "evergreen"
    assert accepted[0]["news"] is None, "a durable idea would still count against the ceiling"


def test_a_news_idea_on_a_standing_fact_scores_below_one_on_a_commit():
    standing = _pm("standing_fact", "demonstrated")
    commit = _pm("github_commit_group", "demonstrated")
    scored = {}
    for name, anchor in (("standing", standing), ("commit", commit)):
        news = _news_pm([anchor.id])
        pool = [news, anchor]
        accepted, _ = enforce_candidates(
            [_candidate([news.id, anchor.id])], pool, {pm.id for pm in pool}
        )
        scored[name] = accepted[0]["rank_score"]
    assert scored["standing"] < scored["commit"]


# ---------------------------------------------------------------------------
# Loading the anchors a news shard needs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_loads_named_anchors_and_every_standing_fact(editorial_session):
    commit_src = _source("github_commit_group", occurred_at=NOW - timedelta(days=40))
    stand_src = _source("standing_fact", external_id="standing-facts")
    other_src = _source("fathom_meeting")
    commit = _moment(commit_src)
    standing = _moment(stand_src)
    unrelated = _moment(other_src)
    editorial_session.add_all([commit_src, stand_src, other_src, commit, standing, unrelated])
    await editorial_session.flush()

    got = {pm.id for pm in await load_context(editorial_session, WS, [str(commit.id)])}
    assert str(commit.id) in got, "a month-old anchor outside the week could not be cited"
    assert str(standing.id) in got
    assert str(unrelated.id) not in got


@pytest.mark.asyncio
async def test_a_stale_anchor_is_not_citable(editorial_session):
    src = _source("github_commit_group", version_hash="v2")
    stale = _moment(src)
    stale.source_version_hash = "v1"  # the source changed after extraction
    editorial_session.add_all([src, stale])
    await editorial_session.flush()
    got = await load_context(editorial_session, WS, [str(stale.id)], include_standing=False)
    assert got == []


@pytest.mark.asyncio
async def test_resume_context_excludes_standing_facts_it_never_showed(editorial_session):
    stand_src = _source("standing_fact", external_id="standing-facts")
    standing = _moment(stand_src)
    editorial_session.add_all([stand_src, standing])
    await editorial_session.flush()
    got = await load_context(editorial_session, WS, [], include_standing=False)
    assert got == []


# ---------------------------------------------------------------------------
# Recording an appraisal
# ---------------------------------------------------------------------------


def _item() -> NewsItem:
    return NewsItem(
        id=uuid.uuid4(),
        workspace_id=WS,
        external_id="rel-1",
        url="https://vendor.example/r/1",
        primary_url="https://vendor.example/r/1",
        title="Pricing moves to per message",
        publisher="Vendor",
        published_at=NOW - timedelta(days=1),
        content_sha256="abc123",
        extract_private="Conversation-based pricing is retired.",
        source_tier="1a",
    )


PUBLISH = {
    "verdict": "publish",
    "verdict_reason": "Changes a bill for shops.",
    "what_happened": "Per-message billing.",
    "audience_consequence": "Owners pay differently.",
    "distinct_claim": "I run these sequences.",
    "do_differently": ["Count template messages."],
    "confirmed_facts": [{"claim": "Retired", "quote": "Conversation-based pricing is retired"}],
    "ziv_interpretation": ["Owners will notice late."],
    "predictions": ["Length becomes a cost decision."],
    "format": "changes_my_product",
    "perishability": "month",
    "expires_at": NOW + timedelta(days=34),
    "story_weight": "small",
    "weight_reason": None,
    "scores": {"owner_relevance": 5, "consequence_specificity": 4, "distinctiveness": 4},
}


@pytest.mark.asyncio
async def test_a_published_appraisal_becomes_citable_evidence(editorial_session):
    item = _item()
    editorial_session.add(item)
    await editorial_session.flush()
    anchor = str(uuid.uuid4())

    out = await record_appraisal(
        editorial_session, WS, item, PUBLISH,
        anchors=[{"kind": "vendor", "term": "vendor"}], anchor_moment_ids=[anchor], now=NOW,
    )
    assert out["moment_id"]

    moment = await editorial_session.get(EvidenceMoment, uuid.UUID(out["moment_id"]))
    source = await editorial_session.get(EvidenceSource, moment.source_id)
    assert source.source_kind == "news_item"
    assert moment.claim_type == "quoted", "a news claim must never be recorded as measured"
    assert moment.news_ref["anchor_moment_ids"] == [anchor]
    assert moment.news_ref["scores"]["consequence_specificity"] == 4
    assert moment.news_ref["story_weight"] == "small"
    assert source.occurred_at == item.published_at, "a late find was dated as fresh"
    assert item.evidence_source_id == source.id


@pytest.mark.asyncio
async def test_a_watch_verdict_writes_no_evidence(editorial_session):
    item = _item()
    editorial_session.add(item)
    await editorial_session.flush()
    out = await record_appraisal(
        editorial_session, WS, item,
        {"verdict": "watch", "verdict_reason": "Real, does not connect yet."},
        anchors=[{"kind": "vendor", "term": "vendor"}], anchor_moment_ids=[], now=NOW,
    )
    assert out["moment_id"] is None
    assert (await editorial_session.execute(select(EvidenceMoment))).scalars().all() == []
    watched = (await editorial_session.execute(select(NewsWatchlist))).scalars().all()
    assert len(watched) == 1 and watched[0].recheck_anchor_kinds == ["vendor"]


@pytest.mark.asyncio
async def test_a_reject_writes_only_the_ledger(editorial_session):
    item = _item()
    editorial_session.add(item)
    await editorial_session.flush()
    out = await record_appraisal(
        editorial_session, WS, item,
        {"verdict": "reject", "verdict_reason": "Enterprise."},
        anchors=[], anchor_moment_ids=[], now=NOW,
    )
    assert out["moment_id"] is None
    assert (await editorial_session.execute(select(EvidenceMoment))).scalars().all() == []
    assert (await editorial_session.execute(select(NewsWatchlist))).scalars().all() == []
    assert len((await editorial_session.execute(select(NewsAppraisal))).scalars().all()) == 1
