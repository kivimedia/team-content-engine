"""Editorial selector: gates, citations, invented outcomes, pool exclusions, reruns.

Synthetic fixtures only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

import tce.llm
from tce.editorial import selector
from tce.llm import LLMResult, LLMUnavailable
from tce.models.editorial import REJECTION_GATES, EvidenceMoment, EvidenceSource, TopicCandidate

WEEK = datetime(2026, 9, 7)


def gates_all_pass() -> dict:
    return {g: {"pass": True, "reason": f"synthetic reason for {g}"} for g in REJECTION_GATES}


async def add_moment(
    session,
    ws,
    *,
    occurred_at=datetime(2026, 9, 9, 10),
    claim_type="paraphrased",
    status="active",
    meta=None,
    fetch_status="ok",
    speaker_confidence="high",
    translation_label=None,
    source_kind="fathom_meeting",
    version_hash="a" * 64,
    moment_hash=None,
    lesson="Start from the problem a course solves, then order the lessons.",
):
    src = EvidenceSource(
        workspace_id=ws,
        source_kind=source_kind,
        external_id=str(uuid.uuid4()),
        title="Synthetic coaching call",
        occurred_at=occurred_at,
        version_hash=version_hash,
        fetch_status=fetch_status,
        payload_private={"turns": [{"speaker": "Sample Person", "text": "synthetic"}]},
        meta=meta,
        url_private="https://example.invalid/private/1",
    )
    session.add(src)
    await session.flush()
    m = EvidenceMoment(
        workspace_id=ws,
        source_id=src.id,
        source_version_hash=moment_hash or version_hash,
        span_start_s=60.0,
        span_end_s=120.0,
        speaker="Ziv",
        speaker_confidence=speaker_confidence,
        translation_label=translation_label,
        excerpt_private="synthetic excerpt",
        lesson_summary=lesson,
        claim_type=claim_type,
        sensitivity_flags=[],
        status=status,
    )
    session.add(m)
    await session.commit()
    return m


def raw_candidate(moment_ids, **over) -> dict:
    base = {
        "moment_ids": [str(i) for i in moment_ids],
        "title": "Build the course around problems solved",
        "lesson": "Name the problems in order before choosing lessons.",
        "audience": "coaches",
        "reasons_to_care": ["saves rework"],
        "public_angle": "A question to ask before planning any course.",
        "public_safety_notes": "",
        "gates": gates_all_pass(),
        "freshness_role": "evergreen",
        "scores": {"owner_relevance": 4, "useful_lesson": 4, "support_strength": 3},
    }
    base.update(over)
    return base


@pytest.fixture
def fake_llm(monkeypatch):
    calls: list = []
    state = {"response": {"candidates": [], "rejections": []}, "raise": None}

    async def fake_complete(req, *, wait_timeout_s=None):
        calls.append(req)
        if state["raise"]:
            raise state["raise"]
        return LLMResult(
            job_id=uuid.uuid4(), text="", structured=state["response"], model="claude-opus-5"
        )

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    state["calls"] = calls
    return state


async def test_candidate_failing_any_gate_becomes_rejection(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        m = await add_moment(s, ws)
    for gate in REJECTION_GATES:
        gates = gates_all_pass()
        gates[gate] = {"pass": False, "reason": "not relevant to owners"}
        fake_llm["response"] = {
            "candidates": [raw_candidate([m.id], gates=gates)],
            "rejections": [],
        }
        res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
        assert res.candidates == []
        assert res.rejected[0]["gate"] == gate
        assert res.rejected[0]["code"] == "gate_failed"


async def test_gate_without_reason_is_rejected(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        m = await add_moment(s, ws)
    gates = gates_all_pass()
    gates["connects_to_ziv_work"] = {"pass": True, "reason": " "}
    fake_llm["response"] = {"candidates": [raw_candidate([m.id], gates=gates)], "rejections": []}
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    assert res.candidates == [] and res.rejected[0]["code"] == "gate_reason_missing"


async def test_zero_candidates_is_valid(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        m = await add_moment(s, ws)
    fake_llm["response"] = {
        "candidates": [],
        "rejections": [
            {
                "moment_ids": [str(m.id)],
                "gate": "concrete_supported_substance",
                "reason": "too thin",
            }
        ],
    }
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    assert res.status == "complete"
    assert res.candidates == []
    assert res.rejected[0]["code"] == "model_rejected"


async def test_empty_pool_makes_no_llm_call(editorial_sessionmaker, fake_llm):
    res = await selector.select_candidates(editorial_sessionmaker, uuid.uuid4(), WEEK)
    assert res.status == "no_evidence" and res.candidates == []
    assert fake_llm["calls"] == []


async def test_no_padding_when_model_returns_fewer(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        m1 = await add_moment(s, ws)
        m2 = await add_moment(s, ws)
        await add_moment(s, ws)
    fake_llm["response"] = {
        "candidates": [raw_candidate([m1.id]), raw_candidate([m2.id], title="Second idea")],
        "rejections": [],
    }
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK, max_candidates=6)
    assert len(res.candidates) == 2
    assert [c["rank"] for c in res.candidates] == [1, 2]
    async with editorial_sessionmaker() as s:
        proposed = (
            (await s.execute(select(TopicCandidate).where(TopicCandidate.status == "proposed")))
            .scalars()
            .all()
        )
    assert len(proposed) == 2


async def test_max_candidates_cut_is_recorded_not_padded(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        ms = [await add_moment(s, ws) for _ in range(3)]
    fake_llm["response"] = {
        "candidates": [raw_candidate([m.id], title=f"Idea {i}") for i, m in enumerate(ms)],
        "rejections": [],
    }
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK, max_candidates=2)
    assert len(res.candidates) == 2
    assert [r["code"] for r in res.rejected] == ["below_cut"]


async def test_cross_tenant_and_unknown_citations_rejected(editorial_sessionmaker, fake_llm):
    ws, other = uuid.uuid4(), uuid.uuid4()
    async with editorial_sessionmaker() as s:
        mine = await add_moment(s, ws)
        theirs = await add_moment(s, other)
    fake_llm["response"] = {
        "candidates": [
            raw_candidate([theirs.id], title="Cross tenant"),
            raw_candidate([uuid.uuid4()], title="Unknown"),
            raw_candidate([mine.id, "not-a-uuid"], title="Partly invalid"),
            raw_candidate([], title="No citation"),
        ],
        "rejections": [],
    }
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    assert res.candidates == []
    codes = sorted(r["code"] for r in res.rejected)
    assert codes == ["invalid_citation", "invalid_citation", "invalid_citation", "no_citation"]
    # the other tenant's rows are untouched and no candidate was written there
    async with editorial_sessionmaker() as s:
        other_rows = (
            (await s.execute(select(TopicCandidate).where(TopicCandidate.workspace_id == other)))
            .scalars()
            .all()
        )
    assert other_rows == []


async def test_invented_measured_outcome_rejected(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        built = await add_moment(
            s, ws, claim_type="demonstrated", source_kind="github_commit_group"
        )
        measured = await add_moment(s, ws, claim_type="measured")
    fake_llm["response"] = {
        "candidates": [
            raw_candidate([built.id], title="This check doubled bookings"),
            raw_candidate(
                [measured.id],
                title="Reminders halved no-shows",
                lesson="Measured on a synthetic calendar.",
            ),
            raw_candidate([built.id], lesson="It saved 40% of admin time", title="Admin"),
        ],
        "rejections": [],
    }
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    assert [c["title"] for c in res.candidates] == ["Reminders halved no-shows"]
    assert sorted(r["code"] for r in res.rejected) == ["invented_outcome", "invented_outcome"]


async def test_uncertainty_carried_as_public_safety_note(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        m = await add_moment(
            s, ws, speaker_confidence="low", translation_label="English adaptation from Hebrew"
        )
    fake_llm["response"] = {"candidates": [raw_candidate([m.id])], "rejections": []}
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    notes = res.candidates[0]["public_safety_notes"]
    assert "confidence is low" in notes
    assert "English adaptation from Hebrew" in notes
    cit = res.candidates[0]["citations_private"][0]
    assert cit["translation_label"] == "English adaptation from Hebrew"
    assert cit["span_start_s"] == 60.0 and cit["excerpt_private"] == "synthetic excerpt"


async def test_news_candidate_gets_verification_note(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        m = await add_moment(s, ws)
    fake_llm["response"] = {
        "candidates": [
            raw_candidate(
                [m.id],
                freshness_role="news",
                verification_note="check the release is still current",
            )
        ],
        "rejections": [],
    }
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    c = res.candidates[0]
    assert c["freshness_role"] == "news"
    assert "verify" in c["public_safety_notes"].lower()


async def test_pool_excludes_reverted_low_signal_stale_and_used(editorial_session):
    ws = uuid.uuid4()
    s = editorial_session
    good = await add_moment(s, ws)
    reserve = await add_moment(s, ws, occurred_at=datetime(2026, 8, 20))
    await add_moment(
        s,
        ws,
        meta={"reverted": True, "exclude_reason": "reverted"},
        source_kind="github_commit_group",
    )
    await add_moment(
        s,
        ws,
        meta={"low_signal": True, "exclude_reason": "low_signal"},
        source_kind="github_commit_group",
    )
    await add_moment(s, ws, fetch_status="excluded")
    await add_moment(s, ws, status="stale")
    await add_moment(s, ws, moment_hash="b" * 64)  # extracted from an older version
    await add_moment(s, ws, occurred_at=datetime(2026, 9, 20))  # future week
    used = await add_moment(s, ws, occurred_at=datetime(2026, 8, 25))
    s.add(
        TopicCandidate(
            workspace_id=ws,
            week_start=datetime(2026, 8, 24),
            moment_ids=[str(used.id)],
            title="Used",
            lesson="l",
            audience="coaches",
            public_angle="a",
            gates={},
            status="recorded",
        )
    )
    await s.commit()

    pool = await selector.build_pool(s, ws, WEEK)
    ids = {pm.id: pm.in_week for pm in pool}
    assert ids == {str(good.id): True, str(reserve.id): False}


async def test_rerun_supersedes_proposed_without_duplicates(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        m1 = await add_moment(s, ws)
        m2 = await add_moment(s, ws)
    fake_llm["response"] = {
        "candidates": [raw_candidate([m1.id]), raw_candidate([m2.id], title="Two")],
        "rejections": [{"moment_ids": [], "reason": "x"}],
    }
    first = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    # editor selects one of them
    async with editorial_sessionmaker() as s:
        row = (
            await s.execute(
                select(TopicCandidate).where(
                    TopicCandidate.id == uuid.UUID(first.candidates[1]["id"])
                )
            )
        ).scalar_one()
        row.status = "selected"
        await s.commit()

    second = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    assert second.superseded == 2  # one proposed + one selector rejection
    assert [c["title"] for c in second.candidates] == ["Build the course around problems solved"]
    assert "already_selected" in [r["code"] for r in second.rejected]

    async with editorial_sessionmaker() as s:
        rows = (
            (await s.execute(select(TopicCandidate).where(TopicCandidate.workspace_id == ws)))
            .scalars()
            .all()
        )
    live = [r for r in rows if r.status in ("proposed", "selected")]
    assert sorted((r.title, r.status) for r in live) == [
        ("Build the course around problems solved", "proposed"),
        ("Two", "selected"),
    ]
    assert sum(1 for r in rows if r.status == "withdrawn") == 2


async def test_llm_unavailable_persists_nothing(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        m = await add_moment(s, ws)
    fake_llm["response"] = {"candidates": [raw_candidate([m.id])], "rejections": []}
    await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    fake_llm["raise"] = LLMUnavailable("waiting_capacity", "limit reached", job_id=uuid.uuid4())
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    assert res.status == "waiting_capacity" and res.candidates == []
    async with editorial_sessionmaker() as s:
        rows = (
            (await s.execute(select(TopicCandidate).where(TopicCandidate.workspace_id == ws)))
            .scalars()
            .all()
        )
    assert [r.status for r in rows] == ["proposed"]  # prior proposal kept, not superseded


async def test_request_uses_contract_fields(editorial_sessionmaker, fake_llm):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        await add_moment(s, ws)
    await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    req = fake_llm["calls"][0]
    assert req.job_type == "editorial_selection"
    assert req.agent_name == "editorial_selector"
    assert req.prompt_version == "editorial_selection.v2"
    assert req.workspace_id == ws and req.output_schema
    prompt = req.messages[0]["content"]
    assert "EVIDENCE POOL" in prompt and "strategy session" in prompt.lower()
