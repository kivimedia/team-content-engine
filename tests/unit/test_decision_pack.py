"""An idea put to him on a call carries what he needs to decide on the spot.

18 Nov call: 6 of 11 ideas could not be decided as presented. The call read
only the big idea, because the takeaway was empty on all 11, why now on 8, and
the evidence was a bare label ("From your call"). The idea below is seeded the
way "Your first launch is research, not a launch" (5ee40a9a) was: a seed brief
with no why now and no takeaway, four dated moments from his calls behind it,
and a script with points. Read through the editor and then through the call's
own topic tool, he must hear why now, what the source said, his angle, a
takeaway (marked as proposed) and the points, and an idea with nothing on
record must be named as not ready rather than put to him.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from tce.editorial import decision_pack
from tce.models.editorial import EvidenceMoment, EvidenceSource, TopicCandidate
from tests.unit.test_editorial_voice_agent import (  # noqa: F401 - fixtures used by name
    add_candidate,
    add_packet,
    client,
    headers,
)
from tests.unit.test_mcp_voice_tools import run, step

LESSON = (
    "Treat a new program launch as research and validation. Success means selling it "
    "to a handful of first buyers, around five."
)


async def seed_calls(sm, ws, cid, when=datetime(2026, 10, 26, 15, 31)):
    ids = []
    async with sm() as s:
        for n in range(2):
            source = EvidenceSource(
                workspace_id=ws,
                source_kind="fathom_meeting",
                external_id=f"call-{n}",
                title=f"Strategy session {n + 1}",
                version_hash="h",
                payload_private={},
                occurred_at=when,
            )
            s.add(source)
            await s.flush()
            moment = EvidenceMoment(
                workspace_id=ws,
                source_id=source.id,
                source_version_hash="h",
                excerpt_private="So you are starting to launch a program and I call this research.",
                lesson_summary=LESSON if n == 0 else "Hold 20 to 40 conversations first.",
                claim_type="observation",
            )
            s.add(moment)
            await s.flush()
            ids.append(str(moment.id))
        cand = await s.get(TopicCandidate, cid)
        cand.moment_ids = ids
        await s.commit()


async def read_topic(client, ws, cid):  # noqa: F811
    got = await client.get(
        "/api/v1/editorial/voice/topic", params={"id": str(cid)}, headers=headers(ws)
    )
    assert got.status_code == 200, got.text
    return got.json()


def spoken(found):
    """What the call's tce_topic says, fed the editor's own answer."""
    out = run(
        {
            "steps": [step("tce_topic", topic=found["topic"]["short_id"])],
            "responses": {
                "GET /editorial/voice/topic": {"ok": True, "status": 200, "data": found}
            },
        }
    )
    return out["texts"][0]


async def test_a_thin_idea_is_read_with_why_now_evidence_angle_takeaway_and_points(
    client, editorial_sessionmaker  # noqa: F811
):
    ws = uuid.uuid4()
    cid = await add_candidate(
        editorial_sessionmaker,
        ws,
        "Your first launch is research, not a launch",
        public_angle="The people you already know are where it starts.",
    )
    await seed_calls(editorial_sessionmaker, ws, cid)
    await add_packet(editorial_sessionmaker, ws, cid)

    found = await read_topic(client, ws, cid)
    values = found["topic"]["brief"]["values"]
    assert not values.get("why_now") and not values.get("takeaway"), "seeded thin, like 5ee40a9a"

    text = spoken(found)
    assert "Why now: It came up on your call on 26 Oct and 1 other call." in text, text
    assert "What the source said:" in text, text
    assert f"From your call on 26 Oct: {LESSON}" in text, text
    assert "Your angle: The people you already know are where it starts." in text, text
    assert "Proposed takeaway (not written yet, offer it): Third point." in text, text
    assert "The video would make these points:" in text and "  3. Third point." in text, text
    assert "Ready to decide" in text, text
    assert "Not ready" not in text, text


async def test_an_idea_with_nothing_on_record_is_named_not_ready(
    client, editorial_sessionmaker  # noqa: F811
):
    ws = uuid.uuid4()
    cid = await add_candidate(
        editorial_sessionmaker, ws, "Checking your system is a chore", moment_ids=[],
        citations_private=[],
    )
    found = await read_topic(client, ws, cid)
    pack = found["topic"]["decision_pack"]
    assert pack["ready"] is False
    assert pack["missing"][:3] == ["why now", "what the source said", "a takeaway"]

    text = spoken(found)
    assert "Still missing: why now, what the source said, a takeaway" in text, text
    assert "Not ready to decide yet" in text, text


def test_the_news_template_is_not_a_reason_and_a_dated_story_is():
    detail = {
        "brief": {
            "values": {
                "why_now": decision_pack.NEWS_TEMPLATE_PREFIX + ", so it is worth more.",
                "takeaway": "Share one skill, not ten.",
            }
        },
        "script": None,
    }
    evidence = [
        {"source_kind": "standing_fact", "title": "How he works", "lesson": "He runs workshops.",
         "occurred_at": "2026-09-22T13:15:49"},
        {"source_kind": "news_item", "title": "Gemini adds shared skills",
         "lesson": "Teams can share one skill.", "occurred_at": "2026-11-16T21:25:28"},
    ]
    pack = decision_pack.build(detail, evidence)
    assert pack["why_now"] == "In the news on 16 Nov: Gemini adds shared skills."
    assert pack["takeaway"] == "Share one skill, not ten." and pack["takeaway_proposed"] is False
    assert pack["ready"] is True
    assert pack["missing"] == ["the points the video would make", "your angle"]
    assert json.dumps(pack)  # it travels as JSON to the call


def test_a_closing_question_to_the_viewer_is_not_offered_as_the_takeaway():
    # dec839bc on 18 Nov: the script ends on "Your turn: which questions...?"
    detail = {
        "brief": {"values": {}},
        "script": {"points": [
            "Clients stop asking what they were trained not to ask.",
            "Silence is information, so ask again.",
            "Your turn: which questions have you trained clients not to ask?",
        ]},
    }
    pack = decision_pack.build(detail, [])
    assert pack["takeaway"] == "Silence is information, so ask again."
    assert pack["takeaway_proposed"] is True
