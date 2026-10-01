"""Talk to the editor, review of steps 5, 7 and 8 (1-Oct): the server side.

KM BOT's voice test call (scenario F, a note on a paused TCE video) needs to know
whether a notes sheet is already open on a video before it pins a test note there,
and to close the sitting it used, so a request he types afterwards never joins it.
And the notes F drops (one per run, on the same published video) must not become
the editor's "earlier notes" when he types a request on that video.

Synthetic data on SQLite. The subscription and the renderer are replaced; the routes,
the rows and the history query are the real code.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from tce.api.routers import production as prod
from tce.editorial import library
from tce.models.editorial_workspace import EditingRequest, EditSession
from tce.production import autoedit
from tests.unit.test_autoedit_flow import seed as seed_planned
from tests.unit.test_autoedit_flow import wired  # noqa: F401 - fixture
from tests.unit.test_talk_to_editor import (  # noqa: F401 - fixtures
    age_sitting,
    client,
    edited,
    headers,
    open_talk,
    renders,
)


async def _pin(client, ws, sid, render_ref, edit_s=1.0) -> dict:
    r = await client.post(
        f"/api/v1/production/talk/{sid}/notes",
        json={"edit_s": edit_s, "render_ref": render_ref, "by": "voice"},
        headers=headers(ws),
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _patch(client, ws, sid, nid, **body):
    return await client.patch(f"/api/v1/production/talk/{sid}/notes/{nid}", json=body, headers=headers(ws))


async def _close(client, ws, sid):
    return await client.post(f"/api/v1/production/talk/{sid}/close", headers=headers(ws))


async def test_opening_the_notes_says_whether_a_sheet_was_already_in_front_of_him(client, renders, tmp_path):
    ws, uid, _row = await edited(renders, tmp_path)
    first = await open_talk(client, ws, uid)
    assert first["was_active"] is False, "nobody had the notes open"
    again = await open_talk(client, ws, uid)
    assert again["session_id"] == first["session_id"]
    assert again["was_active"] is True, "a sheet checked in a moment ago: the voice test call must leave it alone"
    await age_sitting(renders["sm"], first["session_id"], library.SITTING_ACTIVE_S + 5)
    later = await open_talk(client, ws, uid)
    assert later["session_id"] == first["session_id"] and later["was_active"] is False


async def test_a_sitting_with_no_note_waiting_closes_and_nothing_joins_it(client, renders, tmp_path, monkeypatch):
    ran: list[uuid.UUID] = []
    monkeypatch.setattr(prod, "start_edit_request", lambda rid, ws, *a, **k: ran.append(rid))
    ws, uid, row = await edited(renders, tmp_path)
    sitting = await open_talk(client, ws, uid)
    sid = sitting["session_id"]
    note = await _pin(client, ws, sid, row.render_ref)
    assert (await _patch(client, ws, sid, note["note_id"], heard="Tighten this bit")).status_code == 200

    refused = await _close(client, ws, sid)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "notes_waiting" and refused.json()["detail"]["waiting"] == 1
    assert "1 note is still waiting here" in refused.json()["detail"]["message"]

    assert (await _patch(client, ws, sid, note["note_id"], drop=True)).status_code == 200
    closed = await _close(client, ws, sid)
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "closed" and closed.json()["finished_at"]
    assert (await _close(client, ws, sid)).json()["state"] == "closed", "closing twice changes nothing"

    # A request he types now runs on its own: it never joins the closed sitting.
    r = await client.post(
        f"/api/v1/production/recordings/{uid}/edit-requests",
        json={"request": "Make the captions bigger", "scope": "whole"},
        headers=headers(ws),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("joined_sitting") is None and body.get("session_id") is None, body
    assert ran == [uuid.UUID(body["id"])]

    # Nothing more is pinned there, and opening the notes again starts a new sitting.
    refused_pin = await client.post(
        f"/api/v1/production/talk/{sid}/notes",
        json={"edit_s": 1.0, "render_ref": row.render_ref},
        headers=headers(ws),
    )
    assert refused_pin.status_code == 409
    fresh = await open_talk(client, ws, uid)
    assert fresh["session_id"] != sid and fresh["state"] == "open" and fresh["was_active"] is False


async def test_a_sitting_whose_notes_are_being_made_is_not_closed(client, renders, tmp_path):
    ws, uid, _row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    async with renders["sm"]() as s:
        (await s.get(EditSession, uuid.UUID(sid))).state = "thinking"
        await s.commit()
    r = await _close(client, ws, sid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_open"


async def test_a_typed_requests_history_leaves_out_sitting_notes_that_were_never_made(wired):  # noqa: F811
    """Review finding: each voice test call drops a note on the same published video.
    The typed request's history read every row on the video, so after a few runs his
    real earlier requests fell out of the 12-row window and Opus read test notes (and
    empty taps) as things he had asked for."""
    ws, uid = await seed_planned(wired["sm"], planned=True)
    now = prod._utcnow()
    async with wired["sm"]() as s:
        sitting = EditSession(workspace_id=ws, upload_id=uid, state="open", render_ref=None,
                              keep_snapshot=None, last_seen=now - timedelta(minutes=30))
        s.add(sitting)
        await s.flush()
        s.add_all([
            EditingRequest(workspace_id=ws, upload_id=uid, scope="whole", request="Make the captions bigger",
                           state="done", result={"reply": "Captions are bigger now."},
                           created_at=now - timedelta(minutes=20)),
            # The test call's note, said and then taken back, and a tap with no words.
            EditingRequest(workspace_id=ws, upload_id=uid, scope="moment", start_s=1.0, end_s=None,
                           session_id=sitting.id, request="Tighten this bit, the pause right here drags on.",
                           state="rejected", created_at=now - timedelta(minutes=10)),
            EditingRequest(workspace_id=ws, upload_id=uid, scope="moment", start_s=2.0, end_s=None,
                           session_id=sitting.id, request="", state="rejected",
                           created_at=now - timedelta(minutes=9)),
        ])
        typed = EditingRequest(workspace_id=ws, upload_id=uid, scope="whole", request="Move the title up",
                               state="open", created_at=now)
        s.add(typed)
        await s.commit()
    wired["answers"][autoedit.EDIT_REQUEST_JOB] = {
        "reply": "", "needs_you": True, "question": "Up to where?",
        "corrections": [], "cut": [], "restore": [], "hold": [],
    }
    await prod.run_edit_request(typed.id, ws)
    kind, prompt = wired["asked"][-1]
    assert kind == autoedit.EDIT_REQUEST_JOB
    assert "He wrote: Make the captions bigger | You answered: Captions are bigger now." in prompt
    assert "Tighten this bit" not in prompt, "a note taken back is not something he asked for"
    assert not any(line.strip() == "- He wrote:" for line in prompt.splitlines()), "an empty tap became a line"
    assert set(prod.SITTING_NOTES_NEVER_MADE) == {"rejected", *library.WAITING_NOTE_STATES}
