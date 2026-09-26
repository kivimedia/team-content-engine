"""The weekly lineup: three slots, a reserve, and ordering that works with one thumb.

The plan's "Topic and priority" acceptance tests. Two failures they exist to catch:
ordering that goes wrong after a few taps because ranks drift out of sequence, and
a second device silently overwriting a reorder made on the first.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from tce.editorial import lineup as lineup_service
from tce.editorial.lineup import LineupError
from tce.models.editorial import TopicCandidate

WEEK = lineup_service.week_start_for(datetime(2026, 9, 21))


def gates() -> dict:
    return {
        "small_service_business": {"pass": True, "reason": "yes"},
        "coach_or_event_owner_relevance": {"pass": True, "reason": "yes"},
        "concrete_supported_substance": {"pass": True, "reason": "yes"},
        "connects_to_ziv_work": {"pass": True, "reason": "yes"},
    }


async def add_candidate(session, ws, title, **over) -> TopicCandidate:
    data = dict(
        workspace_id=ws,
        week_start=WEEK,
        moment_ids=[str(uuid.uuid4())],
        title=title,
        lesson=f"The lesson behind {title}.",
        audience="coaches",
        reasons_to_care=["it costs them clients"],
        public_angle="Take a position.",
        gates=gates(),
        citations_private=[
            {"moment_id": str(uuid.uuid4()), "source_kind": "fathom_meeting", "title": "A call"}
        ],
        status="proposed",
        origin="selector",
        freshness_role="evergreen",
    )
    data.update(over)
    row = TopicCandidate(**data)
    session.add(row)
    await session.flush()
    return row


def order_of(payload, slot="primary"):
    return [row["title"] for row in payload[slot]]


# ------------------------------------------------------------------ slots


async def test_a_good_week_takes_a_fourth_video_straight_into_the_week(editorial_session):
    """26-Sep: "I need to be able to promote more than the slots defined if I have a
    good week. nothing wrong with it." The number is his usual week, not a wall:
    a fourth topic goes into the week, never quietly into reserve."""
    ws = uuid.uuid4()
    week = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    for n in range(1, 5):
        candidate = await add_candidate(editorial_session, ws, f"Topic {n}")
        placed = await lineup_service.add_topic(editorial_session, ws, week, candidate)
        assert placed.slot == "primary"
    await editorial_session.commit()

    payload = await lineup_service.lineup_to_json(editorial_session, ws, week)
    assert order_of(payload) == ["Topic 1", "Topic 2", "Topic 3", "Topic 4"]
    assert order_of(payload, "reserve") == []
    assert payload["primary_slots"] == 3 and payload["over_by"] == 1


async def test_videos_a_week_is_his_setting_for_this_week_and_new_weeks(editorial_session):
    """26-Sep: "a setting page that allows me to promote more than 3 videos a week
    (choose how many videos)"."""
    ws = uuid.uuid4()
    this_week = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    assert await lineup_service.videos_per_week(editorial_session, ws) == 3

    await lineup_service.set_videos_per_week(editorial_session, ws, 5)
    await editorial_session.commit()

    assert await lineup_service.videos_per_week(editorial_session, ws) == 5
    assert this_week.primary_slots == 5
    from datetime import timedelta

    later = await lineup_service.ensure_lineup(editorial_session, ws, WEEK + timedelta(days=7))
    assert later.primary_slots == 5
    # Another workspace keeps its own number.
    assert await lineup_service.videos_per_week(editorial_session, uuid.uuid4()) == 3
    for bad in (0, 15, -1):
        with pytest.raises(LineupError):
            await lineup_service.set_videos_per_week(editorial_session, ws, bad)


async def test_adding_the_same_topic_twice_is_one_item(editorial_session):
    ws = uuid.uuid4()
    week = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    candidate = await add_candidate(editorial_session, ws, "Only once")
    await lineup_service.add_topic(editorial_session, ws, week, candidate)
    await lineup_service.add_topic(editorial_session, ws, week, candidate)
    await editorial_session.commit()

    payload = await lineup_service.lineup_to_json(editorial_session, ws, week)
    assert order_of(payload) == ["Only once"]


async def test_the_week_is_created_once_even_when_opened_twice(editorial_session):
    ws = uuid.uuid4()
    first = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    second = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    await editorial_session.commit()
    assert first.id == second.id


# --------------------------------------------------------------- ordering


async def test_make_first_moves_one_item_and_keeps_the_rest_in_order(editorial_session):
    ws = uuid.uuid4()
    week = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    made = {}
    for n in range(1, 4):
        made[n] = await add_candidate(editorial_session, ws, f"Topic {n}")
        await lineup_service.add_topic(editorial_session, ws, week, made[n])
    await editorial_session.commit()

    await lineup_service.move(
        editorial_session,
        ws,
        week,
        {"candidate_id": str(made[3].id), "action": "first"},
    )
    await editorial_session.commit()

    payload = await lineup_service.lineup_to_json(editorial_session, ws, week)
    assert order_of(payload) == ["Topic 3", "Topic 1", "Topic 2"]
    assert [row["rank"] for row in payload["primary"]] == [1, 2, 3]


async def test_ranks_stay_contiguous_after_many_moves(editorial_session):
    """Gaps are how Move up starts behaving unpredictably three taps in."""
    ws = uuid.uuid4()
    week = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    made = []
    for n in range(1, 4):
        candidate = await add_candidate(editorial_session, ws, f"Topic {n}")
        made.append(candidate)
        await lineup_service.add_topic(editorial_session, ws, week, candidate)
    await editorial_session.commit()

    for spec in (
        {"candidate_id": str(made[0].id), "action": "down"},
        {"candidate_id": str(made[2].id), "action": "up"},
        {"candidate_id": str(made[1].id), "action": "first"},
        {"candidate_id": str(made[0].id), "action": "up"},
    ):
        await lineup_service.move(editorial_session, ws, week, spec)
    await editorial_session.commit()

    payload = await lineup_service.lineup_to_json(editorial_session, ws, week)
    assert [row["rank"] for row in payload["primary"]] == [1, 2, 3]
    assert len(set(order_of(payload))) == 3


async def test_moving_up_from_the_top_is_a_no_op_not_an_error(editorial_session):
    """A thumb taps the same button twice. That must not be a failure state."""
    ws = uuid.uuid4()
    week = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    first = await add_candidate(editorial_session, ws, "Topic 1")
    await lineup_service.add_topic(editorial_session, ws, week, first)
    second = await add_candidate(editorial_session, ws, "Topic 2")
    await lineup_service.add_topic(editorial_session, ws, week, second)
    await editorial_session.commit()

    await lineup_service.move(
        editorial_session, ws, week, {"candidate_id": str(first.id), "action": "up"}
    )
    await editorial_session.commit()

    payload = await lineup_service.lineup_to_json(editorial_session, ws, week)
    assert order_of(payload) == ["Topic 1", "Topic 2"]


async def test_a_reserve_topic_can_be_promoted_into_the_week(editorial_session):
    ws = uuid.uuid4()
    week = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    made = []
    for n in range(1, 5):
        candidate = await add_candidate(editorial_session, ws, f"Topic {n}")
        made.append(candidate)
        await lineup_service.add_topic(editorial_session, ws, week, candidate)
    await editorial_session.commit()

    await lineup_service.move(
        editorial_session,
        ws,
        week,
        {"candidate_id": str(made[3].id), "action": "slot", "slot": "primary"},
    )
    await editorial_session.commit()

    payload = await lineup_service.lineup_to_json(editorial_session, ws, week)
    assert "Topic 4" in order_of(payload)
    assert order_of(payload, "reserve") == []


# ------------------------------------------------------------- conflicts


async def test_a_reorder_made_elsewhere_is_not_silently_overwritten(editorial_session):
    """The phone in his pocket and the tab on his desk are the same week."""
    ws = uuid.uuid4()
    week = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    made = []
    for n in range(1, 4):
        candidate = await add_candidate(editorial_session, ws, f"Topic {n}")
        made.append(candidate)
        await lineup_service.add_topic(editorial_session, ws, week, candidate)
    await editorial_session.commit()

    stale_revision = week.revision
    await lineup_service.move(
        editorial_session,
        ws,
        week,
        {"candidate_id": str(made[2].id), "action": "first"},
        expected_revision=stale_revision,
    )
    await editorial_session.commit()

    with pytest.raises(LineupError) as caught:
        await lineup_service.move(
            editorial_session,
            ws,
            week,
            {"candidate_id": str(made[1].id), "action": "first"},
            expected_revision=stale_revision,
        )

    assert caught.value.code == "conflict"
    assert caught.value.extra["current_revision"] == week.revision
    payload = await lineup_service.lineup_to_json(editorial_session, ws, week)
    assert order_of(payload)[0] == "Topic 3"


async def test_a_recorded_topic_stays_in_the_week(editorial_session):
    ws = uuid.uuid4()
    week = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    candidate = await add_candidate(editorial_session, ws, "Already recorded")
    item = await lineup_service.add_topic(editorial_session, ws, week, candidate)
    item.status = "recorded"
    await editorial_session.commit()

    with pytest.raises(LineupError) as caught:
        await lineup_service.remove_topic(editorial_session, ws, week, candidate.id)
    assert caught.value.code == "recorded"


# ------------------------------------------------------------ lanes, reasons


async def test_the_lane_is_read_from_the_evidence_not_guessed(editorial_session):
    ws = uuid.uuid4()
    news = await add_candidate(editorial_session, ws, "A release", freshness_role="news")
    built = await add_candidate(
        editorial_session,
        ws,
        "Something I built",
        citations_private=[
            {"moment_id": str(uuid.uuid4()), "source_kind": "github_commit_group", "title": "repo"}
        ],
    )
    coaching = await add_candidate(editorial_session, ws, "A coaching point")

    assert lineup_service.lane_for(news) == "ai_news"
    assert lineup_service.lane_for(built) == "build"
    assert lineup_service.lane_for(coaching) == "coaching"


async def test_the_first_item_says_why_it_is_first_and_never_shows_a_score(editorial_session):
    ws = uuid.uuid4()
    week = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    candidate = await add_candidate(
        editorial_session, ws, "A timely one", freshness_role="news", rank_score=0.87
    )
    await lineup_service.add_topic(editorial_session, ws, week, candidate)
    await editorial_session.commit()

    payload = await lineup_service.lineup_to_json(editorial_session, ws, week)
    reason = payload["primary"][0]["reason"]
    assert reason.startswith("Record first because")
    assert "timely" in reason
    assert "0.87" not in reason
    assert "87" not in reason


async def test_the_mix_is_shown_as_information_and_never_blocks_an_add(editorial_session):
    ws = uuid.uuid4()
    week = await lineup_service.ensure_lineup(editorial_session, ws, WEEK)
    for n in range(1, 4):
        candidate = await add_candidate(
            editorial_session,
            ws,
            f"Build topic {n}",
            citations_private=[
                {
                    "moment_id": str(uuid.uuid4()),
                    "source_kind": "github_commit_group",
                    "title": "repo",
                }
            ],
        )
        await lineup_service.add_topic(editorial_session, ws, week, candidate)
    await editorial_session.commit()

    payload = await lineup_service.lineup_to_json(editorial_session, ws, week)
    # Three build topics is allowed. It is his week; the label just makes it visible.
    assert len(payload["primary"]) == 3
    assert payload["mix"] == "3 build"
