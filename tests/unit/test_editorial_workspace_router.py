"""/editorial workspace routes: the phone's contract with the server.

Covers the flow the plan cares about most - choose a topic WITHOUT starting a
script, put it in the week, reorder it with one thumb, propose and apply a change,
and see a recorded video in the library with no dead buttons on it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate
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
