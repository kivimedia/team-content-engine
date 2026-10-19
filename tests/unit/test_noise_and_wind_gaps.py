"""19-Oct: background-noise cleaning the editor can ask for, and windy silences the
automatic edit and Jennifer's check let through.

Measured on a walk in wind (upload 9a47ae1f): the wind sat under 300 Hz and was louder
than his voice, so the level reading took 4-8 s of it for speech; the cut kept it whole
because it touched a kept word, and the check's second listen smeared the words on
either side into the gap. "remove background noise that are loud" had no tool at all.
"""

from __future__ import annotations

import subprocess

import pytest

from tce.production import autoedit, media, qc, tightcut
from tce.production.tightcut import Activity, tight_keep


# ---------------------------------------------------------------- the automatic edit


def words_at(*items: tuple[str, float, float]) -> list[dict]:
    return [{"text": t, "start_s": s, "end_s": e, "precision": "word"} for t, s, e in items]


def loud(seconds: float, level: float = -20.0) -> list[float]:
    return [level] * int(round(seconds / tightcut.HOP_S))


def test_wind_between_two_kept_words_is_not_kept_whole():
    # "... more. I [wind 4.9 s] recommend switching": the level never drops (wind louder
    # than his voice), and the recogniser stretched "I" over 1.2 s of it.
    words = words_at(("more.", 0.20, 0.56), ("I", 0.56, 1.76), ("recommend", 6.63, 7.03), ("switching", 7.03, 8.07))
    levels = loud(9.0)
    act = Activity([(0.0, 9.0)], -48.0, -58.0, levels)
    keep, _timed = tight_keep(words, [True] * 4, act, 9.0)
    played = sum(e - s for s, e in keep)
    assert played < 9.0 - 3.5, keep  # the 4.9 s between "I" and "recommend" is down to 0.6 s
    # Every word is still in the edit, whole.
    for w in words:
        mid = (w["start_s"] + w["end_s"]) / 2
        assert any(s <= mid <= e for s, e in keep), (w["text"], keep)


def test_a_stretched_word_keeps_its_whole_span():
    # Same walk, 4:49: he said "I ran... I ran Fable 5.1"; the recogniser merged the two
    # "I ran" and stretched "Fable" 2.4 s back over the second one. Where in that span
    # the word sounds is unknown (the first cut guessed its start, and took out the
    # repeated "I ran"), so nothing inside a word's own span is taken for wind.
    words = words_at(("I", 0.0, 0.44), ("ran", 0.44, 0.98), ("Fable", 0.98, 3.36), ("5", 3.36, 4.2))
    act = Activity([(0.0, 4.4)], -48.0, -58.0, loud(4.6))
    keep, _ = tight_keep(words, [True] * 4, act, 4.6)
    inside = sum(max(0.0, min(e, 3.36) - max(s, 0.98)) for s, e in keep)
    assert inside > 3.36 - 0.98 - 1e-6, keep


def test_speech_that_runs_on_between_words_is_left_alone():
    # Clean speech: one region, words back to back, no stretch far from a word.
    words = words_at(*[(t, 0.2 + 0.35 * k, 0.5 + 0.35 * k) for k, t in enumerate("so go and work for free".split())])
    act = Activity([(0.15, 2.4)], -48.0, -58.0, loud(3.0))
    keep, _ = tight_keep(words, [True] * len(words), act, 3.0)
    assert len(keep) == 1


# ---------------------------------------------------------------- Jennifer's check


def test_a_smeared_second_listen_does_not_hide_a_windy_gap():
    kept = [
        {"text": "accounts", "start": 3.1, "end": 3.6},
        {"text": "run", "start": 3.6, "end": 3.9},
        {"text": "out.", "start": 3.94, "end": 4.38},
        {"text": "Most", "start": 9.86, "end": 10.6},
        {"text": "business", "start": 10.62, "end": 11.0},
        {"text": "owners", "start": 11.0, "end": 11.6},
        {"text": "I", "start": 11.7, "end": 11.8},
        {"text": "coach", "start": 11.8, "end": 12.2},
    ]
    smeared = [{"text": t, "start": s, "end": s + 0.4} for t, s in
               [("out", 3.98), ("most", 4.4), ("owner", 5.6), ("i", 5.94), ("coach", 6.18)]]
    assert qc._wordless(kept, smeared, 14.0, 1.2) == [(4.38, 9.86)]
    # A word the transcript does not hold anywhere near still means someone talked there.
    other = smeared + [{"text": "banana", "start": 7.0, "end": 7.4}]
    assert qc._wordless(kept, other, 14.0, 1.2) == []


def test_short_words_only_match_exactly():
    assert qc._smeared("cloud", ["in", "your", "claude"])
    assert qc._smeared("inside", ["in", "your", "claude"])
    assert not qc._smeared("a", ["at", "the"])
    assert qc._smeared("a", ["at", "a"])


# ---------------------------------------------------------------- the noise tool


def test_the_editor_has_a_noise_tool_and_is_told_what_is_on_now():
    assert "- denoise:" in autoedit.EDIT_REQUEST_SYSTEM
    assert "denoise" in autoedit.EDIT_REQUEST_SCHEMA["required"]
    words = [{"text": "hi", "start_s": 0.0, "end_s": 0.4}]
    text = autoedit.edit_request_prompt(words, [[0.0, 1.0]], "ctx", "less wind", scope="whole",
                                        start_s=None, end_s=None, denoise_now="medium")
    assert "Background noise cleaning on this video now: medium." in text
    batch = autoedit.edit_batch_prompt(words, [[0.0, 1.0]], "ctx", [{"said": "x", "edit_s": 0.1, "source_s": 0.1}])
    assert "Background noise cleaning on this video now: off" in batch


def note(n, **kw):
    base = {"note": n, "reply": "ok", "needs_you": False, "question": "", "corrections": [],
            "cut": [], "restore": [], "hold": [], "trim": [], "denoise": "unchanged"}
    return {**base, **kw}


WORDS = [{"text": t, "start_s": k * 0.5, "end_s": k * 0.5 + 0.4} for k, t in enumerate("a b c d".split())]


def test_a_note_sets_the_cleaning_and_later_notes_keep_it():
    out = autoedit.apply_batch(WORDS, None, {"notes": [note(1, denoise="medium")]}, 1)
    assert out["changed"] and out["notes"][0]["outcome"] == "change"
    assert out["overrides"]["denoise"] == "medium"
    later = autoedit.merge_overrides(out["overrides"], [[0.0, 0.4]], [])
    assert later["denoise"] == "medium"
    off = autoedit.merge_overrides(later, [], [], denoise="off")
    assert "denoise" not in off and off["cut"] == [[0.0, 0.4]]


def test_asking_for_what_is_already_on_changes_nothing():
    now = {"cut": [], "restore": [], "denoise": "medium"}
    out = autoedit.apply_batch(WORDS, now, {"notes": [note(1, denoise="medium"), note(2, denoise="unchanged")]}, 2)
    assert not out["changed"] and [n["outcome"] for n in out["notes"]] == ["answer", "answer"]
    assert autoedit.noise_change(None, "off") is None
    assert autoedit.noise_change("strong", "off") == "off"


def test_the_levels_are_ffmpeg_chains_and_off_is_none():
    assert media.denoise_filter("off") is None and media.denoise_filter(None) is None
    assert set(media.DENOISE_FILTERS) == set(autoedit.DENOISE_LEVELS)


def _band_db(path, flt: str) -> float:
    out = subprocess.run(
        [media.ffmpeg_path(), "-v", "error", "-i", str(path), "-af",
         flt + ",astats=metadata=1:reset=0:measure_overall=RMS_level:measure_perchannel=none,"
         "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    return float([ln for ln in out.splitlines() if "RMS_level=" in ln][-1].split("=")[1])


@pytest.mark.skipif(not media.ffmpeg_path(), reason="ffmpeg not installed")
async def test_medium_cleaning_takes_the_wind_down_and_keeps_the_voice(tmp_path):
    # "Wind": a loud 60 Hz rumble louder than the "voice", a 1 kHz tone that comes and
    # goes four times a second like syllables (a steady tone is what afftdn removes).
    src = tmp_path / "walk.wav"
    subprocess.run(
        [media.ffmpeg_path(), "-y", "-f", "lavfi", "-i", "sine=frequency=60:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
         "-filter_complex",
         "[0:a]volume=1.0[w];[1:a]volume=0.4,tremolo=f=4:d=0.9[v];[w][v]amix=inputs=2:normalize=0", str(src)],
        check=True, capture_output=True,
    )
    statuses: list[str] = []

    async def status(text):
        statuses.append(text)

    made: dict = {}
    plain = await media.render_edit(src, [[0.0, 3.0]], tmp_path / "plain.wav", on_status=status, loudness=False)
    clean = await media.render_edit(src, [[0.0, 3.0]], tmp_path / "clean.wav", on_status=status,
                                    loudness=False, report=made, denoise="medium")
    assert made["denoise"] == "medium" and "Cleaning the background noise (medium)" in statuses
    wind = "lowpass=f=100,lowpass=f=100"
    voice = "highpass=f=700,highpass=f=700"
    assert _band_db(plain, wind) - _band_db(clean, wind) > 20  # the rumble is gone
    assert abs(_band_db(plain, voice) - _band_db(clean, voice)) < 1.5  # the voice is not
