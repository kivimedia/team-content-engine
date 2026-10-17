"""The script check (T-13569): slips named against his own lines, one rewrite, never blocks."""

from __future__ import annotations

import uuid

import pytest

import tce.llm
from tce.editorial import packets, script_check
from tce.llm import LLMResult, LLMUnavailable
from tests.unit.test_editorial_packets import good_output, make_candidate


@pytest.fixture
def two_job_llm(monkeypatch):
    state = {"slips": {"slips": []}, "check_raises": None, "calls": []}

    async def fake_complete(req, *, wait_timeout_s=None):
        state["calls"].append(req.job_type)
        if req.job_type == script_check.JOB_TYPE:
            if state["check_raises"]:
                raise state["check_raises"]
            return LLMResult(job_id=uuid.uuid4(), text="", structured=state["slips"], model="m")
        return LLMResult(job_id=uuid.uuid4(), text="", structured=good_output(), model="m")

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    return state


async def _build(sm):
    ws = uuid.uuid4()
    async with sm() as s:
        c = await make_candidate(s, ws)
    return await packets.build_packet(sm, ws, c.id)


async def test_named_slip_is_rewritten_once_and_reported(editorial_sessionmaker, two_job_llm):
    two_job_llm["slips"] = {
        "slips": [
            {
                "phrase_id": "p003",
                "slip": "this sounds like a coach, not like you",
                "rewrite": "Ask what they can do at the end.",
            },
        ]
    }
    out = await _build(editorial_sessionmaker)
    assert out.status == "ready"
    assert two_job_llm["calls"].count(script_check.JOB_TYPE) == 1
    p = out.packet
    assert p["script_phrases"][2] == "Ask what they can do at the end."
    assert p["script_phrases"][0] == good_output()["script_phrases"][0]
    rep = p["public_safety"]["script_check"]
    assert rep["status"] == "checked" and rep["applied"][0]["slip"].startswith(
        "this sounds like a coach"
    )
    assert rep["applied"][0]["was"] == good_output()["script_phrases"][2]


async def test_no_slips_leaves_the_script_as_written(editorial_sessionmaker, two_job_llm):
    out = await _build(editorial_sessionmaker)
    assert out.packet["script_phrases"] == good_output()["script_phrases"]
    assert out.packet["public_safety"]["script_check"]["slips"] == 0


async def test_unavailable_check_never_blocks_the_script(editorial_sessionmaker, two_job_llm):
    two_job_llm["check_raises"] = LLMUnavailable(
        "waiting", job_id=None, detail="worker busy", retry_at=None
    )
    out = await _build(editorial_sessionmaker)
    assert out.status == "ready"
    assert out.packet["public_safety"]["script_check"]["status"] == "unavailable"


async def test_a_rewrite_that_breaks_the_packet_rules_is_dropped_and_named(
    editorial_sessionmaker, two_job_llm
):
    two_job_llm["slips"] = {
        "slips": [
            {
                "phrase_id": "p003",
                "slip": "pushy ending",
                "rewrite": "Book a strategy session with me.",
            },
        ]
    }
    out = await _build(editorial_sessionmaker)
    assert out.status == "ready"
    assert out.packet["script_phrases"] == good_output()["script_phrases"]
    rep = out.packet["public_safety"]["script_check"]
    assert rep["status"] == "rewrites_refused" and rep["named"][0]["phrase_id"] == "p003"


def test_usable_slips_filters_the_opening_dashes_duplicates_and_unknown_ids():
    phrases = ["a", "b", "c", "d"]
    got = script_check.usable_slips(
        {
            "slips": [
                {"phrase_id": "p001", "slip": "x", "rewrite": "new opening"},
                {"phrase_id": "p002", "slip": "x", "rewrite": "has — dash"},
                {"phrase_id": "p003", "slip": "ok", "rewrite": "fine"},
            ]
        },
        phrases,
    )
    assert [g["phrase_id"] for g in got] == ["p003"]
    got = script_check.usable_slips(
        {
            "slips": [
                {"phrase_id": "p009", "slip": "x", "rewrite": "nope"},
                {"phrase_id": "p003", "slip": "ok", "rewrite": "fine"},
                {"phrase_id": "p003", "slip": "again", "rewrite": "twice"},
            ]
        },
        phrases,
    )
    assert [g["phrase_id"] for g in got] == ["p003"]
    assert script_check.apply_rewrites(phrases, got) == ["a", "b", "fine", "d"]
    assert script_check.usable_slips("junk", phrases) == []


async def test_switch_off_skips_the_job(editorial_sessionmaker, two_job_llm, monkeypatch):
    monkeypatch.setenv("TCE_SCRIPT_SLIP_CHECK", "0")
    out = await _build(editorial_sessionmaker)
    assert script_check.JOB_TYPE not in two_job_llm["calls"]
    assert out.packet["public_safety"]["script_check"]["status"] == "off"
