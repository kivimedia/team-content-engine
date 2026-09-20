"""More ideas comes from the reserve a selection run already validated.

"Show me more ideas" used to mean "show me more of the list I already loaded". When
the list ran out it had nothing to offer, while every run was throwing away a dozen
ideas that had passed all four gates and simply lost their week.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from tce.editorial import more_ideas
from tce.editorial.common import (
    ORIGIN_SELECTOR,
    ORIGIN_SELECTOR_REJECTED,
    ORIGIN_SELECTOR_RESERVE,
)
from tce.models.editorial import TopicCandidate
from tests.unit.test_editorial_coverage_status import (  # noqa: F401,F811 - fixtures
    gates_all_pass,
    real_queue,
    rows_for,
)

WEEK = datetime(2026, 9, 14)


def citation() -> dict:
    return {"moment_id": str(uuid.uuid4()), "source_kind": "meeting_transcript"}


async def add(
    sm,
    ws,
    title,
    *,
    lesson="A lesson that stands on its own and repeats nothing else.",
    status="rejected",
    origin=ORIGIN_SELECTOR_REJECTED,
    code="rank_cap",
    reserve=True,
    cites=True,
    score=0.8,
    week=WEEK,
) -> TopicCandidate:
    gates = gates_all_pass()
    if origin == ORIGIN_SELECTOR_REJECTED:
        gates["_rejection"] = {"gate": "unspecified", "code": code, "reason": f"cut: {code}"}
        gates["_reserve"] = reserve
    row = TopicCandidate(
        workspace_id=ws,
        week_start=week,
        moment_ids=[str(uuid.uuid4())],
        title=title,
        lesson=lesson,
        audience="both",
        reasons_to_care=["it helps"],
        public_angle=f"Angle for {title}",
        gates=gates,
        rank_score=score,
        freshness_role="evergreen",
        citations_private=[citation()] if cites else [],
        status=status,
        origin=origin,
        created_at=week,
        updated_at=week,
    )
    async with sm() as s:
        s.add(row)
        await s.commit()
    return row


async def test_a_cut_finalist_is_offered_as_another_idea(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await add(sm, ws, "The reserve idea nobody has seen yet")

    async with sm() as s:
        out = await more_ideas.offer_more(s, ws)

    assert out["added"] == 1
    assert out["candidates"][0]["title"] == "The reserve idea nobody has seen yet"
    assert "1 more idea on the list" in out["detail"]

    rows = await rows_for(sm, ws)
    row = next(r for r in rows if r.title == "The reserve idea nobody has seen yet")
    assert row.status == "proposed"
    assert row.origin == ORIGIN_SELECTOR_RESERVE  # never pretends it was chosen
    assert row.citations_private  # it kept its evidence
    assert "set aside" in (row.editor_notes or "")


async def test_an_idea_cut_for_cause_is_never_offered(editorial_sessionmaker):
    # Gate failures and duplicates were cut because they were wrong, not unlucky.
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await add(sm, ws, "Failed a gate", code="model_rejected", reserve=False)
    await add(sm, ws, "Repeats something on the list", code="duplicate_existing", reserve=False)

    async with sm() as s:
        out = await more_ideas.offer_more(s, ws)

    assert out["added"] == 0
    assert "Every idea this week's evidence produced" in out["detail"]


async def test_a_reserve_row_without_citations_is_not_offered(editorial_sessionmaker):
    # Older rows predate keeping citations; an idea with no evidence cannot be scripted.
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await add(sm, ws, "Validated long ago, evidence not kept", cites=False)

    async with sm() as s:
        assert (await more_ideas.offer_more(s, ws))["added"] == 0


async def test_it_does_not_offer_what_is_already_on_the_list(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await add(
        sm,
        ws,
        "Before you blame the marketing, find the stage where people actually drop off",
        status="proposed",
        origin=ORIGIN_SELECTOR,
    )
    await add(sm, ws, "Before you fix the marketing, find the stage that is actually leaking")

    async with sm() as s:
        assert (await more_ideas.offer_more(s, ws))["added"] == 0


async def test_asking_twice_never_hands_over_the_same_near_miss_twice(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await add(sm, ws, "Before you blame the marketing, find the stage where people drop off")
    await add(sm, ws, "Before you fix the marketing, find the stage that is actually leaking")
    await add(sm, ws, "Your homepage has one job: show the offer in one glance")

    async with sm() as s:
        out = await more_ideas.offer_more(s, ws, limit=10)

    titles = [c["title"] for c in out["candidates"]]
    assert len(titles) == 2  # the two marketing-stage rows collapse to one
    assert any("homepage" in t for t in titles)


async def test_the_best_ones_come_first_and_the_rest_are_counted(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await add(sm, ws, "Weakest of the three", score=0.2)
    await add(sm, ws, "Strongest of the three", score=0.9)
    await add(sm, ws, "Middle of the three", score=0.5)

    async with sm() as s:
        out = await more_ideas.offer_more(s, ws, limit=1)

    assert out["candidates"][0]["title"] == "Strongest of the three"
    assert out["remaining"] == 2
    assert "2 more where that came from" in out["detail"]


async def test_the_last_one_says_so(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await add(sm, ws, "The only one left")

    async with sm() as s:
        out = await more_ideas.offer_more(s, ws, limit=3)

    assert out["remaining"] == 0
    assert "That was the last one." in out["detail"]


async def test_a_newer_week_is_offered_before_an_older_one(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await add(sm, ws, "From an old week", week=datetime(2026, 8, 3), score=0.99)
    await add(sm, ws, "From this week", week=datetime(2026, 9, 14), score=0.3)

    async with sm() as s:
        out = await more_ideas.offer_more(s, ws, limit=1)

    assert out["candidates"][0]["title"] == "From this week"


async def test_another_workspace_reserve_is_not_touched(editorial_sessionmaker):
    sm, ws, other = editorial_sessionmaker, uuid.uuid4(), uuid.uuid4()
    await add(sm, other, "Someone else's reserve idea")

    async with sm() as s:
        assert (await more_ideas.offer_more(s, ws))["added"] == 0


FOUR_UNRELATED = [
    ("Price your travel time before you quote the job", "Charge for the drive."),
    ("The contract goes out before the deposit, not after", "Paper first, money second."),
    ("Answer the phone or lose the wedding", "Speed of reply wins bookings."),
    ("Your best referral source is the client you just finished", "Ask while it is fresh."),
]


@pytest.mark.parametrize("limit,expected", [(0, 1), (99, 4)])
async def test_the_limit_is_clamped_not_rejected(editorial_sessionmaker, limit, expected):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    for i, (title, lesson) in enumerate(FOUR_UNRELATED):
        await add(sm, ws, title, lesson=lesson, score=0.5 - i / 100)

    async with sm() as s:
        out = await more_ideas.offer_more(s, ws, limit=limit)

    assert out["added"] == expected


async def test_nothing_at_all_is_an_answer_not_an_error(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()

    async with sm() as s:
        out = await more_ideas.offer_more(s, ws)

    assert out == {
        "added": 0,
        "remaining": 0,
        "candidates": [],
        "detail": out["detail"],
    }
    assert "next weekly run collects it" in out["detail"]
