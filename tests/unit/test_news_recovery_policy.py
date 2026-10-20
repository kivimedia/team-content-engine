"""20-Oct: news keeps its proof and gets a bounded route to recording."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tce.editorial import news_rules, selector
from tce.models.editorial import EvidenceMoment, EvidenceSource, TopicCandidate
from tce.models.news import NewsAnchor, NewsItem, NewsMatch
from tce.news import discovery
from tce.news.standing import StandingFact, seed_standing_facts
from tce.settings import settings

WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
NOW = datetime(2026, 10, 14, 9)
DOC = "Forwarded calls fall back to voicemail."


@pytest.fixture(autouse=True)
def configured_owner(monkeypatch):
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(WS))
    monkeypatch.setattr(settings, "owner_workspace_ids", "")


@pytest.fixture
def lane(monkeypatch):
    monkeypatch.setattr(settings, "news_lane", True)


class Model:
    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    async def __call__(self, request):
        self.calls += 1
        return SimpleNamespace(structured=self.answer, job_id=uuid.uuid4())


async def _setup(session, facts):
    await seed_standing_facts(session, WS, facts, now=NOW)
    await session.flush()


async def _discover(session):
    """Start at the matched-item seam; feed/matcher tests own ingestion."""
    from tce.news.anchors import build_anchor_index
    await build_anchor_index(session, WS, now=NOW)
    anchor = (await session.execute(select(NewsAnchor).where(
        NewsAnchor.workspace_id == WS, NewsAnchor.kind == "vendor",
        NewsAnchor.normalized_term == "twilio",
    ))).scalars().one()
    item = NewsItem(
        id=uuid.uuid4(), workspace_id=WS, external_id="twilio-change",
        url="https://vendor.example/change", primary_url="https://vendor.example/change",
        title="Twilio call routing change", matched=True, source_tier="1a",
        published_at=NOW - timedelta(days=1), fetched_at=NOW,
        extract_private=DOC, content_sha256="a" * 64,
    )
    session.add(item)
    await session.flush()
    session.add(NewsMatch(
        id=uuid.uuid4(), workspace_id=WS, news_item_id=item.id, anchor_id=anchor.id,
        match_kind="vendor", matched_span="twilio", score=1,
    ))
    await session.flush()


def _pm(kind, *, ref=None):
    source = EvidenceSource(
        id=uuid.uuid4(), workspace_id=WS, source_kind=kind,
        external_id=str(uuid.uuid4()), version_hash="v1", occurred_at=NOW,
        fetch_status="ok", payload_private={},
    )
    moment = EvidenceMoment(
        id=uuid.uuid4(), workspace_id=WS, source_id=source.id, source_version_hash="v1",
        excerpt_private="An observed fact", lesson_summary="An owner lesson",
        claim_type="demonstrated", speaker_confidence="high", status="active",
        sensitivity_flags=[], news_ref=ref,
    )
    return selector.PoolMoment(moment=moment, source=source, in_week=True)


def _news_pm(anchors):
    return _pm("news_item", ref={
        "news_item_id": str(uuid.uuid4()), "anchor_moment_ids": anchors,
        "published_at": NOW.isoformat(), "expires_at": (NOW + timedelta(days=5)).isoformat(),
        "perishability": "days", "scores": {},
    })


def _candidate(ids):
    return {
        "moment_ids": ids, "title": "A useful AI change", "lesson": "An owner lesson",
        "audience": "both", "public_angle": "Try the change", "freshness_role": "news",
        "gates": {name: {"pass": True, "reason": "supported"} for name in (
            "small_service_business", "coach_or_event_owner_relevance",
            "concrete_supported_substance", "connects_to_ziv_work",
        )},
    }


async def _published_news(session):
    pm = _news_pm([])
    # No actual item is necessary to exercise the selection bookkeeping.
    pm.moment.news_ref = {**pm.moment.news_ref, "news_item_id": None}
    session.add_all([pm.source, pm.moment])
    await session.flush()
    return pm.source, pm.moment


def test_owner_quality_is_identical_for_first_and_later_news():
    candidates = [{"news": False, "score": .95}] + [
        {"news": True, "score": .76} for _ in range(3)
    ]
    decision = news_rules.apply_slot_rules(
        candidates, is_news=lambda c: c["news"], score_of=lambda c: c["score"],
        story_weight_of=lambda c: "small", already=1, owner_workspace=WS,
    )
    assert decision.kept == candidates
    weak = [{"news": True, "score": .69}]
    decision = news_rules.apply_slot_rules(
        weak, is_news=lambda c: True, score_of=lambda c: c["score"],
        story_weight_of=lambda c: "major", owner_workspace=WS,
    )
    assert decision.rejected[0][1] == "news_floor"


def test_quality_does_not_decay_before_verified_expiry_for_owner():
    kwargs = dict(
        citations=[{"source_kind": "standing_fact", "claim_type": "demonstrated"}],
        scores={"owner_relevance": 4, "consequence_specificity": 4, "distinctiveness": 4},
        published_at=NOW, expires_at=NOW + timedelta(days=5), owner_workspace=WS,
    )
    first = news_rules.score_news(now=NOW, **kwargs)
    fourth = news_rules.score_news(now=NOW + timedelta(days=4), **kwargs)
    assert first.total == fourth.total >= .70


def test_other_workspace_keeps_its_existing_slot_policy():
    candidate = {"score": .76}
    decision = news_rules.apply_slot_rules(
        [candidate], is_news=lambda c: True, score_of=lambda c: c["score"],
        story_weight_of=lambda c: "small", already=1, owner_workspace=uuid.uuid4(),
    )
    assert decision.kept == []
    assert decision.rejected[0][1] == "news_ceiling"


@pytest.mark.asyncio
async def test_manual_publication_date_is_not_the_day_it_was_requested(editorial_session):
    async def page(url):
        return {"title": "A release", "body_text": DOC,
                "source_verified": True, "primary_url": url,
                "published_at": datetime(2026, 10, 5)}
    await discovery.check_one(
        editorial_session, WS, url="https://vendor.example/release", fetch_text=page, now=NOW,
    )
    item = (await editorial_session.execute(select(NewsItem))).scalars().one()
    assert item.published_at == datetime(2026, 10, 5)
    assert item.fetched_at == NOW


@pytest.mark.asyncio
async def test_unknown_publication_date_stays_unknown(editorial_session):
    async def page(url):
        return {"title": "Undated release", "body_text": DOC,
                "source_verified": True, "primary_url": url}
    await discovery.check_one(
        editorial_session, WS, url="https://vendor.example/undated", fetch_text=page, now=NOW,
    )
    item = (await editorial_session.execute(select(NewsItem))).scalars().one()
    assert item.published_at is None


@pytest.mark.asyncio
async def test_news_retrieves_a_matching_fathom_call(editorial_session, lane):
    await _setup(editorial_session, [
        StandingFact("vendor", "twilio", "We operate shop reception on Twilio."),
    ])
    await _discover(editorial_session)
    item = (await editorial_session.execute(
        select(NewsItem).where(NewsItem.matched.is_(True))
    )).scalars().first()
    source = EvidenceSource(
        id=uuid.uuid4(), workspace_id=WS, source_kind="fathom_meeting",
        external_id="call-proof", version_hash="v1", occurred_at=NOW - timedelta(days=1),
        fetch_status="ok", payload_private={},
    )
    moment = EvidenceMoment(
        id=uuid.uuid4(), workspace_id=WS, source_id=source.id, source_version_hash="v1",
        excerpt_private="Twilio missed-call routing is the owner's problem.",
        lesson_summary="Check Twilio routing after closing.",
        claim_type="paraphrased", speaker_confidence="high", status="active",
        sensitivity_flags=[],
    )
    editorial_session.add_all([source, moment])
    await editorial_session.flush()
    _, ids, recent, demo = await discovery._anchor_moments(editorial_session, WS, item, NOW)
    assert str(moment.id) in ids
    assert any(r["source_kind"] == "fathom_meeting" for r in recent)
    assert demo is False


def test_rejected_news_keeps_its_verified_citations():
    anchor = _pm("standing_fact")
    news = _news_pm([anchor.id])
    raw = _candidate([news.id, anchor.id])
    raw["gates"] = dict(raw["gates"])
    raw["gates"]["connects_to_ziv_work"] = {"pass": False, "reason": "needs a narrower angle"}
    _, rejected = selector.enforce_candidates(
        [raw], [news, anchor], {news.id, anchor.id},
    )
    assert rejected[0]["news"]["news_item_id"] == news.moment.news_ref["news_item_id"]
    assert {c["source_kind"] for c in rejected[0]["citations_private"]} == {
        "news_item", "standing_fact",
    }


@pytest.mark.asyncio
async def test_old_ceiling_rejection_is_reoffered_once_under_new_owner_policy(editorial_session):
    source, moment = await _published_news(editorial_session)
    editorial_session.add(TopicCandidate(
        id=uuid.uuid4(), workspace_id=WS, week_start=NOW, moment_ids=[str(moment.id)],
        title="Useful owner story", lesson="l", audience="both", reasons_to_care=[],
        public_angle="a", gates={"_rejection": {"code": "news_ceiling"}},
        status="rejected", origin="selector_rejected", created_at=NOW,
    ))
    await editorial_session.flush()
    assert await discovery.news_awaiting_topic(editorial_session, WS, now=NOW) == [source.id]


@pytest.mark.asyncio
async def test_same_recovery_fingerprint_never_requeues_a_selector_rejection(editorial_session):
    source, moment = await _published_news(editorial_session)
    fingerprint = await discovery.selection_fingerprint(editorial_session, WS, source, moment)
    editorial_session.add(TopicCandidate(
        id=uuid.uuid4(), workspace_id=WS, week_start=NOW, moment_ids=[str(moment.id)],
        title="A narrow angle", lesson="l", audience="both", reasons_to_care=[],
        public_angle="a", gates={"_news_recovery": {
            "state": "needs_angle", "fingerprint": fingerprint,
            "policy": news_rules.OWNER_POLICY_VERSION,
        }}, status="rejected", origin="selector_rejected", created_at=NOW,
    ))
    await editorial_session.flush()
    assert await discovery.news_awaiting_topic(editorial_session, WS, now=NOW) == []


@pytest.mark.asyncio
async def test_appraisal_retries_only_on_changed_input_and_stops_at_bound(editorial_session, lane):
    await _setup(editorial_session, [
        StandingFact("vendor", "twilio", "We operate shop reception on Twilio."),
    ])
    await _discover(editorial_session)
    model = Model({
        "verdict": "watch", "verdict_reason": "Need relevant call evidence.",
        "recovery_state": "waiting_for_evidence", "news_category": "ai",
    })
    await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW)
    assert model.calls == 1
    await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW)
    assert model.calls == 1
    item = (await editorial_session.execute(
        select(NewsItem).where(NewsItem.matched.is_(True))
    )).scalars().one()
    for nonce in (1, 2, 3):
        item.editorial_meta = {**(item.editorial_meta or {}), "retry_nonce": nonce}
        await editorial_session.flush()
        await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW)
    assert model.calls == discovery.MAX_OWNER_APPRAISALS
    assert item.editorial_meta["news_category"] == "ai"


def test_owner_prompt_carries_change_without_an_invented_story():
    from tce.news import appraise
    request = appraise.build_request(
        appraise.AppraisalInput(
            title="An AI capability", publisher="Vendor", published_at=NOW,
            primary_url="https://vendor.example/change", document=DOC,
            anchors=[], recent_evidence=[],
        ), workspace_id=WS, news_item_id=uuid.uuid4(), retry_fingerprint="proof",
    )
    assert "Keep the actual change" in request.system
    assert "Do not\ninvent a client anecdote" in request.system
    assert request.prompt_version == appraise.OWNER_PROMPT_VERSION
    assert request.idempotency_key.endswith(":proof")


def test_owner_policy_requires_explicit_configuration(monkeypatch):
    fallback = "30c13a7e-432f-4c3a-bade-52483262d793"
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(settings, "owner_workspace_ids", "")
    assert not news_rules.owner_policy(fallback)
    monkeypatch.setattr(settings, "owner_workspace_ids", f"invalid, {WS}")
    assert news_rules.owner_policy(WS)
    assert not news_rules.owner_policy(fallback)


@pytest.mark.asyncio
async def test_new_capability_gets_only_a_relevant_human_standing_problem(editorial_session):
    await _setup(editorial_session, [
        StandingFact("problem_pattern", "leads go cold",
                     "Enquiries go cold when nobody follows up by email."),
        StandingFact("problem_pattern", "discounting",
                     "Owners discount good work when a buyer resists the price."),
    ])
    item = NewsItem(
        id=uuid.uuid4(), workspace_id=WS, external_id="new-uninstalled-tool",
        title="Acme launches AI follow-up emails", summary="New follow-up emails after enquiries.",
        url="https://vendor.example/change", matched=True, published_at=NOW,
        source_tier="1b", fetched_at=NOW,
    )
    editorial_session.add(item)
    await editorial_session.flush()
    anchors, ids, recent, demo = await discovery._anchor_moments(
        editorial_session, WS, item, NOW,
    )
    moments = (await editorial_session.execute(select(EvidenceMoment).where(
        EvidenceMoment.id.in_([uuid.UUID(i) for i in ids]),
    ))).scalars().all()
    assert len(moments) == 1
    assert "Enquiries go cold" in moments[0].lesson_summary
    assert anchors[0]["kind"] == "problem_pattern"
    assert recent == [] and demo is False
    # This fallback must not assert that the owner uses the newly announced tool.
    assert not any(a["kind"] == "vendor" for a in anchors)
    assert (await discovery._anchor_moments(
        editorial_session, uuid.uuid4(), item, NOW,
    ))[1] == []
    # A fact whose source has changed is no longer evidence for this version.
    source = await editorial_session.get(EvidenceSource, moments[0].source_id)
    source.version_hash = "superseded"
    await editorial_session.flush()
    assert (await discovery._anchor_moments(editorial_session, WS, item, NOW))[1] == []


def test_scout_angle_is_separate_from_verified_evidence_in_prompt():
    from tce.news import appraise
    prompt = appraise.build_prompt(appraise.AppraisalInput(
        title="A new release", publisher="Vendor", published_at=NOW,
        primary_url="https://vendor.example/change", document=DOC,
        anchors=[], recent_evidence=[],
        editorial_notes=["Explore an honest follow-up email test."],
    ))
    assert "Explore an honest follow-up email test." in prompt
    assert "EDITOR SUGGESTIONS (directions, not verified evidence" in prompt


@pytest.mark.asyncio
async def test_latest_editor_note_reaches_selector_and_changes_retry_fingerprint(editorial_session):
    source, moment = await _published_news(editorial_session)
    item = NewsItem(
        id=uuid.uuid4(), workspace_id=WS, external_id="published-with-scout-angle",
        title="New follow-up tool", url="https://vendor.example/follow-up",
        matched=True, published_at=NOW, source_tier="1b", fetched_at=NOW,
        editorial_meta={"submissions": [{"angle": "Try a proposal based on cold enquiries."}]},
    )
    editorial_session.add(item)
    moment.news_ref = {**moment.news_ref, "news_item_id": str(item.id)}
    await editorial_session.flush()
    before = await discovery.selection_fingerprint(editorial_session, WS, source, moment)
    item.editorial_meta = {**item.editorial_meta, "retry_requests": [
        {"reason": "Keep this an untested proposal, and narrow it to unanswered leads."},
    ]}
    await editorial_session.flush()
    after = await discovery.selection_fingerprint(editorial_session, WS, source, moment)
    assert before != after
    pool = await selector.collect_pool(editorial_session, WS, NOW, source_ids=[source.id])
    rendered = selector._pool_prompt_item(pool.moments[0])
    assert rendered["editor_suggestions_not_evidence"] == [
        "Try a proposal based on cold enquiries.",
        "Keep this an untested proposal, and narrow it to unanswered leads.",
    ]


async def _reviewed_pool(session):
    now = datetime.utcnow()
    await _setup(session, [
        StandingFact("problem_pattern", "cold enquiries",
                     "Enquiries go cold when nobody follows up by email."),
    ])
    moment = (await session.execute(select(EvidenceMoment).where(
        EvidenceMoment.workspace_id == WS,
    ))).scalars().one()
    source = await session.get(EvidenceSource, moment.source_id)
    anchor = selector.PoolMoment(moment, source, False)
    item = NewsItem(
        id=uuid.uuid4(), workspace_id=WS, external_id="reviewed-news",
        title="New follow-up emails", url="https://vendor.example/follow-up",
        primary_url="https://vendor.example/follow-up",
        matched=True, published_at=now - timedelta(days=1), source_tier="1b", fetched_at=now,
        editorial_meta={"news_category": "ai"},
    )
    news = _news_pm([anchor.id])
    news.moment.news_ref = {
        **news.moment.news_ref, "news_item_id": str(item.id),
        "published_at": item.published_at.isoformat(),
        "expires_at": (now + timedelta(days=4)).isoformat(), "news_category": "ai",
        "scores": {"owner_relevance": 5, "consequence_specificity": 4, "distinctiveness": 4},
    }
    session.add_all([item, news.source, news.moment])
    await session.flush()
    return [news, anchor]


@pytest.mark.asyncio
async def test_reviewed_news_import_is_idempotent_and_keeps_real_proof(editorial_session):
    pool = await _reviewed_pool(editorial_session)
    raw = _candidate([pm.id for pm in pool])
    row = await selector.save_reviewed_news_candidate(editorial_session, WS, raw, pool, "review-1")
    again = await selector.save_reviewed_news_candidate(editorial_session, WS, raw, pool, "review-1")
    assert row.id == again.id
    assert row.status == "proposed" and row.job_id is None
    assert row.gates["_news_category"] == "ai"
    assert row.rank_score >= .70
    assert {c["source_kind"] for c in row.citations_private} == {"news_item", "standing_fact"}
    assert "review-1" in row.editor_notes
    assert len((await editorial_session.execute(select(TopicCandidate))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_reviewed_news_import_refuses_false_gate(editorial_session):
    pool = await _reviewed_pool(editorial_session)
    raw = _candidate([pm.id for pm in pool])
    raw["gates"]["concrete_supported_substance"]["pass"] = False
    with pytest.raises(ValueError, match="gate"):
        await selector.save_reviewed_news_candidate(editorial_session, WS, raw, pool, "review-bad")


@pytest.mark.asyncio
async def test_reviewed_news_import_refuses_foreign_proof(editorial_session):
    pool = await _reviewed_pool(editorial_session)
    pool[1].moment.workspace_id = uuid.uuid4()
    await editorial_session.flush()
    with pytest.raises(ValueError, match="proof"):
        await selector.save_reviewed_news_candidate(
            editorial_session, WS, _candidate([pm.id for pm in pool]), pool, "review-foreign",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["expired", "weak", "stale"])
async def test_reviewed_news_import_keeps_quality_and_proof_checks(editorial_session, invalid):
    pool = await _reviewed_pool(editorial_session)
    if invalid == "expired":
        pool[0].moment.news_ref = {
            **pool[0].moment.news_ref,
            "expires_at": (datetime.utcnow() - timedelta(days=1)).isoformat(),
        }
    elif invalid == "weak":
        pool[0].moment.news_ref = {**pool[0].moment.news_ref, "scores": {}}
    else:
        pool[1].source.version_hash = "changed"
    await editorial_session.flush()
    with pytest.raises(ValueError):
        await selector.save_reviewed_news_candidate(
            editorial_session, WS, _candidate([pm.id for pm in pool]), pool, "review-invalid",
        )


@pytest.mark.asyncio
async def test_owner_submitted_secondary_is_held_until_primary_is_verified(editorial_session):
    await _setup(editorial_session, [StandingFact("vendor", "twilio", "We run Twilio reception.")])

    async def unresolved(url):
        return {"title": "Twilio launches better call routing", "body_text": DOC,
                "published_at": NOW, "source_verified": False,
                "status": "primary_unresolved", "primary_url": url}

    result = await discovery.check_one(
        editorial_session, WS, url="https://secondary.example/story",
        fetch_text=unresolved, now=NOW,
    )
    assert result["status"] == "unverified"
    item = await editorial_session.get(NewsItem, uuid.UUID(result["item_id"]))
    assert not item.matched and item.primary_url is None
    assert item.source_tier == "2" and item.prefilter_reason == "unverified_source"


@pytest.mark.asyncio
async def test_rechecking_legacy_manual_source_holds_the_existing_row(editorial_session):
    url = "https://secondary.example/legacy"
    old = NewsItem(
        id=uuid.uuid4(), workspace_id=WS, external_id="old-manual", url=url, primary_url=url,
        title="Old claimed primary", source_tier="1a", matched=True, published_at=NOW,
        fetched_at=NOW,
    )
    editorial_session.add(old)
    await editorial_session.flush()

    async def unresolved(url):
        return {"title": "Secondary article", "body_text": DOC, "source_verified": False}

    result = await discovery.check_one(editorial_session, WS, url=url, fetch_text=unresolved, now=NOW)
    assert result["item_id"] == str(old.id)
    assert old.matched is False and old.primary_url is None


@pytest.mark.asyncio
async def test_owner_submission_uses_resolved_primary_and_retains_discovery_url(editorial_session):
    await _setup(editorial_session, [StandingFact("vendor", "twilio", "We run Twilio reception.")])
    primary = "https://www.twilio.com/en-us/changelog/call-routing"
    secondary = "https://secondary.example/story"

    async def resolved(url):
        return {"title": "Twilio launches better call routing", "body_text": DOC,
                "published_at": NOW - timedelta(days=1), "source_verified": True,
                "status": "ok", "primary_url": primary, "discovery_url": secondary}

    result = await discovery.check_one(
        editorial_session, WS, url=secondary, fetch_text=resolved, now=NOW,
    )
    item = await editorial_session.get(NewsItem, uuid.UUID(result["item_id"]))
    assert item.matched and item.primary_url == primary
    assert item.url == secondary
    assert item.editorial_meta["discovery_url"] == secondary


@pytest.mark.parametrize("protected", ["selected", "ready", "recorded"])
def test_workflow_keeps_human_work_visible_over_a_newer_proposal(protected):
    from tce.editorial import news_workflow
    old = SimpleNamespace(id=uuid.uuid4(), created_at=NOW, status="proposed")
    newer = SimpleNamespace(id=uuid.uuid4(), created_at=NOW + timedelta(days=1), status="proposed")
    packets, uploads = {}, set()
    if protected == "selected":
        old.status = "selected"
    elif protected == "ready":
        packets[old.id] = SimpleNamespace(status="ready")
    else:
        uploads.add(old.id)
    assert news_workflow.choose_news_candidate([newer, old], packets, uploads) is old


@pytest.mark.asyncio
async def test_workflow_counts_all_ready_briefs_even_when_one_story_card_is_shown(editorial_session):
    from tce.editorial import news_workflow
    from tce.models.editorial import RecordingPacket
    pool = await _reviewed_pool(editorial_session)
    raw = _candidate([pm.id for pm in pool])
    older = await selector.save_reviewed_news_candidate(editorial_session, WS, raw, pool, "older-review")
    newer = await selector.save_reviewed_news_candidate(editorial_session, WS, raw, pool, "newer-review")
    older.status = "selected"
    for candidate in (older, newer):
        editorial_session.add(RecordingPacket(
            id=uuid.uuid4(), workspace_id=WS, candidate_id=candidate.id,
            version=1, bullets=[], script_phrases=[], status="ready",
        ))
    await editorial_session.flush()
    status = await news_workflow.workflow_status(editorial_session, WS)
    assert len(status["queue"]) == 1
    assert status["queue"][0]["candidate_id"] == str(older.id)
    assert status["ready_to_record"] == 2
