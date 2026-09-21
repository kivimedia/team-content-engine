"""The voice pass: score the openings, rewrite them when they are not his.

The packet writer had no critic while the Facebook and LinkedIn writer has had one
all along. This is that bar applied to the thing he actually records.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

import tce.llm
from tce.editorial import packets
from tce.llm import LLMResult, LLMUnavailable
from tce.models.editorial import RecordingPacket, TopicCandidate
from tests.unit.test_editorial_coverage_status import real_queue  # noqa: F401 - fixture

WS = uuid.UUID("aaaaaaaa-1111-4111-8111-111111111111")
MOMENT = str(uuid.uuid4())


def a_candidate() -> TopicCandidate:
    return TopicCandidate(
        id=uuid.uuid4(),
        workspace_id=WS,
        week_start=datetime(2026, 9, 14),
        moment_ids=[MOMENT],
        title="Before you blame the marketing",
        lesson="Check the stage where people actually drop off.",
        audience="coaches",
        public_angle="Funnel stages.",
        gates={},
        citations_private=[{"moment_id": MOMENT, "excerpt_private": "words"}],
        status="selected",
    )


def a_packet(cand: TopicCandidate, **over) -> RecordingPacket:
    data = {
        "id": uuid.uuid4(),
        "workspace_id": WS,
        "candidate_id": cand.id,
        "version": 1,
        "bullets": ["one", "two", "three", "four", "five"],
        "script_phrases": [
            "Here is why your marketing is not the problem.",
            "Check each stage separately.",
            "Page to sign up, sign up to sale.",
            "The leak is after the sign up.",
            "Fix the stage, not the ads.",
            "If that is useful, book a strategy session.",
        ],
        "facebook_post": "A post. Book a strategy session.",
        "linkedin_post": "A post. Book a strategy session.",
        "interviewer_prompt": "What do you check first?",
        "hook_options": [
            {
                "id": "h1",
                "text": "Here is why your marketing is not the problem.",
                "question": "Why?",
                "payoff_phrase_id": "p004",
                "moment_ids": [MOMENT],
                "rationale": "curiosity",
            }
        ],
        "selected_hook_id": "h1",
        "beats": [],
        "citations_private": [{"moment_id": MOMENT}],
        "public_safety": {"status": "clean", "issues": []},
        "status": "ready",
    }
    data.update(over)
    return RecordingPacket(**data)


async def seed(sm, *rows):
    async with sm() as s:
        for row in rows:
            s.add(row)
        await s.commit()


def replacement(hook_id="v1", text="Most coaches blame the ads before they check the stages."):
    return {
        "id": hook_id,
        "text": text,
        "question": "Which stage is leaking?",
        "payoff_phrase_id": "p004",
        "moment_ids": [MOMENT],
        "rationale": "takes a position",
    }


@pytest.fixture
def critic(monkeypatch):
    state: dict = {"answer": None, "raise": None, "requests": []}

    async def fake_complete(req, **_kw):
        state["requests"].append(req)
        if state["raise"]:
            raise state["raise"]
        return LLMResult(
            job_id=uuid.uuid4(), text="", structured=state["answer"], model="claude-opus-5"
        )

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    return state


async def test_a_curiosity_gap_opening_is_rewritten(editorial_sessionmaker, critic):
    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand)
    await seed(sm, cand, packet)
    critic["answer"] = {
        "score": 3,
        "verdict": "revise",
        "violations": [{"quote": "Here is why", "issue": "a curiosity gap, not a position"}],
        "hook_options": [replacement()],
    }

    out = await packets.voice_pass(sm, WS, packet.id)

    assert out.status == "ok"
    assert out.packet["version"] == 2
    texts = [o["text"] for o in out.packet["hook_options"]]
    assert "Most coaches blame the ads before they check the stages." in texts
    # The original stays, so he can see what changed.
    assert "Here is why your marketing is not the problem." in texts
    # And the rewritten one is the one in use: that is the point of the pass.
    assert out.packet["selected_hook_id"] == "v1"
    assert "scored 3 out of 10" in out.detail


async def test_an_opening_that_already_sounds_like_him_is_left_alone(
    editorial_sessionmaker, critic
):
    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand)
    await seed(sm, cand, packet)
    critic["answer"] = {"score": 9, "verdict": "pass", "violations": [], "hook_options": []}

    out = await packets.voice_pass(sm, WS, packet.id)

    assert out.status == "ok"
    assert out.packet["version"] == 1  # nothing written
    assert "sound like him" in out.detail


async def test_a_critic_that_returned_nothing_usable_is_not_a_pass(
    editorial_sessionmaker, critic
):
    # A skipped check must never earn a pass.
    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand)
    await seed(sm, cand, packet)
    critic["answer"] = {"verdict": "pass"}  # no score

    out = await packets.voice_pass(sm, WS, packet.id)

    assert out.status == "failed"
    assert "no score" in out.detail


async def test_a_failing_score_with_no_replacements_is_a_failure_not_a_pass(
    editorial_sessionmaker, critic
):
    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand)
    await seed(sm, cand, packet)
    critic["answer"] = {"score": 4, "verdict": "revise", "violations": [], "hook_options": []}

    out = await packets.voice_pass(sm, WS, packet.id)

    assert out.status == "failed"
    assert "no replacement openings" in out.detail


async def test_a_replacement_citing_other_evidence_is_refused(editorial_sessionmaker, critic):
    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand)
    await seed(sm, cand, packet)
    bad = replacement()
    bad["moment_ids"] = [str(uuid.uuid4())]
    critic["answer"] = {"score": 3, "verdict": "revise", "violations": [], "hook_options": [bad]}

    out = await packets.voice_pass(sm, WS, packet.id)

    assert out.status == "failed"
    assert "outside this idea" in out.detail


async def test_a_replacement_using_banned_vocabulary_is_refused(editorial_sessionmaker, critic):
    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand)
    await seed(sm, cand, packet)
    critic["answer"] = {
        "score": 3,
        "verdict": "revise",
        "violations": [],
        "hook_options": [replacement(text="This is a game-changer for your funnel.")],
    }

    out = await packets.voice_pass(sm, WS, packet.id)

    assert out.status == "failed"
    assert "banned vocabulary" in out.detail


async def test_the_critic_is_shown_his_rules_and_his_own_words(editorial_sessionmaker, critic):
    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand)
    await seed(sm, cand, packet)
    critic["answer"] = {"score": 9, "verdict": "pass", "violations": [], "hook_options": []}

    await packets.voice_pass(sm, WS, packet.id)

    prompt = critic["requests"][0].messages[0]["content"]
    system = critic["requests"][0].system
    assert "HIS VOICE (the rules)" in prompt
    assert "ZIV'S VOICE AND WRITING STYLE" in prompt  # include_voice reached it
    assert "THE OPENINGS TO JUDGE" in prompt
    assert "curiosity gap" in system.lower()


async def test_a_take_set_in_progress_blocks_the_pass(editorial_sessionmaker, critic):
    from tce.models.recording_session import RecordingSession

    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand)
    await seed(sm, cand, packet)
    await seed(
        sm,
        RecordingSession(
            id=uuid.uuid4(),
            workspace_id=WS,
            candidate_id=cand.id,
            packet_id=packet.id,
            packet_version=1,
            retake_index=1,
            status="recording",
        ),
    )

    out = await packets.voice_pass(sm, WS, packet.id)

    assert out.status == "invalid"
    assert "take set is in progress" in out.detail


async def test_no_worker_is_a_waiting_state_not_a_failure(editorial_sessionmaker, critic):
    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand)
    await seed(sm, cand, packet)
    critic["raise"] = LLMUnavailable(
        status="waiting_worker", job_id=uuid.uuid4(), detail="no worker", retry_at=None
    )

    out = await packets.voice_pass(sm, WS, packet.id)

    assert out.status == "waiting_worker"
