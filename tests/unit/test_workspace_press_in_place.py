"""B8 (23-Nov): a press on a topic, the week or a Library card answers on screen at once.

The page used to wait for TCE, then wipe itself and draw everything again under his
finger. Now the card leaves, moves or says what is starting at once, the request goes
as before, and TCE stays the judge:

- a refused press (an error, a 409) or one that got no answer puts the card back where
  it was, as it was, with one sentence saying it did not go through;
- the pressed card is locked while its own request is out (no double send); another
  card stays usable, and quick presses on different cards each go, in order;
- after the last one settles, one quiet re-read draws the page in place: the DOM then
  equals a fresh render of the same server state, the scroll does not move and the
  focused element is the same node;
- a decision offers TCE's own undo of that one write (undo-decision, by change id);
- a paid step (new backgrounds) and posting only say they are starting until TCE
  answers, and a refusal is said in TCE's own words.

The browser part boots the real workspace shell and the editorial routers on a
throwaway SQLite file behind a fake authenticating proxy, like the Today phone test,
and drives headless Chromium. Requests the test holds, refuses or drops are routed by
Playwright; nothing reaches a paid service or a real database. Skipped when Playwright
or its Chromium build is missing; the static and Node checks always run.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr

from tce.settings import settings

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "src/tce/api/workspace.js").read_text(encoding="utf-8")
HE = ROOT / "src/tce/api/i18n-he.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node not installed")

KEY = "press-" + uuid.uuid4().hex
HE_KEY = "press-he-" + uuid.uuid4().hex
WS = uuid.UUID("beefbeef-4444-4444-8444-444444444444")
HE_WS = uuid.UUID("beefbeef-5555-4555-8555-555555555555")
PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 900}
NO_ANSWER = "No answer from TCE, so this is shown as it was. The page checks again in a moment."


# ------------------------------------------------------------------ static


def _function(name: str) -> str:
    m = re.search(r"^  function " + name + r"\(.*?^  \}$", JS, re.M | re.S)
    assert m, name
    return m.group(0)


def _node(script: str):
    out = subprocess.run([NODE, "-e", script], check=True, capture_output=True, text=True, timeout=30)
    return json.loads(out.stdout)


def test_the_undo_button_is_tappable_and_nothing_else_was_added_to_the_list():
    block = re.search(r"var CLICK_ACTIONS = \[(.*?)\];", JS, re.S).group(1)
    assert '"undo-decision"' in block
    assert "if (d.undoDecision !== undefined)" in JS
    # Its change id rides on data-change-id, which is not the Change button's data-change.
    assert 'setAttribute("data-change-id", changeId)' in JS


def test_the_presses_no_longer_wipe_the_page():
    for name in ("decide", "moveItem", "archiveRecording", "editNow", "renameSave", "pickStyle",
                 "pickBackdrop", "publishDraft", "publishStart"):
        body = _function(name)
        assert "press(" in body, name
        assert "render()" not in body and "renderLibrary()" not in body, name


@needs_node
def test_every_new_line_has_its_hebrew():
    path = json.dumps(str(HE))
    lines = ["Starting", "Posting", "Scheduling", "Asking for the posts", "Saving", "Undo",
             "Undoing", NO_ANSWER, "That did not go through: Nothing was changed."]
    got = _node(f"const t = require({path}).translate; process.stdout.write(JSON.stringify("
                f"{json.dumps(lines)}.map(t)));")
    assert all(got), dict(zip(lines, got, strict=True))
    assert all(re.search("[֐-׿]", g) for g in got), got
    assert got[-1].startswith("זה לא עבר: ")


@needs_node
def test_a_week_move_on_screen_is_the_move_tce_makes():
    week = {
        "primary_slots": 2,
        "primary": [{"candidate_id": c, "rank": i + 1, "slot": "primary", "script_state": "ready",
                     "filmed": False} for i, c in enumerate("abc")],
        "reserve": [{"candidate_id": "d", "rank": 1, "slot": "reserve", "script_state": "none",
                     "filmed": False}],
    }
    script = (
        _function("toFilmNow") + "\n" + _function("movedWeek") + "\n"
        "const w = () => JSON.parse(" + json.dumps(json.dumps(week)) + ");"
        "const ids = (x) => [x.primary.map(i => i.candidate_id + i.rank).join(' '),"
        "                    x.reserve.map(i => i.candidate_id + i.rank).join(' '), x.over_by, x.ready_count];"
        "process.stdout.write(JSON.stringify(["
        "ids(movedWeek(w(), {candidate_id: 'c', action: 'first'})),"
        "ids(movedWeek(w(), {candidate_id: 'a', action: 'down'})),"
        "ids(movedWeek(w(), {candidate_id: 'a', action: 'up'})),"
        "ids(movedWeek(w(), {candidate_id: 'b', action: 'slot', slot: 'reserve'})),"
        "ids(movedWeek(w(), {candidate_id: 'd', action: 'slot', slot: 'primary'})),"
        "ids(movedWeek(w(), {candidate_id: 'b', action: 'remove'})),"
        "ids(movedWeek(w(), {candidate_id: 'zz', action: 'remove'}))]));"
    )
    assert _node(script) == [
        ["c1 a2 b3", "d1", 1, 3],
        ["b1 a2 c3", "d1", 1, 3],
        ["a1 b2 c3", "d1", 1, 3],
        ["a1 c2", "d1 b2", 0, 2],
        ["a1 b2 c3 d4", "", 2, 3],
        ["a1 c2", "d1", 0, 2],
        # A topic not in the week leaves the week as it was.
        ["a1 b2 c3", "d1", None, None],
    ]


@needs_node
def test_which_decisions_leave_the_list_follow_tces_own_filter():
    script = (
        _function("leavesTopics") + "\n"
        "var window = {};"
        "const owner = [leavesTopics('best', 'this_week'), leavesTopics('best', 'discuss'),"
        "  leavesTopics('all', 'away'), leavesTopics('calls', 'away'), leavesTopics('discuss', 'this_week'),"
        "  leavesTopics('discuss', 'discuss'), leavesTopics('away', 'away'), leavesTopics('away', 'this_week')];"
        "window.TCE_SCOPED = true; window.TCE_LANE_TABS = [['fire', 'Fire']];"
        "const client = [leavesTopics('best', 'this_week'), leavesTopics('best', 'discuss'),"
        "  leavesTopics('best', 'later'), leavesTopics('calls', 'this_week'), leavesTopics('fire', 'this_week'),"
        "  leavesTopics('fire', 'away'), leavesTopics('later', 'later')];"
        "process.stdout.write(JSON.stringify([owner, client]));"
    )
    owner, client = _node(script)
    assert owner == [True, True, False, False, True, False, False, True]
    assert client == [True, False, True, False, False, True, False]


# ---------------------------------------------------------------- browser


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _gates() -> dict:
    return {g: {"pass": True, "reason": "y"} for g in (
        "small_service_business", "coach_or_event_owner_relevance",
        "concrete_supported_substance", "connects_to_ziv_work")}


def _candidate(ws, title, rank, **over):
    from tce.models.editorial import TopicCandidate

    data = dict(
        id=uuid.uuid4(), workspace_id=ws, week_start=datetime(2026, 11, 16),
        moment_ids=[str(uuid.uuid4())], title=title, lesson=f"The lesson behind {title}.",
        audience="coaches", reasons_to_care=["it costs them clients"], public_angle="Take a position.",
        gates=_gates(),
        citations_private=[{"moment_id": str(uuid.uuid4()), "source_kind": "fathom_meeting", "title": "A call"}],
        status="proposed", origin="selector", freshness_role="evergreen", rank=rank,
    )
    data.update(over)
    return TopicCandidate(**data)


async def _seed_owner(sessionmaker) -> dict:
    from tce.editorial.common import ORIGIN_AGENT_TALK
    from tce.editorial.lineup import week_start_for
    from tce.models.editorial import RecordingUpload
    from tce.models.editorial_workspace import TopicDecision, WeeklyLineup, WeeklyLineupItem

    ideas = [_candidate(WS, f"Idea {n}", n) for n in range(1, 9)]
    week = [_candidate(WS, f"Week {c}", 20 + i) for i, c in enumerate("ABCD")]
    kept = [_candidate(WS, f"Library {n}", 40 + i, status="recorded") for i, n in enumerate(("one", "two"))]
    solo = _candidate(WS, "Recording, 22 Nov", 50, status="recorded", origin=ORIGIN_AGENT_TALK)
    async with sessionmaker() as s:
        s.add_all(ideas + week + kept + [solo])
        lineup = WeeklyLineup(id=uuid.uuid4(), workspace_id=WS, week_start=week_start_for(None), primary_slots=3)
        s.add(lineup)
        await s.flush()
        for rank, cand in enumerate(week, start=1):
            slot = "reserve" if rank == 4 else "primary"
            s.add(WeeklyLineupItem(id=uuid.uuid4(), workspace_id=WS, lineup_id=lineup.id, candidate_id=cand.id,
                                   rank=1 if slot == "reserve" else rank, slot=slot, lane="coaching",
                                   reason="In this week's list.", status="planned"))
            s.add(TopicDecision(workspace_id=WS, candidate_id=cand.id, decision="this_week", decided_by="ziv"))
        old = datetime.now(UTC) - timedelta(days=3)
        for n, cand in enumerate(kept):
            s.add(RecordingUpload(workspace_id=WS, candidate_id=cand.id, original_filename="take.mp4",
                                  storage_path="/tmp/take.mp4", sha256=uuid.uuid4().hex * 2, status="edited",
                                  duration_s=90.0 + n, edited_path=f"/tmp/take-{n}-edit.mp4",
                                  created_at=old - timedelta(hours=n)))
        s.add(RecordingUpload(workspace_id=WS, candidate_id=solo.id, original_filename="recording.webm",
                              storage_path="/tmp/solo.webm", sha256=uuid.uuid4().hex * 2, status="uploaded",
                              duration_s=40.0, source="solo_take", created_at=old - timedelta(days=1)))
        await s.commit()
    return {"ideas": {c.title: str(c.id) for c in ideas}, "week": {c.title: str(c.id) for c in week}}


async def _seed_hebrew(sessionmaker) -> None:
    async with sessionmaker() as s:
        s.add_all([_candidate(HE_WS, f"רעיון {n}", n) for n in range(1, 6)])
        await s.commit()


@pytest.fixture(params=["owner"])
def server(request, monkeypatch, tmp_path):
    pytest.importorskip("playwright.sync_api")
    import uvicorn
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from tce.api import dashboard
    from tce.api.private_access import ScopedEditorGuard
    from tce.api.routers import editorial as editorial_router
    from tce.api.routers import editorial_voice as voice_router
    from tce.api.routers import editorial_workspace as workspace_router
    from tce.api.routers import production as production_router
    from tce.db.session import get_db
    from tests.editorial_db import create_tables

    hebrew = request.param == "hebrew"
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(WS))
    monkeypatch.setattr(settings, "editor_workspace_keys", SecretStr(f"{HE_KEY}:{HE_WS}"))
    monkeypatch.setattr(settings, "workspace_languages", f"{HE_WS}:he")

    async def enabled() -> bool:
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'press.db').as_posix()}", poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def prepare():
        await create_tables(engine)
        return await (_seed_hebrew(sessionmaker) if hebrew else _seed_owner(sessionmaker))

    seeded = asyncio.run(prepare()) or {}
    app = FastAPI()
    app.include_router(dashboard.router)
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(workspace_router.production_router, prefix="/api/v1")
    app.include_router(voice_router.router, prefix="/api/v1")
    app.include_router(production_router.router, prefix="/api/v1")
    app.add_middleware(ScopedEditorGuard)
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sessionmaker

    async def studio_db():
        async with sessionmaker() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = studio_db
    key = (HE_KEY if hebrew else KEY).encode()

    async def proxy(scope, receive, send):
        # The browser never holds the key; nginx injects it after Basic Auth.
        if scope["type"] == "http" and (hebrew or scope["path"].startswith("/api/v1/")):
            headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"x-tce-editor-key"]
            headers.append((b"x-tce-editor-key", key))
            scope = dict(scope, headers=headers)
        await app(scope, receive, send)

    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(proxy, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(300):
        if srv.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("workspace server did not start")
    try:
        yield {"base": f"http://127.0.0.1:{port}", "sm": sessionmaker, **seeded}
    finally:
        srv.should_exit = True
        thread.join(timeout=10)
        asyncio.run(engine.dispose())


@pytest.fixture
def browser():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(headless=True)
        except PlaywrightError as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Chromium is not installed for Playwright: {exc}")
        yield chromium
        chromium.close()


def _page(browser, size=PHONE):
    context = browser.new_context(viewport=size, device_scale_factor=2, is_mobile=size is PHONE,
                                  has_touch=size is PHONE)
    context.set_default_timeout(30_000)
    page = context.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())
    page.seen = []
    page.on("requestfinished", lambda r: page.seen.append((r.method, r.url)))
    return page


def _shots(tmp_path) -> Path:
    shots = Path(os.environ.get("TCE_TEST_SHOTS") or tmp_path)
    shots.mkdir(parents=True, exist_ok=True)
    return shots


class Hold:
    """Holds every request a route matches until the test lets it go."""

    def __init__(self, page, pattern, method):
        self.routes = []
        self.method = method

        def handler(route):
            if route.request.method != method:
                route.fallback()
                return
            self.routes.append(route)

        page.route(pattern, handler)

    def wait(self, page, n=1):
        for _ in range(400):
            if len(self.routes) >= n:
                return
            page.wait_for_timeout(25)
        raise AssertionError(f"expected {n} held {self.method} requests, got {len(self.routes)}")


def _settle(page, fragment, after):
    """Waits for one more finished GET whose URL holds `fragment`: the quiet re-read."""
    for _ in range(400):
        gets = [u for m, u in page.seen if m == "GET" and fragment in u]
        if len(gets) > after:
            page.wait_for_timeout(250)  # the redraw follows the answer (and its sibling read)
            return
        page.wait_for_timeout(25)
    raise AssertionError(f"no re-read of {fragment}")


def _gets(page, fragment):
    return len([u for m, u in page.seen if m == "GET" and fragment in u])


TITLES = "() => [...document.querySelectorAll('#view article.card h3')].map(h => h.textContent)"


def _card(page, title):
    return page.locator("#view article.card", has=page.locator("h3", has_text=re.compile("^" + re.escape(title) + "$")))


def _fresh(page):
    """The same server state, drawn by a fresh load of the page."""
    page.reload()
    page.wait_for_selector("#view article.card h3")
    page.wait_for_timeout(300)
    return page.inner_html("#view"), page.text_content("#pageStatus")


def test_a_decision_leaves_at_once_quick_presses_go_in_order_and_undo_takes_it_back(server, browser, tmp_path):
    shots = _shots(tmp_path)
    page = _page(browser)
    page.goto(f"{server['base']}/topics")
    page.wait_for_selector("#view article.card h3")
    assert page.evaluate(TITLES)[:8] == [f"Idea {n}" for n in range(1, 9)]
    status_before = page.text_content("#pageStatus")

    held = Hold(page, "**/api/v1/editorial/topics/*/decide", "POST")
    _card(page, "Idea 5").scroll_into_view_if_needed()
    _card(page, "Idea 5").get_by_role("button", name="Good: keep it").click()
    held.wait(page)
    # At once: the card left, while its request is still out.
    assert "Idea 5" not in page.evaluate(TITLES)
    assert page.text_content("#pageStatus") != status_before
    # Another card stays usable, and its press waits its turn: one request at a time.
    _card(page, "Idea 6").get_by_role("button", name="Bad: ditch it").click()
    assert "Idea 6" not in page.evaluate(TITLES)
    page.wait_for_timeout(200)
    assert len(held.routes) == 1
    page.screenshot(path=str(shots / "b8-topics-after-press-phone.png"), full_page=False)

    # The element he is on stays the same node through the re-read, and the page stays put.
    page.evaluate("() => { const b = [...document.querySelectorAll('#view article.card h3')]"
                  ".find(h => h.textContent === 'Idea 7').closest('article').querySelector('[data-open-room]');"
                  " b.__mark = 1; b.focus(); }")
    reads = _gets(page, "/editorial/topics?")
    held.routes[0].continue_()
    held.wait(page, 2)
    # In the order he pressed: Idea 5 first, then Idea 6.
    assert f"/topics/{server['ideas']['Idea 5']}/decide" in held.routes[0].request.url
    assert f"/topics/{server['ideas']['Idea 6']}/decide" in held.routes[1].request.url
    assert json.loads(held.routes[1].request.post_data) == {"decision": "away"}
    scroll = page.evaluate("() => window.scrollY")
    held.routes[1].continue_()
    _settle(page, "/editorial/topics?", reads)
    assert page.evaluate("() => document.activeElement && document.activeElement.__mark === 1")
    assert page.evaluate("() => window.scrollY") == scroll
    assert page.evaluate("() => !document.querySelector('#view [aria-busy]')")

    toast = page.locator(".toast")
    assert "Undo" in toast.text_content()
    page.screenshot(path=str(shots / "b8-undo-line-phone.png"), full_page=False)
    away = page.request.get(f"{server['base']}/api/v1/editorial/topics?filter=away").json()
    assert [t["title"] for t in away["topics"]] == ["Idea 6"]

    # The page after the press and the re-read is a fresh render of the same state.
    after = page.inner_html("#view"), page.text_content("#pageStatus")
    assert _fresh(page) == after

    # Undo on the last decision: TCE's own undo of that one write, and the idea is back.
    page.goto(f"{server['base']}/topics")
    page.wait_for_selector("#view article.card h3")
    reads = _gets(page, "/editorial/topics?")
    _card(page, "Idea 2").get_by_role("button", name="Bad: ditch it").click()
    held.wait(page, 3)
    held.routes[2].continue_()
    page.locator(".toast .toast-undo").wait_for()
    _settle(page, "/editorial/topics?", reads)
    assert "Idea 2" not in page.evaluate(TITLES)
    reads = _gets(page, "/editorial/topics?")
    page.locator(".toast .toast-undo").click()
    _settle(page, "/editorial/topics?", reads)
    assert "Idea 2" in page.evaluate(TITLES)
    assert "is waiting for a decision again" in page.locator(".toast").text_content()
    undo = [u for m, u in page.seen if m == "POST" and "undo-decision" in u]
    assert len(undo) == 1 and f"/editorial/topics/{server['ideas']['Idea 2']}/undo-decision" in undo[0]
    assert page.errors == [], page.errors


def test_a_refused_or_unanswered_decision_comes_back_where_it_was(server, browser, tmp_path):
    shots = _shots(tmp_path)
    for size, name in ((PHONE, "phone"), (DESKTOP, "desktop")):
        page = _page(browser, size)
        page.goto(f"{server['base']}/topics")
        page.wait_for_selector("#view article.card h3")
        before = page.inner_html("#view")
        status_before = page.text_content("#pageStatus")
        refusal = {"detail": {"code": "already", "message": '"Idea 3" is already put away. Nothing was changed.'}}
        held = Hold(page, "**/api/v1/editorial/topics/*/decide", "POST")
        _card(page, "Idea 3").get_by_role("button", name="Bad: ditch it").click()
        held.wait(page)
        assert "Idea 3" not in page.evaluate(TITLES)
        held.routes[0].fulfill(status=409, content_type="application/json", body=json.dumps(refusal))
        page.locator(".toast.is-bad").wait_for()
        assert page.locator(".toast").text_content() == (
            'That did not go through: "Idea 3" is already put away. Nothing was changed.')
        page.wait_for_timeout(400)
        # Back exactly where it was, as it was: the whole page is what it was before the press.
        assert page.inner_html("#view") == before
        assert page.text_content("#pageStatus") == status_before
        page.screenshot(path=str(shots / f"b8-refused-restored-{name}.png"), full_page=False)

        _card(page, "Idea 4").get_by_role("button", name="Good: keep it").click()
        held.wait(page, 2)
        held.routes[1].abort("connectionreset")
        page.locator(".toast.is-bad").wait_for()
        page.wait_for_function("(t) => document.querySelector('.toast').textContent === t", arg=NO_ANSWER)
        page.wait_for_timeout(400)
        assert page.inner_html("#view") == before
        page.context.close()
    # Nothing was decided on the server.
    page = _page(browser)
    best = page.request.get(f"{server['base']}/api/v1/editorial/topics?filter=best").json()
    assert {"Idea 3", "Idea 4"} <= {t["title"] for t in best["topics"]}


def test_week_moves_answer_at_once_and_each_goes_in_order(server, browser, tmp_path):
    shots = _shots(tmp_path)
    page = _page(browser)
    news = {"enabled": False}
    page.route("**/api/v1/news/workflow", lambda r: r.fulfill(json=news))
    page.goto(f"{server['base']}/week")
    page.wait_for_selector("#view article.card h3")
    assert page.evaluate(TITLES) == ["Week A", "Week B", "Week C", "Week D"]

    held = Hold(page, "**/api/v1/editorial/weeks/current/lineup", "PATCH")
    _card(page, "Week A").get_by_role("button", name="Move down").click()
    held.wait(page)
    assert page.evaluate(TITLES) == ["Week B", "Week A", "Week C", "Week D"]
    assert page.locator("#view article.card").nth(1).locator(".rank").text_content() == "2"
    # The moved card is locked while its move is out; the next card is not.
    assert _card(page, "Week A").get_attribute("aria-busy") == "true"
    _card(page, "Week C").get_by_role("button", name="Make first").click()
    assert page.evaluate(TITLES) == ["Week C", "Week B", "Week A", "Week D"]
    page.screenshot(path=str(shots / "b8-week-after-moves-phone.png"), full_page=False)
    page.wait_for_timeout(200)
    assert len(held.routes) == 1
    first = json.loads(held.routes[0].request.post_data)
    held.routes[0].continue_()
    held.wait(page, 2)
    second = json.loads(held.routes[1].request.post_data)
    # The second move goes against the week the first one's answer gave.
    assert second["expected_revision"] == first["expected_revision"] + 1
    assert second["move"] == {"candidate_id": server["week"]["Week C"], "action": "first"}
    reads = _gets(page, "/weeks/current/lineup")
    held.routes[1].continue_()
    _settle(page, "/weeks/current/lineup", reads)
    assert page.evaluate(TITLES) == ["Week C", "Week B", "Week A", "Week D"]
    after = page.inner_html("#view"), page.text_content("#pageStatus")
    assert _fresh(page) == after
    assert page.errors == [], page.errors


def test_library_cards_answer_in_place(server, browser, tmp_path):
    shots = _shots(tmp_path)
    page = _page(browser)
    page.goto(f"{server['base']}/library")
    page.wait_for_selector("#view article.card h3")
    assert page.evaluate(TITLES) == ["Library one", "Library two", "Recording, 22 Nov"]

    # Archive: the card leaves at once and stays gone once TCE agrees.
    held = Hold(page, "**/api/v1/production/recordings/*/archive", "POST")
    _card(page, "Library one").get_by_role("button", name="Archive").click()
    held.wait(page)
    assert page.evaluate(TITLES) == ["Library two", "Recording, 22 Nov"]
    reads = _gets(page, "/production/library?")
    held.routes[0].continue_()
    _settle(page, "/production/library?", reads)
    assert page.evaluate(TITLES) == ["Library two", "Recording, 22 Nov"]
    assert "Archived." in page.locator(".toast").text_content()

    # Rename: the new name is there at once; refused, the old one is back and the box
    # opens again with what he typed.
    renames = Hold(page, "**/api/v1/production/recordings/*/title", "POST")
    _card(page, "Recording, 22 Nov").get_by_role("button", name="Rename").click()
    page.locator(".rename-input").fill("Walk by the river")
    page.locator("[data-rename-save]").click()
    renames.wait(page)
    assert page.evaluate(TITLES) == ["Library two", "Walk by the river"]
    assert page.locator(".rename-form").count() == 0
    renames.routes[0].fulfill(status=409, content_type="application/json",
                              body=json.dumps({"detail": "that name is taken here"}))
    page.locator(".toast.is-bad").wait_for()
    assert page.locator(".toast").text_content() == "That did not go through: that name is taken here"
    assert page.evaluate(TITLES) == ["Library two", "Recording, 22 Nov"]
    assert page.locator(".rename-input").input_value() == "Walk by the river"
    reads = _gets(page, "/production/library?")
    page.locator("[data-rename-save]").click()
    renames.wait(page, 2)
    renames.routes[1].continue_()
    _settle(page, "/production/library?", reads)
    assert page.evaluate(TITLES) == ["Library two", "Walk by the river"]

    # Edit this now: the button says it is starting, the card is locked (one tap, one
    # edit), and it says "editing" only once TCE answered.
    edits = Hold(page, "**/api/v1/production/uploads/*/auto-edit", "POST")
    button = _card(page, "Walk by the river").locator("[data-edit-now]")
    button.click()
    edits.wait(page)
    assert button.text_content() == "Starting" and button.is_disabled()
    button.scroll_into_view_if_needed()
    page.screenshot(path=str(shots / "b8-library-edit-starting-phone.png"), full_page=False)
    button.click(force=True)
    page.wait_for_timeout(200)
    assert len(edits.routes) == 1
    assert "Editing it now" not in (page.locator(".toast").text_content() if page.locator(".toast").count() else "")
    reads = _gets(page, "/production/library?")
    edits.routes[0].fulfill(json={"status_detail": "Queued for editing"})
    _settle(page, "/production/library?", reads)
    assert "Editing it now." in page.locator(".toast").text_content()

    after = page.inner_html("#view"), page.text_content("#pageStatus")
    assert _fresh(page) == after
    assert page.errors == [], page.errors


STUB_ITEM = {
    "upload_id": "11111111-2222-4333-8444-555555555555", "candidate_id": None, "title": "Fire on the pier",
    "recorded_at": "2026-11-20T10:00:00", "duration_s": 61.0, "status": "edited",
    "state_sentence": "Edited and ready.", "qc": None, "proofread": [], "removed": [], "phone_cut": [],
    "review_note": None, "has_preview": False, "render_ref": "r1", "posts_writing": None,
    "last_request": None, "has_edit": True, "archived": False, "published": False, "issues": [],
    "waiting_notes": 0, "notes_made": None, "source": "recording",
    "actions": [
        {"key": "watch_edit", "label": "Watch the edit"},
        {"key": "style", "label": "Style", "current": "creatorz", "pictures": [], "stale": False,
         "backdrop": {"on": False, "about_usd": 2.4, "max_usd": 8.0}},
    ],
    "publishing": [
        {"platform": "instagram", "label": "Instagram Reel", "status": "draft", "copy": {"caption": "Fire on the pier."},
         "url": None, "detail": None, "scheduled_for": None},
        {"platform": "facebook", "label": "Facebook Reel", "status": "draft", "copy": {"message": "Fire on the pier."},
         "url": None, "detail": None, "scheduled_for": None},
    ],
}


def _stub_library(item):
    return {"filter": "todo", "filter_label": "Still to do", "items": [item], "total": 1,
            "filters": [{"key": "todo", "label": "Still to do"}, {"key": "all", "label": "Everything"}],
            "counts": {"editing": 0, "unedited": 0, "unreviewed": 1}}


@pytest.mark.parametrize("size,name", [(PHONE, "phone"), (DESKTOP, "desktop")])
def test_a_paid_step_and_posting_only_say_they_are_starting(server, browser, tmp_path, size, name):
    shots = _shots(tmp_path)
    page = _page(browser, size)
    item = json.loads(json.dumps(STUB_ITEM))
    page.route("**/api/v1/production/library?*", lambda r: r.fulfill(json=_stub_library(item)))
    page.goto(f"{server['base']}/library")
    page.wait_for_selector("#view article.card h3")
    card = _card(page, "Fire on the pier")

    # A style pick is lit at once; TCE refuses it, and the old one is lit again.
    styles = Hold(page, "**/api/v1/production/uploads/*/style", "POST")
    card.get_by_role("button", name="Pill").click()
    styles.wait(page)
    assert card.get_by_role("button", name="Pill").get_attribute("aria-pressed") == "true"
    styles.routes[0].fulfill(status=409, content_type="application/json",
                             body=json.dumps({"detail": {"message": "This video is being edited right now. Nothing was changed."}}))
    page.locator(".toast.is-bad").wait_for()
    assert card.get_by_role("button", name="Creatorz").get_attribute("aria-pressed") == "true"

    # New places: starting, never drawing, until TCE answers; its refusal in its words.
    backdrops = Hold(page, "**/api/v1/production/uploads/*/backdrop", "POST")
    card.get_by_role("button", name="New places").click()
    backdrops.wait(page)
    starting = card.locator('[data-backdrop="on"]')
    assert starting.text_content() == "Starting" and starting.is_disabled()
    assert page.locator(".toast").count() == 0 or "new backgrounds" not in page.locator(".toast").text_content()
    words = "Today's spend cap for new backgrounds is reached ($25 of $25). Nothing was started."
    backdrops.routes[0].fulfill(status=409, content_type="application/json",
                                body=json.dumps({"detail": {"code": "backdrop_cap", "message": words}}))
    page.locator(".toast.is-bad").wait_for()
    assert page.locator(".toast").text_content() == "That did not go through: " + words
    assert card.locator('[data-backdrop="on"]').text_content() == "New places"
    page.screenshot(path=str(shots / f"b8-backdrop-refused-{name}.png"), full_page=False)

    # Posting: says "Posting" at once and never "Posted" before TCE's own read says so.
    page.route("**/api/v1/production/uploads/*/publishing/instagram", lambda r: r.fulfill(json={}))
    page.route("**/api/v1/production/uploads/*/publishing/facebook", lambda r: r.fulfill(json={}))
    posts = Hold(page, "**/api/v1/production/uploads/*/publishing/publish", "POST")
    page.evaluate("() => document.querySelectorAll('.toast').forEach(t => t.remove())")
    card.get_by_role("button", name="Post the ticked ones now").click()
    posts.wait(page)
    posting = card.locator("[data-pub-post]")
    assert posting.text_content() == "Posting" and posting.is_disabled()
    assert "Posted" not in card.inner_text()
    posting.scroll_into_view_if_needed()
    page.screenshot(path=str(shots / f"b8-publishing-in-flight-{name}.png"), full_page=False)
    item["publishing"][0].update(status="posted", url="https://example.invalid/p/1")
    item["publishing"][1].update(status="failed", detail="Facebook refused the video: it is too long.")
    reads = _gets(page, "/production/library?")
    posts.routes[0].fulfill(json={"started": ["instagram", "facebook"]})
    _settle(page, "/production/library?", reads)
    tags = card.locator(".pub-head .tag").all_text_contents()
    assert tags == ["Posted", "Did not go out"]
    assert "Facebook refused the video" in card.text_content()
    page.screenshot(path=str(shots / f"b8-published-partly-{name}.png"), full_page=False)
    assert page.errors == [], page.errors


def test_the_moment_after_a_press_at_desktop_width(server, browser, tmp_path):
    shots = _shots(tmp_path)
    page = _page(browser, DESKTOP)
    page.route("**/api/v1/news/workflow", lambda r: r.fulfill(json={"enabled": False}))
    page.goto(f"{server['base']}/topics")
    page.wait_for_selector("#view article.card h3")
    held = Hold(page, "**/api/v1/editorial/topics/*/decide", "POST")
    _card(page, "Idea 1").get_by_role("button", name="Good: keep it").click()
    held.wait(page)
    assert page.evaluate(TITLES)[0] == "Idea 2"
    page.screenshot(path=str(shots / "b8-topics-after-press-desktop.png"), full_page=False)
    held.routes[0].continue_()
    page.locator(".toast .toast-undo").wait_for()
    page.screenshot(path=str(shots / "b8-undo-line-desktop.png"), full_page=False)
    box = page.locator(".toast").bounding_box()
    undo = page.locator(".toast .toast-undo").bounding_box()
    assert box["x"] <= undo["x"] and undo["x"] + undo["width"] <= box["x"] + box["width"]

    page.goto(f"{server['base']}/week")
    page.wait_for_selector("#view article.card h3")
    news_read = "() => !!document.querySelector('#weekNewsProgress') && !document.querySelector('#weekNewsProgress .working')"
    page.wait_for_function(news_read)
    moves = Hold(page, "**/api/v1/editorial/weeks/current/lineup", "PATCH")
    _card(page, "Week D").get_by_role("button", name="Record it this week").click()
    moves.wait(page)
    # The section that went away is gone; what the page filled in by itself stays filled.
    assert page.evaluate(news_read)
    assert page.get_by_text("Possible replacements").count() == 0
    assert page.evaluate(TITLES) == ["Week A", "Week B", "Week C", "Idea 1", "Week D"]
    assert _card(page, "Week D").get_by_role("button", name="Not this week, keep as a spare").count() == 1
    page.screenshot(path=str(shots / "b8-week-after-move-desktop.png"), full_page=False)
    moves.routes[0].continue_()
    page.wait_for_function("() => !document.querySelector('#view [aria-busy]')")
    assert page.errors == [], page.errors


@pytest.mark.parametrize("server", ["hebrew"], indirect=True)
def test_the_new_lines_read_right_to_left_on_a_hebrew_login(server, browser, tmp_path):
    shots = _shots(tmp_path)
    for size, name in ((PHONE, "phone"), (DESKTOP, "desktop")):
        page = _page(browser, size)
        page.goto(f"{server['base']}/topics")
        page.wait_for_selector("#view article.card h3")
        assert page.evaluate("() => document.documentElement.dir") == "rtl"
        held = Hold(page, "**/api/v1/editorial/topics/*/decide", "POST")
        _card(page, "רעיון 2" if name == "phone" else "רעיון 4").locator('[data-decide="this_week"]').click()
        held.wait(page)
        held.routes[0].continue_()
        page.locator(".toast .toast-undo").wait_for()
        page.wait_for_timeout(300)
        assert page.locator(".toast .toast-undo").text_content() == "ביטול"
        page.screenshot(path=str(shots / f"b8-hebrew-undo-{name}.png"), full_page=False)
        _card(page, "רעיון 3").locator('[data-decide="later"]').click()
        held.wait(page, 2)
        held.routes[1].fulfill(status=409, content_type="application/json",
                               body=json.dumps({"detail": {"message": "Nothing was changed."}}))
        page.locator(".toast.is-bad").wait_for()
        page.wait_for_timeout(300)
        assert page.locator(".toast").text_content().startswith("זה לא עבר: ")
        page.screenshot(path=str(shots / f"b8-hebrew-refused-{name}.png"), full_page=False)
        overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1")
        assert overflow is False
        assert page.errors == [], page.errors
        page.context.close()
