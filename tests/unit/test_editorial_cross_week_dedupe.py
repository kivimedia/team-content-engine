"""A new run must not re-propose an idea already on the list.

The ranker dedupes the finalists of ONE run. Two runs over neighbouring weeks each
saw different evidence, each proposed the funnel-stage lesson, and both were right
on their own terms - which is how Ziv ended up with the same idea twice.
"""

# ruff: noqa: F811 - a fixture taken as a test parameter shadows its import

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest

from tce.editorial import selector
from tce.models.editorial import TopicCandidate
from tests.unit.test_editorial_coverage_status import (  # noqa: F401 - fixtures
    add_moments,
    add_source,
    gates_all_pass,
    real_queue,
    rows_for,
)
from tests.unit.test_editorial_global_rank import cand, editor  # noqa: F401,F811 - fixture

WEEK = date(2026, 9, 14)
EARLIER_WEEK = datetime(2026, 9, 7)

ON_THE_LIST = {
    "title": "Before you blame the marketing, find the stage where people actually drop off",
    "lesson": (
        "When sales are low, check conversion at each step separately. If a healthy share "
        "of visitors sign up but very few sign-ups buy, the marketing is doing its job."
    ),
}
SAME_IDEA_AGAIN = {
    "title": "Before you fix the marketing, find the stage that is actually leaking",
    "lesson": (
        "Check conversion at each stage of the funnel separately. If a healthy share of "
        "page visitors sign up but very few sign-ups buy, the bottleneck is after sign-up."
    ),
}
A_DIFFERENT_IDEA = {
    "title": "Your homepage has one job: show what you offer in one glance",
    "lesson": (
        "Visitors want to see all your core services at the same time, side by side, in "
        "plain words. Internal names hide the offer."
    ),
}


async def put_on_the_list(sm, ws, *, status: str = "proposed", **over) -> TopicCandidate:
    now = datetime(2026, 9, 8, 10)
    row = TopicCandidate(
        workspace_id=ws,
        week_start=EARLIER_WEEK,
        moment_ids=[str(uuid.uuid4())],
        title=ON_THE_LIST["title"],
        lesson=ON_THE_LIST["lesson"],
        audience="both",
        reasons_to_care=[],
        public_angle="Angle",
        gates=gates_all_pass(),
        freshness_role="evergreen",
        citations_private=[],
        status=status,
        origin="selector",
        created_at=now,
        updated_at=now,
        **over,
    )
    async with sm() as s:
        s.add(row)
        await s.commit()
    return row


async def one_shard_week(sm, ws):
    async with sm() as s:
        source = await add_source(s, ws, occurred_at=datetime(2026, 9, 15, 9))
        moments = await add_moments(s, ws, source, 2)
    return moments


async def run_proposing(editor, sm, ws, moments, ideas):
    editor["proposals"] = {
        str(m.id): cand(m.id, idea["title"], idea["lesson"], 5)
        for m, idea in zip(moments, ideas, strict=False)
    }
    return await selector.select_candidates(sm, ws, WEEK, max_candidates=4)


async def test_an_idea_already_on_the_list_is_not_proposed_again(editorial_sessionmaker, editor):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await put_on_the_list(sm, ws)
    moments = await one_shard_week(sm, ws)

    res = await run_proposing(editor, sm, ws, moments, [SAME_IDEA_AGAIN, A_DIFFERENT_IDEA])

    assert res.status == "complete"
    assert [c["title"] for c in res.candidates] == [A_DIFFERENT_IDEA["title"]]
    repeats = [r for r in res.rejected if r["code"] == "duplicate_existing"]
    assert len(repeats) == 1
    assert repeats[0]["title"] == SAME_IDEA_AGAIN["title"]
    # the reason names the idea he would recognise, not a row id
    assert ON_THE_LIST["title"] in repeats[0]["reason"]


async def test_the_repeat_is_recorded_not_dropped(editorial_sessionmaker, editor):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await put_on_the_list(sm, ws)
    moments = await one_shard_week(sm, ws)

    await run_proposing(editor, sm, ws, moments, [SAME_IDEA_AGAIN, A_DIFFERENT_IDEA])

    rows = [r for r in await rows_for(sm, ws) if r.week_start.date() == WEEK]
    repeat = next(r for r in rows if r.title == SAME_IDEA_AGAIN["title"])
    assert repeat.status == "rejected"
    assert (repeat.gates or {})["_rejection"]["code"] == "duplicate_existing"
    assert ON_THE_LIST["title"] in (repeat.editor_notes or "")


@pytest.mark.parametrize("status", ["selected", "recorded", "published"])
async def test_an_idea_he_already_acted_on_also_blocks_a_repeat(
    editorial_sessionmaker, editor, status
):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await put_on_the_list(sm, ws, status=status)
    moments = await one_shard_week(sm, ws)

    res = await run_proposing(editor, sm, ws, moments, [SAME_IDEA_AGAIN, A_DIFFERENT_IDEA])

    assert [c["title"] for c in res.candidates] == [A_DIFFERENT_IDEA["title"]]


@pytest.mark.parametrize("status", ["withdrawn", "rejected"])
async def test_an_idea_he_put_away_does_not_block_a_fresh_one(
    editorial_sessionmaker, editor, status
):
    # Withdrawn and rejected rows are not on his list, so they must not silence a
    # lesson the week's evidence raised again on its own.
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await put_on_the_list(sm, ws, status=status)
    moments = await one_shard_week(sm, ws)

    res = await run_proposing(editor, sm, ws, moments, [SAME_IDEA_AGAIN, A_DIFFERENT_IDEA])

    assert sorted(c["title"] for c in res.candidates) == sorted(
        [SAME_IDEA_AGAIN["title"], A_DIFFERENT_IDEA["title"]]
    )


async def test_the_ranker_is_told_what_is_already_on_the_list(editorial_sessionmaker, editor):
    # The code check is the net. The model should not need it in the first place.
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    await put_on_the_list(sm, ws)
    async with sm() as s:
        first = await add_moments(
            s, ws, await add_source(s, ws, occurred_at=datetime(2026, 9, 15, 9)), 30
        )
        second = await add_moments(
            s, ws, await add_source(s, ws, occurred_at=datetime(2026, 9, 16, 9)), 30
        )

    editor["proposals"] = {
        str(first[0].id): cand(
            first[0].id, A_DIFFERENT_IDEA["title"], A_DIFFERENT_IDEA["lesson"], 5
        ),
        str(second[0].id): cand(second[0].id, "Another thing entirely", "A different lesson.", 4),
    }
    await selector.select_candidates(sm, ws, WEEK, max_candidates=2)

    rank = [r for r in editor["calls"] if "SELECTION STAGE: rank" in r.messages[0]["content"]]
    assert len(rank) == 1
    prompt = rank[0].messages[0]["content"]
    assert "ALREADY ON THE LIST" in prompt
    assert ON_THE_LIST["title"] in prompt


async def test_nothing_on_the_list_means_nothing_is_blocked(editorial_sessionmaker, editor):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    moments = await one_shard_week(sm, ws)

    res = await run_proposing(editor, sm, ws, moments, [SAME_IDEA_AGAIN, A_DIFFERENT_IDEA])

    assert len(res.candidates) == 2
    assert not [r for r in res.rejected if r["code"] == "duplicate_existing"]


async def test_another_workspace_list_is_not_consulted(editorial_sessionmaker, editor):
    sm, ws, other = editorial_sessionmaker, uuid.uuid4(), uuid.uuid4()
    await put_on_the_list(sm, other)
    moments = await one_shard_week(sm, ws)

    res = await run_proposing(editor, sm, ws, moments, [SAME_IDEA_AGAIN, A_DIFFERENT_IDEA])

    assert len(res.candidates) == 2
