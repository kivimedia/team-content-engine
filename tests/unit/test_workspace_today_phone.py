"""Phone-width walk-through of Today's counts and a filmed topic in the week.

28-Sep: Today said 12 "being edited" while the Library's "Being edited" list was
empty, and its card opened the Library on "Everything". A topic he had filmed
still offered "Record this one". Boots the real workspace shell plus the
editorial routers on a throwaway SQLite file behind a fake authenticating proxy,
and drives headless Chromium at 390x844. Asserts:

- the "being edited" card counts the Library's "Being edited" list and opens it
  on that filter, and the other filters still work from there;
- a filmed topic stays in the week with a "Filmed" tag and no record button,
  and "Start recording" goes to the next topic he has not filmed;
- "Record it again" on a filmed topic's recording opens that topic in the
  studio (the studio lists only what is left to film, and used to answer
  "That script is not ready to record yet");
- nothing overflows sideways.

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
from tce.api.routers import editorial_workspace as workspace_router
from tce.api.routers import production as production_router
from tce.db.session import get_db
from tce.editorial.lineup import week_start_for
from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import WeeklyLineup, WeeklyLineupItem
from tce.settings import settings
from tests.editorial_db import create_tables

pytest.importorskip("playwright.sync_api")

KEY = "today-phone-" + uuid.uuid4().hex
WS = uuid.UUID("beefbeef-3333-4333-8333-333333333333")
PHONE = {"width": 390, "height": 844}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
        gates={
            g: {"pass": True, "reason": "y"}
            for g in (
                "small_service_business",
                "coach_or_event_owner_relevance",
                "concrete_supported_substance",
                "connects_to_ziv_work",
            )
        },
        citations_private=[
            {"moment_id": str(uuid.uuid4()), "source_kind": "fathom_meeting", "title": "A call"}
        ],
        status="recorded",
        origin="selector",
        freshness_role="evergreen",
        rank=1,
    )


def _take(candidate: TopicCandidate, status: str) -> RecordingUpload:
    return RecordingUpload(
        workspace_id=WS,
        candidate_id=candidate.id,
        original_filename="take.mp4",
        storage_path="/tmp/take.mp4",
        sha256=uuid.uuid4().hex * 2,
        status=status,
        duration_s=160.0,
        edited_path="/tmp/take-edit.mp4" if status == "edited" else None,
    )


async def _seed(sessionmaker) -> dict:
    filmed = _candidate("Filmed on Sunday")
    next_up = _candidate("Next to film")
    cutting = _candidate("Being cut now")
    resting = _candidate("Resting on the server")
    async with sessionmaker() as s:
        s.add_all([filmed, next_up, cutting, resting])
        lineup = WeeklyLineup(
            id=uuid.uuid4(), workspace_id=WS, week_start=week_start_for(None), primary_slots=3
        )
        s.add(lineup)
        await s.flush()
        for rank, candidate in enumerate((filmed, next_up), start=1):
            s.add(
                WeeklyLineupItem(
                    id=uuid.uuid4(),
                    workspace_id=WS,
                    lineup_id=lineup.id,
                    candidate_id=candidate.id,
                    rank=rank,
                    slot="primary",
                    lane="coaching",
                    reason="In this week's list.",
                    status="planned",
                )
            )
            s.add(
                RecordingPacket(
                    workspace_id=WS,
                    candidate_id=candidate.id,
                    version=1,
                    bullets=["First point."],
                    script_phrases=["First line."],
                    status="ready",
                    citations_private=[],
                    public_safety={},
                )
            )
        # Filmed and edited; two takes resting on the server (not filmed, not
        # being edited); and one being cut now, the only one being edited.
        s.add_all(
            [
                _take(filmed, "edited"),
                _take(next_up, "uploaded"),
                _take(resting, "uploaded"),
                _take(cutting, "rendering"),
            ]
        )
        await s.commit()
    return {"filmed": str(filmed.id), "next_up": str(next_up.id)}


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
    app.include_router(workspace_router.production_router, prefix="/api/v1")
    # The studio's own routes (its queue) read through `get_db`, which commits.
    app.include_router(production_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sessionmaker

    async def studio_db():
        async with sessionmaker() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = studio_db

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


CARDS_JS = """
() => [...document.querySelectorAll('article.card')].map((card) => ({
  title: (card.querySelector('h3') || {}).textContent,
  tags: [...card.querySelectorAll('.tag')].map((t) => t.textContent),
  buttons: [...card.querySelectorAll('.actions a, .actions button')].map((b) => b.textContent),
}))
"""

# The Library's own filter chips (the talk sheet has chips of its own).
PRESSED = '[aria-label="Filter recordings"] .chip[aria-pressed="true"]'

LIBRARY_JS = """
(pressed) => ({
  path: window.location.pathname + window.location.search,
  pressed: [...document.querySelectorAll(pressed)].map((c) => c.textContent),
  titles: [...document.querySelectorAll('article.card h3')].map((h) => h.textContent),
  overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
})
"""


def test_phone_today_counts_what_the_library_shows_and_a_filmed_topic_is_done(
    workspace, tmp_path
):
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
        page.wait_for_selector(".counts .count")
        editing = page.locator(".counts .count", has_text="being edited")
        assert editing.locator("b").text_content() == "1"
        start = page.locator(".actions a.btn.primary", has_text="Start recording")
        assert start.get_attribute("href") == f"/record?candidate={workspace['next_up']}"
        cards = {c["title"]: c for c in page.evaluate(CARDS_JS)}
        assert "Filmed" in cards["Filmed on Sunday"]["tags"], cards
        assert "Record this one" not in cards["Filmed on Sunday"]["buttons"], cards
        assert "Record this one" in cards["Next to film"]["buttons"], cards
        overflow = "document.documentElement.scrollWidth > window.innerWidth + 1"
        assert page.evaluate(overflow) is False
        page.screenshot(path=str(shots / "today-filmed-and-editing-phone.png"), full_page=True)

        # The card opens the list it counts.
        editing.click()
        page.wait_for_function("() => window.location.search === '?filter=editing'")
        page.wait_for_selector(PRESSED)
        library = page.evaluate(LIBRARY_JS, PRESSED)
        assert library["path"] == "/library?filter=editing", library
        assert library["pressed"] == ["Being edited"], library
        assert library["titles"] == ["Being cut now"], library
        assert library["overflowX"] is False, library
        page.screenshot(path=str(shots / "library-being-edited-phone.png"), full_page=True)

        # The other filters still answer from there.
        page.locator('[aria-label="Filter recordings"] .chip', has_text="Everything").click()
        page.wait_for_function(
            "(pressed) => [...document.querySelectorAll(pressed)]"
            ".some((c) => c.textContent === 'Everything')",
            arg=PRESSED,
        )
        assert len(page.evaluate(LIBRARY_JS, PRESSED)["titles"]) == 4

        # Opened straight from a link, the filter holds too.
        page.goto(f"{workspace['base']}/library?filter=editing")
        page.wait_for_selector(PRESSED)
        assert page.evaluate(LIBRARY_JS, PRESSED)["pressed"] == ["Being edited"]

        # ------------------------------------------------------- The week
        page.goto(f"{workspace['base']}/week")
        page.wait_for_selector("article.card h3")
        cards = {c["title"]: c for c in page.evaluate(CARDS_JS)}
        assert "Filmed" in cards["Filmed on Sunday"]["tags"], cards
        assert "Record this one" not in cards["Filmed on Sunday"]["buttons"], cards
        assert page.locator("#pageStatus").text_content() == "1 of 1 scripts ready, 1 filmed"
        page.screenshot(path=str(shots / "week-filmed-phone.png"), full_page=True)

        # --------------------------------------------- Record it again
        # The studio lists only what is left to film; the topic he names is
        # opened all the same.
        page.goto(f"{workspace['base']}/library")
        page.wait_for_selector("article.card h3")
        again = page.locator("article.card", has_text="Filmed on Sunday").locator(
            "a", has_text="Record it again"
        )
        assert again.get_attribute("href") == f"/record?candidate={workspace['filmed']}"
        again.click()
        page.wait_for_selector("#studioView:not([hidden])")
        assert page.locator("#scriptTitle").text_content() == "Filmed on Sunday"
        assert "not ready to record" not in (page.locator("#notice").text_content() or "")
        page.screenshot(path=str(shots / "record-it-again-phone.png"), full_page=True)

        assert errors == [], errors
        browser.close()
