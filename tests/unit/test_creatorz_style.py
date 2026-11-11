"""The per-video style choice: Pill (today's look, the default) or Creatorz (10-Nov-2026).

Creatorz styles TCE's own keep, on TCE's own frame clock, so everything that reads a render's
keep (notes, Jennifer's check, the subtitles) keeps working. The engine and the subscription
worker are replaced here; the engine's own logic has its own suite, run below."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.editorial import library
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.production import autoedit
from tce.production.creatorz import reels
from tce.production.retakes import EDIT_FPS, frame_keep
from tce.settings import settings

KEY = "test-editor-key"
WS = uuid.UUID("aaaaaaaa-1111-4111-8111-111111111111")
OTHER_WS = uuid.UUID("bbbbbbbb-2222-4222-8222-222222222222")
AUTH = {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(WS)}
ENGINE = Path(reels.__file__).parent / "engine"


def tce_words(text, start=1.0, step=0.5):
    return [{"text": w, "start": start + i * step, "end": start + i * step + 0.42, "index": i} for i, w in enumerate(text.split())]


WORDS = tce_words("Most owners never count who came back. That number is the job.")
KEEP = [[0.95, 4.6], [4.7, 7.6]]


def shots():
    return reels.shots_for(KEEP, reels.engine_words(WORDS))


# ---------------------------------------------------------------- the engine's own suite
def test_the_engine_suite_runs_and_passes():
    done = subprocess.run(
        [sys.executable, "-I", "-m", "unittest", "discover", "-s", str(ENGINE), "-t", str(ENGINE), "-p", "*_test.py"],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr[-800:]
    ran = re.search(r"Ran (\d+) tests", done.stderr)
    assert ran and int(ran.group(1)) >= 79, done.stderr[-300:]  # a suite that found nothing must not pass


# ---------------------------------------------------------------- the choice
def test_no_style_means_pill():
    assert reels.style_of({}) == "pill"
    assert reels.style_of({"overrides": {"cut": []}}) == "pill"
    assert reels.style_of({"overrides": {"style": "creatorz"}}) == "creatorz"
    assert reels.style_of({"overrides": {"style": "nonsense"}}) == "pill"


def test_the_choice_is_only_offered_to_listed_workspaces(monkeypatch):
    monkeypatch.setattr(settings, "production_creatorz_workspaces", "")
    assert not reels.enabled_for(WS)
    monkeypatch.setattr(settings, "production_creatorz_workspaces", f"not-a-uuid, {WS}")
    assert reels.enabled_for(WS) and reels.enabled_for(str(WS)) and not reels.enabled_for(OTHER_WS)
    monkeypatch.setattr(settings, "production_creatorz_workspaces", "*")
    assert reels.enabled_for(OTHER_WS)


def test_a_later_note_keeps_the_style():
    # merge_overrides rebuilds the dict from the keys it knows: the choice must survive his next note
    merged = autoedit.merge_overrides({"style": "creatorz", "cut": [[1.0, 2.0]]}, [[3.0, 4.0]], [])
    assert merged["style"] == "creatorz"
    assert "style" not in autoedit.merge_overrides({"cut": []}, [], [])


# ---------------------------------------------------------------- the plan the engine gets
def test_sound_markers_are_not_words():
    got = reels.engine_words([{"text": "[sound]", "start": 1.0, "end": 2.0}, {"text": "hi", "start": 2.0, "end": 2.4}])
    assert got == [{"text": "hi", "start_s": 2.0, "end_s": 2.4}]


def test_the_reel_runs_on_tces_own_frame_clock():
    # joined back up, the shots are exactly the keep the render's readers expect
    joined: list[list[float]] = []
    for s in shots():
        if joined and abs(joined[-1][1] - s["src_in"]) < 1e-6:
            joined[-1][1] = s["src_out"]
        else:
            joined.append([s["src_in"], s["src_out"]])
    assert joined == frame_keep(KEEP)


def test_the_reel_plan_is_exact_and_loads_in_the_engine(tmp_path):
    from tce.production.creatorz.engine.creatorz_reel import plan as engine_plan

    raw = reels.reel_plan(
        src=tmp_path / "raw.mp4", words_path=tmp_path / "w.json", keep=KEEP, lang="he", work=tmp_path / "work",
        moments=[{"type": "tag", "text": "x", "at": {"pick": 0, "at": "start"}}], punchline=1, bed=tmp_path / "b.mp3",
    )
    plan = engine_plan.normalize(raw, str(tmp_path))
    assert plan["exact"] is True and plan["fps"] == EDIT_FPS and plan["lang"] == "he"
    assert plan["picks"] == [{"span": KEEP[0]}, {"span": KEEP[1]}]
    assert plan["length_range"][1] >= 600  # a full edit, not a 40 second reel
    assert plan["punchline"] == 1 and plan["bed"] == str(tmp_path / "b.mp3")


# ---------------------------------------------------------------- the pace
def levels_for(voiced, seconds=10.0):
    """10 ms levels: speech at -20 dB inside each (start, end), air at -60 elsewhere."""
    return [-20.0 if any(a <= i / 100 < b for a, b in voiced) else -60.0 for i in range(int(seconds * 100))]


def word(text, start, end):
    return {"text": text, "start_s": start, "end_s": end}


def test_the_air_at_the_edges_of_a_kept_range_goes():
    # 445b0c26: 12.3 s of its 81 s were air at the edges of TCE's kept ranges
    got = reels.tighten_keep([[1.0, 4.0]], levels_for([(1.5, 3.2)]), [word("hi", 1.6, 3.0)])
    assert got == [[1.45, 3.28]]


def test_a_real_pause_inside_a_range_becomes_a_jump_cut():
    got = reels.tighten_keep([[1.0, 5.0]], levels_for([(1.2, 2.0), (3.0, 4.0)]), [word("a", 1.3, 1.9), word("b", 3.1, 3.9)])
    assert got == [[1.15, 2.08], [2.95, 4.08]]


def test_a_breath_of_a_gap_stays_inside_the_line():
    got = reels.tighten_keep([[1.0, 3.0]], levels_for([(1.2, 1.8), (1.95, 2.8)]), [word("a", 1.3, 2.7)])
    assert got == [[1.15, 2.88]]


def test_an_edge_follows_a_soft_start_and_tail_down_to_the_recording_s_floor():
    # 445b0c26: "It" starts at -50 dB, 100 ms before the meter's -40 dB: a soft start is speech, not air
    levels = [-60.0] * 130 + [-50.0] * 20 + [-20.0] * 50 + [-50.0] * 20 + [-60.0] * 80
    assert reels.tighten_keep([[1.0, 3.0]], levels, [word("it", 1.5, 2.0)], edge_db=-55.0) == [[1.25, 2.28]]
    assert reels.tighten_keep([[1.0, 3.0]], levels, [word("it", 1.5, 2.0)]) == [[1.45, 2.08]]  # no floor given: the meter alone


def test_an_edge_never_walks_further_than_a_breath():
    levels = [-50.0] * 300  # a noisy recording never reaches its floor: the edge stops within reach
    levels[150:200] = [-20.0] * 50
    got = reels.tighten_keep([[0.5, 3.0]], levels, [word("a", 1.5, 2.0)], edge_db=-55.0)
    assert got == [[1.1, 2.43]]


def test_a_cut_never_lands_inside_a_word():
    # Jennifer on 445b0c26: "the cut at 0:13 starts inside You", "agents. is cut short": only the loud middle of the
    # word cleared the meter, so its soft start and tail were cut as air
    got = reels.tighten_keep([[1.0, 3.0]], levels_for([(1.5, 2.0)]), [word("you", 1.3, 2.4)])
    assert got == [[1.25, 2.48]]


def test_her_transcript_times_count_as_the_word_too():
    # her check reads the transcript's times, which can be wider than the plan's
    got = reels.tighten_keep(
        [[1.0, 3.0]], levels_for([(1.5, 2.0)]), [word("you", 1.5, 2.0)], transcript=[word("you", 1.3, 2.4)]
    )
    assert got == [[1.25, 2.48]]


def test_a_first_word_stretched_back_over_silence_still_counts():
    # 445b0c26: "It" is 13.95-14.63 in the transcript, so its middle is before the kept range that starts at 14.4
    levels = levels_for([(14.55, 15.5)], seconds=20.0)
    got = reels.tighten_keep([[14.4, 16.0]], levels, [word("next", 14.7, 15.4)], transcript=[word("It", 13.95, 14.63)])
    assert got[0][0] == 14.4


def test_a_word_cut_by_the_edit_itself_cannot_push_past_the_range():
    assert reels.tighten_keep([[1.5, 2.2]], levels_for([(1.6, 2.0)]), [word("you", 1.3, 2.6)]) == [[1.5, 2.2]]


def test_a_range_of_pure_air_is_dropped():
    assert reels.tighten_keep([[1.0, 2.0], [3.0, 3.5]], levels_for([(1.2, 1.8)]), [word("a", 1.3, 1.7)]) == [[1.15, 1.88]]


def test_a_word_too_quiet_for_the_meter_keeps_its_place():
    # a whisper under the threshold is still something he said
    got = reels.tighten_keep([[1.0, 4.0]], levels_for([(1.2, 1.8)]), [word("a", 1.3, 1.7), word("whisper", 3.0, 3.5)])
    assert got == [[1.15, 1.88], [2.95, 3.58]]


def test_a_kept_laugh_stays_and_only_the_air_around_it_goes():
    # kept on purpose, and it may be quieter than speech (TCE b3a0456); protecting its whole range kept 6 s of air on 445b0c26
    assert reels.tighten_keep([[1.0, 3.0]], levels_for([]), [], protect=[[1.5, 2.5]]) == [[1.5, 2.5]]
    got = reels.tighten_keep([[1.0, 5.0]], levels_for([(1.2, 1.8)]), [word("a", 1.3, 1.7)], protect=[[3.0, 3.6]])
    assert got == [[1.15, 1.88], [3.0, 3.6]]


def test_a_pause_at_the_edge_of_voice_never_passes_the_range():
    assert reels.tighten_keep([[1.5, 3.0]], levels_for([(1.0, 4.0)]), [word("a", 1.6, 2.9)]) == [[1.5, 3.0]]


def test_no_bed_library_means_no_bed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "production_creatorz_beds_dir", "")
    assert reels.bed_for(uuid.uuid4()) is None
    monkeypatch.setattr(settings, "production_creatorz_beds_dir", str(tmp_path))
    assert reels.bed_for(uuid.uuid4()) is None
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "b.mp3").write_bytes(b"x")
    uid = uuid.uuid4()
    first = reels.bed_for(uid)
    assert first and first == reels.bed_for(uid)  # the same video keeps its music across re-renders


# ---------------------------------------------------------------- the moments
def at(pick, word):
    return {"pick": pick, "word": word}


def test_a_cue_on_a_word_the_line_does_not_say_is_dropped_and_named():
    good = {"type": "headline", "text": "COUNT", "place": "top", "at": at(0, "count")}
    bad = {"type": "headline", "text": "PRICE", "place": "chest", "at": at(0, "price")}
    moments, problems = reels.clean_moments([good, bad], shots(), "en")
    assert [m["text"] for m in moments] == ["COUNT"]
    assert len(problems) == 1 and "price" in problems[0]


def test_unknown_fields_and_bad_values_never_reach_the_engine():
    raw = {
        "type": "headline", "text": "COUNT", "place": "orbit", "color": "pink", "look": "neon", "sound": "airhorn",
        "pos": [1, 2], "evil": True, "at": at(0, "count"),
    }
    moments, _ = reels.clean_moments([raw], shots(), "en")
    assert moments == [{"type": "headline", "text": "COUNT", "look": "neon", "place": "top", "at": at(0, "count")}]


def test_a_strike_follows_its_headline_when_an_earlier_moment_is_dropped():
    raw = [
        {"type": "headline", "text": "GONE", "place": "chest", "at": at(0, "price")},
        {"type": "headline", "text": "COUNT", "place": "top", "at": at(0, "count")},
        {"type": "strike", "target": 1, "at": at(1, "came")},
    ]
    moments, problems = reels.clean_moments(raw, shots(), "en")
    assert [m["type"] for m in moments] == ["headline", "strike"] and moments[1]["target"] == 0
    assert len(problems) == 1


def test_a_strike_with_no_headline_is_dropped():
    raw = [{"type": "strike", "target": 7, "at": at(0, "count")}, {"type": "tag", "text": "x", "at": at(0, "count")}]
    moments, problems = reels.clean_moments(raw, shots(), "en")
    assert [m["type"] for m in moments] == ["tag"] and "strike" in problems[0]


def test_two_moments_in_one_place_at_once_keep_the_first():
    raw = [
        {"type": "headline", "text": "ONE", "place": "chest", "at": at(0, "most")},
        {"type": "pair", "light": "a", "bold": "TWO", "at": at(0, "owners")},
    ]
    moments, problems = reels.clean_moments(raw, shots(), "en")
    assert [m.get("text") for m in moments] == ["ONE"] and "overlaps" in problems[0]


def test_a_headline_holds_the_caption_line_for_one_beat_then_it_is_free():
    # 10-Nov: a headline on the caption line lasts a beat (1.2 s), not its whole line, so the
    # next thing in the middle of the screen a moment later is no clash
    raw = [
        {"type": "headline", "text": "ONE", "place": "chest", "at": at(0, "most")},
        {"type": "pair", "light": "a", "bold": "TWO", "at": at(1, "back.")},
    ]
    moments, problems = reels.clean_moments(raw, shots(), "en")
    assert [m["type"] for m in moments] == ["headline", "pair"] and problems == []


def test_the_new_cutaways_reach_the_engine_and_stay_rare():
    # 10-Nov: 74 seconds of face and nothing else. A full-screen number and a whip across a
    # cut are allowed; more than a couple stop being cutaways.
    raw = [
        {"type": "card_stat", "text": 80, "label": "came back", "at": at(0, "count")},
        {"type": "whip", "at": {"pick": 2, "at": "start"}},
        {"type": "card_stat", "text": "3x", "at": at(2, "number")},
        {"type": "card_stat", "text": "9", "at": at(1, "who")},
        {"type": "card_stat", "text": "1234567", "at": at(1, "came")},
    ]
    moments, problems = reels.clean_moments(raw, shots(), "en")
    assert [m["type"] for m in moments] == ["card_stat", "whip", "card_stat"]
    assert moments[0]["text"] == "80"  # a number the writer sent as a number
    assert any("at most 2" in p for p in problems) and any("one short number" in p for p in problems)


def test_a_tag_that_repeats_his_words_goes_back_to_the_writer():
    # 11-Nov, Ziv at 0:06: the tag "our own delivery" sat right above the caption "in our own
    # delivery." ("its weird to show twice the same caption"). A tag names what comes next.
    raw = [
        {"type": "tag", "text": "who came back", "at": at(1, "who")},
        {"type": "tag", "text": "the job:", "at": at(2, "That")},
    ]
    moments, problems = reels.clean_moments(raw, shots(), "en")
    assert [m["text"] for m in moments] == ["the job:"]  # one word he says is a chapter label, the style
    assert len(problems) == 1 and "repeats what he says" in problems[0]
    assert "never the words of the line" in reels.MOMENTS_SYSTEM


def test_one_accent_color_is_the_only_color_the_writer_is_offered():
    assert '"white" or "accent"' in reels.MOMENTS_SYSTEM
    for old in ("yellow", "green", "cyan"):
        assert old not in reels.MOMENTS_SYSTEM
    # saved plans from before still name the old colors: they are kept and drawn as the accent
    kept, _ = reels.clean_moments(
        [{"type": "headline", "text": "A", "color": "green", "place": "top", "at": at(0, "count")},
         {"type": "headline", "text": "B", "color": "accent", "place": "top", "at": at(1, "back.")},
         {"type": "headline", "text": "C", "color": "purple", "place": "top", "at": at(2, "job.")}],
        shots(), "en",
    )
    assert [m.get("color") for m in kept] == ["green", "accent", None]


def test_rubbish_in_the_list_is_ignored():
    moments, problems = reels.clean_moments(["x", {"type": "dissolve", "at": at(0, "count")}], shots(), "en")
    assert moments == [] and len(problems) == 2


async def test_a_bad_answer_is_asked_again_once_then_what_is_good_goes_ahead():
    good = {"type": "headline", "text": "COUNT", "place": "top", "at": at(0, "count")}
    bad = {"type": "tag", "text": "x", "at": at(0, "price")}
    prompts: list[str] = []

    async def ask(prompt, system, schema, attempt):
        prompts.append(prompt)
        return {"moments": [good, bad], "punchline": 1}

    got = await reels.get_moments(shots(), "en", ask)
    assert len(prompts) == 2 and "price" in prompts[1]  # the second ask says what was wrong
    assert got == {"moments": [good], "punchline": 1}


async def test_a_clean_answer_is_not_asked_twice():
    calls = 0

    async def ask(prompt, system, schema, attempt):
        nonlocal calls
        calls += 1
        return {"moments": [{"type": "tag", "text": "x", "at": at(1, "who")}], "punchline": 99}

    got = await reels.get_moments(shots(), "en", ask)
    assert calls == 1 and got["punchline"] is None  # a punchline past the end means none


async def test_a_stretch_with_no_text_goes_back_to_the_writer_once():
    # 11-Nov: the writer let one headline "cover" several lines. A headline is a one-second
    # beat now, so 7 seconds of his real video had nothing on screen and the checklist failed.
    first = [{"type": "headline", "text": "MOST", "place": "top", "at": at(0, "Most")}]
    filled = first + [{"type": "tag", "text": "x", "at": at(2, "number")}]
    prompts: list[str] = []

    async def ask(prompt, system, schema, attempt):
        prompts.append(prompt)
        return {"moments": first if attempt == 0 else filled, "punchline": None}

    got = await reels.get_moments(shots(), "en", ask)
    assert len(prompts) == 2 and "nothing pops between" in prompts[1]
    assert got["moments"] == filled
    assert reels.quiet_gaps(first, shots(), "en") and not reels.quiet_gaps(filled, shots(), "en")


async def test_a_second_answer_with_more_holes_is_not_taken():
    full = [
        {"type": "headline", "text": "MOST", "place": "top", "at": at(0, "Most")},
        {"type": "tag", "text": "x", "at": at(2, "number")},
        {"type": "tag", "text": "y", "at": at(0, "price")},  # a bad cue, so it is asked again
    ]
    worse = [{"type": "headline", "text": "MOST", "place": "top", "at": at(0, "Most")}] * 1

    async def ask(prompt, system, schema, attempt):
        return {"moments": full if attempt == 0 else worse + [{"type": "flash", "at": at(0, "count")}], "punchline": None}

    got = await reels.get_moments(shots(), "en", ask)
    assert [m["type"] for m in got["moments"]] == ["headline", "tag"]


async def test_no_usable_moments_is_a_failure_not_a_bare_reel():
    async def ask(prompt, system, schema, attempt):
        return {"moments": []}

    with pytest.raises(reels.CreatorzFailed):
        await reels.get_moments(shots(), "en", ask)


async def test_an_engine_that_crashes_says_what_broke(tmp_path, monkeypatch):
    # a crash exits 1, the same code as a failed checklist line: the card must say the real error
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "reel.py").write_text(
        "import sys\nprint('cut: 3 shots, 2.0 s')\nprint('Traceback (most recent call last):')\n"
        "print(\"AttributeError: module 'cv2' has no attribute 'CascadeClassifier'\")\nsys.exit(1)\n"
    )
    monkeypatch.setattr(reels, "ENGINE_DIR", engine)
    monkeypatch.setattr(reels, "_wrapper", lambda: [])
    monkeypatch.setattr(settings, "production_creatorz_python", "")
    said: list[str] = []

    async def status(text):
        said.append(text)

    with pytest.raises(reels.CreatorzFailed) as failed:
        await reels.render_reel(
            src=tmp_path / "raw.mp4", words=reels.engine_words(WORDS), keep=KEEP, lang="en", work=tmp_path / "work",
            moments=[], punchline=None, bed=None, on_status=status,
        )
    assert "CascadeClassifier" in str(failed.value)
    assert any("3 shots" in s for s in said)


def test_progress_lines_say_what_is_happening():
    assert "18 shots" in reels.progress_sentence("cut: 18 shots, 39.72 s")
    assert "200 of 1000" in reels.progress_sentence("compose: frame 200/1000")
    assert "100 of 300" in reels.progress_sentence("masks: 100/300 (12 s)")
    assert "mixing" in reels.progress_sentence("mix: 32 cues, bed on -> x.mp4").lower()
    assert "measuring" in reels.progress_sentence("PASS  loudness -14 LUFS +/- 1: -14.38 LUFS").lower()
    assert reels.progress_sentence("something else entirely") is None


# ---------------------------------------------------------------- the render
@pytest.fixture
def wired(monkeypatch, editorial_sessionmaker):
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)

    async def fake_size(_src):
        return (1080, 1920)

    async def no_levels(_src, hiss=False):
        return None

    monkeypatch.setattr(prod.media, "probe_video_size", fake_size)
    monkeypatch.setattr(prod, "_levels", no_levels)
    calls = {"pill": [], "reel": [], "light": []}

    async def fake_render(src, keep, out, **kw):
        calls["pill"].append({"keep": keep, "kw": kw})
        Path(out).write_bytes(b"pill")
        return Path(out)

    async def fake_light(out, on_status):
        calls["light"].append(str(out))

    monkeypatch.setattr(prod.media, "render_edit", fake_render)
    monkeypatch.setattr(prod.media, "make_light_copy", fake_light)
    return {"sm": editorial_sessionmaker, "calls": calls}


async def seed(sm, src, *, overrides=None, ws=WS, edited=None, status="rendering", extra=None):
    plan = {"keep": KEEP, "words": WORDS, "stats": {}, **(extra or {})}
    if overrides is not None:
        plan["overrides"] = overrides
    async with sm() as s:
        cand = TopicCandidate(
            workspace_id=ws, week_start=datetime(2026, 9, 28), moment_ids=["m"], title="t", lesson="l",
            audience="a", public_angle="p", gates={}, status="recorded",
        )
        s.add(cand)
        await s.flush()
        up = RecordingUpload(
            workspace_id=ws, candidate_id=cand.id, original_filename=src.name, storage_path=str(src),
            sha256=uuid.uuid4().hex * 2, status=status, transcript=[], duration_s=9.0, edit_plan=plan,
            edited_path=edited,
        )
        s.add(up)
        await s.flush()
        attempt = prod._claim(up, "rendering", "x") if status == "rendering" else ""
        await s.commit()
        return up.id, attempt


async def load(sm, uid) -> RecordingUpload:
    async with sm() as s:
        return await s.get(RecordingUpload, uid)


def fake_engine(monkeypatch, wired):
    async def fake_moments(shots_, lang, ask, **_kw):
        return {"moments": [{"type": "tag", "text": "x", "at": at(0, "count")}], "punchline": None}

    async def fake_reel(**kw):
        wired["calls"]["reel"].append(kw)
        work = Path(kw["work"])
        work.mkdir(parents=True, exist_ok=True)
        (work / "reel.mp4").write_bytes(b"creatorz")
        (work / "voice.wav").write_bytes(b"voice")
        return reels.ReelResult(
            out=work / "reel.mp4", voice=work / "voice.wav", shots=7,
            checklist=[["PASS", "a", "b"], ["FAIL", "c", "d"], ["INFO", "e", "f"]],
            captions=[[0.0, 1.5, "Most owners never"], [1.5, 3.0, "count who came back."]],
        )

    monkeypatch.setattr(reels, "get_moments", fake_moments)
    monkeypatch.setattr(reels, "render_reel", fake_reel)


async def test_a_video_with_no_style_renders_exactly_as_before(wired, tmp_path, monkeypatch):
    fake_engine(monkeypatch, wired)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    uid, attempt = await seed(wired["sm"], src)
    await prod._run_render(uid, WS, attempt, "cut")
    row = await load(wired["sm"], uid)
    assert row.status == "edited" and row.status_detail.startswith("Captioned MP4 ready")
    assert wired["calls"]["reel"] == [] and len(wired["calls"]["pill"]) == 1
    # the Pill call's arguments, and the sidecar's keys, are the ones it always had
    assert set(wired["calls"]["pill"][0]["kw"]) == {
        "on_status", "ass_text", "srt_text", "caption_band", "make_preview", "report", "denoise", "top_caption",
    }
    side = prod._read_render_sidecar(row.edited_path)
    assert set(side) == {"mode", "keep", "captions", "loudness", "denoise", "top_caption"}


async def test_creatorz_is_made_by_the_engine_on_the_same_clock(wired, tmp_path, monkeypatch):
    fake_engine(monkeypatch, wired)
    monkeypatch.setattr(settings, "production_creatorz_workspaces", str(WS))
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    uid, attempt = await seed(wired["sm"], src, overrides={"style": "creatorz"})
    await prod._run_render(uid, WS, attempt, "cut")
    row = await load(wired["sm"], uid)
    assert wired["calls"]["pill"] == [] and len(wired["calls"]["reel"]) == 1
    assert row.status == "edited" and row.status_detail.startswith("Creatorz style ready")
    assert "1 of 2" in row.status_detail  # the checklist, stated
    assert Path(row.edited_path).read_bytes() == b"creatorz" and wired["calls"]["light"] == [row.edited_path]
    assert row.rendered_keep == frame_keep(KEEP)
    side = prod._read_render_sidecar(row.edited_path)
    assert side["style"] == "creatorz" and side["keep"] == frame_keep(KEEP) and side["mode"] == "cut"
    assert [c["text"] for c in side["captions"]["cues"]] == ["Most owners never", "count who came back."]
    assert Path(prod.creatorz_voice_path(row.edited_path)).read_bytes() == b"voice"
    assert row.edit_plan["creatorz"]["moments"]  # a re-render does not ask again
    assert Path(row.captions_path).exists()


async def test_the_tightened_keep_is_the_render_s_own_clock(wired, tmp_path, monkeypatch):
    fake_engine(monkeypatch, wired)

    async def levels(_src, hiss=False):
        # speech only from 1.0 to 4.4 and from 4.75 to 6.9: the ends of both kept ranges are air
        return levels_for([(1.0, 4.4), (4.75, 6.9)])

    monkeypatch.setattr(prod, "_levels", levels)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    uid, attempt = await seed(wired["sm"], src, overrides={"style": "creatorz"})
    await prod._run_render(uid, WS, attempt, "cut")
    row = await load(wired["sm"], uid)
    tight = wired["calls"]["reel"][0]["keep"]
    assert tight == [[0.95, 4.48], [4.7, 6.98]] and tight != KEEP
    assert row.rendered_keep == frame_keep(tight)                         # the file's clock is what it was cut on
    assert prod._read_render_sidecar(row.edited_path)["keep"] == frame_keep(tight)
    assert row.edit_plan["keep"] == KEEP                                  # going back to Pill loses nothing
    assert library.watched_plan_words(row.edit_plan, row.rendered_keep)   # her check and his notes still get the words
    assert library.watched_plan_words(row.edit_plan, [[0.0, 1.0]]) is None
    assert row.edit_plan["creatorz"]["key"] == reels.moments_key(tight, reels.engine_words(WORDS))


async def test_creatorz_reuses_its_moments_while_the_edit_is_unchanged(wired, tmp_path, monkeypatch):
    fake_engine(monkeypatch, wired)

    async def no_ask(*_a, **_k):
        raise AssertionError("asked again")

    monkeypatch.setattr(reels, "get_moments", no_ask)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    key = reels.moments_key(KEEP, reels.engine_words(WORDS))
    cached = {"key": key, "moments": [{"type": "tag", "text": "kept", "at": at(0, "count")}], "punchline": None}
    uid, attempt = await seed(wired["sm"], src, overrides={"style": "creatorz"}, extra={"creatorz": cached})
    await prod._run_render(uid, WS, attempt, "cut")
    assert wired["calls"]["reel"][0]["moments"][0]["text"] == "kept"


async def test_when_creatorz_cannot_run_he_gets_pill_and_the_reason(wired, tmp_path, monkeypatch):
    fake_engine(monkeypatch, wired)

    async def nope(*_a, **_k):
        raise reels.CreatorzFailed("the writer of the text moments did not answer")

    monkeypatch.setattr(reels, "get_moments", nope)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    uid, attempt = await seed(wired["sm"], src, overrides={"style": "creatorz"})
    await prod._run_render(uid, WS, attempt, "cut")
    row = await load(wired["sm"], uid)
    assert row.status == "edited" and len(wired["calls"]["pill"]) == 1
    assert "did not answer" in row.status_detail and "Pill" in row.status_detail
    assert "style" not in prod._read_render_sidecar(row.edited_path)


async def test_a_sideways_recording_stays_pill_and_says_why(wired, tmp_path, monkeypatch):
    fake_engine(monkeypatch, wired)

    async def wide(_src):
        return (1920, 1080)

    monkeypatch.setattr(prod.media, "probe_video_size", wide)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    uid, attempt = await seed(wired["sm"], src, overrides={"style": "creatorz"})
    await prod._run_render(uid, WS, attempt, "cut")
    row = await load(wired["sm"], uid)
    assert wired["calls"]["reel"] == [] and "upright" in row.status_detail


async def test_the_uncut_version_is_never_styled(wired, tmp_path, monkeypatch):
    fake_engine(monkeypatch, wired)

    async def duration(_src):
        return 9.0

    monkeypatch.setattr(prod.media, "probe_duration", duration)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    uid, attempt = await seed(wired["sm"], src, overrides={"style": "creatorz"})
    await prod._run_render(uid, WS, attempt, "uncut")
    assert wired["calls"]["reel"] == []


def test_her_check_listens_to_the_voice_of_a_creatorz_render(tmp_path):
    # music and whooshes under the words must not read as words he did not say
    edited = tmp_path / "walk-edited.mp4"
    edited.write_bytes(b"x")
    voice = Path(prod.creatorz_voice_path(edited))
    assert prod.qc_listen_source(edited, {"style": "creatorz"}) == edited  # no voice track on disk
    voice.write_bytes(b"v")
    assert prod.qc_listen_source(edited, {"style": "creatorz"}) == voice
    assert prod.qc_listen_source(edited, {}) == edited  # a Pill render over an old Creatorz one


# ---------------------------------------------------------------- the choice in the Library
@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path / "rec"))
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    monkeypatch.setattr(settings, "production_creatorz_workspaces", str(WS))
    spawned: list = []

    def fake_spawn(coro):
        spawned.append(coro)
        coro.close()

    monkeypatch.setattr(prod, "_spawn", fake_spawn)
    app = FastAPI()
    app.include_router(prod.router, prefix="/api/v1")

    async def _db():
        async with editorial_sessionmaker() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        c.spawned = spawned
        yield c


def edited_file(tmp_path):
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    out = tmp_path / "walk-edited.mp4"
    out.write_bytes(b"edit")
    return src, out


async def test_choosing_creatorz_saves_it_and_starts_a_render(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await client.post(f"/api/v1/production/uploads/{uid}/style", json={"style": "creatorz"}, headers=AUTH)
    assert r.status_code == 202, r.text
    row = await load(editorial_sessionmaker, uid)
    assert row.edit_plan["overrides"]["style"] == "creatorz" and row.status == "rendering"
    assert "Creatorz" in row.status_detail and len(client.spawned) == 1


async def test_going_back_to_pill_takes_the_style_off(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited", overrides={"style": "creatorz", "denoise": "light"})
    r = await client.post(f"/api/v1/production/uploads/{uid}/style", json={"style": "pill"}, headers=AUTH)
    assert r.status_code == 202
    row = await load(editorial_sessionmaker, uid)
    assert row.edit_plan["overrides"] == {"denoise": "light"} and len(client.spawned) == 1


async def test_the_style_it_already_has_starts_nothing(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await client.post(f"/api/v1/production/uploads/{uid}/style", json={"style": "pill"}, headers=AUTH)
    assert r.status_code == 202 and client.spawned == []
    assert (await load(editorial_sessionmaker, uid)).status == "edited"


async def test_a_workspace_not_listed_cannot_choose(client, editorial_sessionmaker, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "production_creatorz_workspaces", "")
    src, out = edited_file(tmp_path)
    uid, _ = await seed(editorial_sessionmaker, src, edited=str(out), status="edited")
    r = await client.post(f"/api/v1/production/uploads/{uid}/style", json={"style": "creatorz"}, headers=AUTH)
    assert r.status_code == 404 and client.spawned == []


async def test_a_blocked_plan_cannot_be_restyled(client, editorial_sessionmaker, tmp_path):
    src, out = edited_file(tmp_path)
    uid, _ = await seed(
        editorial_sessionmaker, src, edited=str(out), status="edited", extra={"meaning_check": {"status": "blocked"}}
    )
    r = await client.post(f"/api/v1/production/uploads/{uid}/style", json={"style": "creatorz"}, headers=AUTH)
    assert r.status_code == 409 and client.spawned == []


def card(**kw):
    defaults = dict(
        workspace_id=WS, source=None, status="edited", edited_path="/x/e.mp4", storage_path="/x/s.mp4", transcript=[{"t": 1}],
        archived_at=None, edit_plan={}, qc=None, job_ids=[], status_detail="", id=uuid.uuid4(),
    )
    return RecordingUpload(**{**defaults, **kw})


def test_the_library_offers_the_style_only_where_it_is_on(monkeypatch):
    monkeypatch.setattr(settings, "production_creatorz_workspaces", str(WS))
    action = next(a for a in library._actions(card(), 0) if a["key"] == "style")
    assert action["current"] == "pill"
    chosen = card(edit_plan={"overrides": {"style": "creatorz"}})
    assert next(a for a in library._actions(chosen, 0) if a["key"] == "style")["current"] == "creatorz"
    assert not [a for a in library._actions(card(workspace_id=OTHER_WS), 0) if a["key"] == "style"]
    assert not [a for a in library._actions(card(edited_path=None), 0) if a["key"] == "style"]
    assert not [a for a in library._actions(card(status="rendering"), 0) if a["key"] == "style"]


def test_the_cached_moments_key_follows_the_edit():
    words = reels.engine_words(WORDS)
    assert reels.moments_key(KEEP, words) == reels.moments_key(json.loads(json.dumps(KEEP)), words)
    assert reels.moments_key([[0.95, 4.6]], words) != reels.moments_key(KEEP, words)
