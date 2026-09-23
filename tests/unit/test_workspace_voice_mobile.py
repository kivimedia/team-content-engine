"""Phone-width walk-through of the voice call entry points and "Changes by voice".

Boots the real workspace shell plus the editorial routers on a throwaway SQLite
file behind a fake authenticating proxy, seeds one change and one put-away idea
written by the voice agent, and drives headless Chromium at 390x844. Asserts:

- Talk is a link to the KM BOT call page with the right context (the week from
  Today, the topic from the topic room), and typed chat is still one tap away;
- the panel says what changed in plain words, with Undo and Restore buttons that
  are real 44px tap targets and actually undo and restore;
- nothing overflows sideways and nothing interactive overlaps;
- the dictation Speak button is gone.

Skipped when Playwright or its Chromium build is not installed. Nothing here
calls a paid service or a real database.
"""

from __future__ import annotations

import asyncio
import os
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
from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_voice as voice_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.editorial import inbox as inbox_service
from tce.editorial import voice_agent
from tce.editorial.lineup import week_start_for
from tce.models.editorial import TopicCandidate
from tce.models.editorial_workspace import WeeklyLineup, WeeklyLineupItem
from tce.settings import settings
from tests.editorial_db import create_tables

pytest.importorskip("playwright.sync_api")

KEY = "voice-phone-" + uuid.uuid4().hex
WS = uuid.UUID("beefbeef-2222-4222-8222-222222222222")
PHONE = {"width": 390, "height": 844}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _gates() -> dict:
    return {
        g: {"pass": True, "reason": "y"}
        for g in (
            "small_service_business",
            "coach_or_event_owner_relevance",
            "concrete_supported_substance",
            "connects_to_ziv_work",
        )
    }


def _candidate(title: str) -> TopicCandidate:
    return TopicCandidate(
        id=uuid.uuid4(),
        workspace_id=WS,
        week_start=datetime(2026, 9, 21),
        moment_ids=[str(uuid.uuid4())],
        title=title,
        lesson=f"The lesson behind {title}.",
        audience="coaches",
        reasons_to_care=["it costs them clients"],
        public_angle="Take a position.",
        gates=_gates(),
        citations_private=[
            {"moment_id": str(uuid.uuid4()), "source_kind": "fathom_meeting", "title": "A call"}
        ],
        status="proposed",
        origin="selector",
        freshness_role="evergreen",
        rank=1,
    )


async def _seed(sessionmaker) -> dict:
    kept = _candidate("Nobody opens the report their AI wrote")
    away = _candidate("An idea put away by voice")
    async with sessionmaker() as s:
        s.add_all([kept, away])
        lineup = WeeklyLineup(id=uuid.uuid4(), workspace_id=WS, week_start=week_start_for(None))
        s.add(lineup)
        await s.flush()
        s.add(
            WeeklyLineupItem(
                id=uuid.uuid4(),
                workspace_id=WS,
                lineup_id=lineup.id,
                candidate_id=kept.id,
                rank=1,
                slot="primary",
                lane="other",
            )
        )
        await s.flush()
        await voice_agent.apply_change(
            s,
            WS,
            candidate_id=kept.id,
            target="brief",
            operations=[{"field": "takeaway", "after": "Open the result before you trust it."}],
            summary="Write the takeaway",
        )
        await inbox_service.decide(s, WS, away.id, decision="away", decided_by="voice")
        await s.commit()
    return {"kept": str(kept.id), "away": str(away.id)}


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(WS))

    async def enabled() -> bool:
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)

    db_path = (tmp_path / "workspace.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def prepare():
        await create_tables(engine)
        return await _seed(sessionmaker)

    seeded = asyncio.run(prepare())

    app = FastAPI()
    app.include_router(dashboard.router)
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(voice_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sessionmaker

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
        raise RuntimeError("workspace server did not start")
    try:
        yield {"base": f"http://127.0.0.1:{port}", **seeded}
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        asyncio.run(engine.dispose())


LAYOUT_JS = """
() => {
  const vw = window.innerWidth;
  const rect = (el) => el.getBoundingClientRect();
  const overlaps = (a, b) => {
    const r = rect(a), s = rect(b);
    return r.left < s.right - 1 && s.left < r.right - 1
      && r.top < s.bottom - 1 && s.top < r.bottom - 1;
  };
  const buttons = [...document.querySelectorAll('.voice-btn')];
  const texts = [...document.querySelectorAll('.voice-text')];
  const talk = document.getElementById('talkFab');
  const type = document.getElementById('typeFab');
  const bar = [...document.querySelectorAll('#actionBar .bar-btn')];
  const pairs = [];
  for (let i = 0; i < bar.length; i++) for (let j = i + 1; j < bar.length; j++) {
    if (overlaps(bar[i], bar[j])) pairs.push([bar[i].className, bar[j].className]);
  }
  return {
    overflowX: document.documentElement.scrollWidth > vw + 1,
    panel: !!document.getElementById('voicePanel'),
    items: [...document.querySelectorAll('.voice-item')].map((li) => li.innerText),
    smallButtons: buttons.filter((b) => rect(b).height < 44 || rect(b).width < 44).length,
    buttonOverText: buttons.some((b) => texts.some((t) => overlaps(b, t))),
    buttonsFit: buttons.every((b) => rect(b).right <= vw + 1 && rect(b).left >= 0),
    talkTag: talk && talk.tagName,
    talkHref: talk && talk.getAttribute('href'),
    talkLabel: talk && talk.textContent,
    talkHeight: talk && rect(talk).height,
    typeHeight: type && rect(type).height,
    typeWidth: type && rect(type).width,
    barOverlaps: pairs,
    speakButton: !!document.getElementById('voiceBtn'),
  };
}
"""


def test_phone_talk_opens_the_call_and_voice_changes_can_be_undone(workspace, tmp_path):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    # Screenshots land in tmp_path, or where TCE_TEST_SHOTS points to keep them.
    shots = Path(os.environ.get("TCE_TEST_SHOTS") or tmp_path)
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except PlaywrightError as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Chromium is not installed for Playwright: {exc}")
        context = browser.new_context(
            viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True
        )
        context.set_default_timeout(60_000)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # ---------------------------------------------------------- Today
        page.goto(f"{workspace['base']}/today")
        page.wait_for_selector("#voicePanel")
        page.wait_for_selector("#talkFab")
        layout = page.evaluate(LAYOUT_JS)
        assert layout["overflowX"] is False, layout
        assert layout["talkTag"] == "A", "Talk must be a link to the call, not the chat sheet"
        assert layout["talkHref"] == "/voice?seat=tce&context=week&return=%2Ftoday", layout
        assert layout["talkLabel"] == "Talk about the whole week"
        assert layout["talkHeight"] >= 44 and layout["typeHeight"] >= 44, layout
        assert layout["typeWidth"] >= 44, layout
        assert layout["barOverlaps"] == [], layout
        assert layout["speakButton"] is False, "the dictation Speak button must be gone"
        assert layout["smallButtons"] == 0 and layout["buttonsFit"], layout
        assert layout["buttonOverText"] is False, layout
        joined = "\n".join(layout["items"])
        assert 'The takeaway now says "Open the result before you trust it."' in joined
        assert 'Put "An idea put away by voice" away.' in joined
        page.locator("#voicePanel").scroll_into_view_if_needed()
        page.screenshot(path=str(shots / "voice-panel-today-phone.png"), full_page=True)

        # Typed chat is still one tap away.
        page.click("#typeFab")
        page.wait_for_selector("#talkSheet:not([hidden])")
        assert page.locator("#talkInput").is_visible()
        assert page.locator("#voiceBtn").count() == 0
        page.click("#talkClose")

        # Undo really takes the change back.
        with page.expect_response(
            lambda r: r.url.endswith("/undo") and r.request.method == "POST"
        ) as undone:
            page.locator("[data-voice-undo]").first.click()
        assert undone.value.status == 200
        page.wait_for_selector(".voice-item.is-undone")
        assert page.locator("[data-voice-undo]").count() == 0

        # Restore brings the put-away idea back.
        with page.expect_response(
            lambda r: r.url.endswith("/restore") and r.request.method == "POST"
        ) as restored:
            page.locator("[data-voice-restore]").first.click()
        assert restored.value.status == 200
        page.wait_for_function("() => !document.querySelector('[data-voice-restore]')")
        page.screenshot(path=str(shots / "voice-panel-after-undo-phone.png"), full_page=True)

        # ------------------------------------------------------ Topic room
        page.goto(f"{workspace['base']}/topics/{workspace['kept']}")
        page.wait_for_selector("#talkFab")
        page.wait_for_selector("#voicePanel")
        room = page.evaluate(LAYOUT_JS)
        assert room["overflowX"] is False, room
        expected = (
            f"/voice?seat=tce&context=topic:{workspace['kept']}"
            f"&return=%2Ftopics%2F{workspace['kept']}"
        )
        assert room["talkHref"] == expected, room
        assert room["talkLabel"] == "Talk about this topic"
        # Only this topic's changes, not the idea put away elsewhere.
        assert not any("put away by voice" in i for i in room["items"]), room
        assert room["barOverlaps"] == [], room
        page.screenshot(path=str(shots / "voice-topic-room-phone.png"), full_page=False)

        assert errors == [], errors
        browser.close()
