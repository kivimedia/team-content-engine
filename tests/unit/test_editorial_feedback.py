"""Editorial feedback lanes, versioning, no hard exclusions, calibration seeding."""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import select

from tce.editorial.feedback import (
    CandidateNotFoundError,
    FeedbackError,
    record_feedback,
    seed_calibration,
    summarize_feedback,
)
from tce.models.editorial import EditorialFeedback, TopicCandidate


async def make_candidate(session, ws, title="Synthetic idea", status="proposed"):
    c = TopicCandidate(
        workspace_id=ws,
        week_start=datetime(2026, 9, 7),
        moment_ids=[],
        title=title,
        lesson="A synthetic lesson.",
        audience="coaches",
        public_angle="angle",
        gates={},
        status=status,
    )
    session.add(c)
    await session.commit()
    return c


async def test_preference_version_increments_per_workspace(editorial_session):
    ws, other = uuid.uuid4(), uuid.uuid4()
    c1 = await make_candidate(editorial_session, ws)
    c2 = await make_candidate(editorial_session, other)
    a = await record_feedback(editorial_session, ws, c1.id, kind="note", note="first")
    b = await record_feedback(editorial_session, ws, c1.id, kind="wording", note="shorter")
    c = await record_feedback(editorial_session, other, c2.id, kind="note", note="x")
    assert (a.preference_version, b.preference_version, c.preference_version) == (1, 2, 1)


async def test_invalid_kind_rating_gate_rejected(editorial_session):
    ws = uuid.uuid4()
    c = await make_candidate(editorial_session, ws)
    with pytest.raises(FeedbackError):
        await record_feedback(editorial_session, ws, c.id, kind="ban")
    with pytest.raises(FeedbackError):
        await record_feedback(editorial_session, ws, c.id, kind="source", rating="maybe")
    with pytest.raises(FeedbackError):
        await record_feedback(editorial_session, ws, c.id, kind="gate_reject")


async def test_feedback_on_other_workspace_candidate_is_not_found(editorial_session):
    ws, other = uuid.uuid4(), uuid.uuid4()
    c = await make_candidate(editorial_session, other)
    with pytest.raises(CandidateNotFoundError):
        await record_feedback(editorial_session, ws, c.id, kind="approve")


async def test_feedback_kinds_kept_in_separate_lanes(editorial_session):
    ws = uuid.uuid4()
    right = await make_candidate(editorial_session, ws, "Right source idea")
    wrong = await make_candidate(editorial_session, ws, "Wrong source idea")
    angle = await make_candidate(editorial_session, ws, "Angle idea")
    wording = await make_candidate(editorial_session, ws, "Wording idea")
    await record_feedback(editorial_session, ws, right.id, kind="source", rating="publish")
    await record_feedback(
        editorial_session,
        ws,
        wrong.id,
        kind="gate_reject",
        gate="coach_or_event_owner_relevance",
        rating="not_for_me",
    )
    await record_feedback(
        editorial_session,
        ws,
        angle.id,
        kind="angle",
        rating="change_angle",
        note="lead with the owner's question",
    )
    await record_feedback(
        editorial_session, ws, wording.id, kind="wording", note="fewer adjectives"
    )

    s = await summarize_feedback(editorial_session, ws)
    assert [i["title"] for i in s.source_positive] == ["Right source idea"]
    assert [i["title"] for i in s.source_negative] == ["Wrong source idea"]
    assert [i["title"] for i in s.angle] == ["Angle idea"]
    assert [i["title"] for i in s.wording] == ["Wording idea"]
    assert "coach_or_event_owner_relevance" in s.gate_weights
    text = s.to_prompt_text()
    assert text.index("SOURCE-LEVEL - right source") < text.index("ANGLE-LEVEL")
    assert text.index("ANGLE-LEVEL") < text.index("WORDING-LEVEL")
    # status side effects: approval-like source rating selects, rejection rejects
    await editorial_session.refresh(right)
    await editorial_session.refresh(wrong)
    assert right.status == "selected" and wrong.status == "rejected"


async def test_single_rejection_is_weighted_not_an_exclusion(editorial_session):
    ws = uuid.uuid4()
    c = await make_candidate(editorial_session, ws, "Pricing conversations with clients")
    await record_feedback(
        editorial_session,
        ws,
        c.id,
        kind="gate_reject",
        gate="connects_to_ziv_work",
        rating="not_for_me",
    )
    s = await summarize_feedback(editorial_session, ws)
    assert s.hard_exclusions == []
    assert s.to_dict()["hard_exclusions"] == []
    assert 0 < s.source_negative[0]["weight"] <= 1
    text = s.to_prompt_text().lower()
    assert "not rules" in text and "does not rule out a subject" in text
    assert "never propose" not in text and "exclude" not in text


async def test_seed_calibration_is_workspace_scoped_and_idempotent(editorial_sessionmaker):
    ws, other = uuid.uuid4(), uuid.uuid4()
    items = [
        {
            "title": "Synthetic calibration idea",
            "lesson": "A lesson.",
            "public_angle": "An angle.",
            "audience": "coaches",
            "source_kind": "fathom_meeting",
            "source_ref": "synthetic-ref",
            "span": "01:00-02:00",
            "note": "accepted",
        },
    ]
    first = await seed_calibration(editorial_sessionmaker, ws, items, week_start=date(2026, 9, 7))
    again = await seed_calibration(editorial_sessionmaker, ws, items, week_start=date(2026, 9, 7))
    assert first == {"inserted": 1, "skipped": 0}
    assert again == {"inserted": 0, "skipped": 1}
    async with editorial_sessionmaker() as s:
        cands = (await s.execute(select(TopicCandidate))).scalars().all()
        fbs = (await s.execute(select(EditorialFeedback))).scalars().all()
    assert len(cands) == 1 and cands[0].workspace_id == ws and cands[0].workspace_id != other
    assert (cands[0].origin, cands[0].status) == ("calibration", "selected")
    assert [(f.kind, f.rating) for f in fbs] == [("approve", "publish")]


async def test_seed_calibration_rejects_bad_items(editorial_sessionmaker):
    with pytest.raises(FeedbackError):
        await seed_calibration(editorial_sessionmaker, uuid.uuid4(), [{"title": "x"}])
