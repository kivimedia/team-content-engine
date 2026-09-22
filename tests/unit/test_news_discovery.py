"""The daily run, end to end, with the internet and the model both faked.

What these prove, in the order it matters: nothing happens when the lane is off;
a corporate item costs no page load and no model call; a matched item is
appraised once and becomes citable evidence anchored in his work; capacity
running out waits instead of failing; a stale idea leaves visibly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from tce.llm import LLMUnavailable
from tce.models.editorial import EvidenceMoment, EvidenceSource, TopicCandidate
from tce.models.news import NewsAppraisal, NewsFeed, NewsItem, NewsMatch
from tce.news import discovery
from tce.news.standing import StandingFact, seed_standing_facts
from tce.settings import settings

WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
NOW = datetime(2026, 9, 22, 9, 0, 0)

FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>tag:v,2026:1</id>
    <title>Twilio changes how call forwarding falls back when nobody answers</title>
    <link rel="alternate" href="https://vendor.example/r/forwarding"/>
    <updated>2026-09-21T08:00:00Z</updated>
    <summary>A new fallback parameter for unanswered forwarded calls.</summary>
  </entry>
  <entry>
    <id>tag:v,2026:2</id>
    <title>Vendor raises $400 million at a $9 billion valuation</title>
    <link rel="alternate" href="https://vendor.example/r/funding"/>
    <updated>2026-09-21T09:00:00Z</updated>
  </entry>
  <entry>
    <id>tag:v,2026:3</id>
    <title>A new theme for the settings page</title>
    <link rel="alternate" href="https://vendor.example/r/theme"/>
    <updated>2026-09-21T10:00:00Z</updated>
  </entry>
</feed>
"""

DOC = (
    "Forwarded calls that are not answered now fall back to the configured "
    "voicemail after twenty seconds. The fallback parameter is on by default."
)


@pytest.fixture
def lane(monkeypatch):
    monkeypatch.setattr(settings, "news_lane", True)


def feed_client():
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=FEED))
    )


class Pages:
    """A fake page fetcher that records every URL it was asked for."""

    def __init__(self, body=DOC, fail=False):
        self.body, self.fail, self.asked = body, fail, []

    async def __call__(self, url):
        self.asked.append(url)
        if self.fail:
            raise httpx.ConnectError("down")
        return {"body_text": self.body}


class Model:
    """A fake subscription worker. `answer` may be a dict or an exception."""

    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    async def __call__(self, request):
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return SimpleNamespace(structured=self.answer, job_id=uuid.uuid4())


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


async def _setup(session):
    """A feed, and a standing fact so an anchor is citable."""
    session.add(
        NewsFeed(id=uuid.uuid4(), workspace_id=WS, name="Vendor", url="https://vendor.example/f",
                 kind="atom", tier="1a", enabled=True, consecutive_failures=0,
                 items_seen_total=0)
    )
    await seed_standing_facts(
        session, WS,
        [StandingFact("problem_pattern", "nobody picks up the phone once the office closes",
                      "Calls die in voicemail after hours.")],
        now=NOW,
    )
    await session.flush()


# --- the lane is off ------------------------------------------------------------


@pytest.mark.asyncio
async def test_nothing_happens_when_the_lane_is_off(editorial_session, monkeypatch):
    monkeypatch.setattr(settings, "news_lane", False)
    pages, model = Pages(), Model(PUBLISH)
    async with feed_client() as client:
        a = await discovery.discover(
            editorial_session, WS, client=client, fetch_text=pages, now=NOW
        )
    b = await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW)
    assert "switched off" in a["skipped"] and "switched off" in b["skipped"]
    assert pages.asked == [] and model.calls == 0


# --- stage A --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_quiet_day_costs_a_page_load_only_for_what_matched(editorial_session, lane):
    await _setup(editorial_session)
    pages = Pages()
    async with feed_client() as client:
        out = await discovery.discover(
            editorial_session, WS, client=client, fetch_text=pages, now=NOW
        )

    assert out["items_new"] == 3
    assert out["matched"] == 1, out
    assert out["blocked_shape"] == 1, "the funding round was not caught by shape"
    assert out["no_anchor"] == 1, "the settings-page theme matched something it should not"
    assert pages.asked == ["https://vendor.example/r/forwarding"], (
        "a page was loaded for an item that never matched"
    )
    assert "1 matched something of his" in out["summary"]


@pytest.mark.asyncio
async def test_stage_a_never_calls_the_model(editorial_session, lane):
    """Structural: discover() does not even accept a model to call."""
    import inspect

    assert "complete" not in inspect.signature(discovery.discover).parameters
    assert "complete" not in inspect.signature(discovery.match_pending).parameters


@pytest.mark.asyncio
async def test_an_unreadable_announcement_is_retried_not_appraised(editorial_session, lane):
    await _setup(editorial_session)
    async with feed_client() as client:
        out = await discovery.discover(
            editorial_session, WS, client=client, fetch_text=Pages(fail=True), now=NOW
        )
    assert out["matched"] == 0 and out["unverified"] == 1
    item = (
        await editorial_session.execute(
            select(NewsItem).where(NewsItem.title.like("Twilio%"))
        )
    ).scalar_one()
    assert item.matched is False and item.prefilter_reason is None, (
        "a page that failed once was written off for good"
    )


@pytest.mark.asyncio
async def test_the_same_feed_twice_matches_nothing_twice(editorial_session, lane):
    await _setup(editorial_session)
    async with feed_client() as client:
        await discovery.discover(editorial_session, WS, client=client, fetch_text=Pages(), now=NOW)
        again = await discovery.discover(
            editorial_session, WS, client=client, fetch_text=Pages(), now=NOW
        )
    assert again["items_new"] == 0 and again["matched"] == 0


# --- stage B --------------------------------------------------------------------


async def _commit_mentioning_twilio(session, *, days_ago=3, claim="demonstrated"):
    """His own recent work that names the vendor: what makes the news citable."""
    src = EvidenceSource(
        id=uuid.uuid4(), workspace_id=WS, source_kind="github_commit_group",
        external_id=f"kivimedia/receptionist@{uuid.uuid4().hex[:8]}", version_hash="v1",
        occurred_at=NOW - timedelta(days=days_ago), fetch_status="ok",
        payload_private={"repo": "kivimedia/receptionist", "commits": []},
    )
    session.add(src)
    session.add(
        EvidenceMoment(
            id=uuid.uuid4(), workspace_id=WS, source_id=src.id, source_version_hash="v1",
            excerpt_private="Route unanswered Twilio calls to the after-hours voicemail.",
            lesson_summary="Unanswered calls should land somewhere, not ring out.",
            claim_type=claim, speaker_confidence="high", status="active",
            sensitivity_flags=[],
        )
    )
    await session.flush()


async def _matched(session, *, with_commit=True):
    await _setup(session)
    if with_commit:
        await _commit_mentioning_twilio(session)
    async with feed_client() as client:
        await discovery.discover(session, WS, client=client, fetch_text=Pages(), now=NOW)


@pytest.mark.asyncio
async def test_a_matched_item_becomes_citable_evidence(editorial_session, lane):
    await _matched(editorial_session)
    model = Model(PUBLISH)
    out = await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW)
    assert out["published"] == 1 and model.calls == 1

    moment = (
        await editorial_session.execute(
            select(EvidenceMoment)
            .join(EvidenceSource, EvidenceMoment.source_id == EvidenceSource.id)
            .where(EvidenceSource.source_kind == "news_item")
        )
    ).scalar_one()
    assert moment.news_ref["anchor_moment_ids"], (
        "the news has nothing of his to cite; the selector would reject it"
    )


@pytest.mark.asyncio
async def test_an_item_is_appraised_once_only(editorial_session, lane):
    await _matched(editorial_session)
    model = Model(PUBLISH)
    await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW)
    await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW)
    assert model.calls == 1


@pytest.mark.asyncio
async def test_no_capacity_waits_instead_of_failing(editorial_session, lane):
    await _matched(editorial_session)
    out = await discovery.appraise_pending(
        editorial_session, WS,
        complete=Model(LLMUnavailable("waiting_capacity", "no capacity")),
        now=NOW,
    )
    assert out["waiting"] == 1 and out["appraised"] == 0
    assert (await editorial_session.execute(select(NewsAppraisal))).scalars().all() == [], (
        "an item was written off because the worker was busy"
    )
    later = await discovery.appraise_pending(
        editorial_session, WS, complete=Model(PUBLISH), now=NOW
    )
    assert later["published"] == 1, "the waiting item was not picked up next time"


@pytest.mark.asyncio
async def test_an_answer_that_fails_the_checks_is_recorded_not_retried(editorial_session, lane):
    await _matched(editorial_session)
    lying = {**PUBLISH, "confirmed_facts": [{"claim": "x", "quote": "not in the document"}]}
    out = await discovery.appraise_pending(editorial_session, WS, complete=Model(lying), now=NOW)
    assert out["invalid"] == 1 and out["rejected"] == 1
    row = (await editorial_session.execute(select(NewsAppraisal))).scalar_one()
    assert row.verdict == "reject" and "appraisal refused" in row.verdict_reason


@pytest.mark.asyncio
async def test_the_daily_cap_holds(editorial_session, lane):
    await _matched(editorial_session)
    out = await discovery.appraise_pending(editorial_session, WS, complete=Model(PUBLISH),
                                           now=NOW, cap=0)
    assert out["appraised"] == 0


# --- expiry ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stale_idea_leaves_visibly_and_a_recorded_one_stays(editorial_session):
    item_id = uuid.uuid4()
    editorial_session.add(
        NewsItem(id=item_id, workspace_id=WS, external_id="e", url="https://v/e", title="t",
                 source_tier="1a", matched=True)
    )
    stale = TopicCandidate(
        id=uuid.uuid4(), workspace_id=WS, week_start=NOW, moment_ids=[], title="stale",
        lesson="l", audience="both", reasons_to_care=[], public_angle="a", gates={},
        news_item_id=item_id, expires_at=NOW - timedelta(days=1), status="proposed",
    )
    recorded = TopicCandidate(
        id=uuid.uuid4(), workspace_id=WS, week_start=NOW, moment_ids=[], title="kept",
        lesson="l", audience="both", reasons_to_care=[], public_angle="a", gates={},
        news_item_id=item_id, expires_at=NOW - timedelta(days=1), status="recorded",
    )
    editorial_session.add_all([stale, recorded])
    await editorial_session.flush()

    out = await discovery.expire_sweep(editorial_session, WS, now=NOW)
    assert out["withdrawn"] == 1
    assert stale.status == "withdrawn" and "Went stale on Monday 21 September" in stale.editor_notes
    assert recorded.status == "recorded", "an idea he already recorded was withdrawn"


@pytest.mark.asyncio
async def test_a_changed_announcement_marks_the_idea_not_the_script(editorial_session, lane):
    await _matched(editorial_session)
    await discovery.appraise_pending(editorial_session, WS, complete=Model(PUBLISH), now=NOW)
    item = (
        await editorial_session.execute(select(NewsItem).where(NewsItem.matched.is_(True)))
    ).scalar_one()
    cand = TopicCandidate(
        id=uuid.uuid4(), workspace_id=WS, week_start=NOW, moment_ids=[], title="c", lesson="l",
        audience="both", reasons_to_care=[], public_angle="a", gates={},
        news_item_id=item.id, expires_at=NOW + timedelta(days=5), status="proposed",
    )
    editorial_session.add(cand)
    await editorial_session.flush()

    out = await discovery.refresh_live(
        editorial_session, WS, fetch_text=Pages(body=DOC + " Update: withdrawn."), now=NOW
    )
    assert out["changed"] == 1
    assert "Reread it before recording" in cand.editor_notes
    stale = (
        await editorial_session.execute(
            select(EvidenceMoment).where(EvidenceMoment.source_id == item.evidence_source_id)
        )
    ).scalars().all()
    assert {m.status for m in stale} == {"stale"}
    assert (await editorial_session.execute(select(NewsMatch))).scalars().all()


@pytest.mark.asyncio
async def test_a_vendor_name_with_nothing_of_his_behind_it_costs_no_model_call(
    editorial_session, lane
):
    """A match on a vendor proves the NAME is in his world, not that he did
    anything with it. With no commit and no standing fact to cite, the selector
    would reject whatever the model said, so the model is not asked."""
    await _matched(editorial_session, with_commit=False)
    model = Model(PUBLISH)
    out = await discovery.appraise_pending(editorial_session, WS, complete=model, now=NOW)
    assert model.calls == 0, "a model call was spent on an idea that could never be selected"
    assert out["watched"] == 1 and out.get("unanchored") == 1
    row = (await editorial_session.execute(select(NewsAppraisal))).scalar_one()
    assert row.verdict == "watch" and "nothing of yours is on record" in row.verdict_reason


@pytest.mark.asyncio
async def test_his_commit_after_the_announcement_unlocks_i_tested_it(editorial_session, lane):
    """The one format that can be faked needs work dated AFTER the announcement."""
    await _setup(editorial_session)
    # Published 21-Sep 08:00; this commit is 22-Sep, i.e. after it.
    await _commit_mentioning_twilio(editorial_session, days_ago=0)
    async with feed_client() as client:
        await discovery.discover(editorial_session, WS, client=client, fetch_text=Pages(), now=NOW)
    tested = {**PUBLISH, "format": "i_tested_it"}
    await discovery.appraise_pending(editorial_session, WS, complete=Model(tested), now=NOW)
    row = (await editorial_session.execute(select(NewsAppraisal))).scalar_one()
    assert row.format == "i_tested_it"


@pytest.mark.asyncio
async def test_work_from_before_the_announcement_does_not(editorial_session, lane):
    await _matched(editorial_session)  # the commit is three days before publication
    tested = {**PUBLISH, "format": "i_tested_it"}
    await discovery.appraise_pending(editorial_session, WS, complete=Model(tested), now=NOW)
    row = (await editorial_session.execute(select(NewsAppraisal))).scalar_one()
    assert row.format == "three_things_id_test"
