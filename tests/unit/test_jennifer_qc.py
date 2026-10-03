"""Jennifer's check, one check at a time, on generated fixtures (3-Oct).

Synthetic data only: tones made by ffmpeg stand in for speech (a planted 3 s gap, a quiet
track at about -30 LUFS), caption data built from invented words (with one caption taken
out), and an invented transcript with a line said to a dog. No server, no worker.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tce.production import autoedit, media, qc, tightcut, wordbox
from tce.production.retakes import frame_keep, plan_edit

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

DASHES = ("—", "–", " -- ")


def tone_file(path: Path, pieces: list[tuple[float, float]], rate: int = 48000) -> Path:
    """A mono WAV made of stretches: (seconds, amplitude). Amplitude 0 is digital silence."""
    terms, t = [], 0.0
    for seconds, amp in pieces:
        if amp:
            terms.append(f"{amp}*sin(2*PI*500*t)*between(t,{t:.3f},{t + seconds:.3f})")
        t += seconds
    expr = "+".join(terms) or "0"
    subprocess.run(
        [shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
         f"aevalsrc='{expr}':s={rate}:d={t:.3f}", "-c:a", "pcm_s16le", str(path)],
        check=True, capture_output=True,
    )
    return path


def said(text: str, start: float = 0.0, step: float = 0.5, length: float = 0.4) -> list[dict]:
    """Words on the edit clock, one every `step` seconds."""
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start": round(t, 3), "end": round(t + length, 3)})
        t += step
    return out


def kept(text: str, start: float = 0.0, step: float = 0.5, length: float = 0.4) -> list[dict]:
    """Kept words as qc.kept_on_edit returns them, on an edit that cut nothing."""
    return [
        {**w, "index": i, "source_start": w["start"], "source_end": w["end"]}
        for i, w in enumerate(said(text, start, step, length))
    ]


# ------------------------------------------------------------------ gaps


@needs_ffmpeg
async def test_a_planted_three_second_gap_is_found_on_the_rendered_audio(tmp_path):
    """Speech, 3 s of nothing, speech: one gap, at the second it starts, with the trim
    that takes it out and leaves a breath on both sides."""
    audio = tone_file(tmp_path / "gap.wav", [(2.0, 0.5), (3.0, 0), (2.0, 0.5)])
    levels = await tightcut.measure_levels(str(audio), shutil.which("ffmpeg"))
    words = said("one two three four", 0.0) + said("five six seven eight", 5.0)
    keep = [[10.0, 17.0]]  # the file is 10 s to 17 s of a longer recording
    found = qc.check_gaps(levels, words, max_gap_s=1.2, keep=keep)
    assert found["state"] == "fail" and found["gaps"] == 1
    gap = found["problems"][0]
    # Three seconds of silence, less the bit of air each word owns on either side.
    assert gap["kind"] == "gap" and 2.8 <= gap["seconds"] <= 3.05
    assert "second gap at 0:02" in gap["detail"]
    assert 2.8 <= found["longest_gap_s"] <= 3.05
    # The trim, on the recording's clock: the gap less a breath after and before speech.
    [[a, b]] = gap["fix"]["trim"]
    assert abs(a - (12.0 + qc.BREATH_AFTER_SPEECH_S)) < 0.1
    assert abs(b - (15.0 - qc.BREATH_BEFORE_SPEECH_S)) < 0.1
    assert found["dead_air_pct"] > 40


@needs_ffmpeg
async def test_speech_with_only_short_pauses_passes(tmp_path):
    audio = tone_file(tmp_path / "tight.wav", [(1.5, 0.5), (0.3, 0), (1.5, 0.5), (0.4, 0), (1.5, 0.5)])
    levels = await tightcut.measure_levels(str(audio), shutil.which("ffmpeg"))
    words = said("a b c", 0.0) + said("d e f", 1.8) + said("g h i", 3.7)
    found = qc.check_gaps(levels, words, max_gap_s=1.2, keep=[[0.0, 5.2]])
    assert found["state"] == "pass" and found["problems"] == []
    assert found["longest_gap_s"] <= 0.5 and found["dead_air_pct"] < 20


# One second of level readings: sound at speech level with one 0.1 s dip to digital
# silence, so the thresholds have a floor to stand on (as his phone's recordings do).
NOISY = [-120.0] * 10 + [-20.0] * 90


def test_a_quiet_word_is_never_dead_air_but_a_stretched_stamp_is():
    """A kept word the level reading cannot hear is his speech, not a gap. A word the
    recogniser stretched over 3 s of silence owns only its first second or so."""
    hop = tightcut.HOP_S
    loud, silent = [-20.0] * 100, [-120.0] * 300
    levels = loud + silent + loud  # 1 s speech, 3 s quiet, 1 s speech
    quiet_words = said("a b", 0.0) + said("c d e f g h", 1.0, 0.5) + said("i j", 4.0)
    assert qc.check_gaps(levels, quiet_words, max_gap_s=1.2, keep=[[0.0, 5.0]], hop=hop)["state"] == "pass"
    stretched = said("a b", 0.0) + [{"text": "smart.", "start": 0.9, "end": 3.9}] + said("i j", 4.0)
    found = qc.check_gaps(levels, stretched, max_gap_s=1.2, keep=[[0.0, 5.0]], hop=hop)
    assert found["state"] == "fail"
    [[a, b]] = found["problems"][0]["fix"]["trim"]
    assert a > 0.9 + qc.MAX_WORD_S and b <= 4.0


def test_a_stretch_of_noise_where_nobody_speaks_needs_both_witnesses():
    """Wind is not quiet, so the level reading sees no gap. It is a gap only when no kept
    word is there AND the recogniser listening to the render heard no word there."""
    levels = NOISY * 6  # six seconds of sound, never quiet for longer than a breath
    words = said("one two", 0.0) + said("three four", 5.0)
    heard_nothing = [{"text": w["text"], "start": w["start"], "end": w["end"]} for w in words]
    assert qc.check_gaps(levels, words, max_gap_s=1.2, keep=[[0.0, 6.0]])["state"] == "pass"
    found = qc.check_gaps(levels, words, max_gap_s=1.2, keep=[[0.0, 6.0]], heard=heard_nothing)
    assert found["state"] == "fail"
    assert "nobody says anything for" in found["problems"][0]["detail"]
    assert found["problems"][0]["fix"]["trim"]
    # Something IS said there that the transcript does not hold: never cut it.
    heard_speech = heard_nothing + [{"text": "really", "start": 2.5, "end": 2.9}]
    assert qc.check_gaps(levels, words, max_gap_s=1.2, keep=[[0.0, 6.0]], heard=heard_speech)["state"] == "pass"


def test_a_gap_maps_through_every_kept_range_it_crosses():
    assert qc.edit_to_source(1.5, 3.5, [[10.0, 12.0], [20.0, 23.0]]) == [[11.5, 12.0], [20.0, 21.5]]
    assert qc.edit_to_source(0.0, 1.0, []) == []


def test_unreadable_audio_is_skipped_not_failed():
    found = qc.check_gaps([], [], max_gap_s=1.2)
    assert found["state"] == "skipped" and found["problems"] == []


# ------------------------------------------------------------------ loudness


@needs_ffmpeg
async def test_a_quiet_track_measures_about_minus_thirty_and_fails(tmp_path):
    """A 1 kHz tone at about -30 LUFS: the meter reads it, and the check says so."""
    quiet = tmp_path / "quiet.wav"
    subprocess.run(
        [shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
         "sine=frequency=1000:duration=6:sample_rate=48000", "-af", "volume=-9dB", str(quiet)],
        check=True, capture_output=True,
    )
    measured = await qc.measure_loudness(str(quiet), shutil.which("ffmpeg"))
    assert measured is not None and -32.0 < measured["lufs"] < -28.0
    found = qc.check_loudness(measured, 6.0)
    assert found["state"] == "fail" and found["problems"][0]["kind"] == "loudness"
    assert "where -14 is the target" in found["problems"][0]["detail"]


@needs_ffmpeg
async def test_the_render_brings_a_quiet_track_to_minus_fourteen(tmp_path):
    """The same quiet track through the real render: -14 LUFS, peaks under -1 dB."""
    quiet = tmp_path / "quiet.wav"
    subprocess.run(
        [shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
         "sine=frequency=1000:duration=8:sample_rate=48000", "-af", "volume=-9dB", str(quiet)],
        check=True, capture_output=True,
    )
    statuses: list[str] = []

    async def status(text):
        statuses.append(text)

    report: dict = {}
    out = await media.render_edit(
        quiet, [[0.0, 3.0], [4.0, 8.0]], tmp_path / "out.wav", on_status=status, report=report
    )
    assert statuses[0].startswith("Listening to the cut audio to set its loudness to -14 LUFS")
    assert report["loudness"]["applied"] is True
    assert -32.0 < report["loudness"]["measured"]["input_i"] < -28.0
    measured = await qc.measure_loudness(str(out), shutil.which("ffmpeg"))
    assert abs(measured["lufs"] - (-14.0)) <= qc.LOUDNESS_TOLERANCE_LU
    assert measured["true_peak_db"] <= media.LOUDNESS_PEAK_DB + qc.PEAK_TOLERANCE_DB
    assert qc.check_loudness(measured, 7.0)["state"] == "pass"


async def test_loudnorm_is_in_the_one_render_command_and_the_video_is_encoded_once(tmp_path, monkeypatch):
    """Two ffmpeg runs: one that only listens (no file is written), then the render with
    what it measured. Never a third run that encodes the picture again for loudness."""
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"synthetic")
    runs: list[dict] = []
    listened = json.dumps({
        "input_i": "-30.10", "input_tp": "-27.00", "input_lra": "0.50", "input_thresh": "-40.20",
        "output_i": "-14.00", "output_tp": "-10.90", "output_lra": "0.40", "output_thresh": "-24.10",
        "normalization_type": "linear", "target_offset": "0.02",
    }, indent=1)

    async def fake_ffmpeg(ff, args, *, cwd):
        script = args[args.index("-filter_complex_script") + 1]
        runs.append({"args": list(args), "graph": (cwd / script).read_text(encoding="utf-8")})
        if args[-1] == "-":  # the listening pass writes nothing
            return f"[Parsed_loudnorm_0 @ 0x0]\n{listened}\n"
        Path(args[-1]).write_bytes(b"rendered")
        return ""

    monkeypatch.setattr(media, "_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(media, "ffmpeg_path", lambda: "ffmpeg")

    async def status(_text):
        return None

    report: dict = {}
    await media.render_edit(
        src, [[0.0, 2.0], [3.0, 5.0]], tmp_path / "walk-edited.mp4", on_status=status,
        srt_text="1\n00:00:00,000 --> 00:00:01,000\nHello\n", ass_text="[Script Info]\n", report=report,
    )
    assert len(runs) == 2
    listen, render = runs
    # Pass one: audio only, to nowhere, with the measuring loudnorm.
    assert listen["args"][-3:] == ["-f", "null", "-"] and "-c:v" not in listen["args"]
    assert "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json" in listen["graph"]
    assert "[0:v]" not in listen["graph"]
    # Pass two: THE render, carrying the correction in the same filter graph.
    assert "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=-30.10:measured_TP=-27.00" in render["graph"]
    assert "measured_thresh=-40.20:offset=0.02:linear=true" in render["graph"]
    assert "[outn]" in render["args"] and "[outa]" not in render["args"]
    assert render["args"].count("-c:v") == 1 and "libx264" in render["args"]
    assert report["loudness"]["applied"] is True and report["loudness"]["target_lufs"] == -14.0


async def test_near_silence_is_rendered_as_it_is_and_says_why(tmp_path, monkeypatch):
    src = tmp_path / "walk.wav"
    src.write_bytes(b"synthetic")
    graphs: list[str] = []

    async def fake_ffmpeg(ff, args, *, cwd):
        script = args[args.index("-filter_complex_script") + 1]
        graphs.append((cwd / script).read_text(encoding="utf-8"))
        if args[-1] == "-":
            return '{\n"input_i" : "-inf",\n"input_tp" : "-inf",\n"input_lra" : "0.00",\n' \
                   '"input_thresh" : "-70.00",\n"target_offset" : "inf"\n}'
        Path(args[-1]).write_bytes(b"rendered")
        return ""

    monkeypatch.setattr(media, "_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(media, "ffmpeg_path", lambda: "ffmpeg")

    async def status(_text):
        return None

    report: dict = {}
    await media.render_edit(src, [[0.0, 2.0]], tmp_path / "o.wav", on_status=status, report=report)
    assert "measured_I" not in graphs[1]
    assert report["loudness"] == {"applied": False, "why": "there is no sound loud enough to set a level from"}


def test_the_meters_summary_is_read_not_its_running_lines():
    log = (
        "[Parsed_ebur128_0 @ 0x1] t: 0.5 TARGET:-23 LUFS M: -50.1 S:-120.7 I: -50.1 LUFS LRA: 0.0 LU\n"
        "[Parsed_ebur128_0 @ 0x1] Summary:\n\n  Integrated loudness:\n    I:         -14.2 LUFS\n"
        "    Threshold: -24.4 LUFS\n\n  Loudness range:\n    LRA:         2.1 LU\n\n"
        "  True peak:\n    Peak:       -1.4 dBFS\n"
    )
    assert qc.parse_ebur128(log) == {"lufs": -14.2, "true_peak_db": -1.4}
    silent = "Summary:\n  Integrated loudness:\n    I:         -70.0 LUFS\n  True peak:\n    Peak:       -inf dBFS\n"
    assert qc.parse_ebur128(silent) == {"lufs": None, "true_peak_db": None}
    assert qc.parse_ebur128("no summary here") is None


def test_loudness_decisions():
    assert qc.check_loudness({"lufs": -14.3, "true_peak_db": -1.2}, 60)["state"] == "pass"
    assert qc.check_loudness({"lufs": -14.0, "true_peak_db": 0.4}, 60)["problems"][0]["kind"] == "peak"
    assert qc.check_loudness({"lufs": None, "true_peak_db": None}, 60)["problems"][0]["kind"] == "silent"
    assert qc.check_loudness(None, 60)["state"] == "skipped"
    assert qc.check_loudness({"lufs": -25.0, "true_peak_db": -9.0}, 1.5)["state"] == "skipped"
    # Nothing about loudness is fixable by a cut: it is fixed in the render, or held.
    assert all("fix" not in p for p in qc.check_loudness({"lufs": -30.0, "true_peak_db": -20.0}, 60)["problems"])


# ------------------------------------------------------------------ captions


WALK = "Selling is where the coaching starts. Call them after the service."


def caption_fixture() -> dict:
    words = said(WALK)
    return qc.caption_data(words, wordbox.pages(words), [])


def test_every_word_has_its_box_in_the_renders_caption_data():
    data = caption_fixture()
    assert data["mode"] == "wordbox" and len(data["boxes"]) == len(WALK.split())
    assert [b["text"] for b in data["boxes"]][:3] == ["Selling", "is", "where"]
    found = qc.check_captions(data)
    assert found["state"] == "pass" and found["captioned"] == found["words"] == len(WALK.split())


def test_a_missing_caption_in_the_caption_data_is_found():
    data = caption_fixture()
    gone = next(b for b in data["boxes"] if b["text"] == "coaching")
    data["boxes"].remove(gone)
    found = qc.check_captions(data)
    assert found["state"] == "fail"
    problem = found["problems"][0]
    assert problem["kind"] == "caption_missing" and '"coaching"' in problem["detail"]
    assert "fix" not in problem  # no cut can draw a caption: this one holds the video
    assert found["captioned"] == found["words"] - 1


def test_a_caption_that_says_another_word_is_a_mismatch():
    data = caption_fixture()
    next(b for b in data["boxes"] if b["text"] == "service")["text"] = "surface"
    found = qc.check_captions(data)
    assert found["problems"][0]["kind"] == "caption_mismatch"
    assert 'says "surface" where the word is "service"' in found["problems"][0]["detail"]


def test_the_expected_words_come_from_the_plan_not_from_the_captions_own_list():
    """A word the captions lost on their way (never in the caption data at all) is only
    found when the check is given the words the edit keeps."""
    lost = said(WALK)
    data = qc.caption_data([w for w in lost if w["text"] != "after"], wordbox.pages(
        [w for w in lost if w["text"] != "after"]), [])
    assert qc.check_captions(data)["state"] == "pass"
    found = qc.check_captions(data, expected=lost)
    assert found["state"] == "fail" and '"after"' in found["problems"][0]["detail"]


def test_fillers_and_end_periods_are_not_caption_defects():
    words = said("Um this is it. Uh done.")
    found = qc.check_captions(qc.caption_data(words, wordbox.pages(words), []), expected=words)
    assert found["state"] == "pass" and found["words"] == 4


def test_plain_captions_are_checked_against_the_cue_words():
    words = said("Call them after the service.")
    cues = [{"start": 0.0, "end": 2.6, "lines": ["Call them after", "the service."]}]
    assert qc.check_captions(qc.caption_data(words, None, cues), expected=words)["state"] == "pass"
    short = [{"start": 0.0, "end": 2.6, "lines": ["Call them the service."]}]
    found = qc.check_captions(qc.caption_data(words, None, short), expected=words)
    assert found["state"] == "fail" and '"after"' in found["problems"][0]["detail"]


def test_no_caption_data_is_said_not_failed():
    assert qc.check_captions(None)["state"] == "skipped"
    assert qc.check_captions({})["state"] == "skipped"


# ------------------------------------------------------------------ leftover asides


DOG_WALK = "Selling is the first step. Maple, come here! It is not a detour."


def test_a_line_to_the_dog_left_in_the_video_becomes_a_cut():
    words = kept(DOG_WALK)
    answer = {"asides": [{"first": 5, "last": 7, "heard": "Maple, come here!", "why": "calling the dog (R2)"}]}
    found = qc.check_asides(words, answer)
    assert found["state"] == "fail" and found["asides"] == 1
    problem = found["problems"][0]
    assert problem["kind"] == "aside" and '"Maple, come here!" at 0:02' in problem["detail"]
    assert problem["fix"] == {"cut": [[words[5]["source_start"], words[7]["source_end"]]]}


def test_the_asides_job_is_told_the_dogs_the_skill_file_then_the_learned_rules():
    system = qc.asides_system(
        ["Maple", "Rain"],
        skill="SKILL FILE TEXT",
        rules="RULES YOU LEARNED\nR1. Cut any aside to the dogs, even under 2 seconds.",
        talk="CONVERSATION RULES",
    )
    assert "Maple and Rain" in system
    assert system.index("SKILL FILE TEXT") < system.index("RULES YOU LEARNED") < system.index("CONVERSATION RULES")
    prompt = qc.asides_prompt(kept(DOG_WALK), "Topic: Selling")
    assert "5:Maple," in prompt and "[0:02]" in prompt and prompt.startswith("Topic: Selling")
    assert not any(d in system + prompt for d in DASHES)


def test_an_aside_must_quote_its_words_and_stay_inside_the_video():
    words = kept(DOG_WALK)
    bad = {"asides": [
        {"first": 5, "last": 7, "heard": "Rain, sit down!", "why": "misquoted"},
        {"first": 40, "last": 44, "heard": "x", "why": "outside"},
        {"first": "five", "last": 7, "heard": "Maple, come here!", "why": "not a number"},
    ]}
    found = qc.check_asides(words, bad)
    assert found["state"] == "pass" and found["problems"] == [] and len(found["dropped"]) == 2


def test_the_agents_words_are_never_an_aside():
    words = kept(DOG_WALK)
    answer = {"asides": [{"first": 5, "last": 7, "heard": "Maple, come here!", "why": "dog"}]}
    assert qc.check_asides(words, answer, protected={5, 6, 7})["state"] == "pass"
    part = qc.check_asides(words, answer, protected={6})
    assert part["problems"][0]["fix"]["cut"] == [
        [words[5]["source_start"], words[5]["source_end"]],
        [words[7]["source_start"], words[7]["source_end"]],
    ]


def test_an_answer_that_would_take_out_a_third_of_the_video_is_not_a_check():
    words = kept(DOG_WALK)
    answer = {"asides": [{"first": 0, "last": 7, "heard": " ".join(DOG_WALK.split()[:8]), "why": "all of it"}]}
    found = qc.check_asides(words, answer)
    assert found["state"] == "skipped" and found["problems"] == []
    assert qc.check_asides(words, None)["state"] == "skipped"


# ------------------------------------------------------------------ audibility


def test_a_clipped_word_gets_room_and_a_phone_cut_word_cannot_be_fixed():
    words = kept("We sell the course today.")
    found = qc.check_audibility(
        words, {3: "the edit ends inside this word", 1: "the edit starts inside this word"}, None, None
    )
    assert found["clipped"] == 2 and found["listened"] is False
    fixes = qc.merged_fixes(found["problems"])
    assert fixes == {"hold": [[words[1]["source_start"], "start", qc.CLIPPED_HOLD_S],
                              [words[3]["source_end"], "end", qc.CLIPPED_HOLD_S]]}
    phone = qc.check_audibility(words, {3: "phone cut its end short"}, None, None)
    assert phone["problems"][0]["kind"] == "phone_cut" and "fix" not in phone["problems"][0]
    assert 'the phone cut the end of "course" at 0:01' in phone["problems"][0]["detail"]


def test_a_word_is_inaudible_only_when_the_recogniser_and_the_levels_agree():
    words = kept("We sell the course today.")
    speech = NOISY * 3
    heard_all = [{"text": w["text"]} for w in words]
    assert qc.check_audibility(words, {}, heard_all, speech)["state"] == "pass"
    # The recogniser missed "course", but there is sound at speech level there: it only
    # heard it differently. Not a failure.
    missed = [h for h in heard_all if h["text"] != "course"]
    ok = qc.check_audibility(words, {}, missed, speech)
    assert ok["state"] == "pass" and ok["heard_differently"] == 1 and ok["heard"] == 5
    # ... and with silence where "course" should be, it cannot be heard.
    hole = list(speech)
    for k in range(144, 196):
        hole[k] = -120.0
    bad = qc.check_audibility(words, {}, missed, hole)
    assert bad["state"] == "fail" and bad["problems"][0]["kind"] == "inaudible"
    assert '"course"' in bad["problems"][0]["detail"] and bad["heard"] == 4
    assert "fix" not in bad["problems"][0]
    # A misheard word (replaced, not dropped) is never a failure either.
    wrong = [{"text": "coarse" if h["text"] == "course" else h["text"]} for h in heard_all]
    assert qc.check_audibility(words, {}, wrong, hole)["state"] == "pass"


# ------------------------------------------------------------------ fix or hold


def passing() -> dict:
    return {
        "gaps": {"state": "pass", "problems": [], "longest_gap_s": 0.4, "dead_air_pct": 3.0},
        "loudness": {"state": "pass", "problems": [], "lufs": -14.1, "true_peak_db": -1.3},
        "captions": {"state": "pass", "problems": [], "words": 212, "captioned": 212},
        "audibility": {"state": "pass", "problems": [], "words": 212, "heard": 212, "listened": True},
        "asides": {"state": "pass", "problems": [], "asides": 0},
    }


GAP = {"kind": "gap", "detail": "a 3.0 second gap at 0:05", "fix": {"trim": [[12.1, 14.9]]}}
ASIDE = {"kind": "aside", "detail": '"Maple, come here!" at 0:42 is not said to the viewer',
         "fix": {"cut": [[50.0, 51.2]]}}
CLIPPED = {"kind": "clipped", "detail": 'the cut at 0:10 ends inside "course"', "fix": {"hold": [[11.0, "end", 0.15]]}}
NO_CAPTION = {"kind": "caption_missing", "detail": '1 word has no caption: "coaching", the first at 0:02'}


def with_problems(**by_check) -> dict:
    checks = passing()
    for name, problems in by_check.items():
        checks[name] = {**checks[name], "state": "fail", "problems": problems}
    return checks


def test_a_clean_edit_is_checked_by_jennifer_with_its_numbers():
    verdict = qc.decide(passing(), round_no=0)
    assert verdict["state"] == "passed" and verdict["fixes"] == {}
    assert verdict["line"] == (
        "Checked by Jennifer: longest pause 0.4 s, dead air 3%, loudness -14.1 LUFS, peak -1.3 dB, "
        "212 of 212 words captioned, every word heard, nothing off topic left in."
    )
    assert verdict["numbers"]["lufs"] == -14.1 and verdict["numbers"]["captioned"] == 212


def test_gaps_asides_and_clipped_words_are_fixed_with_the_overrides_his_notes_write():
    verdict = qc.decide(with_problems(gaps=[GAP], asides=[ASIDE], audibility=[CLIPPED]), round_no=0)
    assert verdict["state"] == "fixing"
    assert verdict["fixes"] == {"trim": [[12.1, 14.9]], "cut": [[50.0, 51.2]], "hold": [[11.0, "end", 0.15]]}
    assert verdict["line"].startswith("Jennifer is fixing 3 things and rendering once more")
    # The same overrides a note of his writes: merged, they survive every re-plan.
    merged = autoedit.merge_overrides({"cut": [[1.0, 2.0]], "restore": []}, verdict["fixes"]["cut"], [],
                                      verdict["fixes"]["hold"], verdict["fixes"]["trim"])
    assert merged == {"cut": [[1.0, 2.0], [50.0, 51.2]], "restore": [],
                      "hold": [[11.0, "end", 0.15]], "trim": [[12.1, 14.9]]}


def test_after_her_one_fix_a_clean_recheck_says_what_she_fixed():
    verdict = qc.decide(passing(), round_no=1, fixed=["cut a 3.0 second gap at 0:05"])
    assert verdict["state"] == "fixed"
    assert verdict["line"].startswith("Checked by Jennifer, after one fix (cut a 3.0 second gap at 0:05): ")


def test_what_is_still_wrong_after_one_fix_holds_the_video_never_a_second_fix():
    verdict = qc.decide(with_problems(gaps=[GAP]), round_no=1, fixed=["cut a 3.0 second gap at 0:05"])
    assert verdict["state"] == "held" and verdict["fixes"] == {}
    assert verdict["line"] == "Jennifer is holding this video: a 3.0 second gap at 0:05 after one fix."


def test_what_no_cut_can_fix_holds_at_once_with_one_plain_line():
    verdict = qc.decide(with_problems(captions=[NO_CAPTION]), round_no=0)
    assert verdict["state"] == "held"
    assert verdict["line"] == 'Jennifer is holding this video: 1 word has no caption: "coaching", the first at 0:02.'
    assert "\n" not in verdict["line"]


def test_a_fixable_thing_is_fixed_first_and_the_unfixable_one_is_the_reason_after():
    both = with_problems(gaps=[GAP], captions=[NO_CAPTION])
    assert qc.decide(both, round_no=0)["state"] == "fixing"
    held = qc.decide(both, round_no=1)
    assert held["state"] == "held" and "has no caption" in held["line"] and "(and 1 more)" in held["line"]


def test_report_mode_only_says():
    verdict = qc.decide(with_problems(gaps=[GAP]), round_no=0, mode="report")
    assert verdict["state"] == "report" and verdict["fixes"] == {}
    assert verdict["line"].startswith("Jennifer found 1 thing and changed nothing (checking only)")


def test_a_check_that_could_not_be_made_is_said_and_never_holds():
    checks = passing()
    checks["asides"] = qc.skipped("Jennifer's reading of the words did not come back (timeout)")
    checks["audibility"] = {"state": "pass", "problems": [], "words": 212, "heard": None, "listened": False}
    verdict = qc.decide(checks, round_no=0)
    assert verdict["state"] == "passed"
    assert verdict["line"].endswith("Not checked this time: leftover asides, not listened to again.")


def test_every_line_she_writes_is_plain():
    lines = [
        qc.decide(passing(), round_no=0)["line"],
        qc.decide(with_problems(gaps=[GAP], asides=[ASIDE]), round_no=0)["line"],
        qc.decide(with_problems(captions=[NO_CAPTION]), round_no=1)["line"],
        qc.decide(with_problems(gaps=[GAP]), round_no=0, mode="report")["line"],
    ] + qc.fix_sentences([GAP, ASIDE, CLIPPED])
    for line in lines:
        assert not any(d in line for d in DASHES), line
        assert re.search(r":[A-Za-z]", line) is None, line  # a space after every colon


# ------------------------------------------------------------------ the trim override


def test_a_trim_takes_dead_air_out_of_the_keep_and_a_restore_lifts_it():
    assert tightcut.apply_trims([[0.0, 10.0]], [[3.0, 5.0]]) == [[0.0, 3.0], [5.0, 10.0]]
    assert tightcut.apply_trims([[0.0, 4.0], [6.0, 9.0]], [[3.5, 6.5]]) == [[0.0, 3.5], [6.5, 9.0]]
    assert tightcut.apply_trims([[0.0, 1.0]], []) == [[0.0, 1.0]]
    merged = autoedit.merge_overrides(None, [], [], None, [[3.0, 5.0]])
    assert merged == {"cut": [], "restore": [], "trim": [[3.0, 5.0]]}
    # His restore over the same stretch wins over her trim.
    assert "trim" not in autoedit.merge_overrides(merged, [], [[2.5, 5.5]])
    # A later note of his keeps her trim.
    assert autoedit.merge_overrides(merged, [[8.0, 9.0]], [])["trim"] == [[3.0, 5.0]]


def test_a_plan_with_a_trim_is_shorter_and_every_kept_word_keeps_its_caption():
    """A word stamped over 3 s of silence: the trim removes the air, the word stays."""
    transcript = [
        {"text": "It", "start_s": 0.0, "end_s": 0.4, "precision": "word"},
        {"text": "is", "start_s": 0.5, "end_s": 0.9, "precision": "word"},
        {"text": "smart.", "start_s": 1.0, "end_s": 4.4, "precision": "word"},
        {"text": "Call", "start_s": 4.5, "end_s": 4.9, "precision": "word"},
        {"text": "them.", "start_s": 5.0, "end_s": 5.4, "precision": "word"},
    ]
    before = plan_edit(transcript, None, duration_s=6.0)
    after = plan_edit(transcript, None, duration_s=6.0, overrides={"cut": [], "restore": [], "trim": [[2.3, 4.3]]})
    length = lambda plan: sum(e - s for s, e in plan["keep"])  # noqa: E731
    assert abs((length(before) - length(after)) - 2.0) < 0.01
    assert [w["text"] for w in after["words"]] == [w["text"] for w in before["words"]]
    on_edit = wordbox.on_edit_timeline(after["words"], frame_keep(after["keep"]))
    assert [w["text"] for w in on_edit] == ["It", "is", "smart.", "Call", "them."]
    assert after["meaning_check"]["status"] == "ok"
