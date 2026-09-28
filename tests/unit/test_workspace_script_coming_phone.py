"""Phone-width walk-through of a script that is on its way.

28-Sep-2026: he asked for a script while his Claude limit was used up. For two
days the week card said "No script yet" and offered "Prepare the script", whose
toast promised "a few minutes". Boots the real workspace shell plus the
editorial routers on a throwaway SQLite file behind a fake authenticating proxy,
and drives headless Chromium at 390x844. Asserts:

- Today's card for the asked-for topic says it waits for his Claude limit and
  when it resets, and offers nothing to press; the topic never asked for still
  offers "Prepare the script"; the next action counts the one on its way;
- the topic's own page says the same and offers nothing to press;
- pressing "Prepare the script" says when it comes (not "a few minutes") and the
  button becomes that sentence in place;
- nothing overflows sideways.

Skipped when Playwright or its Chromium build is not installed. Nothing here
calls a paid service, a worker or a real database.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tce.api import dashboard
from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.editorial import status as job_status
from tce.editorial.common import packet_key_text
from tce.editorial.lineup import week_start_for
from tce.llm import LLMRequest
from tce.llm import queue as llm_queue
from tce.models.content_run import WorkerGroupState
from tce.models.editorial import TopicCandidate
from tce.models.editorial_workspace import WeeklyLineup, WeeklyLineupItem
from tce.settings import settings
from tests.editorial_db import create_tables

pytest.importorskip("playwright.sync_api")

KEY = "coming-phone-" + uuid.uuid4().hex
WS = uuid.UUID("c0c0c0c0-4444-4444-8444-444444444444")
PHONE = {"width": 390, "height": 844}
PARK = datetime.now(UTC).replace(tzinfo=None, microsecond=0) + timedelta(days=2)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _candidate(title: str) -> TopicCandidate:
    return TopicCandidate(
        id=uuid.uuid4(),
        workspace_id=WS,
        week_start=week_start_for(None),
        moment_ids=[str(uuid.uuid4())],
        title=title,
        lesson=f"The lesson behind {title}.",
        audience="coaches",
        reasons_to_care=["it costs them clients"],
        public_angle="Take a position.",
        gates={},
        citations_private=[],
        status="selected",
        origin="selector",
        freshness_role="evergreen",
        rank=1,
    )


async def _seed(sessionmaker) -> dict:
    asked = _candidate("Asked during the limit")
    fresh = _candidate("Never asked yet")
    async with sessionmaker() as s:
        s.add_all([asked, fresh])
        lineup = WeeklyLineup(
            id=uuid.uuid4(), workspace_id=WS, week_start=week_start_for(None), primary_slots=3
        )
        s.add(lineup)
        await s.flush()
        for rank, candidate in enumerate((asked, fresh), start=1):
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
        # The 28-Sep job: leased, hit the weekly limit, parked for two days.
        nonce = str(uuid.uuid4())
        job = await llm_queue.enqueue(
            s,
            LLMRequest(
                job_type="recording_packet",
                agent_name="recording_packet_writer",
                messages=[{"role": "user", "content": f"PACKET REQUEST: {nonce}\n\nIDEA"}],
                workspace_id=WS,
                run_id=asked.id,
                idempotency_key=packet_key_text(WS, nonce),
            ),
        )
        job.status, job.error_code, job.retry_at = "waiting_capacity", "capacity", PARK
        s.add(
            WorkerGroupState(
                group_key=llm_queue.WORKER_GROUP_KEY, state="waiting_capacity", retry_at=PARK
            )
        )
        await s.commit()
    return {"asked": str(asked.id), "fresh": str(fresh.id)}


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(WS))

    async def enabled() -> bool:
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)
    asked_for: list[str] = []

    async def no_writer(sm, ws, cid, resume_job_id=None, **kwargs):
        # The packet writer is a PC worker job; here it only records the ask.
        asked_for.append(str(cid))
        job_status.update(ws, "packet", str(cid), state="waiting")

    monkeypatch.setattr(editorial_router, "_run_packet", no_writer)
    job_status.clear()

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
    app.include_router(editorial_router.router, prefix="/api/v1")
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
        yield {"base": f"http://127.0.0.1:{port}", "asked_for": asked_for, **seeded}
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        asyncio.run(engine.dispose())
        job_status.clear()


CARDS_JS = """
() => [...document.querySelectorAll('article.card')].map((card) => ({
  title: (card.querySelector('h3') || {}).textContent,
  tags: [...card.querySelectorAll('.tag')].map((t) => t.textContent),
  hints: [...card.querySelectorAll('.section-hint')].map((t) => t.textContent),
  buttons: [...card.querySelectorAll('.actions a, .actions button')].map((b) => b.textContent),
}))
"""
OVERFLOW = "document.documentElement.scrollWidth > window.innerWidth + 1"


def test_phone_a_script_on_its_way_says_when_and_offers_nothing_to_press(workspace, tmp_path):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    # His clock, worked out here rather than by the code under test.
    local = PARK.replace(tzinfo=UTC).astimezone(ZoneInfo("Asia/Jerusalem"))
    when = f"{local:%a} {local.day}-{local:%b} at {local:%H:%M}"
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
        page.wait_for_selector("article.card h3")
        cards = {c["title"]: c for c in page.evaluate(CARDS_JS)}
        asked = cards["Asked during the limit"]
        assert asked["tags"][-1] == "Script waiting for your Claude limit", asked
        assert any(when in hint and "saves itself" in hint for hint in asked["hints"]), asked
        assert "Prepare the script" not in asked["buttons"], asked
        assert "Prepare the script" in cards["Never asked yet"]["buttons"], cards
        action = page.locator(".next-action").text_content()
        assert "1 of your 2 topics still needs a script" in action, action
        assert "1 more is on the way and saves itself" in action, action
        assert page.evaluate(OVERFLOW) is False
        page.screenshot(path=str(shots / "today-script-coming-phone.png"), full_page=True)

        # ------------------------------------------------------ The topic
        page.goto(f"{workspace['base']}/topics/{workspace['asked']}")
        page.wait_for_selector("h2")
        body = page.locator("#view").text_content()
        assert f"reset on {when}" in body and "saves itself" in body, body
        assert page.locator("[data-ask-script]").count() == 0
        assert page.evaluate(OVERFLOW) is False
        page.screenshot(path=str(shots / "topic-script-coming-phone.png"), full_page=True)

        # ------------------------------------------- Asking for the other one
        page.goto(f"{workspace['base']}/week")
        page.wait_for_selector("article.card h3")
        button = page.locator(f'[data-ask-script="{workspace["fresh"]}"]')
        button.click()
        page.wait_for_function(
            '(id) => !document.querySelector(`[data-ask-script="${id}"]`)',
            arg=workspace["fresh"],
        )
        card = page.locator("article.card", has_text="Never asked yet")
        said = card.locator(".section-hint").last.text_content()
        assert said.startswith("Asked. Waiting for your Claude limit"), said
        assert when in said and "few minutes" not in said, said
        assert workspace["asked_for"] == [workspace["fresh"]]
        assert page.evaluate(OVERFLOW) is False
        page.screenshot(path=str(shots / "week-asked-during-limit-phone.png"), full_page=True)

        assert errors == [], errors
        browser.close()
