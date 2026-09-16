"""Recording packets: validation, CTA, public-safety scan, versioning, waiting state."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

import tce.llm
from tce.editorial import packets
from tce.editorial.safety import scan_public_text
from tce.llm import LLMResult, LLMUnavailable
from tce.models.editorial import EvidenceSource, RecordingPacket, TopicCandidate


def good_output(**over) -> dict:
    data = {
        "bullets": [
            "Start from what the person can do afterward",
            "Name the problems in the way",
            "Put the problems in order",
            "Match each lesson to one problem",
            "Cut what does not help",
            "Let AI challenge the sequence",
        ],
        "script_phrases": [
            "When a coach asks me what lessons to put in a course,",
            "I go back one step.",
            "What will someone be able to do when they finish?",
            "Name the problems first.",
            "Put them in order.",
            "Then decide what each lesson is for.",
            "If you want help with that in your coaching business,",
            "book a strategy session.",
        ],
        "facebook_post": "A question before you plan a course. Book a strategy session.",
        "linkedin_post": "Plan the course from the problems. Book a strategy session.",
        "interviewer_prompt": "What do you ask before discussing lessons?",
        "self_check": {"one_lesson": True, "cta_is_strategy_session": True},
    }
    data.update(over)
    return data


async def make_candidate(session, ws, status="selected"):
    src = EvidenceSource(
        workspace_id=ws,
        source_kind="fathom_meeting",
        external_id=str(uuid.uuid4()),
        version_hash="a" * 64,
        payload_private={
            "turns": [
                {"speaker": "Dana Example", "text": "synthetic"},
                {"speaker": "Ziv Raviv", "text": "synthetic"},
            ]
        },
    )
    session.add(src)
    await session.flush()
    c = TopicCandidate(
        workspace_id=ws,
        week_start=datetime(2026, 9, 7),
        moment_ids=[],
        title="Build the course around problems solved",
        lesson="Order problems first.",
        audience="coaches",
        public_angle="angle",
        gates={},
        status=status,
        citations_private=[
            {
                "source_id": str(src.id),
                "speaker": "Ziv Raviv",
                "claim_type": "paraphrased",
                "excerpt_private": "synthetic",
            }
        ],
    )
    session.add(c)
    await session.commit()
    return c


@pytest.fixture
def fake_llm(monkeypatch):
    state = {"output": good_output(), "raise": None, "calls": []}

    async def fake_complete(req, *, wait_timeout_s=None):
        state["calls"].append(req)
        if state["raise"]:
            raise state["raise"]
        return LLMResult(
            job_id=uuid.uuid4(), text="", structured=state["output"], model="claude-opus-5"
        )

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    return state


@pytest.mark.parametrize("count", [4, 8])
def test_bullets_outside_5_to_7_rejected(count):
    with pytest.raises(packets.PacketValidationError, match="bullets"):
        packets.validate_packet_output(good_output(bullets=[f"b{i}" for i in range(count)]))


@pytest.mark.parametrize("count", [5, 7])
def test_bullets_within_range_accepted(count):
    out = packets.validate_packet_output(good_output(bullets=[f"b{i}" for i in range(count)]))
    assert len(out["bullets"]) == count


def test_script_must_end_with_strategy_session():
    phrases = good_output()["script_phrases"][:-2] + ["Thanks for watching."]
    with pytest.raises(packets.PacketValidationError, match="strategy-session"):
        packets.validate_packet_output(good_output(script_phrases=phrases))


def test_giveaway_cta_rejected():
    with pytest.raises(packets.PacketValidationError, match="giveaway"):
        packets.validate_packet_output(
            good_output(facebook_post="Comment GUIDE and I will send the free guide.")
        )


def test_safety_scan_catches_money_email_participant_and_token_url():
    result = scan_public_text(
        {
            "script_phrases": [
                "My client paid $4,500 for this.",
                "Email me at someone@example.com",
                "Dana told me it worked.",
                "See https://example.com/report?token=abc123",
                "Revenue went up 30% that month.",
                "Call 054-123-4567 today.",
                "This is guaranteed to work.",
                "My client said it changed everything.",
            ]
        },
        participants=["Dana Example", "Ziv Raviv", "Speaker 2"],
    )
    kinds = {i["kind"] for i in result["issues"]}
    assert result["status"] == "issues"
    assert {
        "money",
        "email",
        "participant_name",
        "token_url",
        "revenue_percentage",
        "phone",
        "absolute_guarantee",
        "customer_quote",
    } <= kinds
    # Ziv himself and generic speaker labels are not flagged
    assert all(i["match"] != "Ziv Raviv" for i in result["issues"])


def test_safety_scan_clean_text():
    result = scan_public_text(good_output(), participants=["Dana Example"])
    assert result == {"checked": True, "status": "clean", "issues": []}


async def test_build_packet_persists_clean_packet_with_cta_and_no_price(
    editorial_sessionmaker, fake_llm
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    out = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert out.status == "ready"
    p = out.packet
    assert p["version"] == 1 and p["public_safety"]["status"] == "clean"
    assert "strategy session" in " ".join(p["script_phrases"][-2:]).lower()
    assert "$" not in " ".join(p["script_phrases"] + p["bullets"])
    req = fake_llm["calls"][0]
    assert (req.job_type, req.prompt_version) == ("recording_packet", "recording_packet.v1")


async def test_packet_with_participant_name_and_price_flags_issues(
    editorial_sessionmaker, fake_llm
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    phrases = ["Dana asked me about pricing.", "I charge $900 a session."] + good_output()[
        "script_phrases"
    ]
    fake_llm["output"] = good_output(script_phrases=phrases)
    out = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert out.status == "issues"
    kinds = {i["kind"] for i in out.packet["public_safety"]["issues"]}
    assert {"participant_name", "money"} <= kinds
    assert out.packet["status"] == "draft"


async def test_versions_increment_and_older_superseded(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    await packets.build_packet(editorial_sessionmaker, ws, c.id)
    second = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert second.packet["version"] == 2
    async with editorial_sessionmaker() as s:
        rows = (
            (await s.execute(select(RecordingPacket).order_by(RecordingPacket.version)))
            .scalars()
            .all()
        )
    assert [r.status for r in rows] == ["superseded", "ready"]


async def test_invalid_output_and_unavailable_persist_nothing(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    fake_llm["output"] = good_output(bullets=["only one"])
    bad = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert bad.status == "failed" and bad.packet is None and bad.errors

    fake_llm["raise"] = LLMUnavailable("waiting_capacity", "limit", job_id=uuid.uuid4())
    waiting = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert waiting.status == "waiting_capacity" and waiting.packet is None
    async with editorial_sessionmaker() as s:
        assert (await s.execute(select(RecordingPacket))).scalars().all() == []


async def test_other_workspace_candidate_not_found(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, uuid.uuid4())
    with pytest.raises(LookupError):
        await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert fake_llm["calls"] == []
