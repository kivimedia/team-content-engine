"""His word on the Book wakes the book editor (23-Nov-2026, wait-less item B10, part 2).

A write ask, a layout note or a layout approval used to sit in the editor's record until
its next turn. Once the record holds it, the Book now sends the editor one fleet message so
the turn starts at once. The tap never waits for that message and never fails on it, a burst
of taps sends one, and a refused tap sends none. The layout-first hold (423) and the
narration budget (409 device_voice) refuse exactly as before. Same app, record and fixtures
as test_book.py; synthetic text only. No test runs the fleet command of this box: the wake
is recorded in its place, or a script in the test's own folder stands in for it.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys

import httpx
import pytest

from tce.api.routers import book as book_routes
from tce.settings import settings
from tests.unit.test_book import (  # noqa: F401 - the fixtures are used by name
    CLIENT,
    OWNER,
    api,
    held,
)
from tests.unit.test_book_fast_clicks import HELD_WORDS


def _pending() -> list[asyncio.Task]:
    return list(getattr(book_routes, "_wakes", ()))


async def _all_sent() -> None:
    left = _pending()
    if left:
        await asyncio.wait_for(asyncio.gather(*left), 30)


def _entry(held, n: int) -> dict:
    return next(e for e in json.loads((held / "chapters.json").read_text())["chapters"] if e["number"] == n)


@pytest.fixture(autouse=True)
def fresh_wakes():
    getattr(book_routes, "_woken", {}).clear()
    yield
    getattr(book_routes, "_woken", {}).clear()


@pytest.fixture
async def tap(api):
    """The same app in this test's own loop, so a wake sent off by a tap can be watched."""
    transport = httpx.ASGITransport(app=api.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://book.test", headers=OWNER) as c:
        yield c
    await _all_sent()


@pytest.fixture
async def wakes(monkeypatch, held, tmp_path):
    """Each wake as it is sent off, recorded in place of the fleet command. It waits for
    `go`, so a test sees the tap answer while its wake is still on the way."""
    monkeypatch.setattr(settings, "book_editor_wake", str(tmp_path / "never-run" / "kmbot-send.sh"))
    sent: list[dict] = []
    go = asyncio.Event()

    async def recorded(command: str, text: str) -> None:
        await go.wait()
        sent.append({"command": command, "text": text, "chapter_12": _entry(held, 12)})

    monkeypatch.setattr(book_routes, "_send_wake", recorded, raising=False)
    box = {"sent": sent, "go": go}
    yield box
    go.set()
    await _all_sent()


async def test_a_write_ask_answers_first_then_wakes_the_editor_once_the_record_holds_it(api, held, tap, wakes):
    approve = await tap.post("/api/v1/book/chapters/12/layout", json={"action": "approve", "by": "dev-test"})
    assert approve.status_code == 200, approve.text
    write = await tap.post("/api/v1/book/chapters/12/write", json={"by": "dev-test"})
    assert write.status_code == 200, write.text
    asked_at = write.json()["write_requested_at"]
    # Both taps answered while their wakes were still on the way.
    assert wakes["sent"] == [] and len(_pending()) == 2
    wakes["go"].set()
    await _all_sent()
    approved, asked = wakes["sent"]
    assert "the layout of chapter 12 was approved" in approved["text"] and "by dev-test" in approved["text"]
    assert approved["chapter_12"]["layout_status"] == "approved"
    assert f"chapter 12 has a new ask to write it from its approved layout ({asked_at}, by dev-test)" in asked["text"]
    assert asked["chapter_12"]["write_requested_at"] == asked_at, "the wake comes after the record holds the ask"
    assert all(w["text"].startswith("From the Book in TCE: ") for w in wakes["sent"])


async def test_a_burst_of_taps_wakes_it_once_and_a_later_tap_wakes_it_again(api, held, tap, wakes):
    for _ in range(3):
        r = await tap.post("/api/v1/book/chapters/12/layout", json={"action": "note", "note": "Coaching first"})
        assert r.status_code == 200, r.text
    assert len(_pending()) == 1
    # Another word on the same chapter is its own wake.
    assert (await tap.post("/api/v1/book/chapters/12/layout", json={"action": "approve"})).status_code == 200
    for _ in range(2):  # the second ask is "already" asked: still one wake
        assert (await tap.post("/api/v1/book/chapters/12/write", json={})).status_code == 200
    assert len(_pending()) == 3
    wakes["go"].set()
    await _all_sent()
    assert len(wakes["sent"]) == 3
    # The note itself stays in the record; the wake only points at it.
    assert not any("Coaching first" in w["text"] for w in wakes["sent"])
    # Past the gap the same word wakes it again.
    book_routes._woken[(12, "note")] -= float(settings.book_editor_wake_gap_s) + 1
    assert (await tap.post("/api/v1/book/chapters/12/layout", json={"action": "note", "note": "One more"})).status_code == 200
    await _all_sent()
    assert len(wakes["sent"]) == 4 and "new note on its layout" in wakes["sent"][-1]["text"]


async def test_a_refused_tap_wakes_nobody_and_the_holds_are_as_strict(api, held, tap, wakes, monkeypatch):
    # Refused: a write before his yes, an empty note, part one, a client login. A reopen is no ask.
    r = await tap.post("/api/v1/book/chapters/12/write", json={})
    assert r.status_code == 422 and "chapter" not in r.json()
    assert (await tap.post("/api/v1/book/chapters/12/layout", json={"action": "note", "note": "  "})).status_code == 422
    assert (await tap.post("/api/v1/book/chapters/1/layout", json={"action": "approve"})).status_code == 422
    assert (await tap.post("/api/v1/book/chapters/12/layout", headers=CLIENT, json={"action": "approve"})).status_code == 403
    assert (await tap.post("/api/v1/book/chapters/12/write", headers=CLIENT, json={})).status_code == 403
    assert (await tap.post("/api/v1/book/chapters/99/layout", json={"action": "approve"})).status_code == 404
    assert (await tap.post("/api/v1/book/chapters/12/layout", json={"action": "reopen"})).status_code == 200
    assert _pending() == [] and getattr(book_routes, "_woken", {}) == {}
    # His yes wakes the editor, and the holds refuse exactly as before.
    assert (await tap.post("/api/v1/book/chapters/12/layout", json={"action": "approve"})).status_code == 200
    held_audio = await tap.get("/api/v1/book/chapters/12/audio/0")
    assert held_audio.status_code == 423 and held_audio.json()["detail"] == HELD_WORDS
    called = []

    class Boom:
        def __init__(self, *a, **k):
            called.append(1)

    monkeypatch.setattr("tce.services.tts.TTSService", Boom)
    budget = await tap.get("/api/v1/book/chapters/1/audio/0")
    assert budget.status_code == 409 and budget.json()["device_voice"] is True
    assert called == []
    wakes["go"].set()
    await _all_sent()
    assert [w["text"].split(": ", 1)[1].split(" (")[0] for w in wakes["sent"]] == [
        "the layout of chapter 12 was approved"
    ]


async def test_a_wake_that_cannot_go_out_never_fails_the_tap(api, held, tap, monkeypatch, tmp_path):
    # No such command on this box.
    monkeypatch.setattr(settings, "book_editor_wake", str(tmp_path / "missing" / "kmbot-send.sh"))
    assert (await tap.post("/api/v1/book/chapters/12/layout", json={"action": "approve"})).status_code == 200
    await _all_sent()
    # A command that refuses.
    refuses = tmp_path / "refuses.sh"
    refuses.write_text("#!/bin/sh\necho 'no such agent' >&2\nexit 3\n", encoding="utf-8")
    refuses.chmod(refuses.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(settings, "book_editor_wake", str(refuses))
    r = await tap.post("/api/v1/book/chapters/12/write", json={})
    assert r.status_code == 200 and r.json()["already"] is False
    await _all_sent()
    # Waking switched off: the tap works and nothing is sent off.
    monkeypatch.setattr(settings, "book_editor_wake", "")
    assert (await tap.post("/api/v1/book/chapters/12/layout", json={"action": "note", "note": "Later"})).status_code == 200
    assert _pending() == []


async def test_the_wake_is_one_fleet_message_to_the_book_editor_sent_as_a_script(api, held, tap, monkeypatch, tmp_path):
    out = tmp_path / "told.json"
    stand_in = tmp_path / "kmbot-send.sh"
    stand_in.write_text(
        f"#!{sys.executable}\nimport json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'sender': os.environ.get('KMBOT_SENDER')}}, open({str(out)!r}, 'w'))\n",
        encoding="utf-8",
    )
    stand_in.chmod(stand_in.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(settings, "book_editor_wake", str(stand_in))
    assert (await tap.post("/api/v1/book/chapters/12/layout", json={"action": "approve", "by": "dev-test"})).status_code == 200
    await _all_sent()
    told = json.loads(out.read_text())
    assert told["sender"] == "api:tce-book", "sent as a script, never as him"
    agent, text = told["argv"]
    assert agent == "book-editor" == settings.book_editor_agent
    assert text.startswith("From the Book in TCE: the layout of chapter 12 was approved (")
    assert "No reply is needed." in text
    assert os.environ.get("KMBOT_SENDER") != "api:tce-book", "the server's own environment is untouched"


def test_no_wake_is_sent_off_without_a_running_loop():
    assert book_routes.wake_editor(12, "write", "", "ziv") is False
    assert book_routes._woken == {}
    assert book_routes.wake_editor(12, "reopen", "", "ziv") is False
