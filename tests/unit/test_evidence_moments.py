"""Moment extraction: span/speaker/code-ref validation, LLMUnavailable surfaced. Synthetic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

import tce.llm as llm
from tce.evidence import moments as moments_mod
from tce.evidence.moments import chunk_meeting, extract_moments
from tce.models.editorial import EvidenceCollectionRun, EvidenceMoment, EvidenceSource

WS = uuid.uuid4()
START = datetime(2026, 9, 7, tzinfo=UTC)
END = datetime(2026, 9, 14, tzinfo=UTC)
BLOB = f"https://github.com/o/r/blob/{'1' * 40}/src/timer.py"


def turns():
    return [
        {"index": 0, "speaker": "Host", "speaker_email": "h@example.test", "start_s": 10.0,
         "end_s": 40.0, "text": "Answer every enquiry within an hour.",
         "speaker_confidence": "high", "language": "en", "language_uncertain": False},
        {"index": 1, "speaker": "Guest", "speaker_email": None, "start_s": 40.0,
         "end_s": 55.0, "text": "Why an hour?", "speaker_confidence": "medium",
         "language": "en", "language_uncertain": False},
        {"index": 2, "speaker": "Host", "speaker_email": "h@example.test", "start_s": 55.0,
         "end_s": 90.0, "text": "כי follow up fast wins", "speaker_confidence": "low",
         "language": "mixed", "language_uncertain": True},
    ]


async def seed(sessionmaker):
    async with sessionmaker() as s:
        meeting = EvidenceSource(
            workspace_id=WS, source_kind="fathom_meeting", external_id="m1",
            occurred_at=datetime(2026, 9, 8), version_hash="a" * 64,
            payload_private={"turns": turns(), "language": "en"}, meta={},
        )
        group = EvidenceSource(
            workspace_id=WS, source_kind="github_commit_group", external_id="o/r@abc",
            occurred_at=datetime(2026, 9, 9), version_hash="b" * 64,
            payload_private={"repo": "o/r", "commits": [{
                "sha": "1" * 40, "repo": "o/r", "message": "feat: follow-up timer",
                "committed_at": "2026-09-09T00:00:00Z", "url": "u", "reverts": [],
                "reverted_by": [],
                "files": [{"path": "src/timer.py", "additions": 3, "deletions": 0,
                           "patch_excerpt": "+x",
                           "blob_url_at_sha": BLOB}],
            }]},
            meta={"reverted": False, "low_signal": False, "exclude_reason": None},
        )
        reverted = EvidenceSource(
            workspace_id=WS, source_kind="github_commit_group", external_id="o/r@rev",
            occurred_at=datetime(2026, 9, 9), version_hash="c" * 64,
            payload_private={"repo": "o/r", "commits": []},
            meta={"reverted": True, "exclude_reason": "reverted"},
        )
        other_ws = EvidenceSource(
            workspace_id=uuid.uuid4(), source_kind="fathom_meeting", external_id="m1",
            occurred_at=datetime(2026, 9, 8), version_hash="d" * 64,
            payload_private={"turns": turns()}, meta={},
        )
        s.add_all([meeting, group, reverted, other_ws])
        await s.commit()
        return meeting.id, group.id


def fake_complete(responses_by_kind, calls):
    async def complete(req, *, wait_timeout_s=None):
        calls.append(req)
        text = req.messages[0]["content"]
        kind = "commit" if "Group of related commits" in text else "meeting"
        return llm.LLMResult(
            job_id=uuid.uuid4(), text="", structured=responses_by_kind[kind], model="m",
        )

    return complete


async def test_extraction_validates_spans_speakers_and_code_refs(
    editorial_sessionmaker, monkeypatch
):
    meeting_id, group_id = await seed(editorial_sessionmaker)
    calls = []
    meeting_moments = {"moments": [
        {"span_start_s": 10, "span_end_s": 40, "speaker": "Host",
         "excerpt_private": "Answer every enquiry within an hour.",
         "lesson_summary": "Fast replies win bookings.", "claim_type": "quoted",
         "sensitivity_flags": []},
        {"span_start_s": 55, "span_end_s": 90, "speaker": "Host",
         "excerpt_private": "follow up fast wins", "lesson_summary": "Speed wins.",
         "claim_type": "paraphrased", "translation_label": "English adaptation from Hebrew"},
        {"span_start_s": 500, "span_end_s": 600, "speaker": "Host",  # out of range
         "excerpt_private": "x", "lesson_summary": "y", "claim_type": "quoted"},
        {"span_start_s": 10, "span_end_s": 40, "speaker": "Somebody Else",  # unknown speaker
         "excerpt_private": "x", "lesson_summary": "y", "claim_type": "quoted"},
        {"span_start_s": 10, "span_end_s": 30, "speaker": "Guest",  # not speaking in span
         "excerpt_private": "x", "lesson_summary": "y", "claim_type": "quoted"},
    ]}
    commit_moments = {"moments": [
        {"code_refs": [{"sha": "1" * 40, "path": "src/timer.py"}],
         "excerpt_private": "+x", "lesson_summary": "Automate the reminder.",
         "claim_type": "demonstrated"},
        {"code_refs": [{"sha": "2" * 40, "path": "src/timer.py"}],
         "excerpt_private": "+x", "lesson_summary": "y", "claim_type": "demonstrated"},
        {"code_refs": [{"sha": "1" * 40, "path": "src/other.py"}],
         "excerpt_private": "+x", "lesson_summary": "y", "claim_type": "demonstrated"},
        {"code_refs": [{"sha": "1" * 40, "path": "src/timer.py"}],
         "excerpt_private": "+x", "lesson_summary": "y", "claim_type": "measured"},
    ]}
    monkeypatch.setattr(
        llm, "complete", fake_complete({"meeting": meeting_moments, "commit": commit_moments},
                                       calls)
    )
    run_id = await extract_moments(editorial_sessionmaker, WS, START, END)

    assert len(calls) == 2  # reverted group and other workspace are not sent
    assert all(c.job_type == "evidence_moments" for c in calls)
    assert all(c.agent_name == "evidence_moment_extractor" for c in calls)
    assert all(c.prompt_version == "evidence_moments.v1" for c in calls)
    assert all(c.workspace_id == WS and c.output_schema for c in calls)

    async with editorial_sessionmaker() as s:
        rows = (await s.execute(select(EvidenceMoment))).scalars().all()
        run = await s.get(EvidenceCollectionRun, run_id)
        meeting = await s.get(EvidenceSource, meeting_id)
    by_source = {}
    for m in rows:
        by_source.setdefault(m.source_id, []).append(m)
    assert len(by_source[meeting_id]) == 2
    assert len(by_source[group_id]) == 1
    code = by_source[group_id][0]
    assert code.code_refs[0]["url_at_sha"].endswith(f"/blob/{'1' * 40}/src/timer.py")
    assert code.span_start_s is None
    mixed = next(m for m in by_source[meeting_id] if m.span_start_s == 55)
    assert mixed.language_uncertain is True
    assert mixed.speaker_confidence == "low"
    assert mixed.translation_label == "English adaptation from Hebrew"
    assert all(m.extraction_job_id is not None for m in rows)
    reasons = meeting.meta["extraction"]["dropped"]
    assert {r["reason"] for r in reasons} == {
        "span outside the source turn range",
        "speaker does not exist in the source",
        "speaker does not speak inside the span",
    }
    assert run.counts["moments_stored"] == 3
    assert run.counts["moments_dropped"] == 6
    states = {i["external_id"]: i["state"] for i in run.items}
    assert states["o/r@rev"] == "excluded"
    assert run.status == "complete"

    # rerun: nothing left to extract
    calls.clear()
    await extract_moments(editorial_sessionmaker, WS, START, END)
    assert calls == []


async def test_llm_unavailable_is_surfaced(editorial_sessionmaker, monkeypatch):
    await seed(editorial_sessionmaker)
    retry_at = datetime(2026, 9, 16, 18, 0, tzinfo=UTC)
    job_id = uuid.uuid4()

    async def complete(req, *, wait_timeout_s=None):
        raise llm.LLMUnavailable(
            "waiting_capacity", "subscription limit", job_id=job_id, retry_at=retry_at
        )

    monkeypatch.setattr(llm, "complete", complete)
    run_id = await extract_moments(editorial_sessionmaker, WS, START, END)
    async with editorial_sessionmaker() as s:
        run = await s.get(EvidenceCollectionRun, run_id)
        moments = (await s.execute(select(EvidenceMoment))).scalars().all()
        pending = await moments_mod.sources_needing_extraction(s, WS, START, END)
    assert moments == []
    assert run.status == "partial" and run.complete is False
    assert "waiting_capacity" in run.current_activity
    assert str(job_id) in run.current_activity
    item = next(i for i in run.items if i["state"] == "unavailable")
    assert item["llm_job_id"] == str(job_id)
    assert item["retry_at"].startswith("2026-09-16T18:00")
    assert len(pending) >= 2  # nothing marked as extracted; rerun will retry


async def _seed_meetings(sessionmaker, n: int) -> None:
    async with sessionmaker() as s:
        s.add_all([
            EvidenceSource(
                workspace_id=WS, source_kind="fathom_meeting", external_id=f"mc{i}",
                occurred_at=datetime(2026, 9, 8, i), version_hash=f"{i:064x}",
                payload_private={"turns": turns(), "language": "en"}, meta={},
            )
            for i in range(n)
        ])
        await s.commit()


async def test_extraction_waits_on_several_sources_at_once(editorial_sessionmaker, monkeypatch):
    import asyncio

    await _seed_meetings(editorial_sessionmaker, 6)
    live = {"now": 0, "peak": 0}

    async def complete(req, *, wait_timeout_s=None):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0.05)  # a worker elsewhere is running the job
        live["now"] -= 1
        return llm.LLMResult(job_id=uuid.uuid4(), text="", structured={"moments": []}, model="m")

    monkeypatch.setattr(llm, "complete", complete)
    run_id = await extract_moments(editorial_sessionmaker, WS, START, END, concurrency=3)
    async with editorial_sessionmaker() as s:
        run = await s.get(EvidenceCollectionRun, run_id)
    assert live["peak"] == 3  # bounded, and actually parallel
    assert run.counts["processed"] == 6 and run.status == "complete"
    assert run.counts.get("not_started", 0) == 0


async def test_parallel_stop_counts_every_unstarted_source(editorial_sessionmaker, monkeypatch):
    await _seed_meetings(editorial_sessionmaker, 7)
    calls = []

    async def complete(req, *, wait_timeout_s=None):
        calls.append(req)
        raise llm.LLMUnavailable("waiting_capacity", "subscription limit", job_id=uuid.uuid4())

    monkeypatch.setattr(llm, "complete", complete)
    run_id = await extract_moments(editorial_sessionmaker, WS, START, END, concurrency=2)
    async with editorial_sessionmaker() as s:
        run = await s.get(EvidenceCollectionRun, run_id)
    # the two in flight stop; nothing new starts after the first stop
    assert len(calls) == 2
    assert run.counts["unavailable"] == 2
    assert run.counts["not_started"] == 5
    assert run.status == "partial" and run.complete is False
    assert "waiting_capacity" in run.current_activity


async def test_one_source_crash_is_recorded_not_fatal(editorial_sessionmaker, monkeypatch):
    await _seed_meetings(editorial_sessionmaker, 3)
    n = {"i": 0}

    async def complete(req, *, wait_timeout_s=None):
        n["i"] += 1
        if n["i"] == 2:
            raise RuntimeError("worker returned garbage")
        return llm.LLMResult(job_id=uuid.uuid4(), text="", structured={"moments": []}, model="m")

    monkeypatch.setattr(llm, "complete", complete)
    run_id = await extract_moments(editorial_sessionmaker, WS, START, END, concurrency=1)
    async with editorial_sessionmaker() as s:
        run = await s.get(EvidenceCollectionRun, run_id)
    assert run.counts["processed"] == 2 and run.counts["failed"] == 1
    assert run.status == "partial" and run.complete is False  # never a false success


def test_chunking_overlaps_and_covers_all_turns():
    many = [
        {"index": i, "speaker": "Host", "start_s": float(i * 10), "end_s": float(i * 10 + 10),
         "text": "word " * 40, "speaker_confidence": "high", "language": "en",
         "language_uncertain": False}
        for i in range(60)
    ]
    chunks = chunk_meeting(many, max_chars=3000, overlap=3)
    assert len(chunks) > 1
    covered = {t["index"] for c in chunks for t in c}
    assert covered == set(range(60))
    assert chunks[0][-1]["index"] >= chunks[1][0]["index"]  # overlap


@pytest.mark.parametrize("claim", ["measured"])
def test_code_cannot_be_measured(claim):
    fields, reason = moments_mod.validate_commit_moment(
        {"code_refs": [{"sha": "1" * 40, "path": "a.py"}], "excerpt_private": "x",
         "lesson_summary": "y", "claim_type": claim},
        {"repo": "o/r", "commits": [{"sha": "1" * 40, "files": [
            {"path": "a.py", "blob_url_at_sha": "u"}]}]},
    )
    assert fields is None and reason == "code cannot support a measured claim"


async def test_sources_needing_extraction_can_be_limited_by_kind(editorial_session):
    import uuid as _uuid
    from datetime import datetime as _dt

    from tce.evidence.moments import sources_needing_extraction
    from tce.models.editorial import EvidenceSource as _Src

    ws = _uuid.uuid4()
    for kind, ext in (("fathom_meeting", "m-1"), ("github_commit_group", "g-1")):
        editorial_session.add(_Src(
            workspace_id=ws, source_kind=kind, external_id=ext, version_hash=ext * 8,
            payload_private={}, occurred_at=_dt(2026, 9, 8),
        ))
    await editorial_session.commit()
    only = await sources_needing_extraction(editorial_session, ws, None, None, ["fathom_meeting"])
    both = await sources_needing_extraction(editorial_session, ws, None, None)
    assert [s.external_id for s in only] == ["m-1"]
    assert len(both) == 2


def test_commit_group_prompt_is_bounded_and_says_what_it_dropped():
    # 20-Sep-2026: one group rendered to 2.9 MB (~1.24M tokens) and failed the
    # 1M limit three times. Messages and file lists must survive; patches go.
    payload = {
        "repo": "kivimedia/big",
        "commits": [
            {
                "sha": f"sha{i:03d}",
                "committed_at": "2026-09-10T10:00:00Z",
                "message": f"commit {i}",
                "files": [
                    {
                        "path": f"f{i}_{j}.py",
                        "additions": 1,
                        "deletions": 0,
                        "patch_excerpt": "x" * 5000,
                    }
                    for j in range(4)
                ],
            }
            for i in range(60)
        ],
    }
    unbounded = moments_mod.render_commit_group(payload, max_chars=10**9)
    assert len(unbounded) > 1_000_000
    bounded = moments_mod.render_commit_group(payload, max_chars=100_000)
    # Patches stop at the budget; only the small per-commit headers may run past it.
    headers = sum(len(row) + 1 for row in bounded.splitlines() if not row.startswith("x"))
    assert len(bounded) <= 100_000 + headers
    assert len(bounded) < 110_000
    assert bounded.count("## Commit ") == 60
    assert "- f59_3.py (+1 -0)" in bounded
    assert "patch excerpt(s) not shown: group prompt budget" in bounded
    assert bounded.count("### Patch ") < unbounded.count("### Patch ")
    # The default budget keeps this pathological group under the ceiling too.
    assert len(moments_mod.render_commit_group(payload)) < moments_mod.GROUP_PROMPT_CHARS + 10_000
