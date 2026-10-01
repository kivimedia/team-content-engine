"""Talk to the editor, step 5 (1-Oct): the notes sheet in the Library, at phone width.

Boots the real workspace shell, the Library and the talk routes on a throwaway SQLite
file behind a fake authenticating proxy, and drives headless Chromium at 390x844. KM
BOT's /voice-client.js is the stub from test_talk_voice_phone.py, which records what
the sheet asks of the call and lets the test play its events. The batch is the real
run_talk_session with the subscription call (_ask) and the ffmpeg render (_run_render)
replaced, as in test_talk_batch.py; the sitting, the notes, the plan and the settle are
the real code.

Asserts, each one a sentence in plans/30-Sep-26-talk-to-the-editor.md (sections 1, 7):
- the card offers "Talk to the editor", which opens /library/<id>/talk: a full screen
  sheet with the video (playsinline, no native fullscreen, no picture in picture, the
  render's own ?v=), the notes, and the bar with the 72px Hold to talk button and Make
  the new version; nothing in it overlaps and nothing scrolls sideways;
- the call starts when the sheet opens: the tce seat, video:<id>, muted, no greeting;
- drawing the page again never takes the player away mid-sitting;
- hold to talk pins the paused second and saves his words on that note;
- a typed note is pinned to the second the player is paused on;
- Make the new version reads the notes back, sends the read-back's check code, shows
  the batch's live step, renders once, and then each note says what was done;
- closing keeps the notes (the close route leaves a sitting with notes open), the card
  says "1 note waiting - Make the new version", and opening it again finds them;
- a request typed on the card does not stop a video playing in that card.

Skipped when Playwright, its Chromium build or ffmpeg is missing. Nothing here calls a
paid service or a real database.
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
from fastapi.responses import FileResponse, Response
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tce.api import dashboard
from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.api.routers import production as prod
from tce.llm import LLMUnavailable
from tce.llm.provider import LLMResult
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.production.retakes import frame_keep
from tce.settings import settings
from tests.editorial_db import create_tables
from tests.unit.test_talk_voice_phone import FAKE_VOICE, VOICE_STATE, WAKE_STUB

API_DIR = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
KEY = "talk-sheet-" + uuid.uuid4().hex
WS = uuid.UUID("beefbeef-5555-4555-8555-555555555555")
PHONE = {"width": 390, "height": 844}
TITLE = "Call them after the service"
SEED_REF = "0000seedrender00"
NEW_REF = "1111newrender111"
ASK_S = 3.0     # the editor reads this long: the bar shows the batch's own step meanwhile
RENDER_S = 4.0  # the render runs this long: the bar shows the upload's live step meanwhile
# 0 Getting 1 them 2 back 3 is 4 really 5 smart. 6 Not 7 after 8 you've 9 finished
# 10 your 11 service. 12 Call 13 them.
SPOKEN = "Getting them back is really smart. Not after you've finished your service. Call them."
SAID = "Take out the not, it should read after you have finished"
TYPED = "Keep the pause after service"


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


async def _seed(sm, clip: Path, tmp_path: Path) -> uuid.UUID:
    """An edited, stamped video whose plan is the real one. The recording file does not
    exist (no audio is read); the edit plays the test clip."""
    w = _words(SPOKEN)
    async with sm() as s:
        cand = TopicCandidate(
            workspace_id=WS, week_start=datetime(2026, 9, 28), moment_ids=["m"],
            title=TITLE, lesson="l", audience="a", public_angle="p", gates={}, status="recorded",
        )
        s.add(cand)
        await s.flush()
        up = RecordingUpload(
            workspace_id=WS, candidate_id=cand.id, original_filename="walk.mp4",
            storage_path=str(tmp_path / "missing-walk.mp4"), sha256=uuid.uuid4().hex * 2,
            status="transcribed", transcript=w, duration_s=w[-1]["end_s"] + 0.5,
        )
        s.add(up)
        await s.commit()
        await prod._compute_plan(s, WS, up)
        assert up.status == "planned", up.status_detail
        up.status, up.edited_path = "edited", str(clip)
        up.rendered_keep = frame_keep(up.edit_plan["keep"])
        up.render_ref = SEED_REF
        await s.commit()
        return up.id


@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> Path:
    """Eight seconds of a plain frame, VP8: Playwright's Chromium has no H.264."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is not installed")
    out = tmp_path_factory.mktemp("sheetclip") / "clip.webm"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=0x10213b:s=180x320:r=10:d=8", "-c:v", "libvpx", "-b:v", "60k", "-y", str(out)],
        check=True, timeout=120,
    )
    return out


@pytest.fixture
def host(monkeypatch, tmp_path, clip):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(WS))

    async def enabled() -> bool:
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)

    db_path = (tmp_path / "sheet.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(prod, "session_factory", lambda: sessionmaker)
    monkeypatch.setattr(prod, "TALK_WORKER_RETRY_S", 0.0)

    asked: list[dict] = []
    answers: list = []
    renders: list = []
    requests_started: list = []

    async def fake_ask(kind, prompt, system, schema, ws, key, **opts):
        asked.append({"kind": kind, "prompt": prompt, "key": key})
        await asyncio.sleep(ASK_S)
        answer = answers.pop(0) if answers else LLMUnavailable("failed", "no answer in this test")
        if isinstance(answer, BaseException):
            raise answer
        return LLMResult(job_id=uuid.uuid4(), text="", structured=answer, model="claude-opus-5-5")

    async def fake_render(upload_id, ws, attempt, mode):
        renders.append(upload_id)
        await asyncio.sleep(RENDER_S)
        async with sessionmaker() as s:
            row = await prod._load(s, upload_id, ws)
            row.status = "edited"
            row.edited_path = str(clip)
            row.rendered_keep = frame_keep(row.edit_plan["keep"])
            row.render_ref = NEW_REF
            row.status_detail = f"Captioned MP4 ready: {len(row.edit_plan['keep'])} ranges"
            row.job_ids = prod._with_lease(row.job_ids, None)
            await s.commit()

    monkeypatch.setattr(prod, "_ask", fake_ask)
    monkeypatch.setattr(prod, "_run_render", fake_render)
    # A request typed on the card runs on its own: only that it was started is recorded.
    monkeypatch.setattr(prod, "start_edit_request", lambda rid, ws, **_k: requests_started.append(rid))

    async def prepare():
        await create_tables(engine)
        return await _seed(sessionmaker, clip, tmp_path)

    upload_id = asyncio.run(prepare())

    app = FastAPI()
    app.include_router(dashboard.router)
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(workspace_router.production_router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sessionmaker
    # /library/<id>/talk is dashboard.py's own route (1-Oct final review): a reload of
    # the sheet, a restored tab or a pasted link reach the shell, never a 404.

    @app.get("/voice-client.js")
    async def voice_client():
        return Response(FAKE_VOICE, media_type="application/javascript")

    @app.get("/api/v1/production/uploads/{upload}/edited")
    async def edited(upload: str):
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
        raise RuntimeError("sheet host did not start")
    try:
        yield {
            "base": f"http://127.0.0.1:{port}",
            "upload": str(upload_id),
            "asked": asked,
            "answers": answers,
            "renders": renders,
            "requests_started": requests_started,
            "sm": sessionmaker,
        }
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        asyncio.run(engine.dispose())


# ----------------------------------------------------------------- helpers


SHEET_LAYOUT_JS = """() => {
  const box = (sel) => {
    const e = document.querySelector(sel);
    if (!e) return null;
    const b = e.getBoundingClientRect();
    return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, height: b.height, width: b.width };
  };
  const parts = {
    head: box('#notesSheet .sheet-head'), video: box('.ns-player'), notes: box('.ns-notes'),
    foot: box('#notesFoot'), status: box('.tv-status'), slot: box('.tv-slot'), hold: box('.tv-hold'),
    make: box('.ns-make-row'),
  };
  const overlaps = [];
  const stack = (names) => {
    for (let i = 0; i < names.length - 1; i++) {
      const a = parts[names[i]], b = parts[names[i + 1]];
      if (!a || !b || a.bottom > b.top + 0.5) overlaps.push(names[i] + '/' + names[i + 1]);
    }
  };
  stack(['head', 'video', 'notes', 'foot']);
  stack(['status', 'slot', 'hold', 'make']);
  const buttons = [...document.querySelectorAll('#notesFoot button, #notesSheet .sheet-head button')]
    .map((b) => b.getBoundingClientRect())
    .filter((r) => r.width > 0);
  const vw = window.innerWidth;
  return {
    vw, vh: window.innerHeight, parts, overlaps,
    outside: Object.entries(parts).filter(([, p]) => p && (p.left < -0.5 || p.right > vw + 0.5)).map(([k]) => k),
    smallButtons: buttons.filter((r) => r.height < 44).length,
    overflowX: document.documentElement.scrollWidth > vw + 1,
    sheetCovers: (() => { const s = box('#notesSheet'); return s.top <= 0 && s.bottom >= window.innerHeight - 0.5; })(),
  };
}"""

# Whether the top of an element is inside the visible part of the notes strip.
IN_NOTES_JS = """(sel) => {
  const region = document.querySelector('.ns-notes').getBoundingClientRect();
  const el = document.querySelector(sel);
  if (!el) return false;
  const r = el.getBoundingClientRect();
  return r.top >= region.top - 0.5 && r.top < region.bottom - 10;
}"""

VIDEO_JS = """() => {
  const v = document.querySelector('.ns-player');
  return v && { src: v.getAttribute('src'), playsinline: v.hasAttribute('playsinline'),
    controlslist: v.getAttribute('controlslist'), pip: v.disablePictureInPicture,
    controls: v.controls, paused: v.paused, t: v.currentTime, mark: v.__mark || null };
}"""


class Phone:
    def __init__(self, page):
        self.page = page

    def voice(self) -> list[dict]:
        return self.page.evaluate(VOICE_STATE)

    def emit(self, index: int, kind: str, data: dict | None = None) -> None:
        self.page.evaluate("([i, t, d]) => window.__voice.starts[i].emit(t, d)", [index, kind, data or {}])

    def wait_status(self, text: str, timeout: float = 20_000) -> None:
        self.page.wait_for_function(
            "(s) => ((document.querySelector('.tv-status') || {}).textContent || '').includes(s)",
            arg=text, timeout=timeout,
        )

    def video(self, expr: str):
        return self.page.evaluate(f"() => {{ const v = document.querySelector('.ns-player'); return {expr}; }}")

    def wait_row(self, text: str, timeout: float = 15_000) -> None:
        self.page.wait_for_function(
            "(s) => [...document.querySelectorAll('.ns-list .tv-note')].some((li) => li.textContent.includes(s))",
            arg=text, timeout=timeout,
        )

    def row(self, text: str):
        return self.page.locator(".ns-list .tv-note", has_text=text)

    def hold_point(self) -> tuple[float, float]:
        box = self.page.locator(".tv-hold").bounding_box()
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    def seek_and_pause(self, t: float) -> None:
        self.page.evaluate(
            """(t) => new Promise((done) => {
                 const v = document.querySelector('.ns-player');
                 v.pause();
                 v.addEventListener('seeked', () => done(), { once: true });
                 v.currentTime = t;
               })""",
            t,
        )


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


def _pinned(response) -> bool:
    return response.url.endswith("/notes") and response.request.method == "POST"


def _patched(response) -> bool:
    return "/notes/" in response.url and response.request.method == "PATCH"


def _opened(response) -> bool:
    return response.url.endswith("/talk") and response.request.method == "POST"


def _closed(response) -> bool:
    return response.url.endswith("/close") and response.request.method == "POST"


def _shots(tmp_path: Path) -> Path:
    shots = Path(os.environ.get("TCE_TEST_SHOTS") or tmp_path)
    shots.mkdir(parents=True, exist_ok=True)
    return shots


def _type_note(page, phone: Phone, at: float, text: str) -> dict:
    """Pause at `at`, tap Type, write, save. Returns the pin's request body."""
    phone.seek_and_pause(at)
    page.locator("[data-ns-type]").click()
    page.wait_for_selector("#nsTyped")
    label = page.locator(".ns-typed-label").inner_text()
    whole = int(at)
    assert label == f"Your note at {whole // 60}:{whole % 60:02d}", label
    page.fill("#nsTyped", text)
    with page.expect_response(_patched) as words:
        with page.expect_response(_pinned) as pinned:
            page.locator("[data-ns-save]").click()
    assert pinned.value.status == 200, pinned.value.text()
    assert words.value.status == 200, words.value.text()
    assert words.value.request.post_data_json == {"heard": text}
    phone.wait_row(text)
    assert page.locator(".ns-typed").is_hidden()
    return pinned.value.request.post_data_json


# ------------------------------------------------------------------- the card


def test_the_card_offers_talk_to_the_editor_only_where_there_is_an_edit():
    from tce.editorial import library

    def keys(**fields) -> list[str]:
        upload = RecordingUpload(
            workspace_id=WS, original_filename="take.mp4", storage_path="/tmp/take.mp4",
            sha256="c" * 64, status=fields.pop("status", "edited"), **fields,
        )
        return [a["key"] for a in library._actions(upload, 0)]

    edited = keys(edited_path="/tmp/take-edit.mp4", transcript=_words(SPOKEN))
    assert "talk_edit" in edited
    # Right after watching it, before the older typed request.
    assert edited.index("talk_edit") < edited.index("request_edit")
    assert "talk_edit" not in keys(status="uploaded")


# ------------------------------------------------------------------- walks


def test_the_notes_sheet_from_the_card_to_one_new_version(host, tmp_path):
    from playwright.sync_api import sync_playwright

    shots = _shots(tmp_path)
    uid = host["upload"]
    with sync_playwright() as pw:
        browser = _launch(pw)
        page, errors = _phone(browser)
        phone = Phone(page)

        # ---- the card offers it, and nothing waits yet
        page.goto(f"{host['base']}/library")
        card = page.locator("article.card", has_text=TITLE)
        card.wait_for()
        talk = card.locator("button[data-talk-edit]", has_text="Talk to the editor")
        assert talk.count() == 1
        assert card.locator(".waiting-notes").count() == 0

        # ---- its own address, a full screen sheet, the call started muted and silent
        with page.expect_response(_opened) as opened:
            talk.click()
        sitting = opened.value.json()
        sid = sitting["session_id"]
        page.wait_for_function("(p) => window.location.pathname === p", arg=f"/library/{uid}/talk")
        page.wait_for_selector("#notesSheet:not([hidden]) video.ns-player")
        assert page.locator("#notesContext").inner_text() == TITLE
        video = page.evaluate(VIDEO_JS)
        assert video["src"] == f"/api/v1/production/uploads/{uid}/edited?v={SEED_REF}", video
        assert video["playsinline"] and video["controls"] and video["pip"] is True, video
        assert video["controlslist"] == "nofullscreen", video
        page.wait_for_function("() => window.__voice && window.__voice.starts.length === 1")
        call = phone.voice()[0]
        assert call["opts"] == {
            "seat": "tce", "context": f"video:{uid}", "api": "live", "greet": False, "startMuted": True,
        }
        assert page.evaluate("() => window.__wake.requested") == ["screen"]
        page.wait_for_function("() => document.querySelector('.ns-player').readyState >= 1")
        phone.emit(0, "ear", {"open": True})
        phone.wait_status("Pause where something is wrong, then hold to talk.")
        make = page.locator("[data-ns-make]")
        assert make.inner_text() == "Make the new version (no notes yet)" and make.is_disabled()

        # ---- nothing overlaps at 390 px, and the video has most of the screen
        layout = page.evaluate(SHEET_LAYOUT_JS)
        assert layout["overlaps"] == [], layout
        assert layout["outside"] == [] and layout["overflowX"] is False, layout
        assert layout["sheetCovers"] is True, layout
        assert layout["smallButtons"] == 0, layout
        parts = layout["parts"]
        assert parts["hold"]["height"] >= 72, layout
        assert parts["foot"]["bottom"] <= layout["vh"] + 0.5, layout
        assert parts["notes"]["height"] >= 119, layout
        # About 55dvh where the screen allows; at 390x844 the bar and a strip of notes need the rest.
        assert 0.4 * layout["vh"] <= parts["video"]["height"] <= 0.55 * layout["vh"] + 1, layout
        page.screenshot(path=str(shots / "talk-sheet-open-phone.png"))

        # ---- drawing the page again never takes the player away mid-sitting
        phone.video("v.play()")
        page.wait_for_function("() => document.querySelector('.ns-player').currentTime > 1.2")
        page.evaluate(
            "() => { document.querySelector('.ns-player').__mark = 'the same player';"
            " document.getElementById('talkHeader').href = '/before-render'; }"
        )
        page.evaluate("() => window.dispatchEvent(new PopStateEvent('popstate'))")
        # render() ran: it set the header microphone again.
        page.wait_for_function("() => !document.getElementById('talkHeader').href.endsWith('/before-render')")
        page.wait_for_timeout(400)
        after = page.evaluate(VIDEO_JS)
        assert after["mark"] == "the same player", after
        assert after["paused"] is False and after["t"] > 1.2, after
        assert after["src"] == video["src"], after
        assert page.locator("#notesSheet").is_visible()
        assert len(phone.voice()) == 1, "drawing the page again must not start another call"

        # ---- hold to talk: the paused second is pinned, his words are saved on it
        x, y = phone.hold_point()
        page.mouse.move(x, y)
        with page.expect_response(_pinned) as pinned:
            page.mouse.down()
        pin = pinned.value.json()
        assert pinned.value.status == 200
        assert phone.video("v.paused") is True
        assert abs(pin["edit_s"] - phone.video("v.currentTime")) < 0.1
        assert pinned.value.request.post_data_json["render_ref"] == SEED_REF
        phone.wait_status(f"Listening at {pin['clock']}")
        assert phone.voice()[0]["muted"] is False
        phone.emit(0, "hearing", {"text": SAID})
        page.wait_for_timeout(400)
        with page.expect_response(_patched) as heard:
            page.mouse.up()
            phone.wait_status(f"Finishing what you said at {pin['clock']}")
            phone.emit(0, "said", {"text": SAID})
        assert heard.value.request.post_data_json == {"heard": SAID}
        phone.wait_row(SAID)
        assert phone.row(SAID).locator(".tv-when").inner_text() == pin["clock"]
        page.wait_for_function(
            "() => document.querySelector('[data-ns-make]').textContent === 'Make the new version (1 note)'"
        )

        # ---- typing still works: a typed note is pinned to the paused second
        typed = _type_note(page, phone, 4.3, TYPED)
        assert abs(typed["edit_s"] - 4.3) < 0.05 and typed["render_ref"] == SEED_REF, typed
        assert phone.row(TYPED).locator(".tv-when").inner_text() == "0:04"
        page.wait_for_function(
            "() => document.querySelector('[data-ns-make]').textContent === 'Make the new version (2 notes)'"
        )
        page.screenshot(path=str(shots / "talk-sheet-two-notes-phone.png"))

        # ---- Make the new version: the read-back, his yes with its check code, one render
        host["answers"].append({
            "summary": "Took out the 'Not'; the pause after service stays.",
            "notes": [
                {"note": 1, "reply": "Removed the 'Not'.", "needs_you": False, "question": "",
                 "corrections": [{"first": 6, "last": 7, "heard": "Not after", "replacement": "After",
                                  "why": "his note"}],
                 "cut": [], "restore": [], "hold": []},
                {"note": 2, "reply": "The pause after service stays as it is.", "needs_you": False,
                 "question": "", "corrections": [], "cut": [], "restore": [], "hold": []},
            ],
        })
        with page.expect_response(
            lambda r: r.url.endswith(f"/talk/{sid}/submit") and r.request.method == "GET"
        ) as asked:
            page.locator("[data-ns-make]").click()
        preview = asked.value.json()
        assert preview["count"] == 2 and preview["read_back"].startswith("2 notes: at "), preview
        page.wait_for_selector(".ns-readback:not([hidden])")
        assert preview["read_back"] in page.locator(".ns-readback").inner_text()
        # The read-back is in sight, not under an older sentence.
        assert page.evaluate(IN_NOTES_JS, ".ns-readback h3") is True
        assert page.locator(".ns-message").is_hidden()
        confirm = page.locator("[data-ns-confirm]")
        assert confirm.inner_text() == "Yes, make it (2 notes)"
        assert host["asked"] == [] and host["renders"] == [], "nothing is made before his yes"
        layout = page.evaluate(SHEET_LAYOUT_JS)
        assert layout["overlaps"] == [] and layout["overflowX"] is False, layout
        page.screenshot(path=str(shots / "talk-sheet-read-back-phone.png"))
        with page.expect_response(
            lambda r: r.url.endswith(f"/talk/{sid}/submit") and r.request.method == "POST"
        ) as made:
            confirm.click()
        assert made.value.status == 200, made.value.text()
        assert made.value.request.post_data_json["check"] == preview["check"]
        # 1-Oct final review: nothing can be said to the editor while the notes are
        # made, so the call (billed by the minute) ends and the screen may sleep.
        page.wait_for_function("() => window.__voice.starts[0].stopped === true", timeout=3_000)
        assert page.evaluate("() => window.__wake.released") == 1

        # The live step, never a bare spinner: the batch's own, then the render's.
        phone.wait_status("Reading your 2 notes on the subscription")
        page.wait_for_function(
            "() => document.querySelector('.ns-make-row button').textContent === 'Making the new version (2 notes)'"
        )
        page.screenshot(path=str(shots / "talk-sheet-making-phone.png"))
        phone.wait_status("Cutting and burning in your captions")
        phone.wait_status("New version made from your 2 notes.", timeout=30_000)

        # Each note says what was done, and the player has the new version.
        phone.wait_row("Removed the 'Not'.")
        phone.wait_row("The pause after service stays as it is.")
        page.wait_for_function("(ref) => document.querySelector('.ns-player').getAttribute('src').endsWith('v=' + ref)",
                               arg=NEW_REF)
        assert page.locator("[data-ns-again]").inner_text() == "Give notes on the new version"
        # The notes strip starts at the first note, with what was done with it.
        assert page.evaluate(IN_NOTES_JS, ".ns-list .tv-note") is True
        assert page.locator(".ns-list .tv-note").first.locator(".tv-answer").inner_text() == "Removed the 'Not'."
        assert len(host["asked"]) == 1 and len(host["renders"]) == 1
        layout = page.evaluate(SHEET_LAYOUT_JS)
        assert layout["overlaps"] == [] and layout["overflowX"] is False, layout
        page.screenshot(path=str(shots / "talk-sheet-made-phone.png"))

        # ---- the card says what was made, note by note
        lib = page.evaluate("async () => (await fetch('/api/v1/production/library?filter=all')).json()")
        item = [i for i in lib["items"] if i["upload_id"] == uid][0]
        assert item["waiting_notes"] == 0
        made_json = item["notes_made"]
        assert made_json["session_id"] == sid and made_json["state"] == "done"
        assert [n["reply"] for n in made_json["notes"]] == [
            "Removed the 'Not'.", "The pause after service stays as it is.",
        ]
        assert [n["said"] for n in made_json["notes"]] == [SAID, TYPED]

        # ---- more notes on the new version: a fresh sitting on it, and a fresh call
        with page.expect_response(_opened) as fresh:
            page.locator("[data-ns-again]").click()
        again = fresh.value.json()
        assert again["session_id"] != sid and again["render_ref"] == NEW_REF and again["state"] == "open"
        page.wait_for_function("() => window.__voice.starts.length === 2")
        assert phone.voice()[0]["stopped"] is True
        page.wait_for_function(
            "() => (document.querySelector('[data-ns-make]') || {}).textContent === 'Make the new version (no notes yet)'"
        )
        assert page.locator(".ns-list .tv-empty").count() == 1

        assert errors == [], errors
        browser.close()


def test_closing_keeps_the_notes_and_the_card_says_they_wait(host, tmp_path):
    from playwright.sync_api import sync_playwright

    shots = _shots(tmp_path)
    uid = host["upload"]
    with sync_playwright() as pw:
        browser = _launch(pw)
        page, errors = _phone(browser)
        phone = Phone(page)

        # ---- a request typed on the card does not stop the video playing in that card
        page.goto(f"{host['base']}/library")
        card = page.locator("article.card", has_text=TITLE)
        card.wait_for()
        card.locator("[data-watch]").first.click()
        page.wait_for_selector("article.card .player video")
        page.evaluate("() => document.querySelector('.player video').play()")
        page.wait_for_function("() => document.querySelector('.player video').currentTime > 0.6")
        page.evaluate("() => { document.querySelector('.player video').__mark = 'the same player'; }")
        page.once("dialog", lambda dialog: dialog.accept("Make the captions bigger"))
        with page.expect_response(
            lambda r: r.url.endswith("/edit-requests") and r.request.method == "POST"
        ) as typed_request:
            card.locator("[data-edit-request]").click()
        assert typed_request.value.status == 200
        page.wait_for_timeout(800)
        playing = page.evaluate(
            "() => { const v = document.querySelector('.player video');"
            " return v && { mark: v.__mark || null, paused: v.paused }; }"
        )
        assert playing == {"mark": "the same player", "paused": False}, playing
        assert len(host["requests_started"]) == 1
        # Put away, the card shows the request.
        card.locator("[data-watch-close]").click()
        page.wait_for_function(
            "() => [...document.querySelectorAll('article.card')].some((c) => c.textContent.includes('you asked: Make the captions bigger'))"
        )

        # ---- straight to the sheet's address: the Library is drawn under it
        with page.expect_response(_opened) as opened:
            page.goto(f"{host['base']}/library/{uid}/talk")
        sid = opened.value.json()["session_id"]
        page.wait_for_selector("#notesSheet:not([hidden]) video.ns-player")
        assert page.locator("[data-libfilter]").count() > 0
        page.wait_for_function("() => window.__voice && window.__voice.starts.length === 1")
        page.wait_for_function("() => document.querySelector('.ns-player').readyState >= 1")
        phone.emit(0, "ear", {"open": True})
        _type_note(page, phone, 2.2, TYPED)

        # ---- a reload of the sheet (pull to refresh, a restored tab) reopens the same notes
        with page.expect_response(_opened) as again:
            page.reload()
        assert again.value.json()["session_id"] == sid
        page.wait_for_selector("#notesSheet:not([hidden]) video.ns-player")
        phone.wait_row(TYPED)
        page.wait_for_function("() => window.__voice && window.__voice.starts.length === 1")
        page.wait_for_function("() => document.querySelector('.ns-player').readyState >= 1")
        phone.emit(0, "ear", {"open": True})
        assert page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1") is False

        # ---- closing keeps the note: the sitting stays open, and the card says it waits
        with page.expect_response(_closed) as closed:
            page.locator("#notesClose").click()
        assert closed.value.status == 409, closed.value.text()
        assert closed.value.json()["detail"]["code"] == "notes_waiting"
        page.wait_for_function("() => window.location.pathname === '/library'")
        assert page.locator("#notesSheet").is_hidden()
        assert phone.voice()[0]["stopped"] is True
        assert page.evaluate("() => window.__wake.released") == 1
        waiting = page.locator("article.card", has_text=TITLE).locator(".waiting-notes")
        waiting.wait_for()
        assert waiting.inner_text() == "1 note waiting - Make the new version"
        assert page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1") is False
        page.screenshot(path=str(shots / "talk-sheet-card-waiting-phone.png"))

        # ---- opening it again finds the note in the same sitting
        with page.expect_response(_opened) as reopened:
            waiting.click()
        assert reopened.value.json()["session_id"] == sid
        page.wait_for_function("(p) => window.location.pathname === p", arg=f"/library/{uid}/talk")
        phone.wait_row(TYPED)
        assert phone.row(TYPED).locator(".tv-when").inner_text() == "0:02"
        page.wait_for_function("() => window.__voice.starts.length === 2")

        # ---- taken back, nothing waits: closing closes the sitting, and Back is the Library
        phone.row(TYPED).locator(".tv-drop").click()
        page.wait_for_function("() => !document.querySelector('.ns-list .tv-note')")
        with page.expect_response(_closed) as closed_again:
            page.locator("#notesClose").click()
        assert closed_again.value.status == 200, closed_again.value.text()
        assert closed_again.value.json()["state"] == "closed"
        page.wait_for_function("() => window.location.pathname === '/library'")
        page.locator("article.card", has_text=TITLE).wait_for()
        page.wait_for_timeout(300)
        assert page.locator("article.card", has_text=TITLE).locator(".waiting-notes").count() == 0
        assert page.locator("#notesSheet").is_hidden()

        assert errors == [], errors
        browser.close()


def _block_the_edit(host) -> None:
    """What "Edit it again" leaves when the review's cut fails the meaning check: nothing
    rendered, and the stamped older edit is what he watches. Sync Playwright holds an
    event loop in this thread, so the write runs in a thread of its own."""

    async def write() -> None:
        async with host["sm"]() as s:
            row = await prod._load(s, uuid.UUID(host["upload"]), WS)
            plan = dict(row.edit_plan or {})
            plan["meaning_check"] = {"status": "blocked", "issues": [{"detail": "Dropped take at 0:03"}]}
            row.edit_plan = plan
            row.status = "needs_review"
            row.status_detail = 'Needs review: Dropped take at 0:03 says "not after"'
            await s.commit()

    worker = threading.Thread(target=lambda: asyncio.run(write()))
    worker.start()
    worker.join(timeout=30)


def test_the_sheet_says_when_an_earlier_re_edit_waits_for_his_eyes(host, tmp_path):
    """1-Oct final review: notes made while an earlier re-edit's cut waited for his eyes
    stopped on that cut and were blamed for it. The sheet says so when it opens, his
    notes are kept, and Make is refused with the same sentence before any job."""
    from playwright.sync_api import sync_playwright

    shots = _shots(tmp_path)
    uid = host["upload"]
    _block_the_edit(host)
    with sync_playwright() as pw:
        browser = _launch(pw)
        page, errors = _phone(browser)
        phone = Phone(page)
        with page.expect_response(_opened) as opened:
            page.goto(f"{host['base']}/library/{uid}/talk")
        blocked = opened.value.json()["blocked"]
        assert blocked and "waiting for your eyes" in blocked and "Dropped take at 0:03" in blocked
        message = page.locator(".ns-message")
        message.wait_for()
        assert message.inner_text() == blocked
        page.wait_for_function("() => window.__voice && window.__voice.starts.length === 1")
        page.wait_for_function("() => document.querySelector('.ns-player').readyState >= 1")
        phone.emit(0, "ear", {"open": True})
        _type_note(page, phone, 2.2, TYPED)
        with page.expect_response(lambda r: r.url.endswith("/submit") and r.request.method == "GET") as asked:
            page.locator("[data-ns-make]").click()
        assert asked.value.status == 409 and asked.value.json()["detail"]["code"] == "edit_needs_you"
        page.wait_for_function("(t) => document.querySelector('.ns-message').textContent === t", arg=blocked)
        assert "your notes would make" not in page.locator("body").inner_text().lower()
        assert host["asked"] == [] and host["renders"] == []
        layout = page.evaluate(SHEET_LAYOUT_JS)
        assert layout["overlaps"] == [] and layout["overflowX"] is False, layout
        page.screenshot(path=str(shots / "talk-sheet-edit-waits-phone.png"))
        assert errors == [], errors
        browser.close()
