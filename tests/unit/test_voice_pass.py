"""The voice pass: score the openings, rewrite them when they are not his.

The packet writer had no critic while the Facebook and LinkedIn writer has had one
all along. This is that bar applied to the thing he actually records.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

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
        "beats": [
            {
                "id": f"b{i}",
                "label": f"beat {i}",
                "bullet_index": i - 1,
                "start_phrase_id": f"p{i:03d}",
                "end_phrase_id": f"p{i:03d}",
            }
            for i in range(1, 6)
        ],
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
    # The id is the merge's, not the model's - merge_hook_options re-ids incoming
    # openings, so selecting the model's own id left the packet pointing at nothing
    # and the recorder fell back to the opening the pass had just rejected.
    chosen = next(
        o for o in out.packet["hook_options"] if o["id"] == out.packet["selected_hook_id"]
    )
    assert chosen["text"] == "Most coaches blame the ads before they check the stages."
    assert "scored 3 out of 10" in out.detail


async def test_a_rewritten_opening_is_the_first_line_and_is_scanned(editorial_sessionmaker, critic):
    # 28-Sep-2026: the pass put its opening in use without a scan, carrying the old
    # "ready", and left the rejected opening as the script's first line. An opening
    # IS the first spoken line (choose_hook), so the new one is, and it is scanned.
    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand)
    await seed(sm, cand, packet)
    promise = "This funnel fix works every time."
    critic["answer"] = {
        "score": 3,
        "verdict": "revise",
        "violations": [],
        "hook_options": [replacement(text=promise)],
    }

    out = await packets.voice_pass(sm, WS, packet.id)

    assert out.status == "ok", out.detail
    assert out.packet["script_phrases"][0] == promise
    issues = {(i["field"], i["kind"]) for i in out.packet["public_safety"]["issues"]}
    assert ("script_phrases[0]", "absolute_guarantee") in issues
    assert out.packet["status"] == "draft"
    async with sm() as s:
        assert (await s.get(RecordingPacket, packet.id)).status == "superseded"


async def test_a_pass_on_an_exported_script_makes_a_ready_version(editorial_sessionmaker, critic):
    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand, status="exported")
    await seed(sm, cand, packet)
    critic["answer"] = {
        "score": 3,
        "verdict": "revise",
        "violations": [],
        "hook_options": [replacement()],
    }

    out = await packets.voice_pass(sm, WS, packet.id)

    assert out.status == "ok", out.detail
    assert out.packet["script_phrases"][0] == replacement()["text"]
    assert out.packet["public_safety"]["status"] == "clean"
    assert out.packet["status"] == "ready"
    async with sm() as s:
        assert (await s.get(RecordingPacket, packet.id)).status == "superseded"


async def test_a_pass_on_a_replaced_version_writes_nothing(editorial_sessionmaker, critic):
    # A retried call after the pass applied, or a pass on an old version: its
    # version would be built from the old text and become the current script.
    sm = editorial_sessionmaker
    cand = a_candidate()
    packet = a_packet(cand)
    await seed(sm, cand, packet)
    critic["answer"] = {
        "score": 3,
        "verdict": "revise",
        "violations": [],
        "hook_options": [replacement()],
    }
    first = await packets.voice_pass(sm, WS, packet.id)
    assert first.status == "ok", first.detail
    paid = len(critic["requests"])

    again = await packets.voice_pass(sm, WS, packet.id)

    assert again.status == "invalid"
    assert "version 1" in again.detail
    assert len(critic["requests"]) == paid
    async with sm() as s:
        versions = (
            (
                await s.execute(
                    select(RecordingPacket.version).where(RecordingPacket.candidate_id == cand.id)
                )
            )
            .scalars()
            .all()
        )
    assert sorted(versions) == [1, 2]


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


async def test_a_critic_that_returned_nothing_usable_is_not_a_pass(editorial_sessionmaker, critic):
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


async def test_an_opening_can_be_chosen_after_the_list_has_grown(editorial_sessionmaker, critic):
    """Ziv, 20-Sep: he asked for more openings. Choosing one of them then failed.

    validate_packet_output enforces "exactly three openings", which is the rule for
    a freshly written packet. more_hook_options and the voice pass both grow that
    list on purpose, up to MAX_HOOK_OPTIONS, and choose_hook re-validates the whole
    packet - so every opening added after the first three was unselectable.
    """
    sm = editorial_sessionmaker
    cand = a_candidate()
    grown = a_packet(cand)
    grown.hook_options = [
        {
            "id": f"h{i}",
            "text": f"Opening number {i} that takes a position.",
            "question": "Which stage?",
            "payoff_phrase_id": "p004",
            "moment_ids": [MOMENT],
            "rationale": "r",
        }
        for i in range(1, 7)
    ]
    grown.selected_hook_id = "h1"
    await seed(sm, cand, grown)

    async with sm() as s:
        clone = await packets.choose_hook(s, WS, grown.id, "h6")

    assert clone.selected_hook_id == "h6"
    assert clone.script_phrases[0] == "Opening number 6 that takes a position."
    assert len(clone.hook_options) == 6
