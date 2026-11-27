"""Trend formats in the hook studio (T-25834): good, better, best end to end.

The format's catalog and drawings, the week's pick kept beside the hooks, the script
TCE writes from the topic for him to review and accept, the recording cards, and the
edit putting GOOD, BETTER and BEST on the words he says. The writer is stubbed; the
shots are real (reels.shots_for over synthetic words). Synthetic values."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import types
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tce.hooks import format_edit, format_library, format_script, formats, library, trending
from tce.production.creatorz import reels
from tce.settings import settings
from tests.unit.test_creatorz_style import tce_words

API = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
NODE = shutil.which("node")
WS = uuid.UUID("00000000-0000-4000-8000-000000025834")
WEEK = "2026-11-23"
A, B = "a" * 8, "b" * 8
LINEUP = {
    "primary": [
        {"candidate_id": A, "title": "How to price a package", "big_idea": "Price the outcome", "reason": "", "filmed": False},
        {"candidate_id": B, "title": "Some clients rebook at 80%", "big_idea": "", "reason": "", "filmed": False},
    ],
    "reserve": [],
}
GBB = formats.GOOD_BETTER_BEST
TAKE = ("Three ways to price a package. Good: an hourly rate. Better: one package price. "
        "Best: a monthly plan, because it repeats. I pick the best one.")


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path))
    return tmp_path


def run(coro):
    return asyncio.run(coro)


def shots(text=TAKE):
    return reels.shots_for([[0.0, 30.0]], reels.engine_words(tce_words(text)))


# ------------------------------------------------------------------ the catalog


def test_good_better_best_is_the_first_format_with_three_beats_in_order():
    assert formats.FORMATS[0] is GBB and formats.BY_ID["good-better-best"] is GBB
    assert [s.id for s in GBB.steps] == ["open", "good", "better", "best", "close"]
    assert [b.word for b in GBB.beats] == ["good", "better", "best"]
    assert "No song needed" in GBB.song
    for step in GBB.steps:
        assert 2 <= len(step.coach) <= 3, step.id
        for line in (*step.coach, step.does, step.screen):
            assert len(line) <= 140 and "—" not in line and "--" not in line, line
    for line in (GBB.what, GBB.why, GBB.edit, GBB.song):
        assert len(line) <= 200 and "—" not in line and "--" not in line, line


def test_every_step_has_a_drawing_and_the_word_the_edit_shows():
    for step in GBB.steps:
        svg = formats.drawing(GBB, step.id)
        assert svg.startswith("<svg") and svg.endswith("</svg>"), step.id
        assert re.findall(r">([A-Z]+)</text>", svg) == ([step.word.upper()] if step.word else []), step.id
    assert "#1b6fa8" in formats.drawing(GBB, "best") and "#1b6fa8" not in formats.drawing(GBB, "good")
    assert formats.drawing(GBB, "nope") is None


# ------------------------------------------------------------------ the week's pick


def test_a_hook_write_keeps_the_format_picks(store):
    """read_store dropped every key it did not know, so the next hook save erased the formats."""
    run(format_library.pick(WS, WEEK, GBB.id, LINEUP))
    run(library.toggle_favorite(WS, "big-number", True))
    run(library.pick(WS, WEEK, "whip-in", LINEUP))
    assert format_library.current(WS, WEEK, GBB.id)["candidate_id"] == A
    assert json.loads((store / str(WS) / "hooks.json").read_text())["format_weeks"][WEEK][0]["format_id"] == GBB.id


def test_tce_places_it_on_the_first_video_and_he_can_move_it(store):
    entry = run(format_library.pick(WS, WEEK, GBB.id, LINEUP))
    assert entry["candidate_id"] == A and entry["chosen_by"] == "tce" and "first video" in entry["why"]
    moved = run(format_library.pick(WS, WEEK, GBB.id, LINEUP, B))
    assert moved["candidate_id"] == B and moved["chosen_by"] == "owner"
    assert len(format_library._picks(library.read_store(WS), WEEK)) == 1
    with pytest.raises(library.HookError) as err:
        run(format_library.pick(WS, WEEK, GBB.id, LINEUP, "z" * 8))
    assert err.value.code == "not_this_week"
    with pytest.raises(library.HookError):
        run(format_library.pick(WS, WEEK, "nope", LINEUP))
    run(format_library.unpick(WS, WEEK, GBB.id))
    assert format_library.current(WS, WEEK, GBB.id) is None


def test_a_pick_whose_video_left_the_week_moves_and_says_so(store):
    run(format_library.pick(WS, WEEK, GBB.id, LINEUP, B))
    run(format_library.set_script(WS, WEEK, GBB.id, B, {"state": "ready", "lines": {"open": "x"}}))
    only_a = library.week_videos({"primary": [LINEUP["primary"][0]], "reserve": []})
    page = run(format_library.page(WS, WEEK, only_a))
    pick = page[0]["pick"]
    assert pick["candidate_id"] == A and pick["why"].startswith("Its video left this week's list.")
    assert pick["script"] is None
    assert page[0]["steps"][3]["drawing_url"] == "hooks/formats/good-better-best/drawing/best.svg"


# ------------------------------------------------------------------ the script


def _answer(**over):
    rows = {
        "open": "Three ways to price a package.",
        "good": "Good: an hourly rate.",
        "better": "one package price.",
        "best": "Best: a monthly plan, because it repeats.",
        "close": "I pick the monthly plan.",
    }
    rows.update(over)
    return {"steps": [{"step": k, "line": v, "name": {"good": "Hourly", "better": "Package", "best": "Monthly"}.get(k, "")}
                      for k, v in rows.items()]}


def test_clean_puts_the_word_in_front_and_refuses_a_missing_step():
    lines, names = format_script.clean(GBB, _answer())
    assert lines["better"] == "Better: one package price."
    assert lines["good"] == "Good: an hourly rate." and names == {"good": "Hourly", "better": "Package", "best": "Monthly"}
    assert format_script.clean(GBB, {"steps": _answer()["steps"][:4]}) is None
    assert format_script.clean(GBB, _answer(close="")) is None
    assert format_script.clean(GBB, None) is None
    assert "—" not in format_script.clean(GBB, _answer(open="Three ways — to price."))[0]["open"]


def test_the_prompt_carries_the_steps_the_topic_and_its_script():
    prompt = format_script.build_prompt(GBB, LINEUP["primary"][0], ["Price the outcome, not the hour."])
    assert '"start_the_line_with": "Best"' in prompt and "How to price a package" in prompt
    assert "- Price the outcome, not the hour." in prompt
    assert "(no script yet" in format_script.build_prompt(GBB, LINEUP["primary"][0], [])
    assert "Never invent" in format_script.SYSTEM


def _writer(monkeypatch, answer=None, error=None, packet_lines=("Price the outcome.",)):
    seen = {}

    async def complete(request):
        seen["request"] = request
        if error:
            raise error
        return types.SimpleNamespace(structured=answer, text=json.dumps(answer))

    async def packet(_sm, _ws, _cid):
        return types.SimpleNamespace(script_phrases=list(packet_lines)) if packet_lines else None

    monkeypatch.setattr(format_script._llm, "complete", complete)
    monkeypatch.setattr(format_script.script_fit, "_current_packet", packet)
    return seen


def test_fill_saves_a_draft_to_review(store, monkeypatch):
    seen = _writer(monkeypatch, _answer())
    run(format_library.pick(WS, WEEK, GBB.id, LINEUP))
    got = run(format_script.fill(None, WS, WEEK, GBB.id, A, LINEUP["primary"][0]))
    assert got["state"] == "ready" and "from its script" in got["detail"]
    assert seen["request"].job_type == "format_script" and "Price the outcome." in seen["request"].messages[0]["content"]
    script = format_library.current(WS, WEEK, GBB.id)["script"]
    assert script["lines"]["better"] == "Better: one package price."
    cards = format_library.for_video(WS, WEEK, A)[0]
    assert cards["script_state"] == "ready" and cards["steps"][3]["say"].startswith("Best: a monthly plan")


def test_fill_says_a_failure_and_never_writes_on_a_moved_pick(store, monkeypatch):
    _writer(monkeypatch, error=RuntimeError("parked"))
    run(format_library.pick(WS, WEEK, GBB.id, LINEUP))
    got = run(format_script.fill(None, WS, WEEK, GBB.id, A, {}))
    assert got["state"] == "failed" and "RuntimeError" in got["detail"]
    _writer(monkeypatch, {"steps": []})
    assert run(format_script.fill(None, WS, WEEK, GBB.id, A, {}))["state"] == "failed"
    run(format_library.pick(WS, WEEK, GBB.id, LINEUP, B))
    _writer(monkeypatch, _answer())
    run(format_script.fill(None, WS, WEEK, GBB.id, A, {}))  # a stale run for the old video
    assert format_library.current(WS, WEEK, GBB.id).get("script") is None


def test_he_accepts_the_script_with_his_changes(store, monkeypatch):
    _writer(monkeypatch, _answer())
    run(format_library.pick(WS, WEEK, GBB.id, LINEUP))
    with pytest.raises(library.HookError):
        run(format_library.approve(WS, WEEK, GBB.id, {s.id: "x" for s in GBB.steps}))
    run(format_script.fill(None, WS, WEEK, GBB.id, A, {}))
    lines = {line["step"]: line["text"] for line in run(format_library.page(WS, WEEK, library.week_videos(LINEUP)))[0]["pick"]["script"]["lines"]}
    lines["close"] = "I use the monthly plan — every time."
    entry = run(format_library.approve(WS, WEEK, GBB.id, lines))
    assert entry["script"]["state"] == "approved" and "with your changes" in entry["script"]["detail"]
    assert entry["script"]["lines"]["close"] == "I use the monthly plan - every time."
    with pytest.raises(library.HookError) as err:
        run(format_library.approve(WS, WEEK, GBB.id, {**lines, "good": "  "}))
    assert err.value.code == "empty_line"


# ------------------------------------------------------------------ the edit


def test_the_three_words_land_where_he_starts_each_point():
    cut = shots()
    moments, said, landed = format_edit.ensure_beats([], cut, GBB)
    assert landed == ["GOOD", "BETTER", "BEST"]
    best = next(m for m in moments if m["text"] == "BEST")
    # "Best:" starts its sentence; the "best" in "I pick the best one" does not steal it
    assert best["at"] == {"pick": 3, "word": "Best:"} and best["color"] == "accent" and best["place"] == "chest"
    assert next(m for m in moments if m["text"] == "GOOD")["color"] == "white"
    checked, problems = reels.clean_moments(moments, cut, "en")
    assert [m["text"] for m in checked] == ["GOOD", "BETTER", "BEST"], problems
    assert said == "Cut to Good, better, best: GOOD, BETTER and BEST on screen as you say them."


def test_a_word_he_never_says_is_named_and_the_writers_clash_gives_way():
    cut = shots("Three ways to price. Good: an hourly rate. Then a monthly plan, the best of them.")
    clash = {"type": "card_stat", "text": "1", "label": "first way", "at": {"pick": 1, "word": "Good:"}}
    keep = {"type": "tag", "text": "the fix:", "at": {"pick": 0, "at": "start"}}
    strike_target = {"type": "headline", "text": "PRICE", "color": "white", "place": "top", "at": {"pick": 0, "word": "price."}}
    moments, said, landed = format_edit.ensure_beats([keep, strike_target, {"type": "strike", "target": 1, "at": {"pick": 0, "word": "price."}}, clash], cut, GBB)
    assert landed == ["GOOD", "BEST"] and clash not in moments and keep in moments
    strike = next(m for m in moments if m["type"] == "strike")
    assert moments[strike["target"]] is strike_target
    assert said.endswith("BETTER is not, as the word is not said in this take.")
    assert format_edit.ensure_beats([keep], shots("Nothing here at all."), GBB) == (
        [keep], "The edit could not follow Good, better, best: none of its words is said in this take.", [])


def test_the_moments_writer_is_told_and_the_words_go_in():
    prompts = []

    async def ask(prompt, system, schema, attempt):
        prompts.append(prompt)
        return {"moments": [{"type": "whip", "at": {"pick": 0, "at": "start"}}], "punchline": None}

    got = run(reels.get_moments(shots(), "en", ask, fmt=GBB))
    assert "trend format “Good, better, best”" in prompts[0] and '"BEST" (accent)' in prompts[0]
    assert [m.get("text") for m in got["moments"] if m["type"] == "headline"] == ["GOOD", "BETTER", "BEST"]
    assert got["opening"].startswith("Cut to Good, better, best")
    plain = run(reels.get_moments(shots(), "en", ask))
    assert "trend format" not in prompts[-1] and "opening" not in plain


def test_the_render_finds_the_format_on_the_topic(store):
    assert format_edit.format_on(WS, A) is None
    run(format_library.pick(WS, WEEK, GBB.id, LINEUP))
    assert format_edit.format_on(WS, A) is GBB and format_edit.format_on(WS, B) is None
    assert format_edit.format_on(WS, None) is None


# ------------------------------------------------------------------ the API


def _client(monkeypatch, scoped=False, tasks=None):
    from tce.api.private_access import require_private_workspace
    from tce.api.routers import hooks as hooks_router
    from tce.api.routers.editorial import get_editorial_sessionmaker

    async def lineup(_sm, _ws):
        return LINEUP

    async def fill(*args):
        if tasks is not None:
            tasks.append(args)

    monkeypatch.setattr(hooks_router, "_week_key", lambda: WEEK)
    monkeypatch.setattr(hooks_router, "_lineup", lineup)
    monkeypatch.setattr(hooks_router.format_script, "fill", fill)

    async def think(*args):
        if tasks is not None:
            tasks.append(("think",) + args)

    monkeypatch.setattr(hooks_router.trend_idea, "think", think)
    monkeypatch.setattr(hooks_router, "scoped_editor_workspace", lambda key: WS if scoped else None)
    app = FastAPI()
    app.include_router(hooks_router.router, prefix="/api/v1")
    app.dependency_overrides[require_private_workspace] = lambda: WS
    app.dependency_overrides[get_editorial_sessionmaker] = lambda: None
    return TestClient(app)


def test_api_pick_writes_the_script_in_the_background(monkeypatch, store):
    tasks = []
    client = _client(monkeypatch, tasks=tasks)
    page = client.get("/api/v1/hooks").json()
    assert page["formats"][0]["id"] == GBB.id and page["formats"][0]["pick"] is None and page["hooks"]
    got = client.post(f"/api/v1/hooks/formats/{GBB.id}/pick", json={})
    assert got.status_code == 200
    pick = got.json()["formats"][0]["pick"]
    assert pick["candidate_id"] == A and pick["script"]["state"] == "writing"
    assert tasks and tasks[0][2:5] == (WEEK, GBB.id, A) and tasks[0][5]["title"] == "How to price a package"
    assert client.post(f"/api/v1/hooks/formats/{GBB.id}/script", json={"action": "again"}).status_code == 200
    assert len(tasks) == 2
    assert client.post(f"/api/v1/hooks/formats/{GBB.id}/script", json={"action": "accept", "lines": {}}).status_code == 400
    assert client.post(f"/api/v1/hooks/formats/{GBB.id}/script", json={"action": "dance"}).status_code == 400
    assert client.post("/api/v1/hooks/formats/nope/pick", json={}).status_code == 404
    gone = client.delete(f"/api/v1/hooks/formats/{GBB.id}/pick")
    assert gone.status_code == 200 and gone.json()["formats"][0]["pick"] is None
    assert client.post(f"/api/v1/hooks/formats/{GBB.id}/script", json={"action": "again"}).status_code == 409


def test_api_drawings_examples_and_the_owner_gate(monkeypatch, store):
    monkeypatch.setattr(trending, "youtube_key", lambda: "")
    client = _client(monkeypatch)
    svg = client.get(f"/api/v1/hooks/formats/{GBB.id}/drawing/good.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml") and "GOOD" in svg.text
    assert client.get(f"/api/v1/hooks/formats/{GBB.id}/drawing/nope.svg").status_code == 404
    ex = client.get(f"/api/v1/hooks/formats/{GBB.id}/examples").json()
    assert ex["state"] == "no_key" and ex["videos"] == []
    assert client.get("/api/v1/hooks/formats/nope/examples").status_code == 404
    # the hook routes still answer beside the new ones
    assert client.get("/api/v1/hooks/big-number/preview").status_code in (200, 404)
    assert client.post("/api/v1/hooks/big-number/favorite", json={"on": True}).status_code == 200
    scoped = _client(monkeypatch, scoped=True)
    assert scoped.post(f"/api/v1/hooks/formats/{GBB.id}/pick", json={}).status_code == 403
    assert scoped.get(f"/api/v1/hooks/formats/{GBB.id}/drawing/good.svg").status_code == 403


def test_examples_are_looked_up_once_and_kept(monkeypatch, store):
    calls = []

    async def search(key, query, days=7):
        calls.append((query, days))
        return ["v1", "v2"]

    class Stats:
        def __init__(self, api_key):
            pass

        async def fetch_video_stats(self, ids):
            return [{"video_id": "v1", "title": "Good better best: pricing", "channel": "C", "views": 50},
                    {"video_id": "v2", "title": "Good better best gifts", "channel": "D", "views": 900}]

    monkeypatch.setattr(trending, "youtube_key", lambda: "k")
    monkeypatch.setattr(trending, "_search_shorts", search)
    monkeypatch.setattr(trending, "YouTubeDemandService", Stats)
    got = run(trending.format_examples(WS, GBB.id))
    assert got["state"] == "ok" and [v["video_id"] for v in got["videos"]] == ["v2", "v1"]
    assert calls == [("good better best", trending.FORMAT_DAYS)]
    again = run(trending.format_examples(WS, GBB.id))
    assert again["videos"] == got["videos"] and len(calls) == 1
    run(trending.format_examples(WS, GBB.id, again=True))
    assert len(calls) == 2
    page = run(format_library.page(WS, WEEK, library.week_videos(LINEUP)))
    assert page[0]["examples"][0]["url"] == "https://www.youtube.com/shorts/v2"


def test_the_format_writer_runs_in_the_lane_a_person_waits_on():
    from tce.llm import queue

    assert format_script.JOB_TYPE in queue.INTERACTIVE_JOB_TYPES


# ------------------------------------------------------------------ the pages


def _model(payload):
    source = (API / "recording.js").read_text(encoding="utf-8")
    fn = re.search(r"^function trendFormatModel\(.*?^\}\r?$", source, re.M | re.S).group(0)
    script = fn + f"\nprocess.stdout.write(JSON.stringify(trendFormatModel({json.dumps(payload)}, '/tce/api/v1')));"
    return json.loads(subprocess.run([NODE, "-e", script], check=True, capture_output=True, text=True, timeout=30).stdout)


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_recording_cards_model(store):
    assert _model(None) == {"show": False, "steps": []}
    run(format_library.pick(WS, WEEK, GBB.id, LINEUP))
    guide = _model({"formats": format_library.for_video(WS, WEEK, A)})
    assert guide["show"] and not guide["written"] and len(guide["steps"]) == 5
    step = guide["steps"][2]
    assert step["kicker"] == "Good, better, best, step 3 of 5" and step["title"] == "Better" and step["guide"]
    assert step["say"] == GBB.steps[2].does and step["screen"] == "On screen: BETTER in big letters on the word."
    assert step["drawing"] == "/tce/api/v1/hooks/formats/good-better-best/drawing/better.svg"
    assert step["coach"] == list(GBB.steps[2].coach)
    run(format_library.set_script(WS, WEEK, GBB.id, A, {"state": "ready", "lines": {"better": "Better: one package price."}}))
    written = _model({"formats": format_library.for_video(WS, WEEK, A)})
    assert written["written"] and written["steps"][2]["say"] == "Better: one package price." and not written["steps"][2]["guide"]
    assert written["steps"][0]["guide"]  # a step with no line yet still says what it does


def test_the_pages_wire_the_formats():
    html = (API / "recording.html").read_text(encoding="utf-8")
    js = (API / "recording.js").read_text(encoding="utf-8")
    ws_js = (API / "workspace.js").read_text(encoding="utf-8")
    for el in ("trendFormat", "trendFormatTitle", "trendFormatHow", "formatSheet", "formatSheetTitle",
               "formatStepDrawing", "formatStepSay", "formatStepCoach", "formatStepBack", "formatStepNext"):
        assert f'id="{el}"' in html, el
    assert html.index('id="visualHook"') < html.index('id="trendFormat"') < html.index('id="hookChooser"')
    assert "paintTrendFormat(idea);" in js and "idea.trend_formats" in js and "tce-format-seen-" in js
    # T-26074: the trend page is understand and decide only. The script boxes, the word search
    # for examples and moving a format between videos are off it; a yes or no and the real clip are on it.
    for attr in ("data-format-pick", "data-format-unpick", "data-format-again", "data-format-accept",
                 "data-format-examples", "data-format-move", "data-format-line", "<textarea"):
        assert attr not in ws_js[ws_js.index("function renderTrends"):ws_js.index("function hookStyle")], attr
    for attr in ("data-trend-decide", "data-trend-play"):
        assert ws_js.count(attr) >= 2, attr  # drawn and handled
    assert "paintTrends(data)" in ws_js and 'name: "trends"' in ws_js
    for page in ("workspace.html", "recording.html"):
        nav = (API / page).read_text(encoding="utf-8")
        assert 'href="/trends"  data-route="trends" class="hooks-entry"' in nav, page  # the owner's only
    assert "/api/v1/hooks/formats" not in ws_js  # the prefix comes from the page (the /tce trap)


# ------------------------------------------------- T-26074: understand and decide


def test_every_trend_has_a_real_example_someone_looked_at():
    for fmt in formats.FORMATS:
        assert fmt.real, fmt.id  # a hand-picked creator doing it, never only the word search
        for ex in fmt.real:
            assert re.fullmatch(r"[A-Za-z0-9_-]{11}", ex.video_id), ex
            assert ex.url == f"https://www.youtube.com/shorts/{ex.video_id}"
            assert ex.channel.startswith("@") and ex.title and ex.watch.endswith(".")
            assert "\u2014" not in ex.watch and "--" not in ex.watch


def test_a_yes_goes_on_big_ideas_and_survives_a_hook_save(store):
    assert format_library.wanted(WS) == []
    kept = run(format_library.decide(WS, GBB.id, "want"))
    assert kept["choice"] == "want"
    run(library.toggle_favorite(WS, "big-number", True))  # a hook write must not erase the yes
    ideas = format_library.wanted(WS)
    assert [i["id"] for i in ideas] == [GBB.id] and ideas[0]["name"] == GBB.name
    run(format_library.decide(WS, GBB.id, "pass"))
    assert format_library.wanted(WS) == []  # a no is kept, but it is not a big idea
    assert library.read_store(WS)["format_wants"][GBB.id]["choice"] == "pass"
    run(format_library.decide(WS, GBB.id, None))
    assert GBB.id not in library.read_store(WS)["format_wants"]
    with pytest.raises(library.HookError):
        run(format_library.decide(WS, GBB.id, "maybe"))
    with pytest.raises(library.HookError):
        run(format_library.decide(WS, "nope", "want"))


def test_api_decide_answers_with_the_page_and_writes_nothing_on_a_video(monkeypatch, store):
    tasks = []
    client = _client(monkeypatch, tasks=tasks)
    page = client.get("/api/v1/hooks").json()
    card = page["formats"][0]
    assert page["big_ideas"] == [] and card["decision"] is None
    real = card["real"][0]
    assert real["url"].startswith("https://www.youtube.com/shorts/") and len(real["frames"]) == 3
    assert real["embed"].startswith("https://www.youtube-nocookie.com/embed/" + real["video_id"])
    got = client.post(f"/api/v1/hooks/formats/{GBB.id}/decide", json={"choice": "want"})
    assert got.status_code == 200
    body = got.json()
    assert body["formats"][0]["decision"] == "want" and [i["trend_id"] for i in body["big_ideas"]] == [GBB.id]
    assert body["big_ideas"][0]["idea_state"] == "writing"
    # no video and no script from a yes: only TCE's idea, in the background
    assert body["formats"][0]["pick"] is None and [t[0] for t in tasks] == ["think"] and tasks[0][3] == GBB.id
    assert client.get("/api/v1/hooks/trend-ideas").json()["trends"][0]["trend"] == GBB.name
    assert client.post(f"/api/v1/hooks/formats/{GBB.id}/decide", json={"choice": "dance"}).status_code == 400
    assert client.post("/api/v1/hooks/formats/nope/decide", json={"choice": "want"}).status_code == 404
    back = client.post(f"/api/v1/hooks/formats/{GBB.id}/decide", json={"choice": None}).json()
    assert back["formats"][0]["decision"] is None and back["big_ideas"] == []
    scoped = _client(monkeypatch, scoped=True)
    assert scoped.post(f"/api/v1/hooks/formats/{GBB.id}/decide", json={"choice": "want"}).status_code == 403


# ------------------------------------------------- T-26074: TCE's idea after a yes


IDEA = {
    "pillar": "Coaching", "topic": "How to price a package", "existing_topic": True,
    "why": "Three ways to price fits three steps.",
    "idea": "Three ways to price a coaching package, from an hourly rate to a monthly plan.",
    "steps": [{"step": s.id, "line": f"Line for {s.label}"} for s in GBB.steps],
    "confirm": ["That you moved clients to a monthly plan this year"],
}


def test_the_idea_writer_reads_pillars_and_topics_and_is_batch_work():
    from tce.llm import queue
    from tce.hooks import trend_idea

    assert trend_idea.JOB_TYPE not in queue.INTERACTIVE_JOB_TYPES  # nobody waits on it
    prompt = trend_idea.build_prompt(GBB, ["Build", "Coaching"], ["How to price a package"])
    assert "Good, better, best" in prompt and "- Coaching" in prompt and "- How to price a package" in prompt
    assert all(f'"step": "{s.id}"' in prompt for s in GBB.steps)
    assert trend_idea.pillars_for(WS) == ["Build", "Coaching", "News that excites Ziv"]
    assert "Never invent facts" in trend_idea.SYSTEM and "confirm" in trend_idea.SYSTEM


def test_clean_keeps_a_whole_idea_and_refuses_a_missing_step():
    from tce.hooks import trend_idea

    got = trend_idea.clean(GBB, {**IDEA, "idea": "Three ways \u2014 to price."})
    assert got["topic"] == "How to price a package" and "\u2014" not in got["idea"]
    assert [s["step"] for s in got["steps"]] == [s.id for s in GBB.steps] and got["confirm"]
    assert trend_idea.clean(GBB, {**IDEA, "steps": IDEA["steps"][:-1]}) is None
    assert trend_idea.clean(GBB, {**IDEA, "topic": ""}) is None
    assert trend_idea.clean(GBB, "not json") is None


def test_think_keeps_the_idea_on_the_yes_and_a_no_meanwhile_wins(store, monkeypatch):
    from tce.hooks import trend_idea

    seen = {}

    async def complete(request):
        seen["job"] = request.job_type
        return types.SimpleNamespace(structured=IDEA, text="")

    async def topics(_sm, _ws):
        return ["How to price a package"]

    monkeypatch.setattr(trend_idea._llm, "complete", complete)
    monkeypatch.setattr(trend_idea, "recent_topics", topics)
    run(format_library.decide(WS, GBB.id, "want"))
    idea = run(trend_idea.think(None, WS, GBB.id))
    assert idea["state"] == "ready" and seen["job"] == "trend_idea"
    ready = trend_idea.ready_ideas(WS)
    assert ready[0]["idea_state"] == "ready" and ready[0]["idea"]["topic"] == "How to price a package"
    run(library.toggle_favorite(WS, "big-number", True))  # a hook write keeps the idea
    assert trend_idea.ready_ideas(WS)[0]["idea"]["confirm"] == IDEA["confirm"]
    run(format_library.decide(WS, GBB.id, "pass"))
    assert run(trend_idea.save(WS, GBB.id, {"state": "ready"})) is False  # a late writer never revives a no
    assert trend_idea.ready_ideas(WS) == []


def test_think_says_a_failure_plainly(store, monkeypatch):
    from tce.hooks import trend_idea

    async def broken(request):
        raise RuntimeError("busy")

    async def topics(_sm, _ws):
        return []

    monkeypatch.setattr(trend_idea._llm, "complete", broken)
    monkeypatch.setattr(trend_idea, "recent_topics", topics)
    run(format_library.decide(WS, GBB.id, "want"))
    assert run(trend_idea.think(None, WS, GBB.id))["state"] == "failed"
    assert trend_idea.ready_ideas(WS)[0]["idea_state"] == "failed"
