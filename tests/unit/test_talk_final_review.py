"""Talk to the editor, final review of 1-Oct: the server side.

On the sheet every hold is pinned, typed or spoken, and his "make it", his "yes",
"no, I meant...", "scratch that" and "go back" each arrive as a pin too. These tests
hold the server to what the review asked:

- the editor's default read is the hold he just spoke, picked by his words, never an
  older note nobody read on the call (a typed one, or one Live answered itself);
- a hold that carried an instruction is taken back, and a yes given after the read-back
  never changes the check code or reaches the batch;
- a pin on notes another screen closed opens them again;
- a pin with no words never keeps a sitting open, and never counts as waiting;
- notes are not made while an earlier re-edit waits for his eyes, and nothing blames
  his notes for that;
- the sheet's own address is served, so a reload of it reopens the same notes.

Synthetic data on SQLite. The subscription and the renderer are replaced; the routes,
the rows and the clock are the real code.
"""

from __future__ import annotations

import uuid

from tce.api.routers import production as prod
from tce.editorial import library
from tce.models.editorial_workspace import EditingRequest, EditSession
from tests.unit.test_talk_to_editor import (  # noqa: F401 - fixtures
    age_sitting,
    client,
    edited,
    headers,
    open_talk,
    renders,
)

BLOCKED_DETAIL = 'Needs review: Dropped take at 0:03 says "not after" where the kept one says "after"'


async def _pin(client, ws, sid, render_ref, edit_s=1.0, by="voice") -> dict:
    r = await client.post(
        f"/api/v1/production/talk/{sid}/notes",
        json={"edit_s": edit_s, "render_ref": render_ref, "by": by},
        headers=headers(ws),
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _patch(client, ws, sid, nid, **body):
    return await client.patch(f"/api/v1/production/talk/{sid}/notes/{nid}", json=body, headers=headers(ws))


async def _note(client, ws, sid, render_ref, edit_s, heard, *, by="voice", understood=None) -> str:
    """A hold (or a typed note): the pin, then his words, then the editor's reading."""
    nid = (await _pin(client, ws, sid, render_ref, edit_s, by=by))["note_id"]
    assert (await _patch(client, ws, sid, nid, heard=heard)).status_code == 200
    if understood:
        assert (await _patch(client, ws, sid, nid, understood=understood)).status_code == 200
    return nid


async def _moment(client, ws, sid, **query) -> dict:
    r = await client.get(f"/api/v1/production/talk/{sid}/moment", params=query, headers=headers(ws))
    assert r.status_code == 200, r.text
    return r.json()


async def _command(client, ws, sid, **body):
    return await client.post(f"/api/v1/production/talk/{sid}/command", json=body, headers=headers(ws))


async def _rows(sm, sid) -> dict[str, EditingRequest]:
    from sqlalchemy import select

    async with sm() as s:
        rows = (
            await s.execute(select(EditingRequest).where(EditingRequest.session_id == uuid.UUID(sid)))
        ).scalars()
        return {str(r.id): r for r in rows}


# --------------------------------------------- which note the editor reads


async def test_the_editor_reads_the_hold_he_just_spoke_never_an_older_typed_note(client, renders, tmp_path):
    """Finding 1: the default read took the OLDEST unread note, and a typed note is never
    read on the call, so it took every spoken note's reading for good."""
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    typed = await _note(client, ws, sid, row.render_ref, 1.0, "the title card stays up too long", by="ziv")
    spoken = await _note(client, ws, sid, row.render_ref, 3.0, "cut the end")

    m = await _moment(client, ws, sid)
    assert m["note"]["id"] == spoken and m["at"]["clock"] == "0:03", m["note"]
    # A typed note is already written down: it never waits for a reading on the call.
    assert [w["id"] for w in m["waiting"]] == [spoken]
    assert typed in [e["id"] for e in m["earlier"]]


async def test_the_editor_reads_the_hold_whose_words_it_was_handed(client, renders, tmp_path):
    """Finding 9: a correction hold the brain never read (it rewrote the earlier note)
    stayed the oldest unread note, so every later note was read at its second."""
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    await _note(client, ws, sid, row.render_ref, 1.0, "cut the second basically",
                understood="you want the second basically gone")
    correction = await _note(client, ws, sid, row.render_ref, 2.0, "no, I meant the first one")
    new = await _note(client, ws, sid, row.render_ref, 3.0, "trim the pause here")

    m = await _moment(client, ws, sid, said="Trim the pause here.")
    assert m["note"]["id"] == new and m["at"]["clock"] == "0:03"
    assert (await _moment(client, ws, sid))["note"]["id"] == new, "with no words: the newest hold"
    assert (await _moment(client, ws, sid, said="no I meant the first one"))["note"]["id"] == correction


# --------------------------------------------- holds that carry an instruction


async def test_a_spoken_make_it_and_a_spoken_yes_are_taken_back_and_one_batch_makes_the_real_notes(
    client, renders, tmp_path, monkeypatch
):
    """Findings 2, 7 and 8: "that's all, make it" and "yes" were pinned as notes, the
    read-back held them, and every yes changed the check code, so Make never started."""
    started: list = []
    monkeypatch.setattr(prod, "start_talk_session", lambda sid_, ws_: started.append(sid_))
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    real = await _note(client, ws, sid, row.render_ref, 2.0, "cut the second basically",
                       understood="you want the second basically gone")
    make_it = await _note(client, ws, sid, row.render_ref, 2.0, "That's all, make it.")

    taken = await _command(client, ws, sid, said="that's all, make it")
    assert taken.status_code == 200, taken.text
    assert taken.json()["taken"]["id"] == make_it
    url = f"/api/v1/production/talk/{sid}/submit"
    preview = (await client.get(url, headers=headers(ws))).json()
    assert preview["read_back"] == "1 note: at 0:02: you want the second basically gone. One re-render."
    assert preview["as_of"]

    yes = await _note(client, ws, sid, row.render_ref, 2.0, "Yes.")
    assert (await _command(client, ws, sid, said="yes")).json()["taken"]["id"] == yes
    done = await client.post(url, json={"check": preview["check"], "as_of": preview["as_of"], "by": "voice"},
                             headers=headers(ws))
    assert done.status_code == 200, done.text
    assert done.json()["result"]["notes"] == [real]
    assert started == [uuid.UUID(sid)]
    rows = await _rows(renders["sm"], sid)
    for nid in (make_it, yes):
        assert rows[nid].state == "rejected" and rows[nid].result["taken"] == library.COMMAND_TAKEN


async def test_a_yes_pinned_after_the_read_back_never_changes_the_check(client, renders, tmp_path, monkeypatch):
    """Finding 8: even when nothing took the yes hold back, a yes given after the read-back
    is not a note of the read-back: it is taken back, and only what he heard is made."""
    started: list = []
    monkeypatch.setattr(prod, "start_talk_session", lambda sid_, ws_: started.append(sid_))
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    real = await _note(client, ws, sid, row.render_ref, 2.0, "cut the second basically",
                       understood="you want the second basically gone")
    url = f"/api/v1/production/talk/{sid}/submit"
    first = (await client.get(url, headers=headers(ws))).json()

    # A real note he gave and the editor read after the read-back: he must hear it.
    later = await _note(client, ws, sid, row.render_ref, 3.0, "and trim the pause",
                        understood="you want the pause trimmed")
    yes = await _note(client, ws, sid, row.render_ref, 3.0, "yes")
    changed = await client.post(url, json={"check": first["check"], "as_of": first["as_of"]}, headers=headers(ws))
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "changed"
    detail = changed.json()["detail"]
    assert "trimmed" in detail["read_back"] and '"yes"' not in detail["read_back"], detail
    assert detail["as_of"]
    # The yes stays taken back: the next read-back never reads it out as a note.
    assert (await _rows(renders["sm"], sid))[yes].state == "rejected"

    yes_again = await _note(client, ws, sid, row.render_ref, 3.0, "yes, make it")
    done = await client.post(url, json={"check": detail["check"], "as_of": detail["as_of"]}, headers=headers(ws))
    assert done.status_code == 200, done.text
    assert done.json()["result"]["notes"] == [real, later]
    assert (await _rows(renders["sm"], sid))[yes_again].state == "rejected"
    assert started == [uuid.UUID(sid)]


async def test_late_words_on_a_hold_taken_back_as_an_instruction_are_kept_quietly(client, renders, tmp_path, monkeypatch):
    """The brain can act on "make it" before the sheet saves his words on that hold. The
    sheet's late PATCH must not answer "These notes were already handed to the editor"."""
    monkeypatch.setattr(prod, "start_talk_session", lambda sid_, ws_: None)
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    real = await _note(client, ws, sid, row.render_ref, 1.0, "louder here", understood="you want it louder")
    make_it = (await _pin(client, ws, sid, row.render_ref, 2.0))["note_id"]  # his words not saved yet
    assert (await _command(client, ws, sid, said="make it")).json()["taken"]["id"] == make_it
    late = await _patch(client, ws, sid, make_it, heard="make it")
    assert late.status_code == 200, late.text
    assert late.json()["state"] == "rejected" and late.json()["request"] == "make it"

    url = f"/api/v1/production/talk/{sid}/submit"
    preview = (await client.get(url, headers=headers(ws))).json()
    yes = (await _pin(client, ws, sid, row.render_ref, 2.0))["note_id"]
    assert (await client.post(url, json={"check": preview["check"], "as_of": preview["as_of"]},
                              headers=headers(ws))).status_code == 200
    # The notes are being made; the yes hold's words land after: kept, no refusal.
    after = await _patch(client, ws, sid, yes, heard="yes")
    assert after.status_code == 200 and after.json()["state"] == "rejected", after.text
    # A real note stays frozen once the notes are handed over.
    assert (await _patch(client, ws, sid, real, heard="much louder")).status_code == 409


async def test_a_correction_and_a_scratch_that_take_back_their_own_hold_only(client, renders, tmp_path):
    """Finding 2: "no, I meant..." and "scratch that" left their own hold as a note, which
    went into the batch."""
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    unread = await _note(client, ws, sid, row.render_ref, 0.5, "something Live answered by itself")
    first = await _note(client, ws, sid, row.render_ref, 1.0, "cut the second basically",
                        understood="you want the second basically gone")
    correction = await _note(client, ws, sid, row.render_ref, 2.0, "No, I meant the first one.")
    assert (await _patch(client, ws, sid, first, understood="you want the first basically gone")).status_code == 200
    taken = await _command(client, ws, sid, said="no I meant the first one", keep=first)
    assert taken.json()["taken"]["id"] == correction

    scratch = await _note(client, ws, sid, row.render_ref, 3.0, "scratch that")
    assert (await _patch(client, ws, sid, first, drop=True)).status_code == 200
    # No words given: the newest hold after that note, never one before it.
    assert (await _command(client, ws, sid, keep=first)).json()["taken"]["id"] == scratch

    # A hold that gave a note AND said make it got a reading: it is a note, never taken back.
    both = await _note(client, ws, sid, row.render_ref, 3.5, "cut the end, and that's all, make it",
                       understood="you want the end cut")
    assert (await _command(client, ws, sid, said="cut the end, and that's all, make it")).json()["taken"] is None

    rows = await _rows(renders["sm"], sid)
    assert {nid: rows[nid].state for nid in (unread, first, correction, scratch, both)} == {
        unread: "held", first: "rejected", correction: "rejected", scratch: "rejected", both: "held",
    }
    assert rows[correction].result["command"] == "no I meant the first one"


# --------------------------------------------- closing, and two screens


async def test_a_pin_opens_notes_another_screen_closed(client, renders, tmp_path):
    """Finding 4: the desk closed the sitting the phone was using, and the phone's next
    hold was refused with "These notes were already handed to the editor"."""
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    assert (await open_talk(client, ws, uid))["session_id"] == sid  # the phone and the desk
    closed = await client.post(f"/api/v1/production/talk/{sid}/close", headers=headers(ws))
    assert closed.status_code == 200 and closed.json()["state"] == "closed"

    pinned = await client.post(
        f"/api/v1/production/talk/{sid}/notes",
        json={"edit_s": 2.0, "render_ref": row.render_ref, "by": "voice"},
        headers=headers(ws),
    )
    assert pinned.status_code == 200, pinned.text
    sitting = (await client.get(f"/api/v1/production/talk/{sid}", headers=headers(ws))).json()
    assert sitting["state"] == "open" and sitting["finished_at"] is None

    # Notes opened again since on another sitting: the old one stays closed, and says so.
    await _patch(client, ws, sid, pinned.json()["note_id"], drop=True)
    assert (await client.post(f"/api/v1/production/talk/{sid}/close", headers=headers(ws))).status_code == 200
    newer = await open_talk(client, ws, uid)
    assert newer["session_id"] != sid
    refused = await client.post(
        f"/api/v1/production/talk/{sid}/notes",
        json={"edit_s": 2.0, "render_ref": row.render_ref},
        headers=headers(ws),
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["message"] == library.NOTES_CLOSED


async def test_a_pin_with_no_words_never_keeps_the_notes_open_or_counts_as_waiting(
    client, renders, tmp_path, monkeypatch
):
    """Finding 5: a hold with no words, then a close, kept the sitting open for good, the
    card said "1 note waiting", and later typed requests joined it."""
    ran: list = []
    monkeypatch.setattr(prod, "start_edit_request", lambda rid, ws_, **_k: ran.append(rid))
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    empty = (await _pin(client, ws, sid, row.render_ref, 2.0))["note_id"]

    lib = (await client.get("/api/v1/production/library", headers=headers(ws))).json()
    assert lib["items"][0]["waiting_notes"] == 0, "a pin with no words is not a note waiting"

    closed = await client.post(f"/api/v1/production/talk/{sid}/close", headers=headers(ws))
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "closed"
    note = (await _rows(renders["sm"], sid))[empty]
    assert note.state == "rejected" and note.result["left_out"] == library.NO_WORDS_ON_CLOSE

    r = await client.post(
        f"/api/v1/production/recordings/{uid}/edit-requests",
        json={"request": "Make the captions bigger"},
        headers=headers(ws),
    )
    assert r.json()["joined_sitting"] is None and [str(x) for x in ran] == [r.json()["id"]]


async def test_a_typed_request_never_joins_an_old_sitting_that_only_holds_an_empty_pin(
    client, renders, tmp_path, monkeypatch
):
    ran: list = []
    monkeypatch.setattr(prod, "start_edit_request", lambda rid, ws_, **_k: ran.append(rid))
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    await _pin(client, ws, sid, row.render_ref, 2.0)
    await age_sitting(renders["sm"], sid, library.SITTING_ACTIVE_S + 5)
    r = await client.post(
        f"/api/v1/production/recordings/{uid}/edit-requests",
        json={"request": "Make the captions bigger"},
        headers=headers(ws),
    )
    assert r.json()["joined_sitting"] is None and len(ran) == 1


# --------------------------------------------- an earlier re-edit waits for his eyes


async def _block_the_edit(sm, ws, uid) -> None:
    """What "Edit it again" leaves when the review's cut fails the meaning check: the
    plan is blocked, nothing rendered, and the stamped older render is what he watches."""
    async with sm() as s:
        up = await prod._load(s, uid, ws)
        plan = dict(up.edit_plan or {})
        plan["meaning_check"] = {"status": "blocked", "issues": [{"detail": BLOCKED_DETAIL}]}
        up.edit_plan = plan
        up.status, up.status_detail = "needs_review", BLOCKED_DETAIL
        await s.commit()


async def test_notes_are_not_made_while_an_earlier_re_edit_waits_for_his_eyes(
    client, renders, tmp_path, monkeypatch
):
    """Finding 10: the batch re-planned with the earlier re-edit's blocked cut still in,
    stopped, threw his notes' changes away and said his notes would make the cut."""
    started: list = []
    monkeypatch.setattr(prod, "start_talk_session", lambda sid_, ws_: started.append(sid_))
    ran: list = []
    monkeypatch.setattr(prod, "start_edit_request", lambda rid, ws_, **_k: ran.append(rid))
    ws, uid, row = await edited(renders, tmp_path)
    await _block_the_edit(renders["sm"], ws, uid)

    opened = await open_talk(client, ws, uid)
    sid = opened["session_id"]
    assert opened["render_ref"] == row.render_ref
    assert opened["blocked"] and "waiting for your eyes" in opened["blocked"], opened.get("blocked")
    assert "Dropped take at 0:03" in opened["blocked"]
    await _note(client, ws, sid, row.render_ref, 2.0, "cut the last line")

    url = f"/api/v1/production/talk/{sid}/submit"
    for method in ("GET", "POST"):
        r = await client.request(method, url, json={"check": "x"} if method == "POST" else None, headers=headers(ws))
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "edit_needs_you" and detail["message"] == opened["blocked"]
        assert "your notes would make" not in detail["message"].lower()
    assert started == []

    # The way to settle it is a typed request: it runs on its own, never waits in the notes.
    typed = await client.post(
        f"/api/v1/production/recordings/{uid}/edit-requests",
        json={"request": "Keep the take at 0:03"},
        headers=headers(ws),
    )
    assert typed.json()["joined_sitting"] is None and len(ran) == 1


async def test_a_batch_that_finds_the_edit_waiting_for_his_eyes_hands_the_notes_back(
    client, renders, tmp_path, monkeypatch
):
    asked: list = []

    async def fake_ask(*a, **k):
        asked.append(a)
        raise AssertionError("no job is spent while the edit waits for his eyes")

    monkeypatch.setattr(prod, "_ask", fake_ask)
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    nid = await _note(client, ws, sid, row.render_ref, 2.0, "cut the last line")
    # A sitting already thinking when the edit was blocked (made before this check existed).
    await _block_the_edit(renders["sm"], ws, uid)
    async with renders["sm"]() as s:
        sitting = await s.get(EditSession, uuid.UUID(sid))
        sitting.state, sitting.result = "thinking", {"notes": [nid], "attempt": 1}
        sitting.submitted_at = library._now()
        await s.commit()

    await prod.run_talk_session(uuid.UUID(sid), ws)
    assert asked == []
    body = (await client.get(f"/api/v1/production/talk/{sid}", headers=headers(ws))).json()
    assert body["state"] == "open" and body["waiting"] == 1
    assert body["result"]["status"] == body["blocked"]
    assert renders["cut"][1:] == [], "nothing rendered"


# --------------------------------------------- the sheet's own address


def test_the_sheet_address_serves_the_workspace(monkeypatch):
    """Finding 3: /library/<id>/talk was a workspace.js route only, so a reload, a
    restored tab or KM BOT's sign-in Back link landed on {"detail":"Not Found"}."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from tce.api import dashboard

    async def enabled() -> bool:
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)
    app = FastAPI()
    app.include_router(dashboard.router)
    with TestClient(app) as http:
        r = http.get(f"/library/{uuid.uuid4()}/talk")
        library_page = http.get("/library")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.text == library_page.text and 'id="notesSheet"' in r.text
