"""T-21041: the morning news appraisal must not load whole meeting records.

The live editor jumped to 3.5 GB resident (peak 6.4 GB) every morning at the
05:15 news appraisal and kept about 2.4 GB afterward. Its own hourly memory
reading, taken mid-run, held 1.4 million lists and 1.4 million dicts: parsed
meeting payloads. Each appraised story looked up recent evidence by loading up
to 200 full evidence records, meeting transcripts included, only to read one
key ("repo") from them; the repo anchors did the same over 90 days of commits.

These tests seed heavy meeting payloads and check the lookups read only what
they use: no evidence record (and so no payload) is loaded into the session,
and the memory the call needs stays small.
"""
from __future__ import annotations

import tracemalloc
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from tce.models.editorial import EvidenceMoment, EvidenceSource
from tce.models.news import NewsAnchor, NewsItem, NewsMatch
from tce.news import discovery
from tce.news.anchors import build_anchor_index, repos_from_commit_evidence
from tce.news.standing import StandingFact, seed_standing_facts
from tce.settings import settings

WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
NOW = datetime(2026, 10, 14, 9)
MEETINGS = 30
SEGMENTS = 2000


@pytest.fixture(autouse=True)
def configured_owner(monkeypatch):
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(WS))
    monkeypatch.setattr(settings, "owner_workspace_ids", "")


def _transcript(n: int) -> dict:
    return {
        "title": f"Client call {n}",
        "transcript": [
            {"speaker": "Ziv", "start": i, "end": i + 1, "text": f"segment {i} of call {n}"}
            for i in range(SEGMENTS)
        ],
    }


async def _seed(session) -> NewsItem:
    await seed_standing_facts(session, WS, [
        StandingFact("vendor", "twilio", "We operate shop reception on Twilio."),
    ], now=NOW)
    await session.flush()
    await build_anchor_index(session, WS, now=NOW)
    anchor = (await session.execute(select(NewsAnchor).where(
        NewsAnchor.workspace_id == WS, NewsAnchor.kind == "vendor",
        NewsAnchor.normalized_term == "twilio",
    ))).scalars().one()
    item = NewsItem(
        id=uuid.uuid4(), workspace_id=WS, external_id="twilio-change",
        url="https://vendor.example/change", primary_url="https://vendor.example/change",
        title="Twilio call routing change", matched=True, source_tier="1a",
        published_at=NOW - timedelta(days=3), fetched_at=NOW,
        extract_private="Forwarded calls fall back to voicemail.", content_sha256="a" * 64,
    )
    session.add(item)
    await session.flush()
    session.add(NewsMatch(
        id=uuid.uuid4(), workspace_id=WS, news_item_id=item.id, anchor_id=anchor.id,
        match_kind="vendor", matched_span="twilio", score=1,
    ))
    for n in range(MEETINGS):
        source = EvidenceSource(
            id=uuid.uuid4(), workspace_id=WS, source_kind="fathom_meeting",
            external_id=f"call-{n}", version_hash="v1",
            occurred_at=NOW - timedelta(hours=n + 1), fetch_status="ok",
            payload_private=_transcript(n),
        )
        session.add(source)
        session.add(EvidenceMoment(
            id=uuid.uuid4(), workspace_id=WS, source_id=source.id, source_version_hash="v1",
            excerpt_private=f"Call {n}: nothing about phones.",
            lesson_summary="Unrelated lesson.", claim_type="paraphrased",
            speaker_confidence="high", status="active", sensitivity_flags=[],
        ))
    proof = EvidenceSource(
        id=uuid.uuid4(), workspace_id=WS, source_kind="fathom_meeting",
        external_id="call-proof", version_hash="v1", occurred_at=NOW - timedelta(days=1),
        fetch_status="ok", payload_private=_transcript(999),
    )
    session.add(proof)
    session.add(EvidenceMoment(
        id=uuid.uuid4(), workspace_id=WS, source_id=proof.id, source_version_hash="v1",
        excerpt_private="Twilio missed-call routing is the owner's problem.",
        lesson_summary="Check Twilio routing after closing.", claim_type="demonstrated",
        speaker_confidence="high", status="active", sensitivity_flags=[],
    ))
    for n in range(MEETINGS):
        session.add(EvidenceSource(
            id=uuid.uuid4(), workspace_id=WS, source_kind="github_commit_group",
            external_id=f"kivimedia/busy-repo@{n}", version_hash=f"c{n}",
            occurred_at=NOW - timedelta(days=2),
            payload_private={"repo": "kivimedia/busy-repo", **_transcript(n)},
        ))
    await session.flush()
    item_id = item.id
    session.expunge_all()
    return await session.get(NewsItem, item_id)


def _sources_in(session) -> int:
    return sum(isinstance(o, EvidenceSource) for o in session.identity_map.values())


@pytest.mark.asyncio
async def test_appraisal_evidence_lookup_never_loads_meeting_payloads(editorial_session):
    item = await _seed(editorial_session)
    assert _sources_in(editorial_session) == 0

    tracemalloc.start()
    try:
        _, ids, recent, demo = await discovery._anchor_moments(
            editorial_session, WS, item, NOW,
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # The answer is unchanged: the one call that names Twilio is found and cited.
    assert [r["lesson_summary"] for r in recent] == ["Check Twilio routing after closing."]
    assert recent[0]["source_kind"] == "fathom_meeting"
    assert recent[0]["occurred_at"] == (NOW - timedelta(days=1)).date().isoformat()
    assert recent[0]["moment_id"] in ids
    assert demo is True
    # And nothing heavy was held to get it.
    assert _sources_in(editorial_session) == 0, "a whole evidence record was loaded"
    assert peak < 8 * 1024 * 1024, f"one story's evidence lookup peaked at {peak / 1e6:.1f} MB"


@pytest.mark.asyncio
async def test_repo_anchors_read_only_the_repo_name(editorial_session):
    await _seed(editorial_session)
    tracemalloc.start()
    try:
        anchors = await repos_from_commit_evidence(editorial_session, WS, now=NOW)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert [(a.origin_ref, a.weight) for a in anchors] == [("kivimedia/busy-repo", 1.0)]
    assert _sources_in(editorial_session) == 0, "a whole commit record was loaded"
    assert peak < 8 * 1024 * 1024, f"repo anchors peaked at {peak / 1e6:.1f} MB"
