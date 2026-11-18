"""The owner's week keeps room for ideas from his builds (T-22611, 18-Nov).

Ziv, 18-Nov: "it didn't really have a good amount of topics related to code or related
to AI news ... we are not good at finding these." Measured on the week of 8 Nov: 56
build-led ideas passed all four gates and checked citations, and the global ranking
kept one of them next to five call ideas. The rest were set aside as "not selected
globally". These tests pin the net under the ranking: in the owner's workspace a week
keeps up to two build ideas about software or AI when such finalists passed, while
client workspaces and coaching lessons merely mined from a commit are left alone.

Synthetic fixtures only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from tce.editorial import selector
from tce.settings import settings
from tests.unit.test_editorial_coverage_status import (  # noqa: F401 - fixtures
    add_moments,
    add_source,
    rows_for,
)
from tests.unit.test_editorial_global_rank import (  # noqa: F401 - fixtures
    WEEK,
    cand,
    editor,
    finalists_in,
)

CALL_TITLES = [f"Coaching lesson {i}" for i in range(4)]
# The best build idea teaches a coaching habit and never talks about software: it stays
# a coaching lesson (18-Oct, a Code label on a non-code idea) and is not promoted.
NOT_SOFTWARE = "Send clients the short list, not the long checklist"
SOFTWARE_A = "Try a new AI agent on one account before every customer"
SOFTWARE_B = "After an app update, check what reaches people, not that it deployed"


async def owner_week(sm, ws):
    async with sm() as s:
        calls = await add_moments(
            s, ws, await add_source(s, ws, occurred_at=datetime(2026, 9, 8, 9)), 30
        )
        builds = await add_moments(
            s,
            ws,
            await add_source(
                s, ws, occurred_at=datetime(2026, 9, 9, 9), kind="github_commit_group"
            ),
            30,
        )
    return calls, builds


def proposals(calls, builds) -> dict:
    out = {
        str(calls[i].id): cand(calls[i].id, CALL_TITLES[i], f"Call lesson {i}", 5 - 0.2 * i)
        for i in range(4)
    }
    out[str(builds[0].id)] = cand(builds[0].id, NOT_SOFTWARE, "Short lists get read.", 4)
    out[str(builds[1].id)] = cand(
        builds[1].id, SOFTWARE_A, "Roll a new agent out to one account first.", 3
    )
    out[str(builds[2].id)] = cand(
        builds[2].id, SOFTWARE_B, "Check the message a client gets after an update.", 2
    )
    return out


async def test_owner_week_keeps_two_software_build_ideas_the_ranking_left_out(
    editorial_sessionmaker, editor, monkeypatch
):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    monkeypatch.setattr(settings, "owner_workspace_ids", str(ws))
    calls, builds = await owner_week(sm, ws)
    editor["proposals"] = proposals(calls, builds)

    res = await selector.select_candidates(sm, ws, WEEK, max_candidates=4)

    assert res.status == "complete"
    titles = [c["title"] for c in res.candidates]
    # The ranking picked the four call ideas (support 5 to 4.4 beats 4, 3 and 2). The week
    # still holds two software build ideas, in place of the two weakest-ranked picks.
    assert len(titles) == 4
    assert SOFTWARE_A in titles and SOFTWARE_B in titles
    assert NOT_SOFTWARE not in titles
    assert titles[:2] == CALL_TITLES[:2]

    made_room = [r for r in res.rejected if r["code"] == "lane_room"]
    assert sorted(r["title"] for r in made_room) == sorted(CALL_TITLES[2:])
    assert all("build" in r["reason"] for r in made_room)
    assert res.coverage["rank"]["build_lane"]["kept"] == 2

    rows = {r.title: r for r in await rows_for(sm, ws)}
    assert rows[SOFTWARE_A].status == "proposed"
    assert rows[SOFTWARE_B].status == "proposed"
    # A displaced call idea is set aside as reserve, so "more ideas" can still offer it.
    assert rows[CALL_TITLES[3]].status == "rejected"
    assert rows[CALL_TITLES[3]].gates["_reserve"] is True
    assert rows[NOT_SOFTWARE].gates["_rejection"]["code"] == "not_selected_globally"


async def test_owner_week_with_a_build_already_chosen_tops_up_to_two(
    editorial_sessionmaker, editor, monkeypatch
):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    monkeypatch.setattr(settings, "owner_workspace_ids", str(ws))
    calls, builds = await owner_week(sm, ws)
    editor["proposals"] = proposals(calls, builds)

    def picks_one_build(prompt):
        items = finalists_in(prompt)
        order = [*CALL_TITLES[:3], SOFTWARE_A]
        chosen = sorted(
            (f for f in items if f["title"] in order), key=lambda f: order.index(f["title"])
        )
        return {
            "selected": [{"key": f["key"], "reason": "r"} for f in chosen],
            "duplicates": [],
            "not_selected": [
                {"key": f["key"], "reason": "outranked"} for f in items if f not in chosen
            ],
        }

    editor["rank"] = picks_one_build
    res = await selector.select_candidates(sm, ws, WEEK, max_candidates=4)
    titles = [c["title"] for c in res.candidates]
    assert len(titles) == 4
    assert SOFTWARE_A in titles and SOFTWARE_B in titles
    assert [r["title"] for r in res.rejected if r["code"] == "lane_room"] == [CALL_TITLES[2]]


async def test_a_build_the_ranking_called_a_duplicate_is_never_promoted(
    editorial_sessionmaker, editor, monkeypatch
):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    monkeypatch.setattr(settings, "owner_workspace_ids", str(ws))
    calls, builds = await owner_week(sm, ws)
    editor["proposals"] = proposals(calls, builds)

    def builds_are_duplicates(prompt):
        items = finalists_in(prompt)
        first_call = next(f for f in items if f["title"] == CALL_TITLES[0])
        chosen = sorted(
            (f for f in items if f["title"] in CALL_TITLES),
            key=lambda f: CALL_TITLES.index(f["title"]),
        )
        return {
            "selected": [{"key": f["key"], "reason": "r"} for f in chosen],
            "duplicates": [
                {"key": f["key"], "duplicate_of": first_call["key"], "reason": "same lesson"}
                for f in items
                if f not in chosen
            ],
            "not_selected": [],
        }

    editor["rank"] = builds_are_duplicates
    res = await selector.select_candidates(sm, ws, WEEK, max_candidates=4)
    assert [c["title"] for c in res.candidates] == CALL_TITLES
    assert not [r for r in res.rejected if r["code"] == "lane_room"]


async def test_client_workspace_week_is_ranked_exactly_as_before(
    editorial_sessionmaker, editor, monkeypatch
):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    monkeypatch.setattr(settings, "owner_workspace_ids", str(uuid.uuid4()))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    calls, builds = await owner_week(sm, ws)
    editor["proposals"] = proposals(calls, builds)

    res = await selector.select_candidates(sm, ws, WEEK, max_candidates=4)
    assert [c["title"] for c in res.candidates] == CALL_TITLES
    assert not [r for r in res.rejected if r["code"] == "lane_room"]
    assert "build_lane" not in res.coverage["rank"]
