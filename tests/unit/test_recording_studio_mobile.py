"""Phone-width recorder walk-through with a fake camera: the hook chooser. Synthetic data.

Boots the real recorder pages plus the production and editorial routers on a
throwaway SQLite file, then drives headless Chromium at 390x844 with Chromium's
fake media devices. Asserts the chooser layout at phone width (no horizontal
overflow, tap targets), that choosing the second opening calls choose-hook and
rebinds the studio to the new packet version with the chosen opening as the
first spoken phrase, and that a take set with a clip locks the opening.

Skipped when Playwright or its Chromium build is not installed. Nothing here
calls a paid service or a real database.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tce.api import dashboard
from tce.api.routers import content_runs as content_runs_router
from tce.api.routers import editorial as editorial_router
from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.editorial.lineup import week_start_for
from tce.models.editorial import RecordingPacket, TopicCandidate
from tce.models.editorial_workspace import WeeklyLineup, WeeklyLineupItem
from tce.settings import settings
from tests.editorial_db import create_tables
from tests.unit.test_editorial_packets import good_output

pytest.importorskip("playwright.sync_api")

KEY = "mobile-chooser-" + uuid.uuid4().hex
WS = uuid.UUID("beefbeef-1111-4111-8111-111111111111")
PHONE = {"width": 390, "height": 844}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _seed(sessionmaker) -> dict:
    output = good_output()
    cand = TopicCandidate(
        id=uuid.uuid4(),
        workspace_id=WS,
        week_start=datetime(2026, 9, 14),
        moment_ids=["11111111-1111-1111-1111-111111111111"],
        title="Plan the course from the problems",
        lesson="Start from what the person can do afterward.",
        audience="coaches",
        public_angle="The outline question.",
        gates={},
        status="selected",
    )
    packet = RecordingPacket(
        id=uuid.uuid4(),
        workspace_id=WS,
        candidate_id=cand.id,
        version=1,
        bullets=output["bullets"],
        script_phrases=output["script_phrases"],
        facebook_post=output["facebook_post"],
        linkedin_post=output["linkedin_post"],
        interviewer_prompt=output["interviewer_prompt"],
        hook_options=output["hook_options"],
        selected_hook_id=output["selected_hook_id"],
        beats=output["beats"],
        citations_private=[],
        public_safety={"status": "clean", "issues": []},
        status="ready",
    )
    async with sessionmaker() as s:
        s.add_all([cand, packet])
        # The studio lists this week's lineup, so a recordable idea lives in it.
        lineup = WeeklyLineup(id=uuid.uuid4(), workspace_id=WS, week_start=week_start_for(None))
        s.add(lineup)
        await s.flush()
        s.add(WeeklyLineupItem(
            id=uuid.uuid4(), workspace_id=WS, lineup_id=lineup.id, candidate_id=cand.id,
            rank=1, slot="primary", lane="other",
        ))
        await s.commit()
    return {
        "candidate_id": str(cand.id),
        "packet_id": str(packet.id),
        "hooks": output["hook_options"],
    }


@pytest.fixture
def studio(monkeypatch, tmp_path):
    """The recorder served at http://127.0.0.1:<port>/ behind a fake authenticating proxy."""
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(WS))
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path / "rec"))
    monkeypatch.setattr(settings, "production_google_export", "off")

    db_path = (tmp_path / "studio.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def prepare():
        await create_tables(engine)
        return await _seed(sessionmaker)

    seeded = asyncio.run(prepare())
    monkeypatch.setattr(prod, "session_factory", lambda: sessionmaker)

    app = FastAPI()
    app.include_router(dashboard.router)
    app.include_router(prod.router, prefix="/api/v1")
    app.include_router(editorial_router.router, prefix="/api/v1")
    # The page asks whether a worker is running before he presses anything, so the
    # harness serves that route too rather than letting it 404 into the console.
    app.include_router(content_runs_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sessionmaker

    async def _db():
        async with sessionmaker() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db

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
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("recorder server did not start")
    try:
        yield {"base": f"http://127.0.0.1:{port}", **seeded}
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        asyncio.run(engine.dispose())


LAYOUT_JS = """
() => {
  const vw = window.innerWidth;
  const cards = [...document.querySelectorAll('#hookView .hook-option')];
  const buttons = [...document.querySelectorAll('#hookView .hook-use')];
  const rect = (el) => el.getBoundingClientRect();
  return {
    overflowX: document.documentElement.scrollWidth > vw + 1,
    cardCount: cards.length,
    cardsStacked: cards.every((c, i) => i === 0 || rect(c).top >= rect(cards[i - 1]).bottom - 1),
    cardsFit: cards.every((c) => rect(c).left >= 0 && rect(c).right <= vw + 1),
    smallTargets: buttons.filter((b) => rect(b).height < 44).length,
    firstRank: cards[0]?.querySelector('.hook-rank')?.textContent,
    rationales: cards.map((c) => c.querySelector('.hook-why')?.textContent || ''),
  };
}
"""


def test_phone_hook_chooser_selects_a_new_version_and_locks_after_a_clip(studio, tmp_path):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    hooks = studio["hooks"]
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                headless=True,
                args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
            )
        except PlaywrightError as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Chromium is not installed for Playwright: {exc}")
        context = browser.new_context(
            viewport=PHONE,
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            permissions=["camera", "microphone"],
        )
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(f"{studio['base']}/record")
        page.wait_for_selector(".idea-card")
        page.click(".idea-card")

        # Choosing the opening is its own step now, before the studio opens.
        chooser = page.locator("#hookView")
        chooser.wait_for(state="visible")
        layout = page.evaluate(LAYOUT_JS)
        assert layout["overflowX"] is False, layout
        assert layout["cardCount"] == 3
        assert layout["cardsStacked"] and layout["cardsFit"], layout
        assert layout["smallTargets"] == 0, layout
        assert (
            layout["firstRank"].startswith("Recommended")
            and "current opening" in layout["firstRank"]
        )
        assert all(r.startswith("Why (private):") for r in layout["rationales"]), layout
        # The studio is not reached until the opening is chosen.
        assert page.locator("#studioView").is_hidden()
        page.screenshot(path=str(tmp_path / "hook-chooser-phone.png"))

        with page.expect_response(
            lambda r: "/choose-hook" in r.url and r.request.method == "POST"
        ) as chosen:
            page.locator("#hookView .hook-option").nth(1).locator(".hook-use").click()
        assert chosen.value.status == 200
        chooser.wait_for(state="hidden")
        second_text = hooks[1]["text"]
        # ...and then the studio opens on the script, with that opening in it.
        page.wait_for_selector("#studioView:not([hidden])")
        page.click("#scriptTab")
        first_line = page.locator("#reader .reader-line").first.text_content()
        assert first_line.endswith(second_text), first_line
        page.screenshot(path=str(tmp_path / "hook-chosen-phone.png"))

        # The studio is now bound to version 2 with its own draft take set.
        queue = page.evaluate(
            "() => fetch('/api/v1/production/recording-queue').then((r) => r.json())"
        )
        idea = queue["ideas"][0]
        assert idea["packet_version"] == 2 and idea["selected_hook_id"] == hooks[1]["id"]
        assert idea["packet_id"] != studio["packet_id"]
        assert idea["active_session_status"] == "draft"

        # A clip binds that take set; reopening the idea offers no chooser and says why.
        clip = page.evaluate(
            """(sid) => fetch(`/api/v1/production/recording-sessions/${sid}/clips`, {
                 method: 'POST', headers: {'Content-Type': 'application/json'},
                 body: JSON.stringify({local_clip_id: crypto.randomUUID(),
                                       mime_type: 'video/webm', extension: 'webm'}),
               }).then((r) => r.status)""",
            idea["active_session_id"],
        )
        assert clip == 201
        page.click("#homeButton")
        page.wait_for_selector(".idea-card")
        page.click(".idea-card")
        # A bound take set skips the opening step entirely and says why in the studio.
        page.wait_for_selector("#hookPanel .hook-lock")
        assert page.locator("#hookView").is_hidden()
        assert page.locator("#hookChooser").is_hidden()
        lock = page.locator("#hookPanel .hook-lock").text_content()
        assert "locked" in lock and "v2" in lock, lock
        refused = page.evaluate(
            """(pid) => fetch(`/api/v1/editorial/packets/${pid}/choose-hook`, {
                 method: 'POST', headers: {'Content-Type': 'application/json'},
                 body: JSON.stringify({hook_id: 'hook-3'}),
               }).then((r) => r.status)""",
            idea["packet_id"],
        )
        assert refused == 409
        page.screenshot(path=str(tmp_path / "hook-locked-phone.png"))
        browser.close()

    # The deliberate refused probe above logs one 409 in the console; nothing else may.
    unexpected = [e for e in errors if "409" not in e]
    assert not unexpected, unexpected
    Path(tmp_path / "hook-chooser-report.json").write_text(json.dumps(layout, indent=2))


def test_a_landscape_camera_is_previewed_and_recorded_as_a_vertical_video(studio, tmp_path):
    """Chromium's fake camera is landscape, which is exactly what Ziv's Android
    Chrome handed back on 22-Sep: every clip came out 2288x1288 and cut off the
    top of his head. What the preview shows must be what the recorder gets."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                headless=True,
                args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
            )
        except PlaywrightError as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Chromium is not installed for Playwright: {exc}")
        context = browser.new_context(
            viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True,
            permissions=["camera", "microphone"],
        )
        page = context.new_page()
        # Chromium's fake camera is portrait inside a phone context, which is the
        # case that always worked. Android Chrome hands back a LANDSCAPE camera on
        # a portrait phone, so the test has to hand the page one too, or it proves
        # nothing: this version of the test passed against the unfixed code.
        page.add_init_script(
            """
            const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            navigator.mediaDevices.getUserMedia = async (constraints) => {
              const stream = await real(constraints);
              const canvas = document.createElement('canvas');
              canvas.width = 1280; canvas.height = 720;
              const context2d = canvas.getContext('2d');
              const paint = () => {
                context2d.fillStyle = '#123'; context2d.fillRect(0, 0, 1280, 720);
                requestAnimationFrame(paint);
              };
              paint();
              const landscape = canvas.captureStream(30);
              stream.getAudioTracks().forEach((track) => landscape.addTrack(track));
              return landscape;
            };
            """
        )
        page.goto(f"{studio['base']}/record")
        page.wait_for_selector(".idea-card")
        page.click(".idea-card")
        page.locator("#hookView .hook-option").first.locator(".hook-use").click()
        page.wait_for_selector("#studioView:not([hidden])")

        shapes = page.wait_for_function(
            """() => {
                 const preview = document.getElementById('camera').srcObject;
                 const track = preview && preview.getVideoTracks()[0];
                 const settings = track && track.getSettings();
                 if (!settings || !settings.width) return null;
                 return {preview: [settings.width, settings.height],
                         audio: preview.getAudioTracks().length};
               }""",
            timeout=20000,
        ).json_value()

        width, height = shapes["preview"]
        assert height > width, f"the preview is still landscape: {width}x{height}"
        assert abs(width / height - 9 / 16) < 0.02, f"{width}x{height} is not 9:16"
        assert shapes["audio"] == 1, "the cropped stream lost the microphone"
        page.screenshot(path=str(tmp_path / "studio-portrait.png"))
        context.close()
        browser.close()
