"""His own words on this subject reach the writer, and never block it.

A rule list makes a model obedient. What makes it sound like him is hearing him
first, on the thing it is about to write about.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from tce.editorial import voice_retrieval as vr
from tce.models.voice_sample import VoiceSample
from tests.unit.test_editorial_coverage_status import real_queue  # noqa: F401 - fixture

WS = uuid.uuid4()

PRICING = (
    "Based on ten different factors in your life, the sky, the weather, your tummy "
    "feeling, whether you have been to the gym, whether you are busy with other "
    "bookings, there are ten factors that might affect your decision about your price."
)
FUNNEL = (
    "When the sales are low you check the conversion at each step separately, page to "
    "sign up, sign up to sale, and then you know which stage is actually leaking."
)
COURSES = (
    "A course module is a problem that somebody solves, and the mistake is to build it "
    "around a topic you happen to know instead of the problem in their way."
)


async def add(sm, text, *, opening="", when=datetime(2026, 9, 18), kind="teaching", ws=WS):
    from tce.editorial.dedupe import tokens

    row = VoiceSample(
        id=uuid.uuid4(),
        workspace_id=ws,
        source_id=uuid.uuid4(),
        source_title="A call",
        occurred_at=when,
        first_turn_index=0,
        turn_count=3,
        language="en",
        text=text,
        word_count=len(text.split()),
        opening=opening,
        kind=kind,
        keywords=sorted(tokens(text)),
    )
    async with sm() as s:
        s.add(row)
        await s.commit()
    return row


async def test_the_closest_mini_speech_to_the_idea_comes_first(editorial_sessionmaker):
    sm = editorial_sessionmaker
    await add(sm, PRICING)
    await add(sm, FUNNEL)
    await add(sm, COURSES)

    async with sm() as s:
        out = await vr.for_idea(
            s,
            WS,
            title="Before you blame the marketing, find the stage that is leaking",
            lesson="Check conversion at each stage of the funnel separately.",
        )

    assert out
    assert "conversion at each step" in out[0].text


async def test_a_stretch_that_shares_nothing_is_not_offered_as_evidence(editorial_sessionmaker):
    sm = editorial_sessionmaker
    await add(sm, COURSES)

    async with sm() as s:
        out = await vr.for_idea(s, WS, title="Wedding photography lighting", lesson="Flash angles.")

    assert out == []


async def test_only_teaching_stretches_are_shown(editorial_sessionmaker):
    sm = editorial_sessionmaker
    await add(sm, FUNNEL, kind="operating")

    async with sm() as s:
        out = await vr.for_idea(s, WS, title="Funnel stages", lesson="Check conversion.")

    assert out == []


async def test_another_workspace_is_never_read(editorial_sessionmaker):
    sm = editorial_sessionmaker
    await add(sm, FUNNEL, ws=uuid.uuid4())

    async with sm() as s:
        out = await vr.for_idea(s, WS, title="Funnel stages", lesson="Check conversion.")

    assert out == []


async def test_the_opening_bank_is_real_first_sentences_deduplicated(editorial_sessionmaker):
    sm = editorial_sessionmaker
    await add(sm, PRICING, opening="Most coaches price by how they feel that morning.")
    await add(sm, FUNNEL, opening="Most coaches price by how they feel that morning.")
    await add(sm, COURSES, opening="Great question.")  # too short to be a shape

    async with sm() as s:
        bank = await vr.opening_bank(s, WS)

    assert bank == ["Most coaches price by how they feel that morning."]


async def test_the_block_tells_the_writer_not_to_quote_any_of_it(editorial_sessionmaker):
    sm = editorial_sessionmaker
    await add(sm, PRICING, opening="Most coaches price by how they feel that morning.")

    async with sm() as s:
        block, used = await vr.block_for_idea(
            s, WS, title="Your minimum price", lesson="Keep the floor price internal."
        )

    assert "HOW ZIV TALKS" in block
    assert "Do NOT quote any of it" in block
    assert "tummy feeling" in block  # his words are there
    assert "HOW HE STARTS" in block
    assert used["samples"] and used["sample_words"] > 0


async def test_an_empty_corpus_is_simply_no_block(editorial_sessionmaker):
    async with editorial_sessionmaker() as s:
        block, used = await vr.block_for_idea(s, WS, title="Anything", lesson="At all.")

    assert block == ""
    assert used == {"samples": [], "sample_words": 0, "openings": 0}


async def test_a_broken_corpus_never_stops_a_script_and_says_why(editorial_sessionmaker):
    # The corpus improves a script; it is not a precondition for one. A missing table
    # or an unhappy database must not cost him the packet.
    from sqlalchemy.exc import OperationalError

    async def boom(*_a, **_kw):
        raise OperationalError("select", {}, Exception("no such table: voice_samples"))

    async with editorial_sessionmaker() as s:
        original = vr.for_idea
        vr.for_idea = boom
        try:
            block, used = await vr.block_for_idea(s, WS, title="Anything", lesson="At all.")
        finally:
            vr.for_idea = original

    assert block == ""
    assert used["error"] == "OperationalError"  # reported, not swallowed


def test_the_score_rewards_covering_the_ideas_ground():
    wanted = frozenset({"funnel", "conversion", "stage"})

    assert vr.score(["funnel", "conversion", "stage", "webinar", "ads"], wanted) == 1.0
    assert vr.score(["funnel"], wanted) < 1.0
    assert vr.score([], wanted) == 0.0
    assert vr.score(["funnel"], frozenset()) == 0.0
