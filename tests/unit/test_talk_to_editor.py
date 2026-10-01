"""Talk to the editor (30-Sep): the render stamp, the sitting, its notes and its gates.

Synthetic data. ffmpeg and the subscription are replaced; the database rows, the
routes and the clock are the real code.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.editorial import library
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import EditingRequest, EditSession
from tce.production import autoedit
from tce.production.retakes import edit_join, edit_length, frame_keep, map_to_edit, map_to_source
from tce.settings import settings

KEY = "synthetic-test-key"


def words(text: str, start: float = 0.0, step: float = 0.5) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start_s": t, "end_s": t + step - 0.1, "precision": "word"})
        t += step
    return out


SPOKEN = "Getting them back is really smart. After you've finished your service. Call them."


async def seed(sm, tmp_path: Path, *, planned: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
    ws = uuid.uuid4()
    src = tmp_path / f"walk-{uuid.uuid4().hex[:6]}.mp4"
    src.write_bytes(b"synthetic")
    async with sm() as s:
        cand = TopicCandidate(
            workspace_id=ws, week_start=datetime(2026, 9, 28), moment_ids=["m"],
            title="Call them after the service", lesson="l", audience="a",
            public_angle="p", gates={}, status="recorded",
        )
        s.add(cand)
        await s.flush()
        up = RecordingUpload(
            workspace_id=ws, candidate_id=cand.id, original_filename="walk.mp4",
            storage_path=str(src), sha256=uuid.uuid4().hex * 2, status="transcribed",
            transcript=words(SPOKEN), duration_s=8.0,
        )
        s.add(up)
        await s.commit()
        if planned:
            await prod._compute_plan(s, ws, up)
            await s.commit()
        return ws, up.id


@pytest.fixture
def renders(monkeypatch, editorial_sessionmaker):
    """The real _run_render with ffmpeg replaced: records each keep it was asked to cut."""
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    cut: list[list[list[float]]] = []
    fail: list[str] = []

    async def fake_render_edit(src, keep, out, **_kw):
        if fail:
            raise RuntimeError(fail[0])
        cut.append([list(r) for r in keep])
        Path(out).write_bytes(b"edited")
        return Path(out)

    async def fake_size(_src):
        return (1080, 1920)

    monkeypatch.setattr(prod.media, "render_edit", fake_render_edit)
    monkeypatch.setattr(prod.media, "probe_video_size", fake_size)
    monkeypatch.setattr(prod.wordbox, "usable", lambda *_a, **_k: False)
    return {"sm": editorial_sessionmaker, "cut": cut, "fail": fail}


async def render_once(sm, ws, uid, mode: str = "cut") -> RecordingUpload:
    async with sm() as s:
        row = await prod._load(s, uid, ws)
        attempt = prod._claim(row, "rendering", "Queued")
        await s.commit()
    await prod._run_leased(uid, ws, "rendering", attempt, lambda: prod._run_render(uid, ws, attempt, mode))
    async with sm() as s:
        return await prod._load(s, uid, ws)


# ---------------------------------------------------------------- render stamp


async def test_a_successful_render_stamps_the_keep_that_made_the_file(renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    row = await render_once(renders["sm"], ws, uid)
    assert row.status == "edited"
    assert row.rendered_keep == frame_keep(renders["cut"][0])
    assert row.rendered_keep and all(abs(s * 30 - round(s * 30)) < 1e-9 for r in row.rendered_keep for s in r)
    assert row.render_ref and len(row.render_ref) == 16
    assert prod.upload_json(row)["render_ref"] == row.render_ref


async def test_every_render_gets_its_own_ref_even_with_the_same_keep(renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    first = (await render_once(renders["sm"], ws, uid)).render_ref
    second = await render_once(renders["sm"], ws, uid)
    assert renders["cut"][0] == renders["cut"][1]
    assert second.render_ref != first


async def test_a_failed_render_keeps_the_stamp_of_the_file_that_exists(renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    good = await render_once(renders["sm"], ws, uid)
    assert good.render_ref and good.rendered_keep
    renders["fail"].append("ffmpeg exploded")
    bad = await render_once(renders["sm"], ws, uid)
    assert bad.status == "failed"
    assert bad.render_ref == good.render_ref
    assert bad.rendered_keep == good.rendered_keep


async def test_a_plan_that_never_renders_does_not_move_the_stamp(renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    good = await render_once(renders["sm"], ws, uid)
    assert good.render_ref and good.rendered_keep
    async with renders["sm"]() as s:
        row = await prod._load(s, uid, ws)
        plan = dict(row.edit_plan)
        plan["overrides"] = {"cut": [[0.0, 1.4]], "restore": []}
        row.edit_plan = plan
        await prod._compute_plan(s, ws, row)
        await s.commit()
        assert row.edit_plan["keep"] != renders["cut"][0]
        assert row.render_ref == good.render_ref and row.rendered_keep == good.rendered_keep


async def test_an_uncut_render_stamps_the_whole_recording(renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    row = await render_once(renders["sm"], ws, uid, mode="uncut")
    assert row.rendered_keep == [[0.0, 8.0]]


def test_the_watch_button_puts_the_render_on_the_address():
    js = (Path(__file__).parents[2] / "src/tce/api/workspace.js").read_text(encoding="utf-8")
    assert '"v=" + encodeURIComponent(item.render_ref)' in js
    assert 'query.push("preview=1")' in js


# ---------------------------------------------------------------- the library


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(workspace_router.production_router, prefix="/api/v1")
    app.include_router(prod.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: (
        editorial_sessionmaker
    )

    async def _db():
        async with editorial_sessionmaker() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def headers(ws) -> dict:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


async def test_the_library_card_carries_the_render_it_would_play(client, renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    row = await render_once(renders["sm"], ws, uid)
    body = (await client.get("/api/v1/production/library", headers=headers(ws))).json()
    item = body["items"][0]
    assert item["upload_id"] == str(uid)
    assert row.render_ref and item["render_ref"] == row.render_ref


# ---------------------------------------------------------------- the sitting


async def edited(renders, tmp_path) -> tuple[uuid.UUID, uuid.UUID, RecordingUpload]:
    ws, uid = await seed(renders["sm"], tmp_path)
    return ws, uid, await render_once(renders["sm"], ws, uid)


async def open_talk(client, ws, uid) -> dict:
    r = await client.post(f"/api/v1/production/recordings/{uid}/talk", headers=headers(ws))
    assert r.status_code == 200, r.text
    return r.json()


async def pin(client, ws, sid, edit_s, render_ref):
    return await client.post(
        f"/api/v1/production/talk/{sid}/notes",
        json={"edit_s": edit_s, "render_ref": render_ref},
        headers=headers(ws),
    )


async def say(client, ws, sid, nid, **body):
    return await client.patch(f"/api/v1/production/talk/{sid}/notes/{nid}", json=body, headers=headers(ws))


async def age_sitting(sm, sid, seconds: float) -> None:
    from datetime import timedelta

    async with sm() as s:
        row = await s.get(EditSession, uuid.UUID(sid))
        row.last_seen = library._now() - timedelta(seconds=seconds)
        await s.commit()


async def test_opening_the_notes_starts_a_sitting_on_the_render_he_watches(client, renders, tmp_path):
    ws, uid, row = await edited(renders, tmp_path)
    body = await open_talk(client, ws, uid)
    assert body["state"] == "open" and body["notes"] == [] and body["waiting"] == 0
    assert body["render_ref"] == row.render_ref
    assert body["file_url"].endswith(f"v={row.render_ref}")
    assert body["edit_length_s"] == pytest.approx(edit_length(row.rendered_keep), abs=1e-3)
    again = await open_talk(client, ws, uid)
    assert again["session_id"] == body["session_id"]


async def test_opening_is_refused_while_the_video_is_being_edited(client, renders, tmp_path):
    ws, uid, _ = await edited(renders, tmp_path)
    url = f"/api/v1/production/recordings/{uid}/talk"
    async with renders["sm"]() as s:
        row = await prod._load(s, uid, ws)
        row.status, row.status_detail = "rendering", "Cutting and burning in your captions"
        await s.commit()
    r = await client.post(url, headers=headers(ws))
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "busy", "message": "Cutting and burning in your captions"}

    async with renders["sm"]() as s:
        row = await prod._load(s, uid, ws)
        row.status, row.status_detail = "edited", "Your editor is reading 14 words"
        row.job_ids = [prod.AUTO_MARK]
        await s.commit()
    r = await client.post(url, headers=headers(ws))
    assert r.status_code == 409 and r.json()["detail"]["message"] == "Your editor is reading 14 words"

    async with renders["sm"]() as s:
        row = await prod._load(s, uid, ws)
        row.job_ids = []
        await s.commit()
    async with prod._render_lock(uid):
        r = await client.post(url, headers=headers(ws))
    assert r.status_code == 409
    assert (await client.post(url, headers=headers(ws))).status_code == 200


async def test_a_render_whose_process_died_does_not_hold_the_notes_shut(client, renders, tmp_path):
    ws, uid, _ = await edited(renders, tmp_path)
    async with renders["sm"]() as s:
        row = await prod._load(s, uid, ws)
        row.status, row.status_detail = "rendering", "Cutting and burning in your captions"
        # This process started it and no longer runs it: the lease is provably dead.
        row.job_ids = [prod._lease_entry("rendering", "deadbeef0000", prod._utcnow())]
        await s.commit()
    body = await open_talk(client, ws, uid)
    assert body["state"] == "open"
    async with renders["sm"]() as s:
        assert (await prod._load(s, uid, ws)).status == "interrupted"


async def test_there_is_no_sitting_without_an_edit(client, renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    r = await client.post(f"/api/v1/production/recordings/{uid}/talk", headers=headers(ws))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_edit"


async def test_an_edit_made_before_the_stamp_opens_on_its_plan(client, renders, tmp_path):
    ws, uid, row = await edited(renders, tmp_path)
    async with renders["sm"]() as s:
        up = await prod._load(s, uid, ws)
        up.render_ref, up.rendered_keep = None, None
        await s.commit()
    body = await open_talk(client, ws, uid)
    assert body["render_ref"] is None
    assert body["edit_length_s"] == pytest.approx(edit_length(frame_keep(row.edit_plan["keep"])), abs=1e-3)
    assert (await pin(client, ws, body["session_id"], 1.0, None)).status_code == 200


async def test_a_pin_is_the_paused_second_on_both_clocks(client, renders, tmp_path):
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    r = await pin(client, ws, sid, 2.0, row.render_ref)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["edit_s"] == 2.0 and body["clock"] == "0:02"
    assert body["source_s"] == pytest.approx(map_to_source(2.0, row.rendered_keep), abs=1e-3)
    note = body["note"]
    assert note["scope"] == "moment" and note["where"] == "at 0:02"
    assert note["state"] == "listening" and note["end_s"] is None and note["created_by"] == "ziv"
    sitting = (await client.get(f"/api/v1/production/talk/{sid}", headers=headers(ws))).json()
    assert [n["id"] for n in sitting["notes"]] == [body["note_id"]]
    assert sitting["waiting"] == 1


async def test_a_pin_on_another_render_is_refused_and_reopening_moves_the_sitting(client, renders, tmp_path):
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    r = await pin(client, ws, sid, 1.0, "0123456789abcdef")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale_render"
    first = (await pin(client, ws, sid, 2.0, row.render_ref)).json()

    # Re-rendered under the player anyway (the gates are for the routes, not this test):
    # the next pin is refused with the new render, and reopening moves the sitting to it.
    newer = await render_once(renders["sm"], ws, uid)
    r = await pin(client, ws, sid, 3.0, row.render_ref)
    assert r.status_code == 409 and r.json()["detail"]["render_ref"] == newer.render_ref
    moved = await open_talk(client, ws, uid)
    assert moved["session_id"] == sid and moved["render_ref"] == newer.render_ref
    note = moved["notes"][0]
    assert note["source_s"] == first["source_s"]
    assert note["start_s"] == pytest.approx(map_to_edit(first["source_s"], newer.rendered_keep), abs=0.01)
    assert (await pin(client, ws, sid, 3.0, newer.render_ref)).status_code == 200


async def test_a_pin_outside_the_edit_is_refused(client, renders, tmp_path):
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    total = edit_length(row.rendered_keep)
    assert (await pin(client, ws, sid, total + 5, row.render_ref)).status_code == 400
    assert (await pin(client, ws, sid, -1, row.render_ref)).status_code == 400
    ok = await pin(client, ws, sid, total + 0.2, row.render_ref)  # a hair past the last frame
    assert ok.status_code == 200 and ok.json()["edit_s"] == pytest.approx(total, abs=0.01)


async def test_his_words_and_the_editors_reading_hold_the_note_and_drop_takes_it_back(client, renders, tmp_path):
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    nid = (await pin(client, ws, sid, 2.0, row.render_ref)).json()["note_id"]
    heard = await say(client, ws, sid, nid, heard="  cut the second basically  ")
    assert heard.json()["state"] == "held" and heard.json()["request"] == "cut the second basically"
    read = await say(client, ws, sid, nid, understood="At 0:02 you want the second 'basically' gone.")
    assert read.json()["understood"].startswith("At 0:02") and read.json()["request"] == "cut the second basically"
    assert (await say(client, ws, sid, nid)).status_code == 400
    assert (await say(client, ws, sid, nid, heard="   ")).status_code == 400
    dropped = await say(client, ws, sid, nid, drop=True)
    assert dropped.json()["state"] == "rejected"
    assert (await say(client, ws, sid, nid, heard="again")).status_code == 409
    sitting = (await client.get(f"/api/v1/production/talk/{sid}", headers=headers(ws))).json()
    assert sitting["waiting"] == 0


async def test_the_editors_reading_can_land_before_his_words(client, renders, tmp_path):
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    nid = (await pin(client, ws, sid, 2.0, row.render_ref)).json()["note_id"]
    r = await say(client, ws, sid, nid, understood="At 0:02 you want a longer pause.")
    assert r.json()["state"] == "held" and r.json()["request"] == ""


async def test_the_moment_waits_for_his_words_and_shows_the_words_around_it(client, renders, tmp_path):
    import asyncio

    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    earlier = (await pin(client, ws, sid, 1.0, row.render_ref)).json()["note_id"]
    await say(client, ws, sid, earlier, heard="louder here", understood="At 0:01 you want it louder.")
    nid = (await pin(client, ws, sid, 3.0, row.render_ref)).json()["note_id"]

    async def words_arrive():
        await asyncio.sleep(0.6)
        await say(client, ws, sid, nid, heard="the word after smart sounds clipped")

    moment, _ = await asyncio.gather(
        client.get(f"/api/v1/production/talk/{sid}/moment?window=2&rules=1", headers=headers(ws)),
        words_arrive(),
    )
    assert moment.status_code == 200, moment.text
    m = moment.json()
    assert m["note"]["id"] == nid and m["waited_for_words"] is True
    assert m["heard"] == "the word after smart sounds clipped"
    assert m["at"]["clock"] == "0:03"
    assert m["at"]["source_s"] == pytest.approx(map_to_source(3.0, row.rendered_keep), abs=1e-3)
    assert "in the edit]" in m["transcript"]
    indexes = [w["index"] for w in m["words"]]
    assert indexes == list(range(indexes[0], indexes[-1] + 1)) and 0 < len(indexes) < len(SPOKEN.split())
    assert all(abs(w["edit_s"] - 3.0) <= 2.6 for w in m["words"] if w["edit_s"] is not None)
    assert m["earlier"] == [
        {"id": earlier, "where": "at 0:01", "said": "louder here", "understood": "At 0:01 you want it louder.",
         "state": "held", "reply": None, "question": None, "sitting": sid}
    ]
    assert m["waiting"] == [{"id": nid, "where": "at 0:03", "heard": "the word after smart sounds clipped"}]
    assert m["rules"] == autoedit.editor_skill() and m["rules"]


async def test_the_moment_does_not_wait_for_ever(client, renders, tmp_path, monkeypatch):
    monkeypatch.setattr(library, "MOMENT_WAIT_S", 0.3)
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    await pin(client, ws, sid, 2.0, row.render_ref)
    m = (await client.get(f"/api/v1/production/talk/{sid}/moment", headers=headers(ws))).json()
    assert m["waited_for_words"] is True and m["heard"] is None and m["note"]["state"] == "listening"
    assert "rules" not in m


async def test_the_moment_at_a_second_needs_no_note(client, renders, tmp_path):
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    empty = await client.get(f"/api/v1/production/talk/{sid}/moment", headers=headers(ws))
    assert empty.status_code == 404
    m = (await client.get(f"/api/v1/production/talk/{sid}/moment?at=4", headers=headers(ws))).json()
    assert m["note"] is None and m["at"]["clock"] == "0:04" and m["words"]


async def test_the_read_back_carries_a_check_and_only_a_matching_yes_submits(client, renders, tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(prod, "start_talk_session", lambda sid, ws: started.append(sid))
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    a = (await pin(client, ws, sid, 1.0, row.render_ref)).json()["note_id"]
    b = (await pin(client, ws, sid, 3.0, row.render_ref)).json()["note_id"]
    await pin(client, ws, sid, 4.0, row.render_ref)  # never got words: left out
    await say(client, ws, sid, a, heard="louder here")
    await say(client, ws, sid, b, heard="cut basically", understood="At 0:03 you want 'basically' gone.")

    url = f"/api/v1/production/talk/{sid}/submit"
    preview = (await client.get(url, headers=headers(ws))).json()
    assert preview["read_back"] == (
        '2 notes: at 0:01: you said "louder here"; at 0:03: At 0:03 you want \'basically\' gone. '
        "One re-render. 1 note with no words yet is left out."
    )
    assert len(preview["check"]) == 12 and preview["count"] == 2

    wrong = await client.post(url, json={"check": "000000000000"}, headers=headers(ws))
    assert wrong.status_code == 409 and wrong.json()["detail"]["check"] == preview["check"]
    assert (await client.post(url, json={}, headers=headers(ws))).status_code == 409

    # He re-said a note after hearing the read-back: the old yes no longer fits.
    await say(client, ws, sid, a, heard="much louder here")
    stale = await client.post(url, json={"check": preview["check"]}, headers=headers(ws))
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "changed"
    fresh = (await client.get(url, headers=headers(ws))).json()
    assert fresh["check"] != preview["check"]

    done = await client.post(url, json={"check": fresh["check"]}, headers=headers(ws))
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["state"] == "thinking" and body["summary"] == fresh["read_back"]
    assert body["result"]["notes"] == [a, b]
    assert started == [uuid.UUID(sid)]
    # The notes he heard are frozen now.
    assert (await say(client, ws, sid, a, heard="more")).status_code == 409
    assert (await pin(client, ws, sid, 2.0, row.render_ref)).status_code == 409
    # Reopening the sheet shows the sitting that is thinking, never a new one.
    assert (await open_talk(client, ws, uid))["session_id"] == sid


async def test_a_sitting_with_no_notes_has_nothing_to_make(client, renders, tmp_path):
    ws, uid, _ = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    r = await client.get(f"/api/v1/production/talk/{sid}/submit", headers=headers(ws))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_notes"


async def test_nothing_else_renders_while_he_gives_notes(client, renders, tmp_path, monkeypatch):
    started = []

    async def fake_auto_edit(upload_id, ws):
        started.append(upload_id)

    monkeypatch.setattr(prod, "auto_edit", fake_auto_edit)
    ws, uid, _ = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    again = await client.post(f"/api/v1/production/uploads/{uid}/auto-edit", headers=headers(ws))
    assert again.status_code == 409 and again.json()["detail"] == prod.SITTING_REFUSAL
    render = await client.post(f"/api/v1/production/uploads/{uid}/render", headers=headers(ws))
    assert render.status_code == 409 and render.json()["detail"] == prod.SITTING_REFUSAL
    assert started == []

    # The sheet went away two minutes ago: the video is his to re-edit again.
    await age_sitting(renders["sm"], sid, library.SITTING_ACTIVE_S + 5)
    again = await client.post(f"/api/v1/production/uploads/{uid}/auto-edit", headers=headers(ws))
    assert again.status_code == 202
    await asyncio_idle()
    assert started == [uid]


async def asyncio_idle():
    import asyncio

    for _ in range(3):
        await asyncio.sleep(0)


async def test_a_late_review_waits_until_he_has_finished_giving_notes(client, renders, tmp_path, monkeypatch):
    ws, uid, _ = await edited(renders, tmp_path)
    sm = renders["sm"]
    async with sm() as s:
        row = await prod._load(s, uid, ws)
        words = list(row.transcript)
        context = await prod._script_context(s, ws, row)
        prompt, system = prod._review_request(words, context)
        plan = dict(row.edit_plan)
        plan["review"] = {"state": "waiting", "key": prod._review_key(uid, prompt, system),
                          "since": prod._utcnow().isoformat()}
        row.edit_plan = plan
        await s.commit()
    sid = (await open_talk(client, ws, uid))["session_id"]

    asked, rendered_while = [], []

    async def fake_ask(kind, prompt, system, schema, ws_, key, **_opts):
        from tce.llm.provider import LLMResult

        asked.append(key)
        if len(asked) == 2:  # he closes the sheet: the sitting ends
            async with sm() as s:
                (await s.get(EditSession, uuid.UUID(sid))).state = "closed"
                await s.commit()
        return LLMResult(job_id=uuid.uuid4(), text="", structured={"removals": [], "corrections": []},
                         model="claude-opus-5-5")

    async def fake_plan_and_render(upload_id, ws_, *, restore_if_blocked=None):
        async with sm() as s:
            rendered_while.append(await library.active_sitting(s, ws_, upload_id))

    monkeypatch.setattr(prod, "_ask", fake_ask)
    monkeypatch.setattr(prod, "_plan_and_render_locked", fake_plan_and_render)
    monkeypatch.setattr(prod, "SITTING_RECHECK_S", 0.0)
    await prod._await_review(uid, ws)
    assert len(asked) >= 2
    assert rendered_while == [None]  # one render, and only once no sitting was in front of him


async def test_a_typed_request_joins_the_sitting_he_is_in(client, renders, tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(prod, "start_edit_request", lambda rid, ws, **_k: ran.append(rid))
    ws, uid, _ = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    r = await client.post(
        f"/api/v1/production/recordings/{uid}/edit-requests",
        json={"request": "Make the captions bigger", "scope": "whole"},
        headers=headers(ws),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["joined_sitting"] == sid and body["state"] == "held" and body["session_id"] == sid
    assert ran == []
    preview = (await client.get(f"/api/v1/production/talk/{sid}/submit", headers=headers(ws))).json()
    assert preview["read_back"].startswith('1 note: the whole video: you said "Make the captions bigger"')

    lib = (await client.get("/api/v1/production/library", headers=headers(ws))).json()
    item = lib["items"][0]
    assert item["waiting_notes"] == 1 and item["last_request"] is None and item["open_requests"] == 0


async def test_a_typed_request_does_not_wait_on_an_old_empty_sitting(client, renders, tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(prod, "start_edit_request", lambda rid, ws, **_k: ran.append(rid))
    ws, uid, _ = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    await age_sitting(renders["sm"], sid, library.SITTING_ACTIVE_S + 5)
    r = await client.post(
        f"/api/v1/production/recordings/{uid}/edit-requests",
        json={"request": "Make the captions bigger"},
        headers=headers(ws),
    )
    assert r.json()["joined_sitting"] is None and r.json()["state"] == "open"
    assert [str(x) for x in ran] == [r.json()["id"]]


async def test_a_closed_sheet_with_notes_waiting_still_collects_a_typed_request(client, renders, tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(prod, "start_edit_request", lambda rid, ws, **_k: ran.append(rid))
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    nid = (await pin(client, ws, sid, 2.0, row.render_ref)).json()["note_id"]
    await say(client, ws, sid, nid, heard="cut that")
    await age_sitting(renders["sm"], sid, library.SITTING_ACTIVE_S + 5)
    r = await client.post(
        f"/api/v1/production/recordings/{uid}/edit-requests",
        json={"request": "and the captions bigger"},
        headers=headers(ws),
    )
    assert r.json()["joined_sitting"] == sid and ran == []


async def test_another_workspace_never_reaches_a_sitting(client, renders, tmp_path):
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    other = uuid.uuid4()
    assert (await client.get(f"/api/v1/production/talk/{sid}", headers=headers(other))).status_code == 404
    assert (await pin(client, other, sid, 1.0, row.render_ref)).status_code == 404
    r = await client.post(f"/api/v1/production/recordings/{uid}/talk", headers=headers(other))
    assert r.status_code == 404


def test_a_window_of_the_transcript_keeps_the_real_word_numbers():
    ws_ = words("one two three. four five six. seven eight")
    keep = [[0.0, 1.4], [2.0, 4.0]]
    text = autoedit.numbered_transcript(ws_, keep, span=(2, 5))
    assert text.startswith("[0:01 in the edit] 2:three.")
    assert "~~3:four~~" in text and "5:six." in text
    assert "1:two" not in text and "6:seven" not in text


def test_the_note_row_says_where_a_moment_is():
    row = EditingRequest(upload_id=uuid.uuid4(), scope="moment", start_s=38.4, request="cou", state="held")
    assert library.edit_request_to_json(row)["where"] == "at 0:38"


# ---------------------------------------------------------------- review findings, 1-Oct


async def test_the_moment_takes_the_note_he_gave_first_and_lists_every_waiting_one(
    client, renders, tmp_path, monkeypatch
):
    # He pauses at 0:01 and says "drop the not", plays on and pauses again at 0:03
    # before the editor has read the first: the first delegation is about the first note.
    monkeypatch.setattr(library, "MOMENT_WAIT_S", 0.1)
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    silent = (await pin(client, ws, sid, 0.5, row.render_ref)).json()["note_id"]  # he never spoke
    first = (await pin(client, ws, sid, 1.0, row.render_ref)).json()["note_id"]
    await say(client, ws, sid, first, heard="drop the not")
    second = (await pin(client, ws, sid, 3.0, row.render_ref)).json()["note_id"]
    await say(client, ws, sid, second, heard="cut the end")
    url = f"/api/v1/production/talk/{sid}/moment"

    m = (await client.get(url, headers=headers(ws))).json()
    assert m["note"]["id"] == first and m["heard"] == "drop the not" and m["waited_for_words"] is False
    assert [(w["id"], w["heard"]) for w in m["waiting"]] == [
        (silent, None), (first, "drop the not"), (second, "cut the end")
    ]
    await say(client, ws, sid, first, understood="At 0:01 you want the 'not' gone.")
    m = (await client.get(url, headers=headers(ws))).json()
    assert m["note"]["id"] == second
    assert [e["id"] for e in m["earlier"]] == [silent, first]
    await say(client, ws, sid, second, understood="At 0:03 you want the end cut.")
    m = (await client.get(url, headers=headers(ws))).json()
    assert m["note"]["id"] == silent and m["waited_for_words"] is True


async def test_a_note_whose_second_the_new_version_cut_keeps_its_own_word(client, renders, tmp_path):
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    pinned = (await pin(client, ws, sid, 3.2, row.render_ref)).json()
    await say(client, ws, sid, pinned["note_id"], heard="this word sounds off")
    src = pinned["source_s"]
    # He closed the sheet; later something else re-planned with a cut over that second.
    await age_sitting(renders["sm"], sid, library.SITTING_ACTIVE_S + 5)
    async with renders["sm"]() as s:
        up = await prod._load(s, uid, ws)
        up.edit_plan = {**up.edit_plan, "overrides": {"cut": [[src - 0.4, src + 0.6]], "restore": []}}
        await prod._compute_plan(s, ws, up)
        await s.commit()
    newer = await render_once(renders["sm"], ws, uid)
    assert map_to_edit(src, newer.rendered_keep) is None  # the new version cut that second

    moved = await open_talk(client, ws, uid)
    note = moved["notes"][0]
    join = edit_join(src, newer.rendered_keep)
    assert note["source_s"] == src
    assert note["start_s"] == pytest.approx(join, abs=0.01)
    assert note["result"] == {"moved": library.NOTE_CUT_IN_NEW_VERSION}
    m = (await client.get(f"/api/v1/production/talk/{sid}/moment?note={note['id']}", headers=headers(ws))).json()
    assert m["at"]["source_s"] == pytest.approx(src, abs=1e-3)
    assert m["at"]["in_edit"] is False
    assert m["at"]["edit_s"] == pytest.approx(join, abs=0.01)
    word = next(w for w in m["words"] if w["source_s"] <= src <= w["source_s"] + 0.45)
    assert word["cut"] is True and word["text"] == "After"


def test_a_second_the_edit_left_out_sits_at_the_join_of_its_cut():
    keep = [[0.0, 2.0], [3.0, 5.0], [6.0, 7.0]]
    assert edit_join(2.5, keep) == pytest.approx(2.0)
    assert edit_join(5.5, keep) == pytest.approx(4.0)
    assert edit_join(9.0, keep) == pytest.approx(5.0)
    assert edit_join(-1.0, [[1.0, 2.0]]) == 0.0
    assert edit_join(3.5, keep) == pytest.approx(map_to_edit(3.5, keep))  # in the edit: its own second


async def test_two_opens_at_once_leave_one_live_sitting(client, renders, tmp_path, monkeypatch):
    ws, uid, _ = await edited(renders, tmp_path)
    first = await open_talk(client, ws, uid)
    real = library._sittings
    calls = {"n": 0}

    async def not_committed_yet(db, ws_, upload_id, states):
        # Two opens in flight at once: this one cannot see the other's row yet.
        calls["n"] += 1
        return [] if calls["n"] == 1 else await real(db, ws_, upload_id, states)

    # Called on open_sitting itself: the route also asks active_sitting first, which
    # would take the one blank answer and leave open_sitting seeing the row.
    monkeypatch.setattr(library, "_sittings", not_committed_yet)
    async with renders["sm"]() as s:
        second = await library.open_sitting(s, ws, uid)
        await s.commit()
        second_id = str(second.id)
    assert second_id == first["session_id"]
    assert calls["n"] >= 2  # it looked again after the database refused a second one
    from sqlalchemy import select

    async with renders["sm"]() as s:
        live = (
            await s.execute(
                select(EditSession).where(
                    EditSession.upload_id == uid, EditSession.state.in_(library.SITTING_LIVE_STATES)
                )
            )
        ).scalars().all()
    assert len(live) == 1


async def test_the_database_holds_one_live_sitting_per_video(renders, tmp_path):
    from sqlalchemy.exc import IntegrityError

    ws, uid, _ = await edited(renders, tmp_path)
    async with renders["sm"]() as s:
        s.add(EditSession(workspace_id=ws, upload_id=uid, state="done"))
        s.add(EditSession(workspace_id=ws, upload_id=uid, state="done"))  # finished ones: any number
        s.add(EditSession(workspace_id=ws, upload_id=uid, state="open"))
        await s.commit()
        s.add(EditSession(workspace_id=ws, upload_id=uid, state="thinking"))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_make_it_is_refused_while_something_else_edits_the_video_or_it_changed(
    client, renders, tmp_path, monkeypatch
):
    started = []
    monkeypatch.setattr(prod, "start_talk_session", lambda sid_, ws_: started.append(sid_))
    ws, uid, row = await edited(renders, tmp_path)
    sid = (await open_talk(client, ws, uid))["session_id"]
    nid = (await pin(client, ws, sid, 2.0, row.render_ref)).json()["note_id"]
    await say(client, ws, sid, nid, heard="cut that")
    url = f"/api/v1/production/talk/{sid}/submit"
    check = (await client.get(url, headers=headers(ws))).json()["check"]

    # He closed the sheet and tapped Edit it again; a still-loaded sheet taps Make.
    doing = "Editing it again: your editor's review, then the cut and the captions"
    async with renders["sm"]() as s:
        up = await prod._load(s, uid, ws)
        up.job_ids, up.status_detail = [prod.AUTO_MARK], doing
        await s.commit()
    r = await client.get(url, headers=headers(ws))
    assert r.status_code == 409 and r.json()["detail"] == {"code": "busy", "message": doing}
    r = await client.post(url, json={"check": check}, headers=headers(ws))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "busy"

    # The auto edit made a new version: the notes were pinned on the old one.
    async with renders["sm"]() as s:
        up = await prod._load(s, uid, ws)
        up.job_ids = []
        await s.commit()
    newer = await render_once(renders["sm"], ws, uid)
    r = await client.post(url, json={"check": check}, headers=headers(ws))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale_render"
    assert r.json()["detail"]["render_ref"] == newer.render_ref
    body = (await client.get(f"/api/v1/production/talk/{sid}", headers=headers(ws))).json()
    assert body["state"] == "open" and body["waiting"] == 1

    # Reopening moves the notes to the new version, and then it can be made.
    assert (await open_talk(client, ws, uid))["render_ref"] == newer.render_ref
    check = (await client.get(url, headers=headers(ws))).json()["check"]
    assert (await client.post(url, json={"check": check}, headers=headers(ws))).status_code == 200
    assert started == [uuid.UUID(sid)]
