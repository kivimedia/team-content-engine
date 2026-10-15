"""Add anyway: his own turned-down idea joins his topics, and nothing else can.

15-Oct-2026, Ziv: "add a add anyway button then". The gates keep deciding what the
engine finds; this only lets an idea HE said past them, marked as his call.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from tce.editorial import add_anyway, idea_lane, inbox
from tce.editorial.common import ORIGIN_OWNER_OVERRIDE, ORIGIN_SELECTOR_REJECTED
from tce.models.editorial import TopicCandidate
from tests.unit.test_editorial_coverage_status import (  # noqa: F401,F811 - fixtures
    gates_all_pass,
    rows_for,
)

REASON = "A personal developer tool; a coach would not use it in a normal week."


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _rejected(sm, ws, moment_id: str) -> TopicCandidate:
    gates = gates_all_pass()
    gates["_rejection"] = {
        "gate": "coach_or_event_owner_relevance",
        "code": "model_rejected",
        "reason": REASON,
    }
    gates["_reserve"] = False
    row = TopicCandidate(
        workspace_id=ws,
        week_start=_now(),
        moment_ids=[moment_id],
        title="Rejected: model_rejected",
        lesson="",
        audience="both",
        reasons_to_care=[],
        public_angle="",
        gates=gates,
        freshness_role="evergreen",
        citations_private=[],
        status="rejected",
        editor_notes=REASON,
        origin=ORIGIN_SELECTOR_REJECTED,
        created_at=_now(),
        updated_at=_now(),
    )
    async with sm() as s:
        s.add(row)
        await s.commit()
    return row


async def _spoken(sm, ws, idea="I built Auth Buddy to fill my 2FA codes"):
    async with sm() as s:
        source, moment = await idea_lane.record_spoken_idea(
            s, ws, run_id=uuid.uuid4(), said="lets add as a topic", idea=idea,
            angle="What happened when I built it",
        )
        await s.commit()
    return source, moment


async def test_his_turned_down_idea_is_listed_with_the_reason(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    _, moment = await _spoken(sm, ws)
    row = await _rejected(sm, ws, str(moment.id))
    await _rejected(sm, ws, str(uuid.uuid4()))  # an engine idea from a call: never offered

    async with sm() as s:
        ideas = await add_anyway.turned_down(s, ws)

    assert [i["candidate_id"] for i in ideas] == [str(row.id)]
    assert ideas[0]["idea"] == "I built Auth Buddy to fill my 2FA codes"
    assert ideas[0]["gate"] == "coach or event owner relevance"
    assert ideas[0]["reason"] == REASON


async def test_add_anyway_puts_it_on_his_topics_marked_as_his_call(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    source, moment = await _spoken(sm, ws)
    row = await _rejected(sm, ws, str(moment.id))

    async with sm() as s:
        out = await add_anyway.add_anyway(s, ws, row.id)
    assert out == {"candidate_id": str(row.id), "title": "I built Auth Buddy to fill my 2FA codes", "already": False}

    saved = next(r for r in await rows_for(sm, ws) if r.id == row.id)
    assert saved.origin == ORIGIN_OWNER_OVERRIDE
    assert saved.status == "proposed"
    assert saved.lesson == "What happened when I built it"
    assert saved.gates["_override"]["reason"] == REASON
    assert saved.citations_private[0]["source_id"] == str(source.id)
    assert "Added anyway" in saved.editor_notes and REASON in saved.editor_notes

    async with sm() as s:
        listed = await inbox.list_topics(s, ws)
        assert [t["candidate_id"] for t in listed["topics"]] == [str(row.id)]
        assert listed["topics"][0]["why_this_is_yours"] == "It came out of an idea you said yourself."
        assert await add_anyway.turned_down(s, ws) == []
        again = await add_anyway.add_anyway(s, ws, row.id)
    assert again["already"] is True


async def test_an_engine_rejection_cannot_be_added_anyway(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    row = await _rejected(sm, ws, str(uuid.uuid4()))

    async with sm() as s:
        with pytest.raises(add_anyway.AddAnywayError) as caught:
            await add_anyway.add_anyway(s, ws, row.id)
    assert caught.value.code == "not_his_idea"


async def test_another_workspace_cannot_add_it(editorial_sessionmaker):
    sm, ws = editorial_sessionmaker, uuid.uuid4()
    _, moment = await _spoken(sm, ws)
    row = await _rejected(sm, ws, str(moment.id))

    async with sm() as s:
        with pytest.raises(add_anyway.AddAnywayError) as caught:
            await add_anyway.add_anyway(s, uuid.uuid4(), row.id)
    assert caught.value.status == 404


def test_only_add_anyway_sets_the_owner_override_origin():
    """The override origin is a person's decision; no generator may write it."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "tce"
    writers = []
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr == "origin" for t in node.targets
            ) and getattr(node.value, "id", None) == "ORIGIN_OWNER_OVERRIDE":
                writers.append(path.relative_to(src).as_posix())
    assert writers == ["editorial/add_anyway.py"]
