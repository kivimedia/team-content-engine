"""scripts/rescan_packet_safety.py: drafts parked by a false positive get their status back.

28-Sep-2026: three scripts were saved as drafts because the scanner flagged a
disclaimed guarantee and the word "The" from a client's company name. Fixing the
scanner stops new ones; this re-checks the ones already parked. Dry run by default.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from tce.models.editorial import RecordingPacket, TopicCandidate

SCRIPT = Path(__file__).parents[2] / "scripts" / "rescan_packet_safety.py"
SPEC = importlib.util.spec_from_file_location("rescan_packet_safety", SCRIPT)
assert SPEC and SPEC.loader
rescan_script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rescan_script
SPEC.loader.exec_module(rescan_script)

PARTICIPANT = "Tim Hollis - In The Box Events"


def candidate(ws: uuid.UUID, title: str) -> TopicCandidate:
    return TopicCandidate(
        workspace_id=ws,
        week_start=datetime(2026, 9, 28),
        moment_ids=[],
        title=title,
        lesson="One lesson.",
        audience="coaches",
        public_angle="angle",
        gates={},
        status="selected",
        citations_private=[{"moment_id": str(uuid.uuid4()), "speaker": PARTICIPANT}],
    )


def packet(ws, cand, version, phrases, status, issues) -> RecordingPacket:
    return RecordingPacket(
        workspace_id=ws,
        candidate_id=cand.id,
        version=version,
        bullets=["Start from the problem"],
        script_phrases=phrases,
        facebook_post="A post.",
        linkedin_post="Another post.",
        interviewer_prompt="What do you ask first?",
        status=status,
        citations_private=list(cand.citations_private),
        public_safety={
            "checked": True,
            "status": "issues",
            "issues": issues,
            "model_self_check": {"one_lesson": True},
        },
    )


FALSE_POSITIVES = [
    {"field": "script_phrases[0]", "kind": "participant_name", "match": PARTICIPANT},
    {"field": "script_phrases[1]", "kind": "absolute_guarantee", "match": "not a guarantee"},
]


async def seed(session):
    ws = uuid.uuid4()
    parked = candidate(ws, "Parked by a false positive")
    named = candidate(ws, "Really names the client")
    other_ws = uuid.uuid4()
    elsewhere = candidate(other_ws, "Another workspace")
    session.add_all([parked, named, elsewhere])
    await session.flush()
    clean_lines = [
        "The first draft asked if a call would help.",
        "It's not a guarantee, it's a starting point.",
    ]
    old = packet(ws, parked, 1, clean_lines, "superseded", FALSE_POSITIVES)
    current = packet(ws, parked, 2, clean_lines, "draft", FALSE_POSITIVES)
    real = packet(
        ws,
        named,
        1,
        ["Tim asked me about pricing."],
        "draft",
        [{"field": "script_phrases[0]", "kind": "participant_name", "match": PARTICIPANT}],
    )
    foreign = packet(other_ws, elsewhere, 1, clean_lines, "draft", FALSE_POSITIVES)
    session.add_all([old, current, real, foreign])
    await session.commit()
    return ws, old, current, real, foreign


async def test_dry_run_reports_and_changes_nothing(editorial_session):
    ws, old, current, real, foreign = await seed(editorial_session)

    report = await rescan_script.rescan(editorial_session, ws, apply=False)

    by_id = {row["packet_id"]: row for row in report}
    assert set(by_id) == {str(current.id), str(real.id)}
    assert by_id[str(current.id)]["new_status"] == "clean"
    assert by_id[str(current.id)]["action"] == "would flip to ready"
    assert {i["kind"] for i in by_id[str(current.id)]["old_issues"]} == {
        "participant_name",
        "absolute_guarantee",
    }
    assert by_id[str(real.id)]["new_status"] == "issues"
    assert by_id[str(real.id)]["action"] == "stays draft"
    for row in (old, current, real, foreign):
        await editorial_session.refresh(row)
    assert [row.status for row in (old, current, real, foreign)] == [
        "superseded",
        "draft",
        "draft",
        "draft",
    ]


async def test_apply_flips_only_the_drafts_that_are_now_clean(editorial_session):
    ws, old, current, real, foreign = await seed(editorial_session)

    report = await rescan_script.rescan(editorial_session, ws, apply=True)

    assert {row["action"] for row in report} == {"flipped to ready", "stays draft"}
    rows = (
        (await editorial_session.execute(select(RecordingPacket).order_by(RecordingPacket.version)))
        .scalars()
        .all()
    )
    status = {row.id: row.status for row in rows}
    assert status[current.id] == "ready"
    assert status[real.id] == "draft"
    assert status[old.id] == "superseded"
    assert status[foreign.id] == "draft"

    flipped = next(row for row in rows if row.id == current.id)
    safety = flipped.public_safety
    assert safety["status"] == "clean" and safety["issues"] == []
    # What the writer stored is kept, and so is what the old scan said, for audit.
    assert safety["model_self_check"] == {"one_lesson": True}
    assert safety["rescanned"]["previous_issues"] == FALSE_POSITIVES


async def test_apply_never_overwrites_a_draft_that_changed_while_it_was_scanned(
    editorial_session, editorial_sessionmaker, monkeypatch
):
    # Review, 28-Sep-2026: the app keeps running while this script scans, and an
    # accepted edit or an export can mark the draft superseded or exported in that
    # window. A plain ORM write then put "ready" over it: a replaced version came
    # back as a live script, or the version that was sent lost its "exported".
    for changed_to in ("superseded", "exported"):
        ws, old, current, real, foreign = await seed(editorial_session)
        real_scan = rescan_script.scan_packet_safety

        async def scan_while_the_app_moves(db, workspace_id, fields, **kwargs):
            async with editorial_sessionmaker() as app:
                row = await app.get(RecordingPacket, current.id)
                row.status = changed_to
                await app.commit()
            return await real_scan(db, workspace_id, fields, **kwargs)

        monkeypatch.setattr(rescan_script, "scan_packet_safety", scan_while_the_app_moves)

        report = await rescan_script.rescan(editorial_session, ws, apply=True)

        by_id = {row["packet_id"]: row for row in report}
        assert by_id[str(current.id)]["action"] == "changed since read, skipped"
        status = (
            await editorial_session.execute(
                select(RecordingPacket.status).where(RecordingPacket.id == current.id)
            )
        ).scalar_one()
        assert status == changed_to
        monkeypatch.setattr(rescan_script, "scan_packet_safety", real_scan)
