"""14-Oct: the news lane found nothing for three weeks while news arrived daily.

Ziv: "tce also is failing on ai news ... fix it so it can find things! there are
valid news almost every day!" Live funnel, 14 days: 877 items, 132 matched, 116
appraisals ever, 1 publish ever, 0 topics. Each test here is one place it died.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from tce.api.routers import content_runs
from tce.editorial import news_rules
from tce.models.editorial import EvidenceMoment, EvidenceSource, TopicCandidate
from tce.models.news import NewsAppraisal, NewsFeed
from tce.news import appraise, discovery
from tce.news.standing import StandingFact, seed_standing_facts
from tce.settings import settings

WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
NOW = datetime(2026, 10, 14, 9, 0, 0)

FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>tag:v,2026:twilio</id>
    <title>Twilio changes how call forwarding falls back when nobody answers</title>
    <link rel="alternate" href="https://vendor.example/r/forwarding"/>
    <updated>2026-10-13T08:00:00Z</updated>
    <summary>A new fallback parameter for unanswered forwarded calls.</summary>
  </entry>
  <entry>
    <id>tag:v,2026:stripe</id>
    <title>Stripe changes how payment links expire</title>
    <link rel="alternate" href="https://vendor.example/r/links"/>
    <updated>2026-10-13T10:00:00Z</updated>
    <summary>Payment links now expire after ninety days.</summary>
  </entry>
</feed>
"""

DOC = (
    "Forwarded calls that are not answered now fall back to the configured "
    "voicemail after twenty seconds. Payment links now expire after ninety days."
)

PUBLISH = {
    "verdict": "publish",
    "verdict_reason": "Changes what happens to a shop's unanswered calls.",
    "what_happened": "Unanswered forwarded calls now fall back to voicemail.",
    "audience_consequence": "A shop owner's missed calls route differently.",
    "distinct_claim": "I run reception for shops and can say what this changes.",
    "do_differently": ["Check where an unanswered forwarded call ends up."],
    "confirmed_facts": [
        {"claim": "There is a fallback", "quote": "fall back to the configured voicemail"}
    ],
    "ziv_interpretation": ["Most owners never check this path."],
    "predictions": ["Fewer calls will die silently."],
    "format": "changes_my_product",
    "perishability": "week",
    "story_weight": "small",
    "weight_reason": "",
    "scores": {"owner_relevance": 5, "consequence_specificity": 4, "distinctiveness": 4},
}

PROBLEM = StandingFact(
    "problem_pattern", "nobody picks up the phone once the office closes",
    "Calls die in voicemail after hours.",
)


@pytest.fixture
def lane(monkeypatch):
    monkeypatch.setattr(settings, "news_lane", True)


class Pages:
    async def __call__(self, url):
        return {"body_text": DOC}


class Model:
    def __init__(self, answer=PUBLISH):
        self.answer, self.calls = answer, 0

    async def __call__(self, request):
        self.calls += 1
        return SimpleNamespace(structured=self.answer, job_id=uuid.uuid4())


async def _discover(session):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=FEED))
    )
    async with client:
        return await discovery.discover(session, WS, client=client, fetch_text=Pages(), now=NOW)


async def _setup(session, facts):
    session.add(
        NewsFeed(id=uuid.uuid4(), workspace_id=WS, name="Vendor", url="https://vendor.example/f",
                 kind="atom", tier="1a", enabled=True, consecutive_failures=0,
                 items_seen_total=0)
    )
    await seed_standing_facts(session, WS, facts, now=NOW)
    await session.flush()


# --- B: vendor news had nothing of his to cite --------------------------------


@pytest.mark.asyncio
async def test_a_stack_fact_makes_vendor_news_citable(editorial_session, lane):
    """Reproduction: 69 of 116 appraisals were parked without a model call because
    a vendor match (anthropic, claude code, google workspace...) had nothing to
    cite unless a commit's text happened to name the vendor. A standing fact about
    what Kivi Media runs on that vendor is the citable connection."""
    await _setup(editorial_session, [
        PROBLEM,
        StandingFact("vendor", "twilio",
                     "Kivi Media runs AI phone reception on Twilio numbers for small shops."),
    ])
    await _discover(editorial_session)
    model = Model()
    out = await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW, cap=5)
    assert model.calls >= 1, out
    assert out["published"] >= 1, out


# --- C: auto-parks ate the daily cap ------------------------------------------


@pytest.mark.asyncio
async def test_parking_an_unanchored_item_does_not_spend_the_daily_cap(editorial_session, lane):
    """Reproduction: an auto-park counted as one of the 5 a day. Newest first, the
    unanchored Stripe item took the only slot and the Twilio item, which had
    something to cite, waited until it went stale."""
    await _setup(editorial_session, [PROBLEM])
    src = EvidenceSource(
        id=uuid.uuid4(), workspace_id=WS, source_kind="github_commit_group",
        external_id="kivimedia/receptionist@abc", version_hash="v1",
        occurred_at=NOW - timedelta(days=3), fetch_status="ok",
        payload_private={"repo": "kivimedia/receptionist", "commits": []},
    )
    editorial_session.add(src)
    editorial_session.add(EvidenceMoment(
        id=uuid.uuid4(), workspace_id=WS, source_id=src.id, source_version_hash="v1",
        excerpt_private="Route unanswered Twilio calls to the after-hours voicemail.",
        lesson_summary="Unanswered calls should land somewhere, not ring out.",
        claim_type="demonstrated", speaker_confidence="high", status="active",
        sensitivity_flags=[],
    ))
    await editorial_session.flush()
    await _discover(editorial_session)
    model = Model()
    await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW, cap=1)
    await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW, cap=1)
    assert model.calls == 1, "the citable item never reached the model"


@pytest.mark.asyncio
async def test_a_parked_item_comes_back_once_it_has_something_to_cite(editorial_session, lane):
    await _setup(editorial_session, [PROBLEM])
    await _discover(editorial_session)
    model = Model()
    await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW)
    assert model.calls == 0
    parked = (await editorial_session.execute(select(NewsAppraisal))).scalars().all()

    # Parking again while still unanchored writes nothing new.
    await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW)
    again = (await editorial_session.execute(select(NewsAppraisal))).scalars().all()
    assert len(again) == len(parked), "the same item was parked twice"

    await seed_standing_facts(editorial_session, WS, [
        PROBLEM,
        StandingFact("vendor", "stripe",
                     "Kivi Media runs Stripe payments inside the booking systems it builds."),
    ], now=NOW)
    await _discover(editorial_session)  # rebuilds the anchor index
    out = await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW)
    assert model.calls == 1, out


# --- D: the appraiser prompt argued against his own answers -------------------


def test_the_appraiser_no_longer_rejects_what_anyone_could_say():
    """16-Sep, settled: "any creator could say it" is NOT why he rejects a topic."""
    prompt = appraise.SYSTEM_PROMPT
    assert "If anyone with the link could write it, reject" not in prompt
    assert "is expected most of the time" not in prompt
    assert "has no interest in being one" not in prompt


def test_the_appraiser_carries_his_reasons_and_his_correction():
    prompt = appraise.SYSTEM_PROMPT
    for reason in ("too niche", "click-bait", "corporate", "what he actually does"):
        assert reason in prompt, reason
    assert "sharing it is the job" in prompt
    assert appraise.PROMPT_VERSION == "news_appraisal.v2"


# --- A: the daily run never turned a publish into a topic ---------------------


async def _published_news(session, *, days_ago=1):
    src = EvidenceSource(
        id=uuid.uuid4(), workspace_id=WS, source_kind="news_item",
        external_id=str(uuid.uuid4()), version_hash="v1", fetch_status="ok",
        occurred_at=NOW - timedelta(days=days_ago), title="Skills arrive in Gemini",
        payload_private={},
    )
    moment = EvidenceMoment(
        id=uuid.uuid4(), workspace_id=WS, source_id=src.id, source_version_hash="v1",
        excerpt_private="q", lesson_summary="l", claim_type="quoted",
        speaker_confidence="high", status="active", sensitivity_flags=[],
        news_ref={"expires_at": (NOW + timedelta(days=5)).isoformat(),
                  "anchor_moment_ids": []},
    )
    session.add_all([src, moment])
    await session.flush()
    return src, moment


@pytest.mark.asyncio
async def test_published_news_with_no_topic_is_waiting_for_one(editorial_session):
    src, _ = await _published_news(editorial_session)
    assert await discovery.news_awaiting_topic(editorial_session, WS, now=NOW) == [src.id]


@pytest.mark.asyncio
async def test_news_the_selector_already_judged_is_not_tried_again(editorial_session):
    src, moment = await _published_news(editorial_session)
    editorial_session.add(TopicCandidate(
        id=uuid.uuid4(), workspace_id=WS, week_start=NOW, moment_ids=[str(moment.id)],
        title="Rejected: model_rejected", lesson="l", audience="both", reasons_to_care=[],
        public_angle="a", gates={}, status="rejected", origin="selector_rejected",
    ))
    await editorial_session.flush()
    assert await discovery.news_awaiting_topic(editorial_session, WS, now=NOW) == []


@pytest.mark.asyncio
async def test_expired_news_is_not_waiting(editorial_session):
    src, moment = await _published_news(editorial_session)
    moment.news_ref = {**moment.news_ref, "expires_at": (NOW - timedelta(hours=1)).isoformat()}
    await editorial_session.flush()
    assert await discovery.news_awaiting_topic(editorial_session, WS, now=NOW) == []


@pytest.mark.asyncio
async def test_the_daily_run_turns_published_news_into_topics(
    editorial_sessionmaker, monkeypatch
):
    """Reproduction: the daily run's last stage is extracting. Only Monday's run
    selects, so news judged on a Tuesday expired before anything could pick it."""
    monkeypatch.setattr(settings, "news_lane", True)
    async with editorial_sessionmaker() as session:
        src, _ = await _published_news(session)
        await session.commit()

    async def appraised(*args, **kwargs):
        return {"appraised": 1, "published": 1}

    asked = {}

    async def fake_select(sm, ws, week, **kwargs):
        asked.update(kwargs, ws=ws)
        return SimpleNamespace(status="complete", candidates=[{"id": "c1", "title": "t"}],
                               rejected=[], detail=None)

    from tce.editorial import selector

    monkeypatch.setattr(discovery, "appraise_pending", appraised)
    monkeypatch.setattr(selector, "select_candidates", fake_select)
    run = SimpleNamespace(id=uuid.uuid4(), workspace_id=WS, scope_kind="week")
    out = await content_runs._news_step(editorial_sessionmaker, run, appraise=True)

    assert asked.get("source_ids") == [src.id], out
    assert asked.get("adds_only") is True
    assert asked.get("week_news_counts") is True
    assert out["topics"]["proposed"] == 1, out


# --- the weekly ceiling still holds across daily runs -------------------------


def test_a_news_idea_already_on_this_weeks_list_counts_toward_the_ceiling():
    news = {"news": {"story_weight": "small"}, "score": 0.9}
    decision = news_rules.apply_slot_rules(
        [news],
        is_news=lambda c: bool(c.get("news")),
        score_of=lambda c: c["score"],
        story_weight_of=lambda c: c["news"]["story_weight"],
        already=1,
    )
    assert decision.kept == [] and decision.rejected[0][1] == news_rules.CODE_CEILING
