"""F13, TCE half (23-Nov): one read where there were two, and polls that answer faster
without asking more of TCE.

- Every /production/library answer carries `counts` (editing, unedited, unreviewed),
  equal to what the page counted itself from a second read of Still to do, for every
  filter. The page uses them when present and reads again only when they are absent
  (a TCE from before this change).
- The topic room reads the topic and the voice activity at the same time. A voice read
  that fails leaves the room drawn without its panel; a topic read that fails is the
  page's error at once, without waiting for the voice read.
- Jennifer's sheet (talk-voice.js) reads the sitting 1 s after a change, a press or
  his words, then 2 s, 4 s and on, never slower than before: 2 s while something is
  waiting, 30 s when nothing is. An opened sheet with nothing happening reads at the
  old 30 s beat, so idle asks no more of TCE than before.
- Typed Talk (workspace.js startTalkPoll) reads 1 s after he sends, then 2 s, then
  every 4 s as before, and 1 s after anything in the thread changes.

The counts run on SQLite through library.list_library, compared with the page's own
countMatch run in Node. The polls run talk-voice.js and startTalkPoll in Node with a
fake clock. The room runs in headless Chromium through the B8 harness.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tce.editorial import library
from tce.editorial.common import ORIGIN_TECHNICAL_VALIDATION
from tce.models.editorial import RecordingUpload, TopicCandidate, VideoPublication
from tests.unit.test_workspace_press_in_place import (  # noqa: F401  (fixtures)
    DESKTOP,
    PHONE,
    Hold,
    _page,
    _shots,
    browser,
    server,
)

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "src/tce/api/workspace.js").read_text(encoding="utf-8")
TALK = ROOT / "src/tce/api/talk-voice.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node not installed")
WS = uuid.UUID("cafecafe-1111-4111-8111-111111111111")
OTHER = uuid.UUID("cafecafe-2222-4222-8222-222222222222")


def _node(script: str):
    out = subprocess.run([NODE, "-e", script], check=True, capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1])


def _js(pattern: str) -> str:
    m = re.search(pattern, JS, re.M | re.S)
    assert m, pattern
    return m.group(0)


def _fn(name: str, source: str = JS, prefix: str = "") -> str:
    m = re.search(r"^  " + prefix + r"function " + name + r"\(.*?^  \}$", source, re.M | re.S)
    assert m, name
    return m.group(0)


# ------------------------------------------------------------ 1. library counts


def _candidate(ws, title, **over) -> TopicCandidate:
    data = dict(workspace_id=ws, week_start=datetime(2026, 11, 16), moment_ids=["m"], title=title,
                lesson="l", audience="a", public_angle="p", gates={}, status="recorded")
    data.update(over)
    return TopicCandidate(id=uuid.uuid4(), **data)


def _upload(ws, cand, status, *, edited=False, archived=False, age=1) -> RecordingUpload:
    return RecordingUpload(
        id=uuid.uuid4(), workspace_id=ws, candidate_id=cand.id, original_filename="take.mp4",
        storage_path="/tmp/take.mp4", sha256=uuid.uuid4().hex * 2, status=status,
        edited_path="/tmp/take-edit.mp4" if edited else None,
        archived_at=datetime.now(UTC) if archived else None,
        created_at=datetime.now(UTC) - timedelta(days=age),
    )


async def _seed(sm) -> None:
    """One video for each rule of the three counts, and for each way out of the pool."""
    rows: list = []
    pubs: list = []

    def take(title, status, *, ws=WS, pub=None, **kw):
        cand = _candidate(ws, title, **{k: kw.pop(k) for k in ("origin",) if k in kw})
        if kw.pop("hand_published", False):
            cand.status = "published"
        up = _upload(ws, cand, status, **kw)
        rows.extend([cand, up])
        for platform, state in (pub or {}).items():
            pubs.append(VideoPublication(workspace_id=ws, upload_id=up.id, candidate_id=cand.id,
                                         platform=platform, status=state, copy={}))

    take("Edited, no posts yet", "edited", edited=True)                       # unreviewed
    take("Edited, out on Instagram", "edited", edited=True, pub={"instagram": "posted"})  # published
    take("Edited, a draft post", "edited", edited=True, pub={"facebook": "draft"})        # unreviewed
    take("Edited, posting now", "edited", edited=True, pub={"facebook": "posting"})       # reviewed
    take("Edited, scheduled", "edited", edited=True, pub={"youtube": "scheduled"})        # published
    take("On the server", "uploaded")                                         # unedited
    take("Needs his eyes", "needs_review")                                    # unedited
    take("Being cut", "rendering")                                            # editing
    take("Being proofread", "proofreading")                                   # editing
    take("Archived mid-edit", "transcribing", archived=True)                  # out: archived
    take("Archived edit", "edited", edited=True, archived=True)               # out: archived
    take("Replaced take", "superseded")                                       # out: superseded
    take("Pipeline proof", "edited", edited=True, origin=ORIGIN_TECHNICAL_VALIDATION)  # out
    take("Receipt by hand", "uploaded", hand_published=True)                  # Everything only
    take("Someone else's", "rendering", ws=OTHER)                             # out: other workspace
    async with sm() as s:
        s.add_all(rows)
        await s.flush()
        s.add_all(pubs)
        await s.commit()


def _page_counts(responses: dict) -> dict:
    """The page's own counting before this change: countMatch over libraryCounts' pool,
    which is this list for Still to do and Everything and a second read of Still to do
    for every other filter."""
    script = (
        _js(r"^  var LIBRARY_LIVE = \[.*?\];") + "\n" + _fn("countMatch") + "\n"
        "const r = JSON.parse(" + json.dumps(json.dumps(responses)) + ");"
        "const out = {};"
        "for (const f of Object.keys(r)) {"
        "  const pool = (f === 'todo' || f === 'all') ? r[f].items : r.todo.items;"
        "  out[f] = {};"
        "  for (const k of ['editing', 'unedited', 'unreviewed']) out[f][k] = pool.filter(i => countMatch(k, i)).length;"
        "}"
        "process.stdout.write(JSON.stringify(out));"
    )
    return _node(script)


@needs_node
async def test_the_counts_in_the_read_are_what_the_page_counted_from_a_second_read(editorial_sessionmaker):
    await _seed(editorial_sessionmaker)
    async with editorial_sessionmaker() as s:
        responses = {f: await library.list_library(s, WS, filter_key=f) for f in library.LIBRARY_FILTERS}
    page = _page_counts(responses)
    for f, body in responses.items():
        assert body["counts"] == page[f], f
    # Each rule is exercised: Still to do counts over what is still on his plate...
    assert responses["todo"]["counts"] == {"editing": 2, "unedited": 2, "unreviewed": 2}
    # ...and Everything over its own list, as the page did (a take of a topic he
    # recorded a receipt for by hand is in Everything only).
    assert responses["all"]["counts"] == {"editing": 2, "unedited": 3, "unreviewed": 2}
    for f in ("uploading", "editing", "needs_review", "ready", "published", "archived"):
        assert responses[f]["counts"] == responses["todo"]["counts"], f


async def test_an_empty_library_counts_nothing(editorial_sessionmaker):
    async with editorial_sessionmaker() as s:
        body = await library.list_library(s, uuid.uuid4(), filter_key="archived")
    assert body["counts"] == {"editing": 0, "unedited": 0, "unreviewed": 0}
    assert body["items"] == []


@needs_node
def test_the_page_uses_the_counts_and_reads_again_only_without_them():
    script = (
        _js(r"^  var LIBRARY_LIVE = \[.*?\];") + "\n" + _js(r"^  var COUNT_KINDS = \[.*?\];") + "\n"
        + _fn("countMatch") + "\n" + _fn("libraryCounts", prefix="async ") + "\n"
        "const calls = [];"
        "async function api(p) { calls.push(p); return {items: [{has_edit: false, status: 'rendering'},"
        "  {has_edit: true, status: 'edited', publishing: []}]}; }"
        "(async () => {"
        "  const told = await libraryCounts({filter: 'editing', items: [], counts: {editing: 4, unedited: 5, unreviewed: 6}});"
        "  const before = calls.length;"
        "  const old = await libraryCounts({filter: 'editing', items: []});"
        "  const half = await libraryCounts({filter: 'todo', items: [], counts: {editing: 1}});"
        "  process.stdout.write(JSON.stringify([told, before, old, half, calls]));"
        "})();"
    )
    told, before, old, half, calls = _node(script)
    assert told == {"editing": 4, "unedited": 5, "unreviewed": 6} and before == 0
    # A TCE from before this change: the second read, as it always was.
    assert old == {"editing": 1, "unedited": 0, "unreviewed": 1}
    assert calls == ["/production/library?filter=todo"]
    # Counts that are not all there are not trusted (Still to do counts its own list).
    assert half == {"editing": 0, "unedited": 0, "unreviewed": 0}


# ------------------------------------------------------- 2. Jennifer's sheet


HARNESS = r"""
const vm = require("vm"), fs = require("fs");
function run(name, steps) {
  let now = 0, nextId = 1; const timers = [];
  const ctx = {};
  ctx.setTimeout = (fn, ms) => { const id = nextId++; timers.push({ id, at: now + (ms || 0), fn }); return id; };
  ctx.clearTimeout = (id) => { const i = timers.findIndex(t => t.id === id); if (i >= 0) timers.splice(i, 1); };
  ctx.setInterval = () => 0; ctx.clearInterval = () => {};
  function el() {
    const e = { hidden: false, disabled: false, textContent: "", title: "", _q: {}, listeners: {},
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
      setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
      addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
      removeEventListener() {}, setPointerCapture() {}, focus() {}, remove() {},
      querySelector(s) { return this._q[s] || (this._q[s] = el()); } };
    Object.defineProperty(e, "innerHTML", { get() { return ""; }, set() { e._q = {}; } });
    return e;
  }
  ctx.document = { visibilityState: "visible", addEventListener() {}, removeEventListener() {},
                   createElement: el, head: el() };
  ctx.navigator = {};
  ctx.location = { pathname: "/library/u1/talk", search: "" };
  ctx.console = console; ctx.Promise = Promise; ctx.JSON = JSON; ctx.Date = Date; ctx.Math = Math;
  ctx.window = ctx;
  let call = null;
  ctx.KmVoice = { start(opts) { call = opts;
    return { mute() {}, quiet() {}, hush() {}, stop() {}, send() {}, interrupt() {},
             muted: true, quieted: false, speaking: false, busy: true, live: true }; } };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
  const sitting = { session_id: "s1", upload_id: "u1", state: "open", render_ref: "r1", notes: [],
                    last_seen: "t0", video_status: "edited", video_step: null, result: null };
  const reads = [];
  async function api(path, o) {
    o = o || {};
    if ((o.method || "GET") === "GET") { reads.push(now); sitting.last_seen = "t" + now; return JSON.parse(JSON.stringify(sitting)); }
    if (path.endsWith("/notes")) return { note_id: "n1", note: { id: "n1", state: "listening", edit_s: 0 } };
    return { id: "n1", state: "listening" };
  }
  const root = el();
  const talk = ctx.TceTalkVoice.open({ root, sitting: JSON.parse(JSON.stringify(sitting)), api });
  const flush = async () => { for (let i = 0; i < 30; i++) await new Promise(r => setImmediate(r)); };
  async function until(t) {
    for (;;) {
      timers.sort((a, b) => a.at - b.at);
      const next = timers[0];
      if (!next || next.at > t) break;
      timers.shift(); now = next.at; next.fn(); await flush();
    }
    now = t;
  }
  return (async () => {
    await flush();
    const out = {};
    for (const [at, what] of steps) {
      await until(at);
      if (what === "change") sitting.summary = "changed at " + now;
      if (what === "progress") sitting.video_step = "Rendering " + now;
      if (what === "busy") sitting.state = "thinking";
      if (what === "words") call.on("hearing", { text: "the caption is late here" });
      if (what === "mark") out.mark = reads.length;
      await flush();
    }
    out.reads = reads;
    talk.close();
    return out;
  })();
}
"""


def _talk(steps) -> dict:
    script = HARNESS + "run('x', " + json.dumps(steps) + ").then(o => process.stdout.write(JSON.stringify(o)));"
    out = subprocess.run([NODE, "-e", script, str(TALK)], check=True, capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1])


def _gaps(reads):
    return [b - a for a, b in zip([0, *reads], reads, strict=False)]


@needs_node
def test_jennifers_sheet_asks_no_more_than_before_while_nothing_happens():
    # Opening the sheet is not news: the 30 s heartbeat it always had.
    idle = _talk([[125_000, "end"]])["reads"]
    assert _gaps(idle) == [30000, 30000, 30000, 30000]
    # The heartbeat stamp and a render's progress line move on every read; neither is news.
    moving = _talk([[20_000, "progress"], [50_000, "progress"], [125_000, "end"]])["reads"]
    assert _gaps(moving) == [30000, 30000, 30000, 30000]


@needs_node
def test_a_change_goes_back_to_one_second_and_backs_off_one_two_four():
    reads = _talk([[40_000, "change"], [160_000, "end"]])["reads"]
    # Idle at 30 s and 60 s; the read at 60 s sees the change: 1 s, 2 s, 4 s, 8 s, 16 s,
    # then the 30 s heartbeat again.
    after = reads[reads.index(60_000):]
    assert _gaps(after)[1:8] == [1000, 2000, 4000, 8000, 16000, 30000, 30000]


@needs_node
def test_while_a_job_runs_it_never_waits_longer_than_today():
    got = _talk([[20_000, "busy"], [60_000, "end"]])["reads"]
    busy = [r for r in got if r >= 30_000]
    # The read at 30 s sees the batch start: 1 s, then every 2 s (as before), never more.
    assert _gaps(busy)[1:12] == [1000] + [2000] * 10


@needs_node
def test_his_words_bring_the_next_read_within_a_second():
    got = _talk([[40_000, "words"], [60_000, "end"]])["reads"]
    # Idle at 30 s; his words at 40 s pin a note and read again 250 ms later, then 1 s.
    after = [r for r in got if r > 30_000]
    assert after[0] == 40_250
    assert after[1] - after[0] == 1000
    assert all(b - a <= 2000 for a, b in zip(after, after[1:], strict=False))


def test_the_hidden_tab_and_the_reopened_sitting_keep_their_paths():
    source = TALK.read_text(encoding="utf-8")
    # Coming back to the tab reads at once, as before; nothing else listens to visibility.
    visible = re.search(r"^    function onVisible\(\) \{.*?^    \}$", source, re.M | re.S).group(0)
    assert visible.count("refresh();") == 1
    assert source.count('addEventListener("visibilitychange"') == 1
    assert "POLL_FAST_MS = 2000" in source and "POLL_SLOW_MS = 30000" in source


# -------------------------------------------------------------- 3. typed Talk


TALK_POLL = r"""
let now = 0, nextId = 1; const timers = [];
global.setTimeout = (fn, ms) => { const id = nextId++; timers.push({ id, at: now + ms, fn }); return id; };
global.clearInterval = (id) => { const i = timers.findIndex(t => t.id === id); if (i >= 0) timers.splice(i, 1); };
const state = { thread: { thread_id: "t1", pending: true, messages: [{ seq: 1, status: "queued" }] } };
const sheet = { hidden: false };
const $ = () => sheet;
const reads = [], spoken = [];
let reply = () => JSON.parse(JSON.stringify(state.thread));
async function api() { reads.push(now); return reply(); }
function renderTalk() {}
function speak(t) { spoken.push(t); }
""" + "\n"


@needs_node
def test_typed_talk_reads_one_two_then_four_seconds_and_again_after_a_change():
    script = (
        TALK_POLL + _js(r"^  var TALK_POLL_MS = \[.*?\];") + "\n" + _fn("startTalkPoll") + "\n"
        "const flush = async () => { for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r)); };"
        "async function until(t) { for (;;) { timers.sort((a, b) => a.at - b.at); const n = timers[0];"
        "  if (!n || n.at > t) break; timers.shift(); now = n.at; n.fn(); await flush(); } now = t; }"
        "(async () => {"
        "  startTalkPoll(); await until(20000);"
        "  const quiet = reads.slice();"
        "  state.thread.messages[0].status_detail = 'Waiting for the subscription worker';"
        "  reply = () => ({ ...JSON.parse(JSON.stringify(state.thread)) });"
        "  await until(40000);"
        "  reply = () => ({ thread_id: 't1', pending: false, messages: [{ role: 'assistant', status: 'complete', text: 'Done.' }] });"
        "  await until(60000);"
        "  process.stdout.write(JSON.stringify({ quiet, all: reads, spoken, left: timers.length }));"
        "})();"
    )
    got = _node(script)
    gaps = [b - a for a, b in zip([0, *got["quiet"]], got["quiet"], strict=False)]
    assert gaps == [1000, 2000, 4000, 4000, 4000, 4000]   # 1, 3, 7, 11, 15, 19 s
    later = [r for r in got["all"] if r > 20000]
    # The thread changed (read at 23 s): 1 s, then 2 s, then the 4 s it always was.
    assert later[:4] == [23000, 24000, 26000, 30000]
    # The reply landed: it is read out (when he asked for that) and the polling stops.
    assert got["spoken"] == ["Done."] and got["left"] == 0


def test_today_and_the_new_numbers_for_the_report():
    # Today's numbers stay the ceilings; the new first step is 1 s.
    assert "var TALK_POLL_MS = [1000, 2000, 4000];" in JS
    assert "var POLL_FIRST_MS = 1000;" in TALK.read_text(encoding="utf-8")


# ------------------------------------------------------------------ 4. room


def test_the_room_reads_both_at_once_and_one_failing_never_blanks_the_other(server, browser, tmp_path):  # noqa: F811
    shots = _shots(tmp_path)
    cid = server["ideas"]["Idea 1"]
    for size, name in ((PHONE, "phone"), (DESKTOP, "desktop")):
        page = _page(browser, size)
        rooms = Hold(page, "**/api/v1/editorial/topics/*/room", "GET")
        voices = Hold(page, "**/api/v1/editorial/voice/activity*", "GET")
        page.goto(f"{server['base']}/topics/{cid}")
        # Both reads are out before either has answered.
        rooms.wait(page)
        voices.wait(page)
        voices.routes[0].fulfill(status=500, content_type="application/json",
                                 body=json.dumps({"detail": "voice activity unavailable"}))
        rooms.routes[0].continue_()
        page.wait_for_selector("#view h1")
        assert page.text_content("#view h1") == "Idea 1"
        assert page.locator("#voicePanel").count() == 0
        assert page.locator("[data-decide]").count() == 4
        page.screenshot(path=str(shots / f"f13-room-voice-failed-{name}.png"), full_page=False)

        # The topic cannot be read: the page says so at once, while the voice read is out.
        page.goto(f"{server['base']}/topics/{cid}")
        rooms.wait(page, 2)
        voices.wait(page, 2)
        rooms.routes[1].fulfill(status=404, content_type="application/json",
                                body=json.dumps({"detail": "that topic is not here"}))
        page.locator(".load-error").wait_for()
        assert "that topic is not here" in page.text_content(".load-error")
        page.screenshot(path=str(shots / f"f13-room-failed-{name}.png"), full_page=False)
        voices.routes[1].continue_()
        assert page.errors == [], page.errors
        page.context.close()
