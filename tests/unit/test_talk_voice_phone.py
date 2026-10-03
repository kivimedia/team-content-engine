"""Talk to the editor, step 8 (1-Oct): hold to talk, at phone width.

Boots the real TCE talk routes (sitting, pins, notes) on a throwaway SQLite file
behind a fake authenticating proxy, plus a small host page that plays an edit and
opens the hold bar exactly as the notes sheet does (TceTalkVoice.open). KM BOT's
/voice-client.js is replaced by a stub that records what the page asks of the call
(mute, quiet, hush, stop) and lets the test play the call's events (the ear opening,
his words, the editor talking, a dropped connection). Headless Chromium at 390x844.

Asserts, each one a sentence in plans/30-Sep-26-talk-to-the-editor.md:
- the voice client loads only when the sheet opens, and a 401 shows "Sign in to the
  voice" linking to /voice?seat=tce&context=video:<id>;
- the call starts on the tce seat, context video:<id>, Live, no greeting, muted;
- a press pauses the video and pins its currentTime at once, and unmutes; a release
  mutes and saves his words on that note; pointercancel counts as a release;
- the editor's written answer is the note row TCE stores, never the voice's speech;
- play hushes the editor and keeps it quiet with the mic muted; pause lifts it;
- a wake lock is held while the sheet is open and let go when it closes;
- "Voice dropped - hold to reconnect", and the next hold is a fresh call on the same sitting.

Skipped when Playwright, its Chromium build or ffmpeg is missing. Nothing here calls
a paid service or a real database.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tce.api import dashboard
from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.api.routers import production as prod
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.settings import settings
from tests.editorial_db import create_tables

API_DIR = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
KEY = "talk-voice-" + uuid.uuid4().hex
WS = uuid.UUID("beefbeef-3333-4333-8333-333333333333")
PHONE = {"width": 390, "height": 844}
REF = "a1b2c3d4e5f60718"
SPOKEN = "Getting them back is really smart after you have finished your service"


# ------------------------------------------------------------------ static


def test_the_hold_bar_is_served_and_linked_and_the_voice_client_is_not():
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(dashboard.router)
    with TestClient(app) as client:
        js = client.get("/talk-voice.js")
        css = client.get("/talk-voice.css")
    assert js.status_code == 200 and js.headers["content-type"].startswith("application/javascript")
    assert "TceTalkVoice" in js.text
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert "touch-action: none" in css.text and "-webkit-touch-callout: none" in css.text

    html = (API_DIR / "workspace.html").read_text(encoding="utf-8")
    assert html.index('src="talk-voice.js"') < html.index('src="workspace.js"')
    assert 'href="talk-voice.css"' in html
    # KM BOT's client is loaded by talk-voice.js when a sheet opens, never by the shell.
    assert 'src="/voice-client.js"' not in html and 'src="voice-client.js"' not in html
    source = js.text
    assert 'VOICE_SCRIPT = "/voice-client.js"' in source
    for option in ('seat: "tce"', 'api: "live"', "greet: false", "startMuted: true"):
        assert option in source, option


# ---------------------------------------------------------------- the stub


FAKE_VOICE = """
(function (g) {
  var starts = [];
  g.__voice = { starts: starts };
  g.KmVoice = {
    start: function (opts) {
      /* el is the element carrying the editor's voice, driven the way KM BOT's
         web/voice-client.js drives it: hush() pauses it, quiet(true) mutes it, and
         quiet(false) unmutes it AND plays it again when hush() paused it
         (resumeRemote). heard is the voice's running buffer of his words: stop()
         writes it down first, as one "said" (flushHeard), like the real client. */
      var c = { opts: opts, log: [], times: [], muted: !!opts.startMuted, quieted: false,
                stopped: false, speakingNow: false, el: { paused: false, muted: false }, heard: "" };
      var mark = function (what) { c.log.push(what); c.times.push({ what: what, at: performance.now() }); };
      c.emit = function (type, data) {
        data = data || {};
        if (type === "hearing") c.heard = data.text || "";
        if (type === "said") c.heard = "";
        if (type === "partial") c.speakingNow = true;
        opts.on(type, data);
      };
      var handle = {
        mute: function (on) { on = on === undefined ? true : !!on; c.muted = on;
                              mark(on ? "mute" : "unmute"); return on; },
        quiet: function (on) {
          on = on === undefined ? true : !!on; c.quieted = on;
          if (on) c.el.muted = true; else { c.el.muted = false; c.el.paused = false; }
          mark(on ? "quiet" : "unquiet"); return on;
        },
        hush: function () { c.el.paused = true; c.speakingNow = false; mark("hush"); },
        interrupt: function () { mark("interrupt"); },
        send: function () {},
        stop: function () {
          if (c.stopped) return;
          c.stopped = true; mark("stop");
          if (c.heard) { var h = c.heard; c.heard = ""; opts.on("said", { text: h }); }
          setTimeout(function () { opts.on("closed", {}); opts.on("stopped", {}); }, 0);
        },
        get muted() { return c.muted; },
        get quieted() { return c.quieted; },
        get speaking() { return c.speakingNow; },
        get busy() { return !c.stopped; },
        get live() { return !c.stopped; }
      };
      // KM BOT's client before K1 (origin/main on the box until K1 deploys): no mute, no quiet.
      if (g.__noK1) { delete handle.mute; delete handle.quiet; }
      starts.push(c);
      opts.on("connecting", { agent: "TCE" });
      return handle;
    }
  };
})(window);
"""

HOST = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/workspace.css">
<link rel="stylesheet" href="/talk-voice.css">
<style>
  .host { padding: 12px 16px; display: grid; gap: 12px; }
  .host video { width: 100%; height: 40dvh; background: #000; display: block; }
</style></head>
<body>
<main class="host">
  <video id="player" playsinline controls controlslist="nofullscreen" disablepictureinpicture
         preload="auto" src="/clip.webm"></video>
  <ol id="notes"></ol>
  <div id="bar"></div>
</main>
<script src="/talk-voice.js"></script>
<script>
window.__stale = [];
window.__sittings = 0;
window.__openSheet = async function (uploadId) {
  var r = await fetch("/api/v1/production/recordings/" + uploadId + "/talk", { method: "POST" });
  var sitting = await r.json();
  window.talk = TceTalkVoice.open({
    handsFree: false,   // these tests are the hold-to-talk sheet; hands-free has its own
    root: document.getElementById("bar"),
    video: document.getElementById("player"),
    sitting: sitting,
    notes: document.getElementById("notes"),
    onStale: function (ref) { window.__stale.push(ref); },
    onSitting: function () { window.__sittings += 1; }
  });
  return sitting;
};
</script>
</body></html>
"""

WAKE_STUB = """
window.__wake = { requested: [], released: 0 };
Object.defineProperty(navigator, "wakeLock", { configurable: true, value: {
  request: async function (type) {
    window.__wake.requested.push(type);
    return { release: async function () { window.__wake.released += 1; },
             addEventListener: function () {} };
  }
}});
"""

VOICE_STATE = """() => (window.__voice ? window.__voice.starts : []).map(function (c) {
  return { opts: { seat: c.opts.seat, context: c.opts.context, api: c.opts.api,
                   greet: c.opts.greet, startMuted: c.opts.startMuted },
           log: c.log.slice(), muted: c.muted, quieted: c.quieted, stopped: c.stopped,
           audible: !c.el.paused && !c.el.muted, times: c.times.slice() };
})"""

LAYOUT_JS = """() => {
  const vw = window.innerWidth;
  const hold = document.querySelector('.tv-hold');
  const r = hold.getBoundingClientRect();
  const cs = getComputedStyle(hold);
  const menu = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
  hold.dispatchEvent(menu);
  const drops = [...document.querySelectorAll('.tv-drop')].map(b => b.getBoundingClientRect());
  return {
    overflowX: document.documentElement.scrollWidth > vw + 1,
    holdHeight: r.height, holdLeft: r.left, holdRight: r.right,
    touchAction: cs.touchAction, userSelect: cs.userSelect || cs.webkitUserSelect,
    menuPrevented: menu.defaultPrevented,
    smallDrops: drops.filter(d => d.width < 44 || d.height < 44).length,
    statusColor: getComputedStyle(document.querySelector('.tv-status')).color,
  };
}"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _words(text: str, step: float = 0.5) -> list[dict]:
    out, t = [], 0.0
    for w in text.split():
        out.append({"text": w, "start_s": t, "end_s": t + step - 0.1, "precision": "word"})
        t += step
    return out


async def _seed(sessionmaker, tmp_path: Path) -> uuid.UUID:
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"synthetic")
    edited = tmp_path / "walk-edited.mp4"
    edited.write_bytes(b"edited")
    async with sessionmaker() as s:
        cand = TopicCandidate(
            workspace_id=WS, week_start=datetime(2026, 9, 28), moment_ids=["m"],
            title="Call them after the service", lesson="l", audience="a",
            public_angle="p", gates={}, status="recorded",
        )
        s.add(cand)
        await s.flush()
        up = RecordingUpload(
            workspace_id=WS, candidate_id=cand.id, original_filename="walk.mp4",
            storage_path=str(src), sha256=uuid.uuid4().hex * 2, status="edited",
            transcript=_words(SPOKEN), duration_s=6.0, edited_path=str(edited),
            render_ref=REF, rendered_keep=[[0.0, 6.0]], edit_plan={"keep": [[0.0, 6.0]]},
        )
        s.add(up)
        await s.commit()
        return up.id


def _set_ref(sessionmaker, upload_id: uuid.UUID, ref: str) -> None:
    """A new render of the video lands while the sheet is open. Sync Playwright holds an
    event loop in this thread, so the write runs in a thread of its own."""

    async def write() -> None:
        async with sessionmaker() as s:
            row = await s.get(RecordingUpload, upload_id)
            row.render_ref = ref
            await s.commit()

    worker = threading.Thread(target=lambda: asyncio.run(write()))
    worker.start()
    worker.join(timeout=30)


@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> Path:
    """Six seconds of a plain frame, VP8: Playwright's Chromium has no H.264."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is not installed")
    out = tmp_path_factory.mktemp("clip") / "clip.webm"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=0x10213b:s=180x320:r=10:d=6", "-c:v", "libvpx", "-b:v", "60k", "-y", str(out)],
        check=True, timeout=120,
    )
    return out


@pytest.fixture
def host(monkeypatch, tmp_path, clip):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(WS))

    db_path = (tmp_path / "talk.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(prod, "session_factory", lambda: sessionmaker)

    async def prepare():
        await create_tables(engine)
        return await _seed(sessionmaker, tmp_path)

    upload_id = asyncio.run(prepare())
    voice = {"status": 200}

    app = FastAPI()
    app.include_router(dashboard.router)
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(workspace_router.production_router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sessionmaker

    @app.get("/voice-client.js")
    async def voice_client():
        # KM BOT's own sign-in ("KM BOT" realm) when the phone has not passed it yet.
        if voice["status"] == 401:
            return Response("", status_code=401, headers={"WWW-Authenticate": 'Basic realm="KM BOT"'})
        return Response(FAKE_VOICE, media_type="application/javascript")

    @app.get("/talk-host")
    async def talk_host():
        return HTMLResponse(HOST)

    @app.get("/clip.webm")
    async def clip_file():
        return FileResponse(clip, media_type="video/webm")

    async def proxy(scope, receive, send):
        # The browser never holds the key; nginx injects it after Basic Auth.
        if scope["type"] == "http" and scope["path"].startswith("/api/v1/"):
            headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"x-tce-editor-key"]
            headers.append((b"x-tce-editor-key", KEY.encode()))
            scope = dict(scope, headers=headers)
        await app(scope, receive, send)

    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(proxy, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(300):
        if server.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("talk host did not start")
    try:
        yield {
            "base": f"http://127.0.0.1:{port}",
            "upload": str(upload_id),
            "upload_id": upload_id,
            "sm": sessionmaker,
            "voice": voice,
        }
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        asyncio.run(engine.dispose())


# ----------------------------------------------------------------- helpers


class Phone:
    def __init__(self, page):
        self.page = page

    def voice(self) -> list[dict]:
        return self.page.evaluate(VOICE_STATE)

    def emit(self, index: int, kind: str, data: dict | None = None) -> None:
        self.page.evaluate("([i, t, d]) => window.__voice.starts[i].emit(t, d)", [index, kind, data or {}])

    def status(self) -> str:
        return self.page.locator(".tv-status").inner_text()

    def wait_status(self, text: str, timeout: float = 15_000) -> None:
        self.page.wait_for_function(
            "(s) => (document.querySelector('.tv-status') || {}).textContent.includes(s)",
            arg=text, timeout=timeout,
        )

    def sitting(self, sid: str) -> dict:
        return self.page.evaluate(
            "async (sid) => (await fetch('/api/v1/production/talk/' + sid)).json()", sid
        )

    def notes_in(self, sid: str, state: str, count: int, timeout: float = 8.0) -> list[dict]:
        deadline = time.monotonic() + timeout
        while True:
            notes = [n for n in self.sitting(sid)["notes"] if n["state"] == state]
            if len(notes) == count or time.monotonic() > deadline:
                return notes
            time.sleep(0.2)

    def hold_point(self) -> tuple[float, float]:
        button = self.page.locator(".tv-hold")
        button.scroll_into_view_if_needed()
        box = button.bounding_box()
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    def video(self, expr: str):
        return self.page.evaluate(f"() => {{ const v = document.getElementById('player'); return {expr}; }}")


def _launch(pw):
    from playwright.sync_api import Error as PlaywrightError

    try:
        return pw.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
    except PlaywrightError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Chromium is not installed for Playwright: {exc}")


def _phone(browser):
    context = browser.new_context(viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True)
    context.set_default_timeout(20_000)
    context.add_init_script(WAKE_STUB)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    return page, errors


def _patched(response) -> bool:
    return "/notes/" in response.url and response.request.method == "PATCH"


def _pinned(response) -> bool:
    return response.url.endswith("/notes") and response.request.method == "POST"


# ------------------------------------------------------------------- walks


def test_hold_to_talk_pins_the_second_saves_his_words_and_writes_the_editors_answer(host, tmp_path):
    from playwright.sync_api import sync_playwright

    shots = Path(os.environ.get("TCE_TEST_SHOTS") or tmp_path)
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = _launch(pw)
        page, errors = _phone(browser)
        phone = Phone(page)
        asked_for_voice: list[str] = []
        page.on("request", lambda r: asked_for_voice.append(r.url) if "voice-client.js" in r.url else None)

        page.goto(f"{host['base']}/talk-host")
        page.wait_for_function("() => !!window.TceTalkVoice")
        page.wait_for_function("() => document.getElementById('player').readyState >= 1")
        # Lazy: nothing asks for KM BOT's client until the sheet opens.
        assert asked_for_voice == []
        assert page.evaluate("() => typeof window.KmVoice") == "undefined"

        sitting = page.evaluate("(id) => window.__openSheet(id)", host["upload"])
        sid = sitting["session_id"]
        page.wait_for_function("() => window.__voice && window.__voice.starts.length === 1")
        assert len(asked_for_voice) >= 1
        call = phone.voice()[0]
        assert call["opts"] == {
            "seat": "tce", "context": f"video:{host['upload']}", "api": "live",
            "greet": False, "startMuted": True,
        }
        assert call["muted"] is True
        # 3-second rule: while it connects, the bar says what is happening.
        phone.wait_status("Connecting Jennifer's voice")
        assert page.evaluate("() => window.__wake.requested") == ["screen"]
        phone.emit(0, "ear", {"open": True})
        phone.wait_status("Pause where something is wrong, then hold to talk.")
        assert page.locator(".tv-empty").inner_text().startswith("No notes yet")

        # ---- play: the editor is hushed and kept quiet, and the mic stays muted
        phone.video("v.play()")
        page.wait_for_function("() => document.getElementById('player').currentTime > 1.3")
        phone.wait_status("Jennifer stays quiet while the video plays")
        call = phone.voice()[0]
        assert call["quieted"] is True and call["muted"] is True
        assert "hush" in call["log"]

        # ---- press: pause, pin currentTime at once, unmute
        x, y = phone.hold_point()
        page.mouse.move(x, y)
        with page.expect_response(_pinned) as pinned:
            page.mouse.down()
        pin = pinned.value.json()
        assert pinned.value.status == 200
        assert phone.video("v.paused") is True
        assert abs(pin["edit_s"] - phone.video("v.currentTime")) < 0.1
        assert pinned.value.request.post_data_json["render_ref"] == REF
        # A hold, not a typed note: the editor's voice reads holds (1-Oct final review).
        assert pinned.value.request.post_data_json["by"] == "voice"
        at = pin["clock"]
        phone.wait_status(f"Listening at {at}")
        call = phone.voice()[0]
        # His mic is open, and nothing of the editor is heard while he holds.
        assert call["muted"] is False and call["quieted"] is True and call["audible"] is False
        assert page.locator(".tv-hold").get_attribute("aria-pressed") == "true"
        assert page.locator(".tv-hold").inner_text() == "Listening - let go when done"

        # His words appear as the voice hears them.
        phone.emit(0, "hearing", {"text": "Cut the second"})
        phone.emit(0, "hearing", {"text": "Cut the second basically here"})
        page.wait_for_function(
            "() => document.querySelector('.tv-words').textContent.includes('Cut the second basically here')"
        )
        page.wait_for_timeout(400)

        # ---- release: the editor may be heard again, the mic closes a moment later,
        # and his words are saved on that note
        with page.expect_response(_patched) as heard:
            page.mouse.up()
            assert phone.voice()[0]["muted"] is False, "the mic stays open for the end of his sentence"
            assert phone.voice()[0]["audible"] is True
            phone.wait_status(f"Finishing what you said at {at}")
            phone.emit(0, "said", {"text": "Cut the second basically here"})
        page.wait_for_function("() => window.__voice.starts[0].muted === true", timeout=5_000)
        assert heard.value.status == 200
        assert heard.value.request.post_data_json == {"heard": "Cut the second basically here"}
        saved = heard.value.json()
        assert saved["id"] == pin["note_id"] and saved["state"] == "held"
        page.wait_for_function(
            "() => [...document.querySelectorAll('.tv-said')].some(p => p.textContent.includes('Cut the second basically here'))"
        )
        row = page.locator(f'.tv-note[data-note-id="{pin["note_id"]}"]')
        assert row.locator(".tv-when").inner_text() == at
        assert row.locator(".tv-answer").inner_text() == "Jennifer is reading this note."

        # ---- the editor talks: its speech is never drawn; its written answer is the row
        phone.emit(0, "partial", {"text": "Sure thing, I will SNIP IT OUT right away"})
        phone.wait_status("Jennifer is answering out loud")
        understood = f"At {at} you want the second 'basically' gone."
        status = page.evaluate(
            """async ([sid, nid, u]) => (await fetch('/api/v1/production/talk/' + sid + '/notes/' + nid, {
                 method: 'PATCH', headers: {'Content-Type': 'application/json'},
                 body: JSON.stringify({understood: u})})).status""",
            [sid, pin["note_id"], understood],
        )
        assert status == 200
        phone.emit(0, "turn_end", {"text": "Sure thing, I will SNIP IT OUT right away"})
        page.wait_for_function(
            "(u) => [...document.querySelectorAll('.tv-answer')].some(p => p.textContent.includes(u))",
            arg=understood,
        )
        assert row.locator(".tv-answer").inner_text() == f"Jennifer: “{understood}”"
        assert "SNIP IT OUT" not in page.locator("body").inner_text()

        # ---- phone layout
        layout = page.evaluate(LAYOUT_JS)
        assert layout["overflowX"] is False, layout
        assert layout["holdHeight"] >= 72, layout
        assert layout["holdLeft"] >= 0 and layout["holdRight"] <= PHONE["width"], layout
        assert layout["touchAction"] == "none" and layout["userSelect"] == "none", layout
        assert layout["menuPrevented"] is True, layout
        assert layout["smallDrops"] == 0, layout
        page.screenshot(path=str(shots / "talk-voice-phone.png"), full_page=True)

        # ---- a tap is not a note
        x, y = phone.hold_point()
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.up()
        phone.wait_status("Keep the button held while you talk. Nothing was saved.")
        assert len(phone.notes_in(sid, "rejected", 1)) == 1

        # ---- a hold with no words is taken back, and says so
        # (measured again: the notes above the bar changed height since the last press)
        page.mouse.move(*phone.hold_point())
        page.mouse.down()
        page.wait_for_timeout(450)
        page.mouse.up()
        phone.wait_status("No words were caught at", timeout=8_000)
        assert len(phone.notes_in(sid, "rejected", 2)) == 2

        # ---- pointercancel (the phone took the gesture) is a release: the words are kept
        hold = page.locator(".tv-hold")
        pointer = {"pointerId": 7, "pointerType": "touch", "isPrimary": True, "button": 0,
                   "bubbles": True, "cancelable": True}
        with page.expect_response(_pinned):
            hold.dispatch_event("pointerdown", pointer)
        phone.emit(0, "hearing", {"text": "Keep the pause after service"})
        page.wait_for_timeout(400)
        with page.expect_response(_patched, timeout=8_000) as kept:
            hold.dispatch_event("pointercancel", pointer)
        assert phone.voice()[0]["muted"] is True
        assert kept.value.request.post_data_json == {"heard": "Keep the pause after service"}
        held = phone.notes_in(sid, "held", 2)
        assert sorted(n["request"] for n in held) == ["Cut the second basically here", "Keep the pause after service"]

        # ---- play again: quiet; pause: the editor may be heard again
        phone.video("v.play()")
        page.wait_for_function("() => !document.getElementById('player').paused")
        page.wait_for_function("() => window.__voice.starts[0].quieted === true")
        phone.video("v.pause()")
        page.wait_for_function("() => window.__voice.starts[0].quieted === false")
        assert phone.voice()[0]["muted"] is True

        # ---- re-rendered under the sheet: the pin is refused and the player reloads
        _set_ref(host["sm"], host["upload_id"], "ffff0000ffff0000")
        reopened_url = f"/production/recordings/{host['upload']}/talk"
        with page.expect_response(
            lambda r: r.url.endswith(reopened_url) and r.request.method == "POST"
        ) as reopened:
            with page.expect_response(_pinned) as stale:
                page.mouse.move(*phone.hold_point())
                page.mouse.down()
            assert stale.value.status == 409
            page.mouse.up()
        phone.wait_status("This is an older edit of the video")
        # Opening the notes again moved the sitting (same one) onto the new render.
        assert reopened.value.status == 200
        moved = reopened.value.json()
        assert moved["session_id"] == sid and moved["render_ref"] == "ffff0000ffff0000"
        assert "v=ffff0000ffff0000" in moved["file_url"]
        page.wait_for_function("() => window.__stale.length === 1")
        assert page.evaluate("() => window.__stale") == ["ffff0000ffff0000"]
        assert page.evaluate("() => window.talk.renderRef") == "ffff0000ffff0000"

        # ---- closing the sheet ends the call and lets the screen sleep
        page.evaluate("() => window.talk.close()")
        call = phone.voice()[0]
        assert call["stopped"] is True
        assert page.evaluate("() => window.__wake.released") == 1
        assert page.locator("#bar").inner_html() == ""
        assert len(phone.voice()) == 1, "closing must not start another call"

        assert errors == [], errors
        browser.close()


def test_a_dropped_voice_says_so_and_the_next_hold_is_a_fresh_call_on_the_same_sitting(host):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = _launch(pw)
        page, errors = _phone(browser)
        phone = Phone(page)
        page.goto(f"{host['base']}/talk-host")
        page.wait_for_function("() => !!window.TceTalkVoice")
        sitting = page.evaluate("(id) => window.__openSheet(id)", host["upload"])
        sid = sitting["session_id"]
        page.wait_for_function("() => window.__voice && window.__voice.starts.length === 1")
        phone.emit(0, "ear", {"open": True})
        phone.wait_status("Pause where something is wrong")

        # The wifi went: the client reports the dropped connection.
        phone.emit(0, "error", {"text": "The voice connection dropped."})
        phone.wait_status("Voice dropped - hold to reconnect")
        assert page.locator(".tv-hold").inner_text() == "Hold to reconnect"
        assert phone.voice()[0]["stopped"] is True
        page.wait_for_timeout(100)  # the old call's own "stopped" must not change anything
        assert phone.status() == "Voice dropped - hold to reconnect"

        # The next hold: a fresh call on the same seat and video, and the pin on the same sitting.
        page.mouse.move(*phone.hold_point())
        with page.expect_response(_pinned) as pinned:
            page.mouse.down()
        assert f"/talk/{sid}/notes" in pinned.value.url
        page.wait_for_function("() => window.__voice.starts.length === 2")
        again = phone.voice()[1]
        assert again["opts"]["context"] == f"video:{host['upload']}" and again["opts"]["greet"] is False
        assert again["muted"] is False, "he is holding: the new call must hear him once it connects"
        phone.wait_status("Connecting Jennifer's voice. Keep holding")
        phone.emit(1, "ear", {"open": True})
        phone.wait_status(f"Listening at {pinned.value.json()['clock']}")
        phone.emit(1, "hearing", {"text": "Tighten the gap here"})
        page.wait_for_timeout(400)
        with page.expect_response(_patched) as heard:
            page.mouse.up()
            phone.emit(1, "said", {"text": "Tighten the gap here"})
        assert heard.value.request.post_data_json == {"heard": "Tighten the gap here"}
        assert f"/talk/{sid}/notes/" in heard.value.url

        # The voice service ends the call on its own (idle reaper, the 2-hour cap).
        phone.emit(1, "closed", {"code": 0, "text": "Call ended."})
        phone.wait_status("Voice dropped - hold to reconnect")
        assert len(phone.voice()) == 2, "a call is started by a hold, never by itself"

        # 1-Oct review: the call drops WHILE he holds, before any word came back. The
        # note is taken back, and the bar blames the voice, not his words.
        page.mouse.move(*phone.hold_point())
        with page.expect_response(_pinned) as third:
            page.mouse.down()
        page.wait_for_function("() => window.__voice.starts.length === 3")
        phone.emit(2, "ear", {"open": True})
        phone.wait_status("Listening at")
        phone.emit(2, "error", {"text": "The voice connection dropped."})
        page.wait_for_timeout(450)
        page.mouse.up()
        clock = third.value.json()["clock"]
        phone.wait_status(f"The voice dropped while you talked at {clock}", timeout=10_000)
        assert "No words were caught" not in phone.status()
        third_id = third.value.json()["note_id"]
        assert [n["id"] for n in phone.notes_in(sid, "rejected", 1)] == [third_id]

        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()


def test_a_voice_that_asks_for_its_own_sign_in_links_to_it_and_typing_still_works(host):
    from playwright.sync_api import sync_playwright

    host["voice"]["status"] = 401
    with sync_playwright() as pw:
        browser = _launch(pw)
        page, errors = _phone(browser)
        phone = Phone(page)
        page.goto(f"{host['base']}/talk-host")
        page.wait_for_function("() => !!window.TceTalkVoice")
        page.evaluate("(id) => window.__openSheet(id)", host["upload"])
        phone.wait_status("needs its own sign-in")
        assert "Typing still works." in phone.status()
        link = page.locator(".tv-signin")
        assert link.is_visible()
        assert link.inner_text() == "Sign in to the voice"
        assert link.get_attribute("href") == (
            f"/voice?seat=tce&context=video:{host['upload']}&return=%2Ftalk-host"
        )
        assert page.locator(".tv-hold").is_disabled()
        assert page.evaluate("() => typeof window.KmVoice") == "undefined"
        assert page.evaluate("() => document.querySelectorAll('script[src$=\"voice-client.js\"]').length") == 0
        assert page.evaluate("() => window.__voice === undefined")

        # He signs in in the other tab and comes back: the voice loads and the call starts.
        host["voice"]["status"] = 200
        page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_function("() => window.__voice && window.__voice.starts.length === 1")
        phone.wait_status("Connecting Jennifer's voice")
        assert page.locator(".tv-hold").is_enabled()
        assert page.locator(".tv-signin").is_hidden()

        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()


def test_his_words_for_a_note_are_what_came_after_the_press():
    """The voice client's buffer can still hold the last note's words, and Live can
    flush it mid-sentence (when it hands the words to the editor)."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    source = (API_DIR / "talk-voice.js").read_text(encoding="utf-8")
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        page.set_content("<!doctype html><title>t</title>")
        page.add_script_tag(content=source)
        got = page.evaluate(
            """() => {
              const C = window.TceTalkVoice.Capture;
              const out = {};
              // Note 2 while the buffer still holds note 1 (the editor has not answered yet).
              let c = new C();
              c.start(); c.hearing(" Cut the"); c.hearing(" Cut the second"); c.stop();
              c.start(); c.hearing(" Cut the second Keep"); c.hearing(" Cut the second Keep the pause");
              out.second = c.words();
              // Live hands the words over mid-sentence ("said"), then he keeps talking.
              c = new C();
              c.start(); c.hearing("Take out"); c.said("Take out");
              c.hearing(" the second one"); out.split = c.words();
              // A realtime turn: "hearing" with nothing, then the whole sentence as "said".
              c = new C();
              c.start(); c.hearing(""); c.said("Move the title up"); out.realtime = c.words();
              // Words that arrive while no note is open belong to no note.
              c = new C();
              c.said("stray words"); c.start(); c.hearing("Fresh"); out.fresh = c.words();
              // The note line never shows the voice's own speech.
              const v = window.TceTalkVoice.noteView(
                {id: "n", start_s: 38.4, request: "cut it", understood: null, state: "held", result: null}, "unconfirmed");
              out.when = v.when; out.answer = v.answer;
              return out;
            }"""
        )
        browser.close()
    assert got["second"] == "Keep the pause"
    assert got["split"] == "Take out the second one"
    assert got["realtime"] == "Move the title up"
    assert got["fresh"] == "Fresh"
    assert got["when"] == "0:38"
    # 1-Oct final review: "hold and say it again" pinned a second copy of the note; the
    # note already goes to the editor as he said it.
    assert got["answer"] == "Jennifer has not confirmed this one. It is still made as you said it."


# ------------------------------------------------------- 1-Oct review fixes


def _ready(page, phone, host) -> str:
    """The sheet open on the seeded edit, its voice up. Returns the sitting id."""
    page.goto(f"{host['base']}/talk-host")
    page.wait_for_function("() => !!window.TceTalkVoice")
    page.wait_for_function("() => document.getElementById('player').readyState >= 1")
    sitting = page.evaluate("(id) => window.__openSheet(id)", host["upload"])
    page.wait_for_function("() => window.__voice && window.__voice.starts.length === 1")
    phone.emit(0, "ear", {"open": True})
    phone.wait_status("Pause where something is wrong")
    return sitting["session_id"]


def _patches(page) -> list[dict]:
    seen: list[dict] = []

    def keep(request) -> None:
        if "/production/talk/" in request.url and request.method == "PATCH":
            seen.append({"url": request.url, "body": request.post_data_json})

    page.on("request", keep)
    return seen


CLOSE_AND_MARK = (
    "() => { window.__closed = false; Promise.resolve(window.talk.close()).then(() => { window.__closed = true; }); }"
)


def test_a_press_over_the_editor_keeps_it_silent_and_the_mic_closes_a_moment_after_letting_go(host):
    """Review findings 4 and 10: hush() then quiet(false) played the editor again, so it
    talked over his "no, I meant...". Finding 6: the sheet muted the moment he let go,
    while scenario F (the receipt) keeps the mic open 1.5 s after the phrase."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = _launch(pw)
        page, errors = _phone(browser)
        phone = Phone(page)
        _ready(page, phone, host)
        page.evaluate(
            """() => { window.__ups = []; document.querySelector('.tv-hold')
                 .addEventListener('pointerup', () => window.__ups.push(performance.now())); }"""
        )

        # The editor is answering out loud on the paused video.
        phone.emit(0, "partial", {"text": "At 0:01 you want the"})
        phone.wait_status("Jennifer is answering out loud")
        assert phone.voice()[0]["audible"] is True

        # He presses over it: cut off, and silent for the whole hold.
        page.mouse.move(*phone.hold_point())
        with page.expect_response(_pinned):
            page.mouse.down()
        call = phone.voice()[0]
        assert call["audible"] is False and call["muted"] is False, call
        assert call["log"][-3:] == ["quiet", "hush", "unmute"], call["log"]
        phone.emit(0, "partial", {"text": " rest of the old answer"})  # Live finishes its sentence
        phone.emit(0, "hearing", {"text": "No I meant the second one"})
        page.wait_for_timeout(500)
        assert phone.voice()[0]["audible"] is False, "the editor talked over his hold"

        # Let go: the answer may be heard; the mic stays open a moment, then closes.
        page.mouse.up()
        assert phone.voice()[0]["audible"] is True
        assert phone.voice()[0]["muted"] is False
        phone.wait_status("Finishing what you said at")
        page.wait_for_function("() => window.__voice.starts[0].muted === true", timeout=5_000)
        call = phone.voice()[0]
        muted_at = [t["at"] for t in call["times"] if t["what"] == "mute"][-1]
        up_at = page.evaluate("() => window.__ups[window.__ups.length - 1]")
        assert 1_400 <= muted_at - up_at <= 2_500, muted_at - up_at
        phone.emit(0, "said", {"text": "No I meant the second one"})

        # The video plays while the editor talks; a press pauses it, and the video's own
        # "pause" event that follows must not bring the editor back.
        phone.video("v.play()")
        page.wait_for_function("() => !document.getElementById('player').paused")
        phone.emit(0, "partial", {"text": "Saved, nothing changes"})
        page.mouse.move(*phone.hold_point())
        with page.expect_response(_pinned):
            page.mouse.down()
        page.wait_for_function("() => document.getElementById('player').paused")
        page.wait_for_timeout(300)
        assert phone.voice()[0]["audible"] is False
        assert phone.voice()[0]["muted"] is False

        # Play in the moment after letting go shuts the mic at once.
        phone.emit(0, "hearing", {"text": "Keep this part"})
        page.wait_for_timeout(450)
        page.mouse.up()
        assert phone.voice()[0]["muted"] is False
        phone.video("v.play()")
        page.wait_for_function("() => window.__voice.starts[0].muted === true", timeout=1_000)

        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()


def test_closing_right_after_letting_go_keeps_the_note_and_its_late_words(host):
    """Review finding 3: close() saved what had arrived and stopped the call at once, so
    the end of his sentence was lost, and a note with no words yet was taken back."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = _launch(pw)
        page, errors = _phone(browser)
        phone = Phone(page)
        patches = _patches(page)
        sid = _ready(page, phone, host)

        page.mouse.move(*phone.hold_point())
        with page.expect_response(_pinned) as pinned:
            page.mouse.down()
        nid = pinned.value.json()["note_id"]
        phone.emit(0, "hearing", {"text": "Take out the long"})
        page.wait_for_timeout(500)
        page.mouse.up()
        page.wait_for_timeout(300)
        page.evaluate(CLOSE_AND_MARK)
        assert page.locator("#bar").inner_html() == "", "the bar goes at once"
        # Live's transcript of the end of his sentence lands after the sheet closed.
        phone.emit(0, "hearing", {"text": "Take out the long pause after service"})
        page.wait_for_function("() => window.__closed === true", timeout=10_000)
        assert phone.voice()[0]["stopped"] is True
        held = phone.notes_in(sid, "held", 1)
        assert [(n["id"], n["request"]) for n in held] == [(nid, "Take out the long pause after service")]

        # Again, and this time no word has come back before he closes: the voice's own
        # last flush (stop() writes down what it still holds) carries them.
        page.evaluate("(id) => window.__openSheet(id)", host["upload"])
        page.wait_for_function("() => window.__voice.starts.length === 2")
        phone.emit(1, "ear", {"open": True})
        phone.wait_status("Pause where something is wrong")
        page.mouse.move(*phone.hold_point())
        with page.expect_response(_pinned) as second:
            page.mouse.down()
        page.wait_for_timeout(500)
        page.mouse.up()
        page.evaluate(CLOSE_AND_MARK)
        page.wait_for_timeout(200)
        page.evaluate("() => { window.__voice.starts[1].heard = 'Move the title up'; }")
        page.wait_for_function("() => window.__closed === true", timeout=10_000)
        held = {n["id"]: n["request"] for n in phone.notes_in(sid, "held", 2)}
        assert held.get(second.value.json()["note_id"]) == "Move the title up", held

        # And a hold that never got a word, even after the voice's own last flush: it
        # carries nothing of his, so it is taken back before the close is done (1-Oct
        # final review: it kept the sitting open for good and said "Listening" later).
        page.evaluate("(id) => window.__openSheet(id)", host["upload"])
        page.wait_for_function("() => window.__voice.starts.length === 3")
        phone.emit(2, "ear", {"open": True})
        phone.wait_status("Pause where something is wrong")
        page.mouse.move(*phone.hold_point())
        with page.expect_response(_pinned) as third:
            page.mouse.down()
        page.wait_for_timeout(500)
        page.mouse.up()
        page.evaluate(CLOSE_AND_MARK)
        page.wait_for_function("() => window.__closed === true", timeout=10_000)
        third_id = third.value.json()["note_id"]
        # Taken back by the time close() resolved: the sheet's close route then finds
        # nothing waiting, and closes the notes.
        drops = [p["url"] for p in patches if (p["body"] or {}).get("drop")]
        assert len(drops) == 1 and drops[0].endswith(third_id), patches
        states = {n["id"]: n["state"] for n in phone.sitting(sid)["notes"]}
        assert states[third_id] == "rejected", states
        assert states[second.value.json()["note_id"]] == "held", "a note with words is never taken back"
        assert errors == [], errors
        browser.close()


def test_a_quick_second_press_keeps_the_end_of_the_first_note_on_it(host):
    """Review finding 7: a press within a second of letting go cut the first note's words
    short, and its late transcript landed on the second note."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = _launch(pw)
        page, errors = _phone(browser)
        phone = Phone(page)
        sid = _ready(page, phone, host)

        page.mouse.move(*phone.hold_point())
        with page.expect_response(_pinned) as first:
            page.mouse.down()
        phone.emit(0, "hearing", {"text": "Cut the second"})
        page.wait_for_timeout(450)
        page.mouse.up()
        page.wait_for_timeout(400)
        page.mouse.move(*phone.hold_point())
        with page.expect_response(_pinned) as second:
            page.mouse.down()
            # Live's transcript of his first sentence is still arriving.
            phone.emit(0, "hearing", {"text": "Cut the second basically"})
        phone.wait_status(f"Listening at {second.value.json()['clock']}")
        page.wait_for_timeout(900)
        phone.emit(0, "hearing", {"text": "Cut the second basically and keep the pause"})
        page.wait_for_function(
            "() => document.querySelector('.tv-words').textContent.includes('and keep the pause')"
        )
        assert "Cut the second" not in page.locator(".tv-words").inner_text()
        page.wait_for_timeout(300)
        page.mouse.up()
        phone.emit(0, "said", {"text": "Cut the second basically and keep the pause"})
        a, b = first.value.json()["note_id"], second.value.json()["note_id"]
        held = {n["id"]: n["request"] for n in phone.notes_in(sid, "held", 2)}
        assert held == {a: "Cut the second basically", b: "and keep the pause"}, held

        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()


STATUS_HOST = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>bar</title></head>
<body><main style="padding: 12px 16px"><video id="player"></video><div id="bar"></div><ol id="notes"></ol></main></body></html>
"""

# The sheet's bar against a scripted sitting, with no server. Writes answer like the routes
# (window.__patchAs: what a PATCH answers with, as the server would for that note).
OPEN_FAKE = """(payload) => {
  window.__payload = payload;
  window.__posts = 0;
  window.__calls = [];
  window.talk = TceTalkVoice.open(Object.assign({
    handsFree: false,   // these tests are the hold-to-talk sheet; hands-free has its own
    root: document.getElementById('bar'),
    video: document.getElementById('player'),
    notes: document.getElementById('notes'),
    sitting: payload,
    api: async (path, o) => {
      const method = (o || {}).method || 'GET';
      window.__calls.push({ method, path, body: (o || {}).body || null });
      if (method === 'POST' && path.endsWith('/notes')) {
        window.__posts += 1;
        const id = 'n' + window.__posts;
        return { note_id: id, edit_s: 0, clock: '0:00',
                 note: { id, state: 'listening', start_s: 0, request: '', understood: null, result: null } };
      }
      if (method === 'PATCH') {
        return Object.assign({ id: path.split('/').pop(), state: 'held', start_s: 0,
                 request: (o.body || {}).heard || '', understood: null, result: null }, window.__patchAs || {});
      }
      return JSON.parse(JSON.stringify(window.__payload));
    }
  }, window.__openOpts || {}));
}"""

BAR_LAYOUT = """() => {
  // Layout positions (offsetTop): the pressed look's own 2 px nudge (a transform) is not a move.
  const bar = document.getElementById('bar'), hold = document.querySelector('.tv-hold');
  const s = document.querySelector('.tv-status'), w = document.querySelector('.tv-words');
  return { offset: hold.offsetTop - bar.offsetTop, height: bar.offsetHeight,
           statusFits: s.scrollHeight <= s.clientHeight + 1, wordsFit: w.scrollHeight <= w.clientHeight + 1,
           overflowX: document.documentElement.scrollWidth > window.innerWidth + 1 };
}"""

OLD_STEP = "Captioned MP4 ready: 61 ranges, 2:14 long, longest pause 0.45 s"


def _bar_page(pw, payload: dict, before: str = "", call: bool = True):
    """The bar alone at phone width, against a scripted sitting (no server). `before`
    runs before the voice client loads; `call`: wait for the call to start."""
    browser = _launch(pw)
    page, errors = _phone(browser)
    page.set_content(STATUS_HOST)
    page.add_style_tag(content=(API_DIR / "workspace.css").read_text(encoding="utf-8"))
    page.add_style_tag(content=(API_DIR / "talk-voice.css").read_text(encoding="utf-8"))
    if before:
        page.add_script_tag(content=before)
    page.add_script_tag(content=FAKE_VOICE)
    page.add_script_tag(content=(API_DIR / "talk-voice.js").read_text(encoding="utf-8"))
    page.evaluate(OPEN_FAKE, payload)
    if call:
        page.wait_for_function("() => window.__voice && window.__voice.starts.length === 1")
    return browser, page, errors


BASE = {"session_id": "s1", "upload_id": "u1", "render_ref": "r1", "state": "open", "notes": [],
        "video_status": "edited", "video_step": OLD_STEP, "result": None}


def test_the_bar_never_moves_the_button_and_says_a_voice_problem_plainly():
    """Review finding 8: the words box appearing mid-hold, and longer sentences, moved
    the hold button under his thumb. Finding 5: a raw "Voice error: {json}" from Live
    went to the status line."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, errors = _bar_page(pw, BASE)
        phone = Phone(page)
        phone.wait_status("Connecting Jennifer's voice")

        layouts = {"idle": page.evaluate(BAR_LAYOUT)}
        page.mouse.move(*phone.hold_point())
        page.mouse.down()
        phone.wait_status("at 0:00 starts when it is ready.")
        layouts["holding, connecting"] = page.evaluate(BAR_LAYOUT)
        phone.emit(0, "ear", {"open": True})
        phone.wait_status("Listening at 0:00")
        long_words = ("Cut the second basically and keep the pause after service because the joke "
                      "lands better when there is a breath before it and the title should move up a bit")
        phone.emit(0, "hearing", {"text": long_words})
        page.wait_for_function("() => document.querySelector('.tv-words').textContent.includes('move up a bit')")
        layouts["holding, words"] = page.evaluate(BAR_LAYOUT)
        page.wait_for_timeout(400)  # a hold, not a tap
        page.mouse.up()
        phone.wait_status("what you said at 0:00")
        layouts["letting go"] = page.evaluate(BAR_LAYOUT)
        offsets = {k: round(v["offset"], 1) for k, v in layouts.items()}
        assert len(set(offsets.values())) == 1, offsets
        assert all(v["statusFits"] and v["wordsFit"] and not v["overflowX"] for v in layouts.values()), layouts

        phone.emit(0, "said", {"text": long_words})
        phone.wait_status("Saved at 0:00")
        raw = 'Voice error: {"type":"error","error":{"type":"invalid_request_error","message":"Unknown event"}}'
        phone.emit(0, "error", {"text": raw})
        page.wait_for_timeout(200)
        assert phone.status() == "Jennifer's voice reported a problem. Your notes are saved.", phone.status()
        problem = page.evaluate(BAR_LAYOUT)
        assert round(problem["offset"], 1) == offsets["idle"] and problem["statusFits"], problem

        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()


def test_the_bar_says_what_the_notes_are_doing_and_when_the_editor_has_stopped():
    """Review finding 1: Live sends no end of turn while his mic is muted, so "answering
    out loud" never ended. Finding 2: while the notes were being made the bar showed the
    last render's line, and a hand-back never said why."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, errors = _bar_page(pw, BASE)
        phone = Phone(page)
        phone.emit(0, "ear", {"open": True})
        phone.wait_status("Pause where something is wrong, then hold to talk.")

        # The editor stops "answering" when its words stop: no turn_end comes on Live.
        phone.emit(0, "partial", {"text": "At 0:00 you want the pause kept."})
        phone.wait_status("Jennifer is answering out loud")
        phone.wait_status("Pause where something is wrong, then hold to talk.", timeout=4_000)
        assert page.evaluate("() => window.talk.speaking") is False

        def status_for(payload: dict) -> str:
            page.evaluate("(p) => { window.__payload = p; return window.talk.refresh(); }", payload)
            return phone.status()

        away = "Waiting for the subscription worker (waiting_capacity)"
        assert status_for(dict(BASE, state="thinking", result={"status": away})) == away
        handed = "Jennifer could not read the notes, so nothing was changed. Make the new version again."
        assert status_for(dict(BASE, state="open", result={"status": handed})) == handed
        reading = "Reading your 3 notes on the subscription"
        assert status_for(dict(BASE, state="thinking", result={"status": reading})) == reading
        cutting = "Cutting and burning in your captions"
        assert status_for(dict(BASE, state="rendering", result={"status": cutting})) == cutting
        live = dict(BASE, state="rendering", video_status="rendering", video_step="Cutting and burning: 41%",
                    result={"status": cutting})
        assert status_for(live) == "Cutting and burning: 41%"
        made = "New version made from your 3 notes. 1 of them needs you."
        assert status_for(dict(BASE, state="needs_you", result={"status": made})) == made
        assert OLD_STEP not in page.locator("body").inner_text()

        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()


# ------------------------------------------------------- 1-Oct final review


HOLD_POINTER = {"pointerId": 9, "pointerType": "touch", "isPrimary": True, "button": 0,
                "bubbles": True, "cancelable": True}


def test_a_voice_client_without_the_calls_own_mute_never_keeps_a_call_open():
    """Finding: a TCE deploy that lands before KM BOT's K1 meets a voice client whose call
    has no mute and no quiet. The call stayed open and unmuted, greeted over the video,
    and every hold threw before its pin."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, errors = _bar_page(pw, BASE, before="window.__noK1 = true;", call=False)
        phone = Phone(page)
        page.wait_for_function("() => window.__voice && window.__voice.starts.length === 1")
        phone.wait_status("older than the notes sheet")
        assert "Typing still works." in phone.status()
        assert phone.voice()[0]["stopped"] is True, "no call stays open"
        assert page.locator(".tv-hold").is_disabled()
        page.locator(".tv-hold").dispatch_event("pointerdown", HOLD_POINTER)
        page.wait_for_timeout(300)
        assert page.evaluate("() => window.__posts") == 0
        assert len(phone.voice()) == 1, "a press never starts another call"
        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()


def test_a_pin_with_no_words_from_an_earlier_visit_says_so_and_is_not_polled_for():
    """Finding 5: an empty pin left behind read "Listening for your words" although
    nothing listened, and kept the sheet polling every 2 s."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    old = {"id": "old", "state": "listening", "start_s": 2.0, "request": "", "understood": None, "result": None}
    with sync_playwright() as pw:
        browser, page, errors = _bar_page(pw, dict(BASE, notes=[old]))
        row = page.locator('.tv-note[data-note-id="old"]')
        row.wait_for()
        assert row.locator(".tv-said").inner_text() == "No words were caught here."
        assert row.locator(".tv-drop").count() == 1, "he can take it back"
        page.wait_for_timeout(4_500)
        gets = page.evaluate("() => window.__calls.filter(c => c.method === 'GET').length")
        assert gets == 0, f"polled {gets} times for a pin nobody is speaking into"
        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()


def test_a_hold_taken_back_as_an_instruction_says_so_not_saved():
    """Finding 2: his "yes" on a hold is his answer. When the server says that hold was
    taken back as an instruction, the bar says so instead of "Saved at 0:00"."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    taken = "This hold was an instruction to Jennifer, not a note."
    with sync_playwright() as pw:
        browser, page, errors = _bar_page(pw, BASE)
        phone = Phone(page)
        phone.emit(0, "ear", {"open": True})
        phone.wait_status("Pause where something is wrong")
        page.evaluate("(t) => { window.__patchAs = {state: 'rejected', result: {command: 'yes', taken: t}}; }", taken)
        page.mouse.move(*phone.hold_point())
        page.mouse.down()
        phone.emit(0, "hearing", {"text": "Yes."})
        page.wait_for_timeout(450)
        page.mouse.up()
        phone.emit(0, "said", {"text": "Yes."})
        phone.wait_status(taken)
        assert "Saved at" not in phone.status()
        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()


def test_once_the_notes_are_handed_over_the_call_hangs_up_and_the_screen_may_sleep():
    """Finding: after Make, the muted Live call (billed by the minute) and the wake lock
    stayed on through thinking and rendering, up to the 12 h worker wait."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    reading = "Reading your 2 notes on the subscription"
    with sync_playwright() as pw:
        browser, page, errors = _bar_page(pw, BASE, before="window.__openOpts = { hangUpWaitMs: 2000 };")
        phone = Phone(page)
        phone.emit(0, "ear", {"open": True})
        phone.wait_status("Pause where something is wrong")
        assert page.evaluate("() => window.__wake.requested") == ["screen"]

        # His spoken yes made it: the editor says so out loud, and the call ends after that.
        page.evaluate("(p) => { window.__payload = p; return window.talk.refresh(); }",
                      dict(BASE, state="thinking", result={"status": reading}))
        phone.emit(0, "partial", {"text": "Making the new version from your two notes now"})
        page.wait_for_timeout(1_000)
        assert phone.voice()[0]["stopped"] is False, "never cut off mid-sentence"
        page.wait_for_function("() => window.__voice.starts[0].stopped === true", timeout=6_000)
        assert page.evaluate("() => window.__wake.released") == 1
        assert phone.status() == reading, "the bar still follows the batch"
        assert page.locator(".tv-hold").is_disabled()

        # Handed back (nothing changed): the next hold starts a fresh call, and the screen stays on.
        handed = "Jennifer could not read the notes, so nothing was changed. Make the new version again."
        page.evaluate("(p) => { window.__payload = p; return window.talk.refresh(); }",
                      dict(BASE, state="open", result={"status": handed}))
        phone.wait_status(handed)
        assert page.locator(".tv-hold").is_enabled()
        page.wait_for_function("() => window.__wake.requested.length === 2")
        page.mouse.move(*phone.hold_point())
        page.mouse.down()
        page.wait_for_function("() => window.__voice.starts.length === 2")
        page.wait_for_timeout(400)
        page.mouse.up()
        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()

        # A sheet opened on notes already being made starts no call and holds no wake lock.
        browser, page, errors = _bar_page(pw, dict(BASE, state="thinking", result={"status": reading}), call=False)
        phone = Phone(page)
        phone.wait_status(reading)
        page.wait_for_timeout(800)
        assert page.evaluate("() => window.__voice ? window.__voice.starts.length : 0") == 0
        assert page.evaluate("() => window.__wake.requested") == []
        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()


def test_notes_another_screen_closed_open_again_with_a_hold():
    """Finding 4: the desk closed the notes the phone was using; the phone's hold was
    refused and his words went nowhere. A hold opens them again (the pin does it)."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, errors = _bar_page(pw, BASE)
        phone = Phone(page)
        phone.emit(0, "ear", {"open": True})
        page.evaluate("(p) => { window.__payload = p; return window.talk.refresh(); }", dict(BASE, state="closed"))
        phone.wait_status("closed on another screen")
        assert page.locator(".tv-hold").is_enabled()
        page.mouse.move(*phone.hold_point())
        page.mouse.down()
        page.wait_for_function("() => window.__posts === 1")
        phone.wait_status("Listening at 0:00")
        page.mouse.up()
        page.evaluate("() => window.talk.close()")
        assert errors == [], errors
        browser.close()
