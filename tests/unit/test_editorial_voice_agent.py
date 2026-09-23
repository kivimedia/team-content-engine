"""The voice agent's contract with TCE: find, change at once, undo, restore, research.

The voice agent applies a change the moment it has read it back (Ziv, 23-Sep), so
these tests pin the three things that make that safe: every write is attributed
to "voice", every change is undoable by id, and a stale read or a later edit is
refused with the current text instead of being overwritten.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_voice as voice_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.editorial import packets as packet_service
from tce.editorial import voice_agent
from tce.models.editorial import (
    EvidenceMoment,
    EvidenceSource,
    RecordingPacket,
    TopicCandidate,
)
from tce.models.editorial_workspace import EditorialChangeSet, IdeaResearch, TopicDecision
from tce.models.recording_session import RecordingSession
from tce.settings import settings

KEY = "synthetic-test-key"
WEEK = datetime(2026, 9, 21)


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    # Offline always: no test may reach a real search engine.
    monkeypatch.setattr(voice_agent, "make_searcher", lambda: None)
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(voice_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: (
        editorial_sessionmaker
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def headers(ws) -> dict:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


def gates() -> dict:
    return {
        "small_service_business": {"pass": True, "reason": "y"},
        "coach_or_event_owner_relevance": {"pass": True, "reason": "y"},
        "concrete_supported_substance": {"pass": True, "reason": "y"},
        "connects_to_ziv_work": {"pass": True, "reason": "y"},
    }


async def add_candidate(sm, ws, title, **over):
    data = dict(
        workspace_id=ws,
        week_start=WEEK,
        moment_ids=[str(uuid.uuid4())],
        title=title,
        lesson=f"The lesson behind {title}.",
        audience="coaches",
        reasons_to_care=["it costs them clients"],
        public_angle="Take a position.",
        gates=gates(),
        citations_private=[
            {"moment_id": str(uuid.uuid4()), "source_kind": "fathom_meeting", "title": "A call"}
        ],
        status="proposed",
        origin="selector",
        freshness_role="evergreen",
        rank=1,
    )
    data.update(over)
    async with sm() as s:
        row = TopicCandidate(**data)
        s.add(row)
        await s.commit()
        return row.id


HOOKS = [
    {
        "id": "h1",
        "text": "Your AI said done. Was it?",
        "question": "q",
        "payoff_phrase_id": "p1",
        "moment_ids": ["m"],
        "rationale": "r",
    },
    {
        "id": "h2",
        "text": "Nobody checks the result.",
        "question": "q",
        "payoff_phrase_id": "p1",
        "moment_ids": ["m"],
        "rationale": "r",
    },
]


async def add_packet(sm, ws, cid):
    async with sm() as s:
        row = RecordingPacket(
            workspace_id=ws,
            candidate_id=cid,
            version=1,
            bullets=["First point.", "Second point.", "Third point."],
            script_phrases=["Your AI said done. Was it?", "Line two.", "Line three."],
            hook_options=HOOKS,
            selected_hook_id="h1",
            status="ready",
            citations_private=[],
            public_safety={},
        )
        s.add(row)
        await s.commit()
        return row.id


async def change(client, ws, cid, target, operations, summary="A change"):
    return await client.post(
        "/api/v1/editorial/voice/change",
        json={
            "candidate_id": str(cid),
            "target": target,
            "operations": operations,
            "summary": summary,
        },
        headers=headers(ws),
    )


async def topic(client, ws, q):
    return (
        await client.get("/api/v1/editorial/voice/topic", params={"q": q}, headers=headers(ws))
    ).json()


# ------------------------------------------------------------------ finding


async def test_a_topic_is_found_by_a_few_words_of_its_title(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Why invoices go unpaid")
    await add_candidate(editorial_sessionmaker, ws, "The receptionist that never sleeps")

    body = await topic(client, ws, "invoices unpaid")
    assert body["status"] == "found"
    assert body["topic"]["candidate_id"] == str(cid)
    assert body["topic"]["brief"]["version"] == 1


async def test_a_short_id_finds_the_topic(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Anything")
    body = await topic(client, ws, str(cid)[:8])
    assert body["topic"]["candidate_id"] == str(cid)


async def test_ambiguous_words_return_the_candidates_so_the_agent_can_ask(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    await add_candidate(editorial_sessionmaker, ws, "Follow up with leads fast")
    await add_candidate(editorial_sessionmaker, ws, "Follow up after the event")
    body = await topic(client, ws, "follow up")
    assert body["status"] == "ambiguous"
    assert len(body["candidates"]) == 2


async def test_a_hebrew_title_is_found_by_its_hebrew_words(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "למה לקוחות לא חוזרים")
    body = await topic(client, ws, "לקוחות חוזרים")
    assert body["status"] == "found" and body["topic"]["candidate_id"] == str(cid)


async def test_no_match_says_none(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    await add_candidate(editorial_sessionmaker, ws, "Something else")
    assert (await topic(client, ws, "zebra accounting"))["status"] == "none"


async def test_the_script_and_its_openings_come_back_numbered(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["opening"] == "Your AI said done. Was it?"
    assert script["points"][2] == "Third point."
    assert [h["n"] for h in script["hooks"]] == [1, 2]
    assert script["hooks"][0]["chosen"] is True


# ------------------------------------------------------------------ changing


async def test_a_brief_change_applies_at_once_and_is_attributed_to_voice(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "A topic")
    response = await change(
        client,
        ws,
        cid,
        "brief",
        [{"op": "set_field", "field": "takeaway", "after": "Open the result before you trust it."}],
        summary="Write the takeaway",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == 2
    assert body["said"] == [
        'The takeaway now says "Open the result before you trust it." (it was empty).'
    ]

    async with editorial_sessionmaker() as s:
        row = (
            await s.execute(select(EditorialChangeSet).where(EditorialChangeSet.workspace_id == ws))
        ).scalar_one()
        assert row.origin == "voice" and row.decided_by == "voice" and row.state == "applied"


async def test_a_script_point_is_changed_by_its_spoken_number(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    response = await change(
        client,
        ws,
        cid,
        "script",
        [{"field": "bullets.2", "after": "A sharper third point.", "expect": "Third point."}],
    )
    assert response.status_code == 200, response.text
    assert response.json()["changes"][0]["label"] == "Point 3"
    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["points"][2] == "A sharper third point."
    assert script["version"] == 2


async def test_a_stale_read_writes_nothing_and_returns_the_current_text(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    response = await change(
        client,
        ws,
        cid,
        "script",
        [{"field": "bullets.0", "after": "New.", "expect": "What it said an hour ago."}],
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "changed"
    assert detail["current"] == "First point."
    assert (await topic(client, ws, "scripted"))["topic"]["script"]["version"] == 1


async def test_choosing_an_opening_by_number_also_changes_the_opening_line(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    response = await change(client, ws, cid, "script", [{"op": "choose_hook", "after": "2"}])
    assert response.status_code == 200, response.text
    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["opening"] == "Nobody checks the result."
    assert script["hooks"][1]["chosen"] is True

    undone = await client.post(
        f"/api/v1/editorial/change-sets/{response.json()['change_set_id']}/undo",
        json={"by": "voice"},
        headers=headers(ws),
    )
    assert undone.status_code == 200, undone.text
    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["opening"] == "Your AI said done. Was it?"
    assert script["hooks"][0]["chosen"] is True


async def test_a_script_being_recorded_is_left_alone(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    pid = await add_packet(editorial_sessionmaker, ws, cid)
    async with editorial_sessionmaker() as s:
        s.add(
            RecordingSession(
                workspace_id=ws,
                candidate_id=cid,
                packet_id=pid,
                packet_version=1,
                retake_index=1,
                status="recording",
            )
        )
        await s.commit()
    response = await change(client, ws, cid, "script", [{"field": "bullets.0", "after": "X."}])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "recording"


def test_the_take_guard_matches_the_packet_writer():
    assert voice_agent.TAKE_IN_PROGRESS == packet_service.RECORDING_IN_PROGRESS_STATUSES


async def test_an_unknown_field_is_refused_with_a_reason(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    response = await change(client, ws, cid, "script", [{"field": "bullets.9", "after": "X."}])
    assert response.status_code == 400
    assert "bullets.9" in response.json()["detail"]["message"]


async def test_an_unknown_actor_is_refused(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "A topic")
    response = await client.post(
        "/api/v1/editorial/voice/change",
        json={
            "candidate_id": str(cid),
            "target": "brief",
            "by": "someone",
            "operations": [{"field": "takeaway", "after": "x"}],
        },
        headers=headers(ws),
    )
    assert response.status_code == 400


# ------------------------------------------------------------------ undo


async def test_undo_puts_a_brief_back_and_is_listed_as_undone(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "A topic")
    original = (await topic(client, ws, "topic"))["topic"]["brief"]["values"]["big_idea"]
    applied = (
        await change(
            client,
            ws,
            cid,
            "brief",
            [{"field": "big_idea", "after": "A worse big idea.", "expect": original}],
        )
    ).json()

    undone = await client.post(
        f"/api/v1/editorial/change-sets/{applied['change_set_id']}/undo",
        json={"by": "voice"},
        headers=headers(ws),
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["already"] is False
    assert (await topic(client, ws, "topic"))["topic"]["brief"]["values"]["big_idea"] == original

    # A retried Undo is a no-op, not a second write.
    again = await client.post(
        f"/api/v1/editorial/change-sets/{applied['change_set_id']}/undo", headers=headers(ws)
    )
    assert again.json()["already"] is True

    items = (await client.get("/api/v1/editorial/voice/activity", headers=headers(ws))).json()[
        "items"
    ]
    first = next(i for i in items if i["id"] == applied["change_set_id"])
    assert first["undone"] is True and first["can_undo"] is False
    assert any(i["is_undo"] for i in items)


async def test_undo_of_a_field_he_wrote_himself_removes_it_again(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "A topic")
    applied = (
        await change(client, ws, cid, "brief", [{"field": "takeaway", "after": "New takeaway."}])
    ).json()
    await client.post(
        f"/api/v1/editorial/change-sets/{applied['change_set_id']}/undo", headers=headers(ws)
    )
    values = (await topic(client, ws, "topic"))["topic"]["brief"]["values"]
    assert "takeaway" not in values, "an undone first draft must read as unwritten again"


async def test_undo_refuses_when_the_text_was_changed_again_since(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    first = (
        await change(
            client,
            ws,
            cid,
            "script",
            [{"field": "bullets.0", "after": "Two.", "expect": "First point."}],
        )
    ).json()
    await change(
        client, ws, cid, "script", [{"field": "bullets.0", "after": "Three.", "expect": "Two."}]
    )

    response = await client.post(
        f"/api/v1/editorial/change-sets/{first['change_set_id']}/undo", headers=headers(ws)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["current"] == "Three."
    assert (await topic(client, ws, "scripted"))["topic"]["script"]["points"][0] == "Three."


async def test_undo_of_the_latest_script_change_works_on_the_current_version(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    await change(
        client,
        ws,
        cid,
        "script",
        [{"field": "bullets.1", "after": "Other.", "expect": "Second point."}],
    )
    last = (
        await change(
            client,
            ws,
            cid,
            "script",
            [{"field": "bullets.0", "after": "Two.", "expect": "First point."}],
        )
    ).json()
    response = await client.post(
        f"/api/v1/editorial/change-sets/{last['change_set_id']}/undo", headers=headers(ws)
    )
    assert response.status_code == 200, response.text
    points = (await topic(client, ws, "scripted"))["topic"]["script"]["points"]
    assert points[:2] == ["First point.", "Other."], "undo must keep the earlier change"


async def test_a_week_move_is_undone_to_the_exact_earlier_order(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    ids = [await add_candidate(editorial_sessionmaker, ws, f"Topic {n}") for n in (1, 2, 3)]
    for cid in ids:
        await client.post(
            f"/api/v1/editorial/topics/{cid}/decide",
            json={"decision": "this_week"},
            headers=headers(ws),
        )

    async def order():
        body = (
            await client.get("/api/v1/editorial/weeks/current/lineup", headers=headers(ws))
        ).json()
        return [row["candidate_id"] for row in body["primary"]]

    before = await order()
    moved = await change(
        client, ws, ids[2], "week", [{"op": "move_topic", "after": {"action": "first"}}]
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["said"] == ["Topic 3 moved to first in the week."]
    assert (await order())[0] == str(ids[2])

    undone = await client.post(
        f"/api/v1/editorial/change-sets/{moved.json()['change_set_id']}/undo", headers=headers(ws)
    )
    assert undone.status_code == 200, undone.text
    assert await order() == before


# ------------------------------------------------------------ decide, put away


async def test_put_away_by_voice_is_listed_and_restores_to_where_it_was(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "An idea he liked once")
    await client.post(
        f"/api/v1/editorial/topics/{cid}/decide",
        json={"decision": "later", "by": "voice"},
        headers=headers(ws),
    )
    away = await client.post(
        f"/api/v1/editorial/topics/{cid}/decide",
        json={"decision": "away", "by": "voice"},
        headers=headers(ws),
    )
    assert away.status_code == 200

    items = (await client.get("/api/v1/editorial/voice/activity", headers=headers(ws))).json()[
        "items"
    ]
    entry = next(i for i in items if i["kind"] == "decision")
    assert entry["decision"] == "away" and entry["can_restore"] is True
    assert entry["lines"] == ['Put "An idea he liked once" away.']

    restored = await client.post(
        f"/api/v1/editorial/topics/{cid}/restore", json={"by": "voice"}, headers=headers(ws)
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["decision"] == "later"
    async with editorial_sessionmaker() as s:
        row = await s.get(TopicCandidate, cid)
        assert row.status == "proposed"


async def test_restoring_a_never_decided_idea_puts_it_back_in_the_inbox(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Fresh idea")
    await client.post(
        f"/api/v1/editorial/topics/{cid}/decide",
        json={"decision": "away", "by": "voice"},
        headers=headers(ws),
    )
    restored = (
        await client.post(f"/api/v1/editorial/topics/{cid}/restore", headers=headers(ws))
    ).json()
    assert restored["restored"] is True and restored["decision"] is None
    assert (await topic(client, ws, "fresh idea"))["topic"]["decision"] is None


async def test_decide_refuses_an_unknown_actor(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Idea")
    response = await client.post(
        f"/api/v1/editorial/topics/{cid}/decide",
        json={"decision": "later", "by": "robot"},
        headers=headers(ws),
    )
    assert response.status_code == 400


async def test_activity_is_tenant_scoped(client, editorial_sessionmaker):
    ws, other = uuid.uuid4(), uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "A topic")
    await change(client, ws, cid, "brief", [{"field": "takeaway", "after": "Mine."}])
    items = (await client.get("/api/v1/editorial/voice/activity", headers=headers(other))).json()
    assert items["items"] == []


async def test_changes_he_typed_are_not_listed_as_voice(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "A topic")
    await client.post(
        f"/api/v1/editorial/topics/{cid}/brief",
        json={"field": "takeaway", "value": "Typed by hand."},
        headers=headers(ws),
    )
    items = (await client.get("/api/v1/editorial/voice/activity", headers=headers(ws))).json()
    assert items["items"] == []


# ------------------------------------------------ undo that really puts it back


async def decide(client, ws, cid, decision, *, by="ziv", note=None):
    payload = {"decision": decision, "by": by}
    if note is not None:
        payload["note"] = note
    return await client.post(
        f"/api/v1/editorial/topics/{cid}/decide", json=payload, headers=headers(ws)
    )


async def week_ids(client, ws, slot="primary"):
    body = (await client.get("/api/v1/editorial/weeks/current/lineup", headers=headers(ws))).json()
    return [row["candidate_id"] for row in body[slot]]


async def undo(client, ws, change_set_id):
    return await client.post(
        f"/api/v1/editorial/change-sets/{change_set_id}/undo",
        json={"by": "voice"},
        headers=headers(ws),
    )


async def today(client, ws):
    return (await client.get("/api/v1/editorial/today", headers=headers(ws))).json()


async def three_in_the_week(client, sm, ws):
    ids = [
        await add_candidate(sm, ws, title)
        for title in ("Invoices nobody opens", "Receptionist at night", "Funnel leaks")
    ]
    for cid in ids:
        assert (await decide(client, ws, cid, "this_week")).status_code == 200
    return ids


async def test_undoing_a_remove_from_the_week_puts_the_topic_back_in_its_place(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    ids = await three_in_the_week(client, editorial_sessionmaker, ws)
    before = await week_ids(client, ws)

    removed = await change(
        client, ws, ids[1], "week", [{"op": "move_topic", "after": {"action": "remove"}}]
    )
    assert removed.status_code == 200, removed.text
    assert await week_ids(client, ws) == [str(ids[0]), str(ids[2])]

    undone = await undo(client, ws, removed.json()["change_set_id"])
    assert undone.status_code == 200, undone.text
    assert await week_ids(client, ws) == before, "Undone must mean the topic is back"


async def test_an_undo_that_cannot_put_the_topic_back_says_so_and_writes_nothing(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    ids = await three_in_the_week(client, editorial_sessionmaker, ws)
    removed = await change(
        client, ws, ids[1], "week", [{"op": "move_topic", "after": {"action": "remove"}}]
    )
    assert removed.status_code == 200, removed.text
    # Put away in the meantime: it may not quietly come back into the week.
    assert (await decide(client, ws, ids[1], "away")).status_code == 200

    undone = await undo(client, ws, removed.json()["change_set_id"])
    assert undone.status_code == 409, undone.text
    assert undone.json()["detail"]["code"] == "not_restored"
    assert await week_ids(client, ws) == [str(ids[0]), str(ids[2])]
    items = (await client.get("/api/v1/editorial/voice/activity", headers=headers(ws))).json()
    entry = next(i for i in items["items"] if i["id"] == removed.json()["change_set_id"])
    assert entry["undone"] is False and entry["can_undo"] is True


async def test_a_week_move_that_fails_leaves_no_change_waiting_for_review(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    in_week = await add_candidate(editorial_sessionmaker, ws, "Invoices nobody opens")
    outside = await add_candidate(editorial_sessionmaker, ws, "Receptionist at night")
    assert (await decide(client, ws, in_week, "this_week")).status_code == 200

    moved = await change(
        client, ws, outside, "week", [{"op": "move_topic", "after": {"action": "first"}}]
    )
    assert moved.status_code == 404, moved.text
    assert moved.json()["detail"]["code"] == "not_in_week"

    async with editorial_sessionmaker() as s:
        states = (
            (
                await s.execute(
                    select(EditorialChangeSet.state).where(EditorialChangeSet.workspace_id == ws)
                )
            )
            .scalars()
            .all()
        )
    assert "proposed" not in states
    body = await today(client, ws)
    assert body["attention"]["pending_reviews"] == 0
    assert body["next_action"]["key"] != "review_changes"


async def test_a_repeated_decision_reports_the_decision_it_replaced_not_an_older_one(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Invoices nobody opens")
    await decide(client, ws, cid, "discuss")
    await decide(client, ws, cid, "later")

    again = await decide(client, ws, cid, "later", by="voice")
    assert again.status_code == 200, again.text
    assert again.json()["previous_decision"] == "later"
    assert again.json()["changed"] is False

    # tce_undo sends the previous decision back; nobody asked for "discuss".
    back = await decide(client, ws, cid, again.json()["previous_decision"], by="voice")
    assert back.json()["decision"] == "later"


async def test_putting_away_by_voice_an_idea_already_put_away_is_refused(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Invoices nobody opens")
    await decide(client, ws, cid, "later")
    await decide(client, ws, cid, "away")
    again = await decide(client, ws, cid, "away", by="voice")
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "already"
    async with editorial_sessionmaker() as s:
        row = (
            await s.execute(select(TopicDecision).where(TopicDecision.candidate_id == cid))
        ).scalar_one()
        assert row.decision == "away" and row.previous_decision == "later"


async def test_undoing_a_first_approval_takes_it_out_of_the_week_and_back_to_undecided(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Invoices nobody opens")
    assert (await today(client, ws))["attention"]["waiting"] == 1

    approved = await decide(client, ws, cid, "this_week", by="voice")
    assert approved.status_code == 200, approved.text
    assert approved.json()["previous_decision"] == "undecided"
    assert approved.json()["added_to_week"] is True
    assert await week_ids(client, ws) == [str(cid)]

    # What tce_undo sends: the decision it replaced.
    undone = await decide(client, ws, cid, approved.json()["previous_decision"], by="voice")
    assert undone.status_code == 200, undone.text
    assert undone.json()["decision"] is None
    assert await week_ids(client, ws) == []
    assert (await topic(client, ws, str(cid)[:8]))["topic"]["decision"] is None
    assert (await today(client, ws))["attention"]["waiting"] == 1


async def test_undoing_an_approval_puts_it_back_where_it_was_and_out_of_the_week(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Invoices nobody opens")
    await decide(client, ws, cid, "later")
    approved = await decide(client, ws, cid, "this_week", by="voice")
    assert approved.json()["previous_decision"] == "later"
    assert await week_ids(client, ws) == [str(cid)]

    undone = await decide(client, ws, cid, approved.json()["previous_decision"], by="voice")
    assert undone.json()["decision"] == "later"
    assert await week_ids(client, ws) == [], "saved for later must not stay on the list"


async def test_putting_away_a_topic_in_the_week_takes_it_off_and_restore_puts_it_back(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    ids = await three_in_the_week(client, editorial_sessionmaker, ws)

    away = await decide(client, ws, ids[1], "away", by="voice")
    assert away.status_code == 200, away.text
    assert away.json()["removed_from_week"] == {"slot": "primary", "rank": 2}
    primary = [row["candidate_id"] for row in (await today(client, ws))["week"]["primary"]]
    assert primary == [str(ids[0]), str(ids[2])]
    assert (await topic(client, ws, str(ids[1])[:8]))["topic"]["in_this_week"] is False

    restored = await client.post(
        f"/api/v1/editorial/topics/{ids[1]}/restore", json={"by": "voice"}, headers=headers(ws)
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["decision"] == "this_week"
    assert await week_ids(client, ws) == [str(i) for i in ids], "back at its old place"


async def test_restoring_an_idea_put_away_with_a_note_keeps_the_note(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Invoices nobody opens")
    await decide(client, ws, cid, "away", note="Not before the launch")

    restored = await client.post(
        f"/api/v1/editorial/topics/{cid}/restore", json={"by": "voice"}, headers=headers(ws)
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["decision"] is None

    async with editorial_sessionmaker() as s:
        row = (
            await s.execute(select(TopicDecision).where(TopicDecision.candidate_id == cid))
        ).scalar_one_or_none()
    assert row is not None, "restoring must not delete the decision row and its note"
    assert row.decision is None and row.note == "Not before the launch"
    assert (await today(client, ws))["attention"]["waiting"] == 1


# ------------------------------------------------------------ read-back guard


async def test_an_edit_to_text_that_was_not_read_back_writes_nothing(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    response = await change(client, ws, cid, "script", [{"field": "bullets.0", "after": "New."}])
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "expect_required"
    assert detail["current"] == "First point."
    assert (await topic(client, ws, "scripted"))["topic"]["script"]["version"] == 1


async def regenerate(sm, ws, cid, hooks):
    """A newer script version with different openings, as the packet writer makes one."""
    async with sm() as s:
        old = (
            await s.execute(select(RecordingPacket).where(RecordingPacket.candidate_id == cid))
        ).scalar_one()
        old.status = "superseded"
        s.add(
            RecordingPacket(
                workspace_id=ws,
                candidate_id=cid,
                version=2,
                bullets=["New first.", "New second."],
                script_phrases=[hooks[0]["text"], "New line two."],
                hook_options=hooks,
                selected_hook_id="h1",
                status="ready",
                citations_private=[],
                public_safety={},
            )
        )
        await s.commit()


async def test_choosing_an_opening_he_never_heard_writes_nothing(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    heard = HOOKS[1]["text"]  # option 2 as it was read to him from version 1
    newer = [
        {**HOOKS[0], "text": "A brand new first opening."},
        {**HOOKS[1], "text": "A brand new second opening."},
    ]
    await regenerate(editorial_sessionmaker, ws, cid, newer)

    response = await change(
        client, ws, cid, "script", [{"op": "choose_hook", "after": "2", "expect": heard}]
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "changed"
    assert [o["text"] for o in detail["current"]] == [h["text"] for h in newer]
    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["version"] == 2 and script["opening"] == "A brand new first opening."

    agreed = await change(
        client,
        ws,
        cid,
        "script",
        [{"op": "choose_hook", "after": "2", "expect": "A brand new second opening."}],
    )
    assert agreed.status_code == 200, agreed.text
    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["opening"] == "A brand new second opening."


# ------------------------------------------------------------------ research


class FakeSearch:
    api_key = "configured"

    def __init__(self):
        self.queries = []

    async def search(self, query, count=10, freshness=None):
        self.queries.append(query)
        return [
            {"title": "A study", "url": "https://example.org/a", "description": "d", "age": "2d"}
        ]


async def seed_evidence(sm, ws, cid):
    async with sm() as s:
        source = EvidenceSource(
            workspace_id=ws,
            source_kind="fathom_meeting",
            external_id="m1",
            title="Call with a coach",
            version_hash="h",
            payload_private={},
        )
        s.add(source)
        await s.flush()
        moment = EvidenceMoment(
            workspace_id=ws,
            source_id=source.id,
            source_version_hash="h",
            excerpt_private="They never opened the report.",
            lesson_summary="Nobody checks.",
            claim_type="observation",
        )
        s.add(moment)
        await s.flush()
        cand = await s.get(TopicCandidate, cid)
        cand.moment_ids = [str(moment.id)]
        await s.commit()


async def test_research_runs_in_the_background_with_evidence_and_web(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Nobody opens the report")
    await seed_evidence(editorial_sessionmaker, ws, cid)
    fake = FakeSearch()
    monkeypatch.setattr(voice_agent, "make_searcher", lambda: fake)

    started = await client.post(
        f"/api/v1/editorial/candidates/{cid}/research", json={"by": "voice"}, headers=headers(ws)
    )
    assert started.status_code == 202
    rid = started.json()["research_id"]
    assert started.json()["state"] == "running", "the request must not wait for the research"

    done = (await client.get(f"/api/v1/editorial/research/{rid}", headers=headers(ws))).json()
    assert done["state"] == "done"
    assert done["web_status"] == "searched" and done["web"][0]["url"] == "https://example.org/a"
    assert done["evidence"][0]["title"] == "Call with a coach"
    assert "1 from your calls" in done["summary"] and "1 web results" in done["summary"]
    assert fake.queries == ["Nobody opens the report"]


async def test_research_without_a_search_key_says_so(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "An idea")
    rid = (
        await client.post(f"/api/v1/editorial/candidates/{cid}/research", headers=headers(ws))
    ).json()["research_id"]
    done = (await client.get(f"/api/v1/editorial/research/{rid}", headers=headers(ws))).json()
    assert done["web_status"] == "no_key"
    assert "web search is not set up" in done["summary"]
    # The candidate's citations still say where it came from when moments are gone.
    assert done["evidence"][0]["title"] == "A call"


async def test_a_failing_search_keeps_the_evidence_half(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "An idea")

    class Broken(FakeSearch):
        async def search(self, query, count=10, freshness=None):
            raise RuntimeError("down")

    monkeypatch.setattr(voice_agent, "make_searcher", lambda: Broken())
    rid = (
        await client.post(f"/api/v1/editorial/candidates/{cid}/research", headers=headers(ws))
    ).json()["research_id"]
    done = (await client.get(f"/api/v1/editorial/research/{rid}", headers=headers(ws))).json()
    assert done["state"] == "done" and done["web_status"] == "failed"
    assert "search failed" in done["summary"]


async def test_asking_twice_while_it_runs_reports_the_same_job(editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "An idea")
    async with editorial_sessionmaker() as s:
        first, created = await voice_agent.start_research(s, ws, cid)
        second, again = await voice_agent.start_research(s, ws, cid)
        await s.commit()
    assert created is True and again is False and first.id == second.id
    async with editorial_sessionmaker() as s:
        rows = (await s.execute(select(IdeaResearch))).scalars().all()
        assert len(rows) == 1
