"""Global ranking across shard finalists: dedupe, no padding, honest failure, durable resume.

Synthetic fixtures only.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import select

import tce.llm
from tce.editorial import selector
from tce.editorial import status as job_status
from tce.llm import LLMResult, LLMUnavailable
from tce.models.llm_job import LLMJob
from tests.unit.test_editorial_coverage_status import (  # noqa: F401 - fixtures
    add_moments,
    add_source,
    finish_jobs,
    gates_all_pass,
    job_count,
    real_queue,
    rows_for,
)

WEEK = date(2026, 9, 7)
_IDS = re.compile(r'"moment_id": "([0-9a-f-]{36})"')

SAME_LESSON = "Reply to every new inquiry within the hour, before anything else that day."
EARLY_LESSON = "Before planning a course, list the problems it solves, in order."


def finalists_in(prompt: str) -> list[dict]:
    return json.loads(prompt.split("FINALISTS (JSON):\n", 1)[1])


def cand(moment_id, title, lesson, score) -> dict:
    return {
        "moment_ids": [str(moment_id)],
        "title": title,
        "lesson": lesson,
        "audience": "both",
        "public_angle": f"Angle for: {title}",
        "reasons_to_care": ["synthetic reason"],
        "gates": gates_all_pass(),
        "scores": {"owner_relevance": score, "useful_lesson": score, "support_strength": score},
    }


def shard_answer(prompt: str, proposals: dict[str, dict]) -> dict:
    ids = _IDS.findall(prompt)
    return {
        "candidates": [proposals[i] for i in ids if i in proposals],
        "rejections": [
            {"moment_ids": [i], "gate": "concrete_supported_substance", "reason": "thin"}
            for i in ids
            if i not in proposals
        ],
    }


def dedupe_editor(prompt: str) -> dict:
    """A deterministic stand-in for the ranking editor: one finalist per lesson (the best
    supported), best first, every other key explained."""
    items = finalists_in(prompt)
    most = int(re.search(r"^RETURN AT MOST (\d+) ", prompt, re.M).group(1))
    best: dict[str, dict] = {}
    for f in sorted(items, key=lambda f: f["support_score"], reverse=True):
        best.setdefault(f["lesson"], f)
    keep = sorted(best.values(), key=lambda f: f["support_score"], reverse=True)[:most]
    kept = {f["key"] for f in keep}
    return {
        "selected": [{"key": f["key"], "reason": "strongest for owners"} for f in keep],
        "duplicates": [
            {"key": f["key"], "duplicate_of": best[f["lesson"]]["key"], "reason": "same lesson"}
            for f in items
            if f["key"] not in kept and best[f["lesson"]]["key"] in kept
        ],
        "not_selected": [
            {"key": f["key"], "reason": "weaker than the chosen set"}
            for f in items
            if f["key"] not in kept and best[f["lesson"]]["key"] not in kept
        ],
    }


@pytest.fixture
def editor(monkeypatch):
    state: dict = {"proposals": {}, "rank": dedupe_editor, "calls": [], "rank_raise": None}

    async def fake_complete(req, *, wait_timeout_s=None, **kw):
        state["calls"].append(req)
        prompt = req.messages[0]["content"]
        if "SELECTION STAGE: rank" in prompt:
            if state["rank_raise"]:
                raise state["rank_raise"]
            out = state["rank"](prompt)
        else:
            out = shard_answer(prompt, state["proposals"])
        return LLMResult(job_id=uuid.uuid4(), text="", structured=out, model="claude-opus-5")

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    return state


async def three_shard_week(sm, ws):
    """Three 30-moment sources, one shard each: an early coaching call, a late meeting and
    a late repository, each with one strong moment."""
    async with sm() as s:
        early = await add_moments(
            s, ws, await add_source(s, ws, occurred_at=datetime(2026, 9, 7, 6)), 30
        )
        meeting = await add_moments(
            s, ws, await add_source(s, ws, occurred_at=datetime(2026, 9, 12, 9)), 30
        )
        repo = await add_moments(
            s,
            ws,
            await add_source(
                s, ws, occurred_at=datetime(2026, 9, 13, 9), kind="github_commit_group"
            ),
            30,
        )
    return early[0], meeting[0], repo[0]


def rank_calls(state) -> list:
    return [r for r in state["calls"] if "SELECTION STAGE: rank" in r.messages[0]["content"]]


async def test_duplicate_strong_lessons_do_not_crowd_out_a_distinct_earlier_lesson(
    editorial_sessionmaker, editor
):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    early, meeting, repo = await three_shard_week(sm, ws)
    editor["proposals"] = {
        str(meeting.id): cand(meeting.id, "The first-hour reply rule", SAME_LESSON, 5),
        str(repo.id): cand(repo.id, "Why we built instant inquiry replies", SAME_LESSON, 5),
        str(early.id): cand(early.id, "Problems before lessons", EARLY_LESSON, 4),
    }

    res = await selector.select_candidates(sm, ws, WEEK, max_candidates=2)

    assert res.status == "complete"
    assert len(rank_calls(editor)) == 1 and len(editor["calls"]) == 4  # 3 shards + 1 rank
    req = rank_calls(editor)[0]
    assert req.agent_name == "editorial_ranker" and req.job_type == "editorial_selection"
    assert req.idempotency_key == f"editorial_selection:{ws}:{res.selection_run_id}:rank"
    finalists = finalists_in(req.messages[0]["content"])
    assert sorted(f["cites"][0] for f in finalists) == sorted(
        str(m.id) for m in (early, meeting, repo)
    )
    # code-only ranking would have kept the two score-5 duplicates and cut the lesson
    assert min(f["support_score"] for f in finalists if f["lesson"] == SAME_LESSON) > max(
        f["support_score"] for f in finalists if f["lesson"] == EARLY_LESSON
    )

    lessons = [c["lesson"] for c in res.candidates]
    assert sorted(lessons) == sorted([SAME_LESSON, EARLY_LESSON])
    dup = [r for r in res.rejected if r["code"] == "duplicate_lesson"]
    assert len(dup) == 1 and "Duplicate of:" in dup[0]["reason"]
    assert res.coverage["rank"]["status"] == "succeeded"
    assert res.coverage["rank"]["duplicates"] == 1

    # wording and provenance are the shard's validated text, untouched
    rows = {r.lesson: r for r in await rows_for(sm, ws) if r.status == "proposed"}
    early_row = rows[EARLY_LESSON]
    assert early_row.title == "Problems before lessons"
    assert early_row.public_angle == "Angle for: Problems before lessons"
    assert [c["moment_id"] for c in early_row.citations_private] == [str(early.id)]
    assert sorted(r.rank for r in rows.values()) == [1, 2]


async def test_rank_picks_fewer_when_fewer_are_strong_and_accounts_for_every_key(
    editorial_sessionmaker, editor
):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    early, meeting, repo = await three_shard_week(sm, ws)
    editor["proposals"] = {
        str(m.id): cand(m.id, f"Idea {i}", f"Lesson {i}", 4)
        for i, m in enumerate((early, meeting, repo))
    }

    def one_and_silence(prompt):
        keys = [f["key"] for f in finalists_in(prompt)]
        return {
            "selected": [
                {"key": keys[0], "reason": "only strong one"},
                {"key": "F99", "reason": "x"},
            ],
            "duplicates": [],
            "not_selected": [{"key": keys[1], "reason": "too thin"}],
        }

    editor["rank"] = one_and_silence
    res = await selector.select_candidates(sm, ws, WEEK, max_candidates=6)
    assert len(res.candidates) == 1  # no padding up to 6
    codes = sorted(r["code"] for r in res.rejected if r["code"].startswith(("not_", "rank_")))
    assert codes == ["not_selected_globally", "rank_unaccounted"]
    unexplained = [r for r in res.rejected if r["code"] == "rank_unaccounted"][0]
    assert (
        unexplained["reason"] == "the global ranking neither selected nor explained this finalist"
    )
    assert res.coverage["rank"]["unknown_keys"] == ["F99"]
    assert "neither selected nor explained" in res.detail


async def test_rank_over_max_is_cut_and_recorded(editorial_sessionmaker, editor):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    early, meeting, repo = await three_shard_week(sm, ws)
    editor["proposals"] = {
        str(m.id): cand(m.id, f"Idea {i}", f"Lesson {i}", 4)
        for i, m in enumerate((early, meeting, repo))
    }
    editor["rank"] = lambda p: {
        "selected": [{"key": f["key"], "reason": "r"} for f in finalists_in(p)],
        "duplicates": [],
        "not_selected": [],
    }
    res = await selector.select_candidates(sm, ws, WEEK, max_candidates=2)
    assert len(res.candidates) == 2
    assert [r["code"] for r in res.rejected if r["code"] == "rank_cap"] == ["rank_cap"]


async def test_shard_returning_more_than_asked_is_capped_explicitly(editorial_sessionmaker, editor):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    async with sm() as s:
        a = await add_moments(
            s, ws, await add_source(s, ws, occurred_at=datetime(2026, 9, 8, 9)), 30
        )
        b = await add_moments(
            s, ws, await add_source(s, ws, occurred_at=datetime(2026, 9, 10, 9)), 30
        )
    editor["proposals"] = {
        str(a[0].id): cand(a[0].id, "A0", "Lesson A0", 5),
        str(a[1].id): cand(a[1].id, "A1", "Lesson A1", 3),
        str(a[2].id): cand(a[2].id, "A2", "Lesson A2", 4),
        str(b[0].id): cand(b[0].id, "B0", "Lesson B0", 4),
    }
    res = await selector.select_candidates(sm, ws, WEEK, max_candidates=2)
    capped = [r for r in res.rejected if r["code"] == "shard_cap"]
    assert [r["title"] for r in capped] == ["A1"]  # lowest support in the over-full shard
    finalists = finalists_in(rank_calls(editor)[0].messages[0]["content"])
    assert sorted(f["title"] for f in finalists) == ["A0", "A2", "B0"]


@pytest.mark.parametrize(
    "failure",
    [
        LLMUnavailable("waiting_capacity", "limit reached", job_id=uuid.uuid4()),
        LLMUnavailable("failed", "worker_error: crashed", job_id=uuid.uuid4()),
        "garbage",
    ],
)
async def test_failed_or_capped_ranking_saves_nothing(editorial_sessionmaker, editor, failure):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    early, meeting, repo = await three_shard_week(sm, ws)
    editor["proposals"] = {str(early.id): cand(early.id, "Only early", EARLY_LESSON, 4)}
    await selector.select_candidates(sm, ws, WEEK)  # one finalist: no rank job, saved
    before = sorted((r.id, r.status) for r in await rows_for(sm, ws))

    editor["proposals"] = {
        str(meeting.id): cand(meeting.id, "M", "Lesson M", 5),
        str(repo.id): cand(repo.id, "R", "Lesson R", 5),
    }
    if failure == "garbage":
        editor["rank"] = lambda p: {"picked": "F1"}
    else:
        editor["rank_raise"] = failure
    res = await selector.select_candidates(sm, ws, WEEK)

    assert res.status in ("waiting_capacity", "failed")
    assert res.candidates == [] and res.rejected == []
    assert res.coverage["rank"]["status"] != "succeeded"
    assert "nothing was saved" in res.detail
    assert sorted((r.id, r.status) for r in await rows_for(sm, ws)) == before


# ---------------------------------------------------------------------------
# Durable status and resume on the real queue
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("real_queue")
async def test_rank_job_is_durable_resumable_and_never_duplicated(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    early, meeting, repo = await three_shard_week(sm, ws)
    proposals = {
        str(meeting.id): cand(meeting.id, "The first-hour reply rule", SAME_LESSON, 5),
        str(repo.id): cand(repo.id, "Why we built instant inquiry replies", SAME_LESSON, 5),
        str(early.id): cand(early.id, "Problems before lessons", EARLY_LESSON, 4),
    }

    first = await selector.select_candidates(sm, ws, WEEK, max_candidates=2)
    run_id = first.selection_run_id
    assert first.status == "timeout"
    await finish_jobs(
        sm,
        ws,
        "editorial_selection",
        lambda job: shard_answer(job.request_json["messages"][0]["content"], proposals),
    )
    job_status.clear()  # restart
    async with sm() as s:
        view = await job_status.latest_selection_run(s, ws, WEEK.isoformat())
    assert view["state"] == "interrupted" and view["resumable"] is True
    assert view["rank"] is None and "global ranking not started" in view["current_activity"]

    second = await selector.select_candidates(
        sm, ws, WEEK, max_candidates=2, selection_run_id=run_id
    )
    assert second.status == "timeout" and second.coverage["rank"]["status"] == "timeout"
    assert await rows_for(sm, ws) == []  # shards done, ranking pending: nothing saved
    assert await job_count(sm, ws) == 4
    job_status.clear()
    async with sm() as s:
        view = await job_status.latest_selection_run(s, ws, WEEK.isoformat())
        in_flight = await job_status.unattended_jobs(s, ws)
    assert view["rank"]["status"] == "queued" and view["rank"]["stage"] == "rank"
    assert view["job_counts"] == {"succeeded": 3, "queued": 1} and view["resumable"] is True
    assert view["rank"]["job_id"] in view["job_ids"]
    assert [(j["stage"], j["status"]) for j in in_flight] == [("rank", "queued")]

    # the worker fails the ranking job once: reported, and resume re-queues the same job
    async with sm() as s:
        rank = (
            await s.execute(select(LLMJob).where(LLMJob.id == uuid.UUID(view["rank"]["job_id"])))
        ).scalar_one()
        rank.status, rank.error_code, rank.error_detail = "failed", "worker_error", "crashed"
        await s.commit()
        view = await job_status.latest_selection_run(s, ws, WEEK.isoformat())
    assert view["state"] == "failed" and view["resumable"] is True
    third = await selector.select_candidates(
        sm, ws, WEEK, max_candidates=2, selection_run_id=run_id
    )
    assert third.status == "timeout" and await job_count(sm, ws) == 4

    async with sm() as s:
        rank = (await s.execute(select(LLMJob).where(LLMJob.id == rank.id))).scalar_one()
        assert rank.status == "queued" and rank.request_json["requeue_count"] == 1
        rank.status = "succeeded"
        rank.result_json = dedupe_editor(rank.request_json["messages"][0]["content"])
        rank.receipt_json = {"models": {"claude-opus-5": {}}}
        await s.commit()

    done = await selector.select_candidates(sm, ws, WEEK, max_candidates=2, selection_run_id=run_id)
    assert done.status == "complete" and done.resumed is True
    assert sorted(c["lesson"] for c in done.candidates) == sorted([SAME_LESSON, EARLY_LESSON])
    assert await job_count(sm, ws) == 4  # 3 shards + 1 ranking job, nothing duplicated
    saved = len(await rows_for(sm, ws))
    again = await selector.select_candidates(
        sm, ws, WEEK, max_candidates=2, selection_run_id=run_id
    )
    assert "already saved" in again.detail and len(await rows_for(sm, ws)) == saved
    async with sm() as s:
        view = await job_status.latest_selection_run(s, ws, WEEK.isoformat())
    assert view["state"] == "done" and view["rank"]["status"] == "succeeded"
