"""/editorial workspace routes: the phone's contract with the server.

Covers the flow the plan cares about most - choose a topic WITHOUT starting a
script, put it in the week, reorder it with one thumb, propose and apply a change,
and see a recorded video in the library with no dead buttons on it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.api.routers import production as prod
from tce.editorial import conversation
from tce.editorial import lineup as lineup_service
from tce.editorial import today as today_service
from tce.models.editorial import (
    RecordingPacket,
    RecordingUpload,
    TopicCandidate,
    VideoPublication,
)
from tce.models.editorial_workspace import TopicDecision, WeeklyLineup, WeeklyLineupItem
from tce.settings import settings

KEY = "synthetic-test-key"
WEEK = datetime(2026, 9, 21)


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(workspace_router.production_router, prefix="/api/v1")
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


async def add_candidate(sm, ws, title, *, rank=1, **over):
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
        rank=rank,
    )
    data.update(over)
    async with sm() as s:
        row = TopicCandidate(**data)
        s.add(row)
        await s.commit()
        return row.id


# ------------------------------------------------------------------ access


async def test_the_workspace_refuses_an_unauthenticated_caller(client):
    response = await client.get("/api/v1/editorial/today")
    assert response.status_code in (401, 403)


# ------------------------------------------------------------------- today


async def test_today_offers_choosing_the_week_when_ideas_are_waiting(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    await add_candidate(editorial_sessionmaker, ws, "A waiting idea")

    body = (await client.get("/api/v1/editorial/today", headers=headers(ws))).json()

    assert body["next_action"]["key"] == "choose_week"
    assert body["attention"]["waiting"] == 1
    assert body["week"]["primary"] == []


async def test_today_says_there_is_nothing_waiting_rather_than_showing_an_empty_list(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    body = (await client.get("/api/v1/editorial/today", headers=headers(ws))).json()

    assert body["next_action"]["key"] == "find_ideas"
    assert "Nothing is waiting" in body["next_action"]["detail"]


# ------------------------------------------------------------------ topics


async def test_choosing_a_topic_does_not_start_a_script(client, editorial_sessionmaker):
    """The decision this whole plan exists to separate from paying for words."""
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Worth recording")

    response = await client.post(
        f"/api/v1/editorial/topics/{cid}/decide",
        json={"decision": "this_week"},
        headers=headers(ws),
    )
    assert response.status_code == 200
    assert response.json()["placed"]["slot"] == "primary"

    async with editorial_sessionmaker() as s:
        from sqlalchemy import func, select

        count = await s.execute(
            select(func.count(RecordingPacket.id)).where(RecordingPacket.workspace_id == ws)
        )
        assert count.scalar_one() == 0


async def test_put_away_and_bring_it_back_keeps_the_note(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Not for me")

    await client.post(
        f"/api/v1/editorial/topics/{cid}/decide",
        json={"decision": "away", "note": "too close to a client story"},
        headers=headers(ws),
    )
    away = (
        await client.get("/api/v1/editorial/topics?filter=away", headers=headers(ws))
    ).json()
    assert [t["title"] for t in away["topics"]] == ["Not for me"]

    back = await client.post(
        f"/api/v1/editorial/topics/{cid}/decide",
        json={"decision": "later"},
        headers=headers(ws),
    )
    # The note he wrote while deciding survives the change of mind.
    assert back.json()["note"] == "too close to a client story"
    assert back.json()["previous_decision"] == "away"


async def test_a_topic_with_no_connection_to_his_work_never_reaches_the_inbox(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    await add_candidate(editorial_sessionmaker, ws, "Good one")
    await add_candidate(
        editorial_sessionmaker, ws, "Unconnected", citations_private=[], reasons_to_care=[]
    )

    body = (await client.get("/api/v1/editorial/topics", headers=headers(ws))).json()

    assert [t["title"] for t in body["topics"]] == ["Good one"]
    # It says so out loud rather than quietly showing a shorter list.
    assert body["withheld"] == 1
    assert "could not say how they connect" in body["withheld_note"]


async def test_today_and_the_topics_page_count_the_same_ideas(client, editorial_sessionmaker):
    """27-Sep: "Tce dashboard shows 18 topics. Topics page says 25." Today counted
    ideas the inbox withheld, and the inbox listed ideas the engine had set aside
    and ideas marked to think about, which Today did not count. One number now."""
    ws = uuid.uuid4()
    await add_candidate(editorial_sessionmaker, ws, "Plain waiting", rank=1)
    thinking = await add_candidate(editorial_sessionmaker, ws, "Thinking about it", rank=2)
    await add_candidate(editorial_sessionmaker, ws, "Set aside", rank=3, status="withdrawn")
    await add_candidate(
        editorial_sessionmaker, ws, "Unconnected", rank=4, citations_private=[], reasons_to_care=[]
    )
    await client.post(
        f"/api/v1/editorial/topics/{thinking}/decide",
        json={"decision": "discuss"},
        headers=headers(ws),
    )

    today = (await client.get("/api/v1/editorial/today", headers=headers(ws))).json()
    best = (await client.get("/api/v1/editorial/topics", headers=headers(ws))).json()
    away = (
        await client.get("/api/v1/editorial/topics?filter=away", headers=headers(ws))
    ).json()

    assert [t["title"] for t in best["topics"]] == ["Plain waiting", "Thinking about it"]
    assert today["attention"]["waiting"] == best["total"] == 2
    # An idea the engine set aside is put away, where he can still bring it back.
    assert [t["title"] for t in away["topics"]] == ["Set aside"]
    assert away["topics"][0]["decision"] == "away"
    assert away["topics"][0]["set_aside_by_engine"] is True


async def test_the_inbox_filters_by_where_the_idea_came_from(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    await add_candidate(editorial_sessionmaker, ws, "From a call", rank=1)
    await add_candidate(
        editorial_sessionmaker,
        ws,
        "From code",
        rank=2,
        citations_private=[
            {"moment_id": str(uuid.uuid4()), "source_kind": "github_commit_group", "title": "repo"}
        ],
    )

    calls = (
        await client.get("/api/v1/editorial/topics?filter=calls", headers=headers(ws))
    ).json()
    code = (
        await client.get("/api/v1/editorial/topics?filter=code", headers=headers(ws))
    ).json()

    assert [t["title"] for t in calls["topics"]] == ["From a call"]
    assert [t["title"] for t in code["topics"]] == ["From code"]


async def test_an_unknown_filter_is_refused_rather_than_silently_showing_everything(client):
    ws = uuid.uuid4()
    response = await client.get(
        "/api/v1/editorial/topics?filter=nonsense", headers=headers(ws)
    )
    assert response.status_code == 400


# -------------------------------------------------------------- topic room


async def test_the_room_shows_why_this_is_yours_before_any_script_exists(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "A topic")

    body = (
        await client.get(f"/api/v1/editorial/topics/{cid}/room", headers=headers(ws))
    ).json()

    blocks = {b["field"]: b for b in body["brief"]["blocks"]}
    assert blocks["why_this_is_yours"]["written"] is True
    assert body["script"] is None
    assert "PC worker" in body["script_note"]
    # Blocks he has not written are invitations, not blank answers.
    assert blocks["takeaway"]["written"] is False


# --------------------------------------------------------------- the week


async def test_the_week_reorders_with_one_thumb_and_reports_the_new_order(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    ids = [
        await add_candidate(editorial_sessionmaker, ws, f"Topic {n}", rank=n)
        for n in (1, 2, 3)
    ]
    for cid in ids:
        await client.post(
            f"/api/v1/editorial/topics/{cid}/decide",
            json={"decision": "this_week"},
            headers=headers(ws),
        )

    before = (
        await client.get("/api/v1/editorial/weeks/current/lineup", headers=headers(ws))
    ).json()
    response = await client.patch(
        "/api/v1/editorial/weeks/current/lineup",
        json={
            "move": {"candidate_id": str(ids[2]), "action": "first"},
            "expected_revision": before["revision"],
        },
        headers=headers(ws),
    )

    assert response.status_code == 200
    assert [r["title"] for r in response.json()["primary"]] == [
        "Topic 3",
        "Topic 1",
        "Topic 2",
    ]


async def test_a_concurrent_week_edit_is_a_reviewable_conflict_not_an_overwrite(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    ids = [
        await add_candidate(editorial_sessionmaker, ws, f"Topic {n}", rank=n)
        for n in (1, 2)
    ]
    for cid in ids:
        await client.post(
            f"/api/v1/editorial/topics/{cid}/decide",
            json={"decision": "this_week"},
            headers=headers(ws),
        )
    stale = (
        await client.get("/api/v1/editorial/weeks/current/lineup", headers=headers(ws))
    ).json()["revision"]

    first = await client.patch(
        "/api/v1/editorial/weeks/current/lineup",
        json={
            "move": {"candidate_id": str(ids[1]), "action": "first"},
            "expected_revision": stale,
        },
        headers=headers(ws),
    )
    assert first.status_code == 200

    second = await client.patch(
        "/api/v1/editorial/weeks/current/lineup",
        json={
            "move": {"candidate_id": str(ids[0]), "action": "first"},
            "expected_revision": stale,
        },
        headers=headers(ws),
    )
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "conflict"
    # The newer state comes back so the client can show a review path.
    assert detail["current_revision"] > stale


# ---------------------------------------------------- the week turns over
# 28-Sep: "tce is showing 0 scripts ready despite the fact that I has around 8
# topics chosen for this week and didnt film them yet". The week key is Monday in
# Israel time, so at 00:00 on Monday 28-Sep "this week" became a new, empty list
# and nothing brought the unrecorded topics over from the week before.

LAST_WEEK = date(2026, 9, 21)
THIS_WEEK = date(2026, 9, 28)


def on_week(monkeypatch, monday: date) -> None:
    """Which Monday the server believes 'this week' starts on."""
    monkeypatch.setattr(lineup_service, "current_week_start", lambda today=None: monday)


async def seed_week(
    sm, ws, monday: date, items: list[dict], *, revision: int = 1, carried: bool = False
):
    """A week's list as the database holds it, one dict per topic.

    title, slot (primary), script ("ready" | "draft" | absent), status of the
    topic (proposed), decision ("this_week", "later", None for one taken back,
    or "no_row" for an item listed before decisions were kept), takes (upload
    states, oldest first; none by default; a dict gives a take its status and
    what the pipeline made of it: transcript, edit_plan, edited_path), archived
    (its takes were archived), posted (its last take has its posts written).
    `carried` marks a week that already ran its own carry, as a week read while
    it was current has.
    """
    ids: dict[str, uuid.UUID] = {}
    for spec in items:
        ids[spec["title"]] = await add_candidate(
            sm, ws, spec["title"], status=spec.get("status", "proposed")
        )
    async with sm() as s:
        lineup = WeeklyLineup(
            workspace_id=ws,
            week_start=datetime(monday.year, monday.month, monday.day),
            revision=revision,
            primary_slots=3,
            carried_at=datetime(monday.year, monday.month, monday.day, 7) if carried else None,
        )
        s.add(lineup)
        await s.flush()
        ranks = {"primary": 0, "reserve": 0}
        for spec in items:
            cid = ids[spec["title"]]
            slot = spec.get("slot", "primary")
            ranks[slot] += 1
            s.add(
                WeeklyLineupItem(
                    workspace_id=ws,
                    lineup_id=lineup.id,
                    candidate_id=cid,
                    rank=ranks[slot],
                    slot=slot,
                    lane="coaching",
                    reason="In this week's list.",
                    status="planned",
                    added_by="ziv",
                )
            )
            decision = spec.get("decision", "this_week")
            if decision != "no_row":
                s.add(
                    TopicDecision(
                        workspace_id=ws,
                        candidate_id=cid,
                        decision=decision,
                        decided_by="ziv",
                        decided_at=datetime(2026, 9, 22),
                    )
                )
            if spec.get("script"):
                s.add(
                    RecordingPacket(
                        workspace_id=ws,
                        candidate_id=cid,
                        version=1,
                        bullets=["First point."],
                        script_phrases=["First line."],
                        status=spec["script"],
                        citations_private=[],
                        public_safety={},
                    )
                )
            take = None
            for state in spec.get("takes", []):
                made = state if isinstance(state, dict) else {"status": state}
                take = RecordingUpload(
                    workspace_id=ws,
                    candidate_id=cid,
                    original_filename="take.mp4",
                    storage_path="/tmp/take.mp4",
                    sha256=uuid.uuid4().hex * 2,
                    duration_s=160.0,
                    archived_at=datetime(2026, 9, 27) if spec.get("archived") else None,
                    **made,
                )
                s.add(take)
            if spec.get("posted") and take is not None:
                await s.flush()
                s.add(
                    VideoPublication(
                        workspace_id=ws,
                        upload_id=take.id,
                        candidate_id=cid,
                        platform="instagram",
                        status="posted",
                        copy={"caption": "Out."},
                    )
                )
        await s.commit()
        return lineup.id, ids


async def current_week(client, ws) -> dict:
    return (
        await client.get("/api/v1/editorial/weeks/current/lineup", headers=headers(ws))
    ).json()


def titles(week: dict, slot: str = "primary") -> list[str]:
    return [row["title"] for row in week[slot]]


async def test_a_new_week_keeps_the_topics_he_chose_and_has_not_recorded(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    on_week(monkeypatch, LAST_WEEK)
    last_id, ids = await seed_week(
        editorial_sessionmaker,
        ws,
        LAST_WEEK,
        [
            {"title": "Invoices nobody opens", "script": "ready"},
            {
                "title": "Already filmed",
                "script": "ready",
                "status": "recorded",
                "takes": ["edited"],
            },
            {"title": "Receptionist at night", "script": "ready"},
            {"title": "Rejected since", "script": "ready", "status": "rejected"},
            {"title": "Still being written", "script": "draft"},
            {"title": "Moved to later", "script": "ready", "decision": "later"},
            {"title": "Funnel leaks", "script": "ready"},
            {"title": "Decision taken back", "script": "ready", "decision": None},
            {"title": "Listed before decisions were kept", "script": "ready", "decision": "no_row"},
            {"title": "No script asked for yet"},
            {"title": "Spare with a script", "slot": "reserve", "script": "ready"},
            {"title": "Spare without one", "slot": "reserve"},
        ],
        revision=23,
    )
    on_week(monkeypatch, THIS_WEEK)

    today = (await client.get("/api/v1/editorial/today", headers=headers(ws))).json()

    week = today["week"]
    assert week["week_start"] == "2026-09-28"
    carried = [
        "Invoices nobody opens",
        "Receptionist at night",
        "Still being written",
        "Funnel leaks",
        "Listed before decisions were kept",
        "No script asked for yet",
    ]
    assert titles(week) == carried, "same order; filmed, rejected and un-chosen stay behind"
    assert [row["rank"] for row in week["primary"]] == [1, 2, 3, 4, 5, 6]
    assert titles(week, "reserve") == ["Spare with a script", "Spare without one"]
    assert week["ready_count"] == 4
    assert today["attention"]["scripts_ready"] == 4
    assert today["next_action"]["key"] == "record"
    assert today["next_action"]["href"] == f"/record?candidate={ids['Invoices nobody opens']}"
    assert week["revision"] == 2, "one revision for the whole carry"

    # The week page and the studio read the same list.
    assert titles(await current_week(client, ws)) == carried
    async with editorial_sessionmaker() as s:
        queue = await prod.recording_queue(ws=ws, db=s)
    assert [i["title"] for i in queue["ideas"]] == [
        "Invoices nobody opens",
        "Receptionist at night",
        "Funnel leaks",
        "Listed before decisions were kept",
    ]

    # Last week is history: left exactly as it was.
    async with editorial_sessionmaker() as s:
        last = await s.get(WeeklyLineup, last_id)
        assert last.revision == 23
        assert len(await lineup_service.list_items(s, ws, last_id)) == 12


async def test_the_carry_runs_once_so_a_topic_he_takes_out_stays_out(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    on_week(monkeypatch, LAST_WEEK)
    _, ids = await seed_week(
        editorial_sessionmaker,
        ws,
        LAST_WEEK,
        [
            {"title": "Invoices nobody opens", "script": "ready"},
            {"title": "Receptionist at night", "script": "ready"},
            {"title": "Funnel leaks", "script": "draft"},
        ],
    )
    on_week(monkeypatch, THIS_WEEK)

    first = await current_week(client, ws)
    assert titles(first) == ["Invoices nobody opens", "Receptionist at night", "Funnel leaks"]
    out = await client.patch(
        "/api/v1/editorial/weeks/current/lineup",
        json={
            "move": {"candidate_id": str(ids["Receptionist at night"]), "action": "remove"},
            "expected_revision": first["revision"],
        },
        headers=headers(ws),
    )
    assert out.status_code == 200, out.text

    again = await current_week(client, ws)
    assert titles(again) == ["Invoices nobody opens", "Funnel leaks"]
    assert again["revision"] == out.json()["revision"], "reading again writes nothing"
    today = (await client.get("/api/v1/editorial/today", headers=headers(ws))).json()
    assert titles(today["week"]) == ["Invoices nobody opens", "Funnel leaks"]
    assert today["attention"]["scripts_ready"] == 1


async def test_an_empty_week_that_already_exists_is_filled_on_its_first_read(
    client, editorial_sessionmaker, monkeypatch
):
    """The live state on 28-Sep: the new week's list was created empty (revision 1)
    before this fix, so the carry has to fill a list that exists, not only a new one."""
    ws = uuid.uuid4()
    on_week(monkeypatch, LAST_WEEK)
    await seed_week(
        editorial_sessionmaker,
        ws,
        LAST_WEEK,
        [
            {"title": "Invoices nobody opens", "script": "ready"},
            {"title": "Receptionist at night", "script": "ready"},
        ],
        revision=23,
    )
    empty_id, _ = await seed_week(editorial_sessionmaker, ws, THIS_WEEK, [])
    on_week(monkeypatch, THIS_WEEK)

    today = (await client.get("/api/v1/editorial/today", headers=headers(ws))).json()

    assert today["week"]["lineup_id"] == str(empty_id)
    assert titles(today["week"]) == ["Invoices nobody opens", "Receptionist at night"]
    assert today["attention"]["scripts_ready"] == 2
    assert today["week"]["revision"] == 2
    async with editorial_sessionmaker() as s:
        row = await s.get(WeeklyLineup, empty_id)
        assert row.carried_at is not None, "Today's read is kept, not rolled back"
        assert row.carried_from_lineup_id is not None


async def test_only_the_current_week_is_filled_and_only_from_an_earlier_one(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    on_week(monkeypatch, LAST_WEEK)
    await seed_week(
        editorial_sessionmaker,
        ws,
        LAST_WEEK,
        [{"title": "Invoices nobody opens", "script": "ready"}],
    )

    # Looking ahead at next week while this one is still running copies nothing.
    ahead = await client.get("/api/v1/editorial/weeks/2026-09-28/lineup", headers=headers(ws))
    assert ahead.json()["primary"] == []
    assert titles(await current_week(client, ws)) == ["Invoices nobody opens"]
    # An older week is history, never filled from one older still. The week before
    # it has a topic, so a carry into a past week would have something to copy:
    # the live diagnostic GET of 14-Sep would otherwise fill it and make it a
    # carry source for the weeks after.
    await seed_week(
        editorial_sessionmaker,
        ws,
        date(2026, 9, 7),
        [{"title": "Older still", "script": "ready"}],
    )
    older = await client.get("/api/v1/editorial/weeks/2026-09-14/lineup", headers=headers(ws))
    assert older.json()["primary"] == []
    async with editorial_sessionmaker() as s:
        row = await s.get(WeeklyLineup, uuid.UUID(older.json()["lineup_id"]))
        assert row.carried_at is None, "a past week never runs the carry"

    # When that week arrives, the list he opened ahead of time is filled then.
    on_week(monkeypatch, THIS_WEEK)
    assert titles(await current_week(client, ws)) == ["Invoices nobody opens"]


async def test_a_decision_on_monday_morning_keeps_the_place_it_took_the_topic_from(
    client, editorial_sessionmaker, monkeypatch
):
    """'Later' as the first thing he does in the new week: the topic comes off the
    carried list at its place, so taking that back puts it back there."""
    ws = uuid.uuid4()
    on_week(monkeypatch, LAST_WEEK)
    _, ids = await seed_week(
        editorial_sessionmaker,
        ws,
        LAST_WEEK,
        [
            {"title": "Invoices nobody opens", "script": "ready"},
            {"title": "Receptionist at night", "script": "ready"},
            {"title": "Funnel leaks", "script": "ready"},
        ],
    )
    on_week(monkeypatch, THIS_WEEK)
    middle = ids["Receptionist at night"]

    later = await client.post(
        f"/api/v1/editorial/topics/{middle}/decide",
        json={"decision": "later", "by": "voice"},
        headers=headers(ws),
    )
    assert later.status_code == 200, later.text
    assert later.json()["removed_from_week"] == {"slot": "primary", "rank": 2}
    assert titles(await current_week(client, ws)) == ["Invoices nobody opens", "Funnel leaks"]

    back = await client.post(
        f"/api/v1/editorial/topics/{middle}/decide",
        json={"decision": "this_week", "by": "voice"},
        headers=headers(ws),
    )
    assert back.json()["placed"]["rank"] == 2
    assert titles(await current_week(client, ws)) == [
        "Invoices nobody opens",
        "Receptionist at night",
        "Funnel leaks",
    ]


async def test_a_filmed_topic_stays_behind_and_a_resting_take_does_not_count(
    client, editorial_sessionmaker, monkeypatch
):
    """28-Sep, the live week: one topic had its captioned edit made and was still
    listed as planned (nothing marks a lineup item recorded), another had only a
    take resting on the server, which he counts as "didn't film them yet". Any
    upload marks the topic "recorded", so that status cannot tell the two apart;
    how far the take got can."""
    ws = uuid.uuid4()
    on_week(monkeypatch, LAST_WEEK)
    filmed = {"script": "ready", "status": "recorded"}
    await seed_week(
        editorial_sessionmaker,
        ws,
        LAST_WEEK,
        [
            {"title": "Edited and captioned", "takes": ["edited"], **filmed},
            {"title": "Resting take only", "takes": ["uploaded"], **filmed},
            {"title": "Being transcribed", "takes": ["transcribing"], **filmed},
            {"title": "Waiting for his review", "takes": ["needs_review"], **filmed},
            {"title": "Edit archived", "takes": ["edited"], "archived": True, **filmed},
            {"title": "Take failed", "takes": ["failed"], **filmed},
            {"title": "Two resting takes", "takes": ["superseded", "uploaded"], **filmed},
            {
                "title": "Posted, then archived",
                "takes": ["edited"],
                "archived": True,
                "posted": True,
                **filmed,
            },
            {"title": "Marked published by hand", "script": "ready", "status": "published"},
            {"title": "Not filmed at all", "script": "ready"},
        ],
    )
    on_week(monkeypatch, THIS_WEEK)

    week = await current_week(client, ws)

    assert titles(week) == [
        "Resting take only",
        "Edit archived",
        "Take failed",
        "Two resting takes",
        "Not filmed at all",
    ]
    assert all(row["filmed"] is False for row in week["primary"])


async def test_a_filmed_topic_in_the_week_is_shown_but_never_offered_for_recording(
    client, editorial_sessionmaker, monkeypatch
):
    """A topic he filmed stays in its week, so the week shows what he did, but it
    is not "Start recording" again: not on Today, not in the count, not in the
    studio."""
    ws = uuid.uuid4()
    on_week(monkeypatch, THIS_WEEK)
    _, ids = await seed_week(
        editorial_sessionmaker,
        ws,
        THIS_WEEK,
        [
            {"title": "Filmed on Sunday", "script": "ready", "takes": ["edited"]},
            {"title": "Next to film", "script": "ready"},
            {"title": "Still being written", "script": "draft"},
        ],
    )

    today = (await client.get("/api/v1/editorial/today", headers=headers(ws))).json()

    week = today["week"]
    assert titles(week) == ["Filmed on Sunday", "Next to film", "Still being written"]
    assert [row["filmed"] for row in week["primary"]] == [True, False, False]
    assert week["ready_count"] == 1
    assert today["attention"]["scripts_ready"] == 1
    assert today["next_action"]["key"] == "record"
    assert today["next_action"]["href"] == f"/record?candidate={ids['Next to film']}"
    async with editorial_sessionmaker() as s:
        queue = await prod.recording_queue(ws=ws, db=s)
    assert [i["title"] for i in queue["ideas"]] == ["Next to film"]


async def test_a_take_is_filmed_by_what_the_pipeline_made_of_it_not_by_how_it_stopped(
    client, editorial_sessionmaker, monkeypatch
):
    """28-Sep review: a re-render of a finished edit that threw left the take
    "failed" with its transcript, cut and edited video still on it, and the topic
    went back to "Record this one", into the studio and into next week's carry.
    A take cut off before anything came of it ("unavailable" with the worker
    away, "interrupted" by a restart) counted as filmed. How a step stopped says
    nothing about whether he filmed it; what the pipeline made of the take does."""
    ws = uuid.uuid4()
    on_week(monkeypatch, THIS_WEEK)
    heard = [{"start_s": 0.0, "end_s": 1.0, "text": "Nobody opens the invoice."}]
    cut = {"keep": [[0.0, 1.0]], "dropped": []}
    _, ids = await seed_week(
        editorial_sessionmaker,
        ws,
        THIS_WEEK,
        [
            {
                "title": "Re-render failed after the edit",
                "script": "ready",
                "takes": [
                    {
                        "status": "failed",
                        "transcript": heard,
                        "edit_plan": cut,
                        "edited_path": "/tmp/take-edited.mp4",
                    }
                ],
            },
            {
                "title": "Cut, then the worker went away",
                "script": "ready",
                "takes": [{"status": "unavailable", "transcript": heard, "edit_plan": cut}],
            },
            {
                "title": "Transcribed, then a restart",
                "script": "ready",
                "takes": [{"status": "interrupted", "transcript": heard}],
            },
            {"title": "Failed before a word was heard", "script": "ready", "takes": ["failed"]},
            {"title": "Worker away before a word", "script": "ready", "takes": ["unavailable"]},
            {"title": "Restart before a word", "script": "ready", "takes": ["interrupted"]},
        ],
    )

    today = (await client.get("/api/v1/editorial/today", headers=headers(ws))).json()

    assert {row["title"]: row["filmed"] for row in today["week"]["primary"]} == {
        "Re-render failed after the edit": True,
        "Cut, then the worker went away": True,
        "Transcribed, then a restart": True,
        "Failed before a word was heard": False,
        "Worker away before a word": False,
        "Restart before a word": False,
    }
    assert today["attention"]["scripts_ready"] == 3
    assert (
        today["next_action"]["href"]
        == f"/record?candidate={ids['Failed before a word was heard']}"
    )


def test_a_week_whose_topics_are_all_filmed_asks_for_no_recording_and_no_script():
    week = {
        "primary": [
            {"title": "Filmed", "candidate_id": "c1", "script_state": "ready", "filmed": True},
            {"title": "Filmed too", "candidate_id": "c2", "script_state": "none", "filmed": True},
        ]
    }

    action = today_service._next_action(week=week, waiting=4, pending_reviews=0)

    assert action["key"] == "choose_week"


async def test_the_carry_comes_from_the_last_week_with_topics_not_an_empty_look(
    client, editorial_sessionmaker, monkeypatch
):
    """Any read of a week's list creates it, so an old week looked at by date is
    an empty row. Last week being one of those must not hide the week before."""
    ws = uuid.uuid4()
    source_id, _ = await seed_week(
        editorial_sessionmaker,
        ws,
        date(2026, 9, 14),
        [
            {"title": "Invoices nobody opens", "script": "ready"},
            {"title": "Funnel leaks", "script": "draft"},
        ],
    )
    await seed_week(editorial_sessionmaker, ws, LAST_WEEK, [])
    on_week(monkeypatch, THIS_WEEK)

    week = await current_week(client, ws)

    assert titles(week) == ["Invoices nobody opens", "Funnel leaks"]
    async with editorial_sessionmaker() as s:
        row = await s.get(WeeklyLineup, uuid.UUID(week["lineup_id"]))
        assert row.carried_from_lineup_id == source_id


async def test_a_week_he_emptied_himself_is_not_skipped_for_an_older_one(
    client, editorial_sessionmaker, monkeypatch
):
    """A week that ran its own carry was a real week: if he took everything out of
    it, the week before must not come back through it."""
    ws = uuid.uuid4()
    await seed_week(
        editorial_sessionmaker,
        ws,
        date(2026, 9, 14),
        [{"title": "Invoices nobody opens", "script": "ready"}],
    )
    await seed_week(editorial_sessionmaker, ws, LAST_WEEK, [], carried=True)
    on_week(monkeypatch, THIS_WEEK)

    assert (await current_week(client, ws))["primary"] == []


async def test_a_topic_he_chose_comes_over_even_when_the_engine_withdrew_it(
    client, editorial_sessionmaker, monkeypatch
):
    """His choice outranks the engine's withdrawal (a re-run of the week's
    selection, a stale news idea), the rule `chosen_and_listed` already keeps.
    What he put away, never chose, or rejected stays behind."""
    ws = uuid.uuid4()
    on_week(monkeypatch, LAST_WEEK)
    await seed_week(
        editorial_sessionmaker,
        ws,
        LAST_WEEK,
        [
            {"title": "Invoices nobody opens", "script": "ready"},
            {"title": "Engine set it aside", "script": "ready", "status": "withdrawn"},
            {
                "title": "Set aside, never decided",
                "status": "withdrawn",
                "decision": "no_row",
            },
            {"title": "Put away by him", "status": "withdrawn", "decision": "away"},
            {"title": "Rejected since", "script": "ready", "status": "rejected"},
        ],
    )
    on_week(monkeypatch, THIS_WEEK)

    week = await current_week(client, ws)

    assert titles(week) == ["Invoices nobody opens", "Engine set it aside"]
    assert week["ready_count"] == 2


async def test_todays_being_edited_count_is_the_librarys_being_edited_list(
    client, editorial_sessionmaker
):
    """28-Sep: Today said 12 being edited while nothing was: it counted takes
    resting on the server ("uploaded", nothing run on them), which the Library
    lists under Uploading. The card opens the Library's "Being edited" list, so it
    counts that list: no resting, archived or synthetic takes."""
    ws = uuid.uuid4()
    real = await add_candidate(editorial_sessionmaker, ws, "A real topic")
    synthetic = await add_candidate(
        editorial_sessionmaker, ws, "SYNTHETIC TECHNICAL TEST", origin="technical_validation"
    )
    takes = [
        (real, "uploaded", None),
        (real, "uploaded", None),
        (real, "transcribing", None),
        (real, "transcribed", None),
        (real, "proofreading", None),
        (real, "planned", None),
        (real, "rendering", None),
        (real, "needs_review", None),
        (real, "edited", None),
        (real, "failed", None),
        (real, "superseded", None),
        (real, "transcribing", datetime(2026, 9, 27)),
        (synthetic, "transcribing", None),
    ]
    async with editorial_sessionmaker() as s:
        for cid, state, archived in takes:
            s.add(
                RecordingUpload(
                    workspace_id=ws,
                    candidate_id=cid,
                    original_filename="take.mp4",
                    storage_path="/tmp/take.mp4",
                    sha256=uuid.uuid4().hex * 2,
                    status=state,
                    archived_at=archived,
                )
            )
        await s.commit()

    today = (await client.get("/api/v1/editorial/today", headers=headers(ws))).json()
    editing = (
        await client.get("/api/v1/production/library?filter=editing", headers=headers(ws))
    ).json()

    assert editing["total"] == 5
    assert today["attention"]["editing"] == editing["total"]


async def test_a_topic_he_names_opens_in_the_studio_even_when_he_filmed_it(
    editorial_sessionmaker, monkeypatch
):
    """28-Sep review: the studio lists what he has still to film, and it opens only
    an idea in its list, so "Record it again" in the Library and "Start recording"
    in the topic room led to "That script is not ready to record yet" for every
    topic he had filmed: a false sentence behind a button that went nowhere. A
    topic he names is opened when its script is ready, filmed or not, in this
    week or not. The list itself is still only what is left to film."""
    ws = uuid.uuid4()
    on_week(monkeypatch, LAST_WEEK)
    _, last = await seed_week(
        editorial_sessionmaker,
        ws,
        LAST_WEEK,
        [{"title": "Filmed last week", "script": "ready", "takes": ["edited"]}],
    )
    on_week(monkeypatch, THIS_WEEK)
    _, ids = await seed_week(
        editorial_sessionmaker,
        ws,
        THIS_WEEK,
        [
            {"title": "Filmed on Sunday", "script": "ready", "takes": ["edited"]},
            {"title": "Next to film", "script": "ready"},
            {"title": "Still being written", "script": "draft", "takes": ["edited"]},
        ],
    )

    async def studio(candidate=None) -> list[str]:
        async with editorial_sessionmaker() as s:
            queue = await prod.recording_queue(ws=ws, db=s, candidate=candidate)
        return [i["title"] for i in queue["ideas"]]

    assert await studio() == ["Next to film"]
    assert await studio(ids["Filmed on Sunday"]) == ["Filmed on Sunday", "Next to film"]
    assert await studio(last["Filmed last week"]) == ["Next to film", "Filmed last week"]
    # Named or not, a script that is not ready is not opened: that notice is true.
    assert await studio(ids["Still being written"]) == ["Next to film"]
    assert await studio(uuid.uuid4()) == ["Next to film"]


async def test_a_topic_with_only_a_resting_take_can_still_be_put_away_or_saved_for_later(
    client, editorial_sessionmaker, monkeypatch
):
    """28-Sep review: any upload marks a topic "recorded", even a take resting on
    the server, and the Topics list and "put away" read that status. So "put that
    one away" was refused "already recorded" for a topic Today lists as still to
    film, and "later" took it off the week into no list at all. Both now ask what
    the week asks: has he filmed it."""
    ws = uuid.uuid4()
    on_week(monkeypatch, THIS_WEEK)
    resting = {"script": "ready", "status": "recorded", "takes": ["uploaded"]}
    _, ids = await seed_week(
        editorial_sessionmaker,
        ws,
        THIS_WEEK,
        [
            {"title": "Resting, put away", **resting},
            {"title": "Resting, saved for later", **resting},
            {
                "title": "Filmed on Sunday",
                "script": "ready",
                "status": "recorded",
                "takes": ["edited"],
            },
        ],
    )

    async def decide(title: str, decision: str, by: str = "voice"):
        return await client.post(
            f"/api/v1/editorial/topics/{ids[title]}/decide",
            json={"decision": decision, "by": by},
            headers=headers(ws),
        )

    async def listed(filter_key: str) -> list[str]:
        body = (
            await client.get(f"/api/v1/editorial/topics?filter={filter_key}", headers=headers(ws))
        ).json()
        return [t["title"] for t in body["topics"]]

    away = await decide("Resting, put away", "away")
    assert away.status_code == 200, away.text
    assert await listed("away") == ["Resting, put away"]

    later = await decide("Resting, saved for later", "later", by="ziv")
    assert later.status_code == 200, later.text
    assert later.json()["removed_from_week"]["slot"] == "primary"
    assert await listed("later") == ["Resting, saved for later"]

    # What he has filmed is done: it lives in the Library, not in Put away.
    filmed = await decide("Filmed on Sunday", "away")
    assert filmed.status_code == 409
    assert filmed.json()["detail"]["code"] == "recorded"
    assert titles(await current_week(client, ws)) == ["Filmed on Sunday"]


async def test_the_typed_conversation_knows_which_topics_he_has_filmed(
    editorial_sessionmaker, monkeypatch
):
    """28-Sep review: the Talk sheet told the model "this is his recording list"
    and asked which one to record first, with no word of the topics Today and the
    week show as Filmed, so it could tell him to record #1 again."""
    ws = uuid.uuid4()
    on_week(monkeypatch, THIS_WEEK)
    await seed_week(
        editorial_sessionmaker,
        ws,
        THIS_WEEK,
        [
            {"title": "Filmed on Sunday", "script": "ready", "takes": ["edited"]},
            {"title": "Next to film", "script": "ready"},
            {"title": "Spare, filmed too", "slot": "reserve", "takes": ["needs_review"]},
            {"title": "Spare to film", "slot": "reserve"},
        ],
    )

    async with editorial_sessionmaker() as s:
        text = await conversation._week_context(s, ws)

    lines = text.splitlines()
    assert "1. Filmed on Sunday (Coaching) - filmed already" in lines
    assert "2. Next to film (Coaching)" in lines
    assert "- Spare, filmed too (Coaching) - filmed already" in lines
    assert "- Spare to film (Coaching)" in lines
    assert "never suggest recording one of those again" in text


# -------------------------------------------------------------- changes


async def test_a_change_is_proposed_reviewed_and_applied_over_http(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "A topic")
    room = (
        await client.get(f"/api/v1/editorial/topics/{cid}/room", headers=headers(ws))
    ).json()

    proposed = await client.post(
        "/api/v1/editorial/change-sets",
        json={
            "target_type": "candidate_brief",
            "target_id": str(cid),
            "base_version": room["brief"]["version"],
            "summary": "Say what they should take away",
            "operations": [
                {
                    "op": "set_field",
                    "field": "takeaway",
                    "after": "If your AI says done, you should be able to open the result.",
                }
            ],
        },
        headers=headers(ws),
    )
    assert proposed.status_code == 200
    change_set = proposed.json()
    assert change_set["state"] == "proposed"
    # `takeaway` was never written, and the diff says so with None rather than an
    # empty string. The review sheet renders "nothing written yet", not a blank
    # line that looks like an answer he already gave.
    assert change_set["operations"][0]["before"] is None

    # Still unchanged while it sits there.
    mid = (
        await client.get(f"/api/v1/editorial/topics/{cid}/room", headers=headers(ws))
    ).json()
    assert mid["brief"]["version"] == 1

    applied = await client.post(
        f"/api/v1/editorial/change-sets/{change_set['id']}/apply", headers=headers(ws)
    )
    assert applied.status_code == 200
    assert applied.json()["version"] == 2

    after = (
        await client.get(f"/api/v1/editorial/topics/{cid}/room", headers=headers(ws))
    ).json()
    assert after["brief"]["values"]["takeaway"].startswith("If your AI says done")
    assert len(after["history"]) == 2


async def test_rejecting_a_proposal_leaves_the_topic_alone(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "A topic")

    change_set = (
        await client.post(
            "/api/v1/editorial/change-sets",
            json={
                "target_type": "candidate_brief",
                "target_id": str(cid),
                "base_version": 1,
                "summary": "A change he will turn down",
                "operations": [
                    {"op": "set_field", "field": "big_idea", "after": "Something worse."}
                ],
            },
            headers=headers(ws),
        )
    ).json()

    rejected = await client.post(
        f"/api/v1/editorial/change-sets/{change_set['id']}/reject", headers=headers(ws)
    )
    assert rejected.json()["state"] == "rejected"

    room = (
        await client.get(f"/api/v1/editorial/topics/{cid}/room", headers=headers(ws))
    ).json()
    assert room["brief"]["version"] == 1


async def test_a_version_can_be_restored_over_http(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "A topic")
    original = (
        await client.get(f"/api/v1/editorial/topics/{cid}/room", headers=headers(ws))
    ).json()["brief"]["values"]["big_idea"]

    change_set = (
        await client.post(
            "/api/v1/editorial/change-sets",
            json={
                "target_type": "candidate_brief",
                "target_id": str(cid),
                "base_version": 1,
                "summary": "Rewrite the lesson",
                "operations": [
                    {"op": "set_field", "field": "big_idea", "after": "A worse sentence."}
                ],
            },
            headers=headers(ws),
        )
    ).json()
    await client.post(
        f"/api/v1/editorial/change-sets/{change_set['id']}/apply", headers=headers(ws)
    )

    restored = await client.post(
        f"/api/v1/editorial/versions/candidate_brief/{cid}/restore",
        json={"to_version": 1},
        headers=headers(ws),
    )
    assert restored.status_code == 200

    room = (
        await client.get(f"/api/v1/editorial/topics/{cid}/room", headers=headers(ws))
    ).json()
    assert room["brief"]["values"]["big_idea"] == original
    assert room["brief"]["version"] == 3


# --------------------------------------------------------------- library


async def test_the_library_never_shows_a_button_that_leads_nowhere(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Recorded topic")
    async with editorial_sessionmaker() as s:
        s.add(
            RecordingUpload(
                workspace_id=ws,
                candidate_id=cid,
                original_filename="take.mp4",
                storage_path="/tmp/take.mp4",
                sha256="b" * 64,
                status="uploaded",
                duration_s=160.0,
            )
        )
        await s.commit()

    body = (await client.get("/api/v1/production/library", headers=headers(ws))).json()

    item = body["items"][0]
    keys = {a["key"] for a in item["actions"]}
    assert item["title"] == "Recorded topic"
    assert "watch_raw" in keys
    # No captions, no edit, no transcript exist yet, so none is offered.
    assert "captions" not in keys
    assert "watch_edit" not in keys
    assert "transcript" not in keys
    assert item["state_sentence"]


async def test_a_synthetic_pipeline_take_never_appears_in_the_library(
    client, editorial_sessionmaker
):
    """Found on his real data: "SYNTHETIC TECHNICAL TEST" sitting in the Library.

    The older /recorded endpoint has always excluded these. The library replaces
    that surface, so it has to agree rather than quietly re-introduce the artifact.
    """
    ws = uuid.uuid4()
    real = await add_candidate(editorial_sessionmaker, ws, "A real topic")
    synthetic = await add_candidate(
        editorial_sessionmaker, ws, "SYNTHETIC TECHNICAL TEST", origin="technical_validation"
    )
    async with editorial_sessionmaker() as s:
        for cid, digest in ((real, "1"), (synthetic, "2")):
            s.add(
                RecordingUpload(
                    workspace_id=ws,
                    candidate_id=cid,
                    original_filename="take.mp4",
                    storage_path="/tmp/take.mp4",
                    sha256=digest * 64,
                    status="uploaded",
                )
            )
        await s.commit()

    body = (await client.get("/api/v1/production/library", headers=headers(ws))).json()

    assert [i["title"] for i in body["items"]] == ["A real topic"]


async def test_the_edited_video_is_first_and_replaced_takes_are_gone(
    client, editorial_sessionmaker
):
    """25-Sep: "I need a way to find the edited video on tce". His Library held 12
    cards with the same title - the edit among old takes and two superseded,
    broken versions - and nothing said which was the edit."""
    from datetime import datetime, timedelta

    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Walk topic")
    now = datetime(2026, 9, 24, 12, 0)
    rows = [
        ("edited", "a", now - timedelta(hours=2), "/tmp/edit.mp4"),
        ("superseded", "b", now - timedelta(hours=1), None),
        ("uploaded", "c", now, None),
    ]
    async with editorial_sessionmaker() as s:
        for status, digest, at, edited in rows:
            s.add(
                RecordingUpload(
                    workspace_id=ws, candidate_id=cid, original_filename=f"{digest}.mp4",
                    storage_path="/tmp/take.mp4", sha256=digest * 64, status=status,
                    edited_path=edited, created_at=at,
                )
            )
        await s.commit()

    body = (await client.get("/api/v1/production/library", headers=headers(ws))).json()

    assert [i["status"] for i in body["items"]] == ["edited", "uploaded"]
    assert body["items"][0]["has_edit"] is True


async def test_published_videos_have_their_own_tab_and_leave_the_to_do_list(
    client, editorial_sessionmaker
):
    """28-Sep, on a call: published videos get their own tab, and the view he opens
    to shows only what still needs pushing through (recorded, being edited, waiting
    to go out). A video counts as out once any post went out or is scheduled, or
    its topic was marked published; the other takes of that topic go with it."""
    ws = uuid.uuid4()
    posted = await add_candidate(editorial_sessionmaker, ws, "Posted on Instagram")
    marked = await add_candidate(editorial_sessionmaker, ws, "Marked published", status="published")
    waiting = await add_candidate(editorial_sessionmaker, ws, "Edited, not out")
    drafted = await add_candidate(editorial_sessionmaker, ws, "Posts drafted only")
    raw = await add_candidate(editorial_sessionmaker, ws, "Just recorded")
    async with editorial_sessionmaker() as s:
        rows = {}
        for cid, digest, status in (
            (posted, "1", "edited"), (posted, "2", "uploaded"), (marked, "3", "edited"),
            (waiting, "4", "edited"), (drafted, "5", "edited"), (raw, "6", "uploaded"),
        ):
            row = RecordingUpload(
                workspace_id=ws, candidate_id=cid, original_filename=f"{digest}.mp4",
                storage_path="/tmp/take.mp4", sha256=digest * 64, status=status,
                edited_path="/tmp/edit.mp4" if status == "edited" else None,
            )
            s.add(row)
            rows[digest] = row
        await s.flush()
        s.add(VideoPublication(workspace_id=ws, upload_id=rows["1"].id, candidate_id=posted,
                               platform="instagram", status="posted"))
        s.add(VideoPublication(workspace_id=ws, upload_id=rows["1"].id, candidate_id=posted,
                               platform="linkedin", status="draft"))
        s.add(VideoPublication(workspace_id=ws, upload_id=rows["5"].id, candidate_id=drafted,
                               platform="facebook", status="draft"))
        await s.commit()

    lib = "/api/v1/production/library"

    async def titles(key):
        body = (await client.get(f"{lib}?filter={key}", headers=headers(ws))).json()
        assert "items" in body, body
        return body, sorted({i["title"] for i in body["items"]})

    body, todo = await titles("todo")
    assert todo == ["Edited, not out", "Just recorded", "Posts drafted only"]
    assert body["filters"][0] == {"key": "todo", "label": "Still to do"}
    assert "published" in [f["key"] for f in body["filters"]]
    _, out = await titles("published")
    assert out == ["Marked published", "Posted on Instagram"]
    _, ready = await titles("ready")
    assert ready == ["Edited, not out", "Posts drafted only"]
    body, everything = await titles("all")
    assert len(body["items"]) == 6
    assert {i["title"] for i in body["items"] if i["published"]} == set(out)


def test_the_library_opens_on_the_to_do_list():
    from pathlib import Path

    js = (Path(__file__).parents[2] / "src/tce/api/workspace.js").read_text()
    assert 'libraryFilter: "todo"' in js


async def test_an_editing_request_is_recorded_against_the_recording(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Recorded topic")
    async with editorial_sessionmaker() as s:
        upload = RecordingUpload(
            workspace_id=ws,
            candidate_id=cid,
            original_filename="take.mp4",
            storage_path="/tmp/take.mp4",
            sha256="c" * 64,
            status="edited",
            edited_path="/tmp/take-edit.mp4",
        )
        s.add(upload)
        await s.commit()
        upload_id = upload.id

    created = await client.post(
        f"/api/v1/production/recordings/{upload_id}/edit-requests",
        json={
            "request": "Cut the pause before the last point.",
            "scope": "timestamp",
            "start_s": 62.0,
            "end_s": 71.5,
        },
        headers=headers(ws),
    )
    assert created.status_code == 200
    assert created.json()["where"] == "1:02 to 1:11"

    listed = (
        await client.get(
            f"/api/v1/production/recordings/{upload_id}/edit-requests", headers=headers(ws)
        )
    ).json()
    assert len(listed["requests"]) == 1
    assert listed["requests"][0]["state"] == "open"


async def test_an_editing_request_with_a_backwards_range_is_refused(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Recorded topic")
    async with editorial_sessionmaker() as s:
        upload = RecordingUpload(
            workspace_id=ws,
            candidate_id=cid,
            original_filename="take.mp4",
            storage_path="/tmp/take.mp4",
            sha256="d" * 64,
            status="edited",
        )
        s.add(upload)
        await s.commit()
        upload_id = upload.id

    response = await client.post(
        f"/api/v1/production/recordings/{upload_id}/edit-requests",
        json={"request": "Cut this", "scope": "timestamp", "start_s": 90.0, "end_s": 12.0},
        headers=headers(ws),
    )
    assert response.status_code == 400


# ------------------------------------------------------------- isolation


async def test_another_workspace_is_never_read(client, editorial_sessionmaker):
    mine = uuid.uuid4()
    theirs = uuid.uuid4()
    await add_candidate(editorial_sessionmaker, theirs, "Not mine")

    body = (await client.get("/api/v1/editorial/topics", headers=headers(mine))).json()
    assert body["topics"] == []


async def test_start_recording_points_at_the_idea_not_the_list(
    client, editorial_sessionmaker
):
    """Ziv: "too many clicks to just start the work."

    Getting from a topic he had already chosen to actually recording it meant
    opening the topic, opening the workshop, going to the studio and then finding
    the same card in the queue again. Today's record action now carries the
    candidate, and the studio opens it directly.
    """
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Ready to record")
    await client.post(
        f"/api/v1/editorial/topics/{cid}/decide",
        json={"decision": "this_week"},
        headers=headers(ws),
    )
    async with editorial_sessionmaker() as s:
        s.add(
            RecordingPacket(
                workspace_id=ws,
                candidate_id=cid,
                version=1,
                bullets=["a"],
                script_phrases=["b"],
                status="ready",
                citations_private=[],
                public_safety={},
            )
        )
        await s.commit()

    body = (await client.get("/api/v1/editorial/today", headers=headers(ws))).json()

    assert body["next_action"]["key"] == "record"
    assert body["next_action"]["href"] == f"/record?candidate={cid}"


# --------------------------------------------------------------- settings


async def test_videos_a_week_is_saved_and_a_fifth_topic_still_goes_into_the_week(
    client, editorial_sessionmaker
):
    """26-Sep: choose how many videos a week, and go past it on a good week."""
    ws = uuid.uuid4()
    assert (await client.get("/api/v1/editorial/settings", headers=headers(ws))).json()[
        "videos_per_week"
    ] == 3
    saved = await client.put(
        "/api/v1/editorial/settings", json={"videos_per_week": 4}, headers=headers(ws)
    )
    assert saved.status_code == 200 and saved.json()["videos_per_week"] == 4
    refused = await client.put(
        "/api/v1/editorial/settings", json={"videos_per_week": 0}, headers=headers(ws)
    )
    assert refused.status_code == 422
    assert (await client.get("/api/v1/editorial/settings", headers=headers(ws))).json()[
        "videos_per_week"
    ] == 4


async def test_post_rules_start_as_no_call_to_action_and_are_his_to_rewrite(
    client, editorial_sessionmaker
):
    """26-Sep: "I want to build an audience without asking anyone for anything." """
    ws = uuid.uuid4()
    first = (await client.get("/api/v1/editorial/settings", headers=headers(ws))).json()
    assert "No call to action" in first["post_rules"]
    saved = await client.put("/api/v1/editorial/settings",
                             json={"post_rules": "Short. No hashtags on Facebook."}, headers=headers(ws))
    assert saved.json()["post_rules"] == "Short. No hashtags on Facebook."
    assert saved.json()["videos_per_week"] == 3, "saving the rules left the weekly number alone"
    cleared = await client.put("/api/v1/editorial/settings", json={"post_rules": ""}, headers=headers(ws))
    assert "No call to action" in cleared.json()["post_rules"], "empty goes back to the default"


async def test_archive_hides_a_recording_and_bring_it_back_restores_it(client, editorial_sessionmaker):
    """27-Sep: "need to be able to archive" in the Library. Nothing is deleted."""
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Old take")
    async with editorial_sessionmaker() as s:
        up = RecordingUpload(workspace_id=ws, candidate_id=cid, original_filename="t.mp4",
                             storage_path="/tmp/t.mp4", sha256="e" * 64, status="uploaded")
        s.add(up)
        await s.commit()
        uid = up.id
    lib = "/api/v1/production/library"
    assert len((await client.get(lib, headers=headers(ws))).json()["items"]) == 1
    r = await client.post(f"/api/v1/production/recordings/{uid}/archive", json={"archived": True}, headers=headers(ws))
    assert r.json()["archived"] is True
    assert (await client.get(lib, headers=headers(ws))).json()["items"] == []
    archived = (await client.get(lib + "?filter=archived", headers=headers(ws))).json()["items"]
    assert [i["archived"] for i in archived] == [True]
    await client.post(f"/api/v1/production/recordings/{uid}/archive", json={"archived": False}, headers=headers(ws))
    assert len((await client.get(lib, headers=headers(ws))).json()["items"]) == 1
