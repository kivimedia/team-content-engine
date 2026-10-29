"""Laughs stay in the edit (29-Oct, Ziv on Connie's videos: "dont cut out her laughs!").

The cut keeps words, and a laugh has none: in "Get your ask in gear" (upload 6584bd50) the
laugh after "Well, guess what?" (detector 38.87-40.08, 0.98) was 0 % in the edit, the keep
jumping from 38.73 straight to 40.70. The words, keep and laugh below are that video's.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tce.production import autoedit, laughs, qc
from tce.production.retakes import plan_edit

# "... feel humiliated. Well, guess what? [laughs] In sales, we humiliate ourselves often,"
WORDS = [
    {"text": "feel", "start_s": 34.93, "end_s": 35.91},
    {"text": "humiliated.", "start_s": 35.91, "end_s": 36.99},
    {"text": "Well,", "start_s": 37.27, "end_s": 37.91},
    {"text": "guess", "start_s": 37.95, "end_s": 38.19},
    {"text": "what?", "start_s": 38.19, "end_s": 38.59},
    {"text": "In", "start_s": 40.13, "end_s": 40.93},
    {"text": "sales,", "start_s": 40.93, "end_s": 41.51},
    {"text": "we", "start_s": 41.89, "end_s": 42.83},
    {"text": "humiliate", "start_s": 42.83, "end_s": 43.63},
]
KEEP = [[35.266667, 36.2], [36.333333, 37.1], [37.766667, 38.266667], [38.3, 38.733333],
        [40.7, 41.833333], [42.6, 45.0]]
LAUGH = [38.874, 40.083, 0.976]


def played(a, b, keep):
    return laughs.played(a, b, keep)


def test_the_laugh_after_guess_what_goes_back_in():
    assert played(LAUGH[0], LAUGH[1], KEEP) == 0.0  # the edit Ziv watched
    keep, lines = laughs.keep_laughs(KEEP, [LAUGH], [], 60.0)
    assert played(LAUGH[0], LAUGH[1], keep) >= (LAUGH[1] - LAUGH[0]) - 1e-6
    assert lines == [{"start": 38.874, "end": 40.083, "peak": 0.98, "kept": True,
                      "why": "put back beside the words"}]
    # "what?" runs straight into the laugh (0.06 s apart: no cut); the 0.54 s after it,
    # before "In", is cut as any pause that long is.
    assert [38.3, 40.166667] in keep
    assert [40.7, 41.833333] in keep
    # Everything that was in the edit still is.
    for a, b in KEEP:
        assert played(a, b, keep) >= (b - a) - 1e-6


def test_the_plan_keeps_it_and_says_so():
    without = plan_edit(WORDS, [], duration_s=60.0)
    assert played(LAUGH[0], LAUGH[1], without["keep"]) < 0.3  # the bug: the laugh is a pause
    assert "laughs" not in without  # no detector = the plan exactly as before
    plan = plan_edit(WORDS, [], duration_s=60.0, laughs=[LAUGH])
    assert played(LAUGH[0], LAUGH[1], plan["keep"]) >= (LAUGH[1] - LAUGH[0]) - 1e-6
    assert plan["laughs"][0]["kept"] is True
    assert not any(d["reason"] == "pause" and d["start"] < 39.5 < d["end"] for d in plan["dropped"])
    assert plan["kept_text"] == without["kept_text"]  # a laugh adds no words


def test_a_laugh_over_a_take_the_edit_removed_stays_out():
    keep, lines = laughs.keep_laughs(KEEP, [LAUGH], [[39.0, 39.6]], 60.0)
    assert keep == [[round(a, 6), round(b, 6)] for a, b in KEEP]
    assert lines[0]["kept"] is False and lines[0]["why"] == "over words the edit took out"


def test_a_cut_he_asked_for_keeps_the_laugh_out():
    plan = plan_edit(WORDS, [], duration_s=60.0, laughs=[LAUGH],
                     overrides={"cut": [[38.8, 40.1]]})
    assert played(LAUGH[0], LAUGH[1], plan["keep"]) < 0.3
    assert plan["laughs"][0]["kept"] is False


def test_a_trim_asked_for_wins_over_the_laugh():
    plan = plan_edit(WORDS, [], duration_s=60.0, laughs=[LAUGH],
                     overrides={"trim": [[38.75, 40.1]]})
    assert played(LAUGH[0], LAUGH[1], plan["keep"]) < 0.1
    assert plan["laughs"][0] == {**plan["laughs"][0], "kept": False, "why": "taken out on request"}


def test_a_laugh_far_from_anything_kept_stays_out():
    keep, lines = laughs.keep_laughs([[10.0, 12.0]], [[2.0, 3.0, 0.9]], [], 60.0)
    assert keep == [[10.0, 12.0]]
    assert lines[0]["why"] == "not beside anything kept"


def test_a_laugh_inside_her_words_is_left_alone():
    keep, lines = laughs.keep_laughs(KEEP, [[42.7, 43.0, 0.66]], [], 60.0)
    assert keep == [[round(a, 6), round(b, 6)] for a, b in KEEP]
    assert lines[0]["why"] == "already in the edit"


def test_a_laugh_starting_inside_a_kept_range_does_not_reopen_the_cut_before_it():
    # "The counterfeit yes" (54b488ad): 7.63-8.00 began inside [7.4, 7.933]; the cut
    # 7.333-7.4 before it is not the laugh's and stays.
    keep, _ = laughs.keep_laughs([[6.233, 7.333], [7.4, 7.933], [8.6, 9.967]],
                                 [[7.626, 7.998, 0.88]], [], 60.0)
    assert keep[0] == [6.233, 7.333]
    assert played(7.626, 7.998, keep) >= 0.37
    assert keep[1] == [7.4, 8.1]  # its tail, then the usual cut before "I'll call you"
    assert keep[2] == [8.6, 9.967]


def test_the_editor_reads_a_kept_laugh_as_a_laugh_not_dead_air():
    keep, _ = laughs.keep_laughs(KEEP, [LAUGH], [], 60.0)
    text = autoedit.numbered_transcript(WORDS, keep, laughs=[LAUGH[:2]])
    assert "4:what? /laughs" in text
    assert "/quiet" not in text
    # Without the laugh list the same stretch reads as a pause, as before.
    assert "4:what? /quiet" in autoedit.numbered_transcript(WORDS, keep)


def test_the_cache_answers_only_for_the_same_recording(tmp_path):
    src = tmp_path / "canonical.mp4"
    src.write_bytes(b"x" * 10)
    cache = tmp_path / ".canonical-laughs.json"
    cache.write_text(json.dumps({"key": "1:2", "laughs": [[1, 2, 0.9]]}))
    assert laughs.cached(src) is None  # another file's answer
    stat = src.stat()
    cache.write_text(json.dumps({"key": f"{stat.st_size}:{int(stat.st_mtime)}", "laughs": [[1, 2, 0.9]]}))
    assert laughs.cached(src) == [[1.0, 2.0, 0.9]]


def test_no_detector_configured_means_no_laughs(monkeypatch):
    monkeypatch.setattr(laughs.settings, "production_laugh_python", "")
    assert laughs.configured() is False


def test_jennifers_check_does_not_trim_a_kept_laugh_as_dead_air():
    # 29-Oct, the first re-edit of 6584bd50: the cut kept the laugh, then the check heard
    # "nobody says anything for 1.6 seconds at 0:25 (only background sound)" and its fix
    # trimmed [38.71, 40.167] straight back out. Edit clock: "what?" ends 25.3, "In" 26.95.
    words = [{"text": "what?", "start": 24.9, "end": 25.3}, {"text": "In", "start": 26.95, "end": 27.5}]
    heard = [dict(w) for w in words]
    # Loud throughout but for single quiet frames (a noise floor for the level reading),
    # so only the re-listen can find the gap, as on the real video (a laugh is loud).
    levels = [-60.0 if i % 8 == 0 else -3.0 for i in range(int(30 / qc.tightcut.HOP_S))]
    without = qc.check_gaps(levels, words, keep=[[0.0, 30.0]], heard=heard)
    assert without["gaps"] == 1 and "nobody says anything" in without["problems"][0]["detail"]
    laughs_edit = qc.laughs_on_edit([[25.35, 26.56]], [[0.0, 30.0]])
    assert laughs_edit == [(25.35, 26.56)]
    kept = qc.check_gaps(levels, words, keep=[[0.0, 30.0]], heard=heard, laughs=laughs_edit)
    assert kept["gaps"] == 0 and kept["problems"] == []
    # A laugh the edit does not play leaves nothing on the edit clock.
    assert qc.laughs_on_edit([[38.874, 40.083]], KEEP) == []


def _worker():
    path = Path(__file__).resolve().parents[2] / "scripts" / "laugh_worker.py"
    spec = importlib.util.spec_from_file_location("laugh_worker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_worker_joins_close_windows_and_drops_unsure_runs():
    w = _worker()
    step = 0.093
    times = [1.0, 1.093, 1.186, 1.6, 3.0, 3.093]
    probs = [0.7, 0.4, 0.9, 0.55, 0.52, 0.55]
    # 1.0 and 1.186 join across one low window; 1.6 is 0.37 s on, its own run; 3.0-3.1 never
    # reaches MIN_PEAK.
    [run] = w.runs(times, probs, step)
    assert run == pytest.approx([0.9535, 1.2325, 0.9], abs=1e-3)
