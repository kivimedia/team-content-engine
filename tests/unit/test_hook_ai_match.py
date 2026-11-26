"""The AI picks the video for a hook (T-25711). The writer is stubbed; synthetic values."""

from __future__ import annotations

import asyncio
import types
import uuid

import pytest

from tce.hooks import ai_match, catalog, library
from tce.settings import settings

WS = uuid.UUID("00000000-0000-4000-8000-0000000257a3")
WEEK = "2026-11-23"
A, B = "a" * 8, "b" * 8
LINEUP = {
    "primary": [
        {"candidate_id": A, "title": "Some clients rebook at 80%", "big_idea": "", "reason": "", "filmed": False},
        {"candidate_id": B, "title": "Three years of client results in one chart", "big_idea": "", "reason": "", "filmed": False},
    ],
    "reserve": [],
}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path))
    return tmp_path


def run(coro):
    return asyncio.run(coro)


def _writer(monkeypatch, answer=None, raises=None):
    seen = {}

    async def complete(request, **_):
        seen["request"] = request
        if raises:
            raise raises
        return types.SimpleNamespace(structured=answer, text="")

    monkeypatch.setattr(ai_match._llm, "complete", complete)
    fitted = []

    async def fit(sm, ws, week, cid, hook_id):
        fitted.append((cid, hook_id))

    monkeypatch.setattr(ai_match.script_fit, "fit_script", fit)
    return seen, fitted


def test_the_ai_moves_the_pick_with_its_reason_then_fits(monkeypatch, store):
    seen, fitted = _writer(monkeypatch, {"candidate_id": B, "why": "The chart gives a real number \u2014 three years \u2014 to fill the screen"})
    entry = run(library.pick(WS, WEEK, "big-number", LINEUP))
    assert entry["candidate_id"] == A  # the word rule's instant guess (80%)
    run(ai_match.match_and_fit(None, WS, WEEK, "big-number", LINEUP))
    on_b = library.for_video(WS, WEEK, B)[0]
    assert on_b["why"] == "TCE chose it: The chart gives a real number - three years - to fill the screen."
    assert fitted == [(B, "big-number")]
    req = seen["request"]
    assert req.job_type == "hook_video_match" and B in req.messages[0]["content"]
    assert catalog.BY_ID["big-number"].script_need in req.messages[0]["content"]


def test_an_unknown_video_or_a_busy_writer_keeps_the_rule_choice(monkeypatch, store):
    _, fitted = _writer(monkeypatch, {"candidate_id": "not-this-week", "why": "x"})
    run(library.pick(WS, WEEK, "big-number", LINEUP))
    run(ai_match.match_and_fit(None, WS, WEEK, "big-number", LINEUP))
    assert library.for_video(WS, WEEK, A)[0]["chosen_by"] == "tce" and fitted == [(A, "big-number")]
    _, fitted = _writer(monkeypatch, raises=RuntimeError("busy"))
    run(ai_match.match_and_fit(None, WS, WEEK, "big-number", LINEUP))
    assert fitted == [(A, "big-number")]
    assert "Its topic says" in library.for_video(WS, WEEK, A)[0]["why"]


def test_his_own_placement_is_never_moved(monkeypatch, store):
    seen, fitted = _writer(monkeypatch, {"candidate_id": B, "why": "y"})
    run(library.pick(WS, WEEK, "big-number", LINEUP, A))
    run(ai_match.match_and_fit(None, WS, WEEK, "big-number", LINEUP))
    assert "request" not in seen and fitted == [(A, "big-number")]
    assert run(library.repoint(WS, WEEK, "big-number", A, B, "y")) is False


def test_a_pick_moved_while_the_ai_thought_stays_put(store):
    run(library.pick(WS, WEEK, "big-number", LINEUP))
    assert run(library.repoint(WS, WEEK, "big-number", B, A, "stale")) is False


def test_the_job_has_a_lane():
    from tce.llm import queue

    assert ai_match.MATCH_JOB_TYPE in queue.INTERACTIVE_JOB_TYPES
