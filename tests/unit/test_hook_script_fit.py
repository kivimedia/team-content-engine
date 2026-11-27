"""The script opens on the hook (T-25711): picking a hook for a video writes one
opening for it and rewrites the whole script to follow, or says plainly why not.
The writer is stubbed; synthetic values."""

from __future__ import annotations

import asyncio
import types
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tce.editorial.packets import PacketOutcome, build_more_hooks_prompt
from tce.hooks import catalog, library, script_fit
from tce.settings import settings

WS = uuid.UUID("00000000-0000-4000-8000-0000000257a2")
WEEK = "2026-11-23"
CID = "11111111-2222-4333-8444-555555555555"
LINEUP = {"primary": [{"candidate_id": CID, "title": "Some clients rebook at 80%", "filmed": False}], "reserve": []}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path))
    return tmp_path


def run(coro):
    return asyncio.run(coro)


def test_every_hook_says_what_the_first_line_must_give_it():
    for hook in catalog.HOOKS:
        assert hook.script_need and len(hook.script_need) <= 120, hook.id
    assert "never invented" in catalog.BY_ID["big-number"].script_need


def test_the_openings_prompt_carries_the_visual_hook():
    packet = types.SimpleNamespace(hook_options=[{"id": "h1", "text": "Old opening.", "question": "Q"}], script_phrases=["Old opening.", "Payoff."])
    cand = types.SimpleNamespace(title="Rebook at 80%", lesson="L", citations_private=[])
    plain = build_more_hooks_prompt(packet, cand, 1)
    assert "VISUAL HOOK" not in plain
    fitted = build_more_hooks_prompt(packet, cand, 1, catalog.BY_ID["big-number"])
    assert "THE VISUAL HOOK THIS VIDEO OPENS WITH" in fitted
    assert catalog.BY_ID["big-number"].script_need in fitted and 'Start each rationale with "Fits Big number: "' in fitted
    assert fitted.index("WRITE 1 NEW OPENING") < fitted.index("VISUAL HOOK") < fitted.index("THE IDEA")


def _stub(monkeypatch, more_status="ok", choose_status="ok"):
    calls = {}
    packet = types.SimpleNamespace(id=uuid.uuid4(), hook_options=[{"id": "h1", "text": "Old opening."}])

    async def current(_sm, _ws, _cid):
        return packet

    async def more(_sm, ws, packet_id, *, wanted, visual_hook):
        calls["more"] = (packet_id, wanted, visual_hook.id)
        if more_status != "ok":
            return PacketOutcome(status=more_status, detail="the writer is busy")
        return PacketOutcome(status="ok", packet={"id": "p2", "hook_options": [
            {"id": "h1", "text": "Old opening."}, {"id": "h2", "text": "Eighty percent of my clients rebook."}]})

    async def choose(_sm, ws, packet_id, hook_id):
        calls["choose"] = (packet_id, hook_id)
        return PacketOutcome(status=choose_status, detail="a take set is in progress")

    monkeypatch.setattr(script_fit, "_current_packet", current)
    monkeypatch.setattr(script_fit, "more_hook_options", more)
    monkeypatch.setattr(script_fit, "choose_hook_with_script", choose)
    return calls, packet


def test_fit_writes_the_opening_and_rewrites_the_script(monkeypatch, store):
    calls, packet = _stub(monkeypatch)
    run(library.pick(WS, WEEK, "big-number", LINEUP))
    got = run(script_fit.fit_script(None, WS, WEEK, CID, "big-number"))
    assert got["state"] == "fitted" and "Eighty percent of my clients rebook." in got["detail"]
    assert calls["more"] == (packet.id, 1, "big-number") and calls["choose"] == ("p2", "h2")
    saved = library.for_video(WS, WEEK, CID)[0]["script"]
    assert saved["state"] == "fitted" and saved["opening"] == "Eighty percent of my clients rebook."
    page = run(library.library(WS, WEEK, LINEUP, lambda i: i))
    assert next(h for h in page["hooks"] if h["id"] == "big-number")["pick"]["script"]["state"] == "fitted"


def test_a_take_in_progress_keeps_the_opening_and_says_so(monkeypatch, store):
    _stub(monkeypatch, choose_status="invalid")
    run(library.pick(WS, WEEK, "big-number", LINEUP))
    got = run(script_fit.fit_script(None, WS, WEEK, CID, "big-number"))
    assert got["state"] == "kept"
    assert "ready to choose on the recording screen" in got["detail"] and "A take set is in progress" in got["detail"]


def test_writer_refusal_and_no_script(monkeypatch, store):
    _stub(monkeypatch, more_status="waiting_capacity")
    run(library.pick(WS, WEEK, "big-number", LINEUP))
    got = run(script_fit.fit_script(None, WS, WEEK, CID, "big-number"))
    assert got == {"state": "kept", "detail": "The script kept its opening: The writer is busy."}

    async def none(_sm, _ws, _cid):
        return None

    monkeypatch.setattr(script_fit, "_current_packet", none)
    got = run(script_fit.fit_script(None, WS, WEEK, CID, "big-number"))
    assert got["state"] == "none"


def test_a_moved_pick_is_not_overwritten_by_a_stale_run(store):
    run(library.pick(WS, WEEK, "big-number", LINEUP))
    assert run(library.set_script(WS, WEEK, "big-number", "someone-else", "fitted", "x")) is False
    assert library.for_video(WS, WEEK, CID)[0]["script"] is None


def test_picking_starts_the_fit(monkeypatch, store):
    from tce.api.private_access import require_private_workspace
    from tce.api.routers import hooks as hooks_router
    from tce.api.routers.editorial import get_editorial_sessionmaker

    started = []

    async def fake_lineup(_sm, _ws):
        return LINEUP

    async def fake_fit(sm, ws, week, cid, hook_id):
        started.append((week, cid, hook_id))

    monkeypatch.setattr(hooks_router, "_lineup", fake_lineup)
    monkeypatch.setattr(hooks_router, "_week_key", lambda: WEEK)
    monkeypatch.setattr(hooks_router, "scoped_editor_workspace", lambda key: None)
    monkeypatch.setattr(hooks_router.script_fit, "fit_script", fake_fit)
    app = FastAPI()
    app.include_router(hooks_router.router, prefix="/api/v1")
    app.dependency_overrides[require_private_workspace] = lambda: WS
    app.dependency_overrides[get_editorial_sessionmaker] = lambda: None
    got = TestClient(app).post("/api/v1/hooks/big-number/pick", json={})
    assert got.status_code == 200
    pick = next(h for h in got.json()["hooks"] if h["id"] == "big-number")["pick"]
    assert pick["script"]["state"] == "writing"
    assert started == [(WEEK, CID, "big-number")]


def test_library_page_paints_the_script_line():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "src/tce/api/workspace.js").read_text(encoding="utf-8")
    assert 'class="hook-script"' in js and "<strong>Script: </strong>" in js
