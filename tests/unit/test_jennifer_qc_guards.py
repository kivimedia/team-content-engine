"""Jennifer's numbers are measured, and her lines are plain (3-Oct review of DECIDED 7).

Every number on the card ("longest pause", "dead air", "loudness", "peak", "N of N words
captioned") is read again here from the rendered file with ffmpeg's own meters, by code
that shares nothing with production/qc.py, and must agree. Her one-line reason for a
hold never carries a dash, even when the words she quotes or the subscription's reason
had one. Synthetic recordings only (tone bursts for words, a faint hum for a pause).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from tce.production import qc, wordbox
from tests.unit.test_jennifer_flow import (  # noqa: F401 - the fixtures are used by name
    CLEAN,
    GAP_HUM,
    GAP_WORDS,
    edit,
    needs_ffmpeg,
    spoken,
    wired,
)

DASHES = ("\u2014", "\u2013", " -- ")


def _ffmpeg_log(path: str, *af: str) -> str:
    out = subprocess.run(
        [shutil.which("ffmpeg"), "-hide_banner", "-nostats", "-i", path, "-vn", *af, "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    return out.stderr


def _ebur128(path: str) -> tuple[float, float]:
    """Integrated loudness and true peak, read from the meter's summary block."""
    summary = _ffmpeg_log(path, "-af", "ebur128=peak=true").rsplit("Summary:", 1)[1]
    lufs = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))
    peak = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary).group(1))
    return lufs, peak


def _silences(path: str, noise_db: float, min_s: float) -> tuple[list[tuple[float, float]], float]:
    """(start, end) of every silence ffmpeg's silencedetect finds, and the duration."""
    log = _ffmpeg_log(path, "-af", f"silencedetect=noise={noise_db}dB:d={min_s}")
    duration = None
    probe = subprocess.run(
        [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    if probe.returncode == 0 and probe.stdout.strip():
        duration = float(probe.stdout.strip())
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", log)]
    if len(ends) < len(starts):
        ends.append(duration)
    return [(max(0.0, s), e) for s, e in zip(starts, ends, strict=True)], duration


@needs_ffmpeg
async def test_the_loudness_and_peak_on_the_card_are_the_files_own(wired, tmp_path):
    _ws, _uid, row = await edit(wired, tmp_path, spoken(CLEAN))
    numbers = row.qc["numbers"]
    lufs, peak = _ebur128(row.edited_path)
    assert abs(numbers["lufs"] - lufs) <= 0.05, (numbers, lufs)
    assert abs(numbers["true_peak_db"] - peak) <= 0.05, (numbers, peak)
    # And the file really is at the target the line claims.
    assert abs(lufs - (-14.0)) <= qc.LOUDNESS_TOLERANCE_LU and peak <= -1.0 + qc.PEAK_TOLERANCE_DB
    assert f"loudness {numbers['lufs']:.1f} LUFS" in row.qc["line"]


@needs_ffmpeg
async def test_the_captioned_count_is_the_captions_beside_the_file(wired, tmp_path):
    _ws, _uid, row = await edit(wired, tmp_path, spoken(CLEAN))
    numbers = row.qc["numbers"]
    src = Path(row.storage_path)
    srt = src.with_name(f"{src.stem}-edited.srt").read_text(encoding="utf-8")
    cue_words = [
        w for line in srt.splitlines()
        if line.strip() and "-->" not in line and not line.strip().isdigit()
        for w in line.split()
    ]
    spoken_words = [w for w in CLEAN.split() if re.sub(r"[^\w']", "", w).lower() not in wordbox.FILLERS]
    assert numbers["words"] == len(spoken_words) == len(cue_words)
    assert numbers["captioned"] == len(cue_words)
    assert f"{len(cue_words)} of {len(spoken_words)} words captioned" in row.qc["line"]


@needs_ffmpeg
async def test_the_longest_pause_and_the_dead_air_are_the_files_own(wired, tmp_path, monkeypatch):
    # Report mode: she measures and changes nothing, so the 3 s hum stays in the file.
    from tce.settings import settings

    monkeypatch.setattr(settings, "production_qc", "report")
    _ws, _uid, row = await edit(wired, tmp_path, GAP_WORDS, GAP_HUM)
    numbers = row.qc["numbers"]
    # The hum sits about 35 dB under the words: -30 dB is silence for both meters.
    quiet, duration = _silences(row.edited_path, -30, 0.2)
    longest = max(e - s for s, e in quiet)
    assert numbers["longest_gap_s"] > 2.0, numbers
    assert abs(numbers["longest_gap_s"] - longest) <= 0.3, (numbers, quiet)
    inner = [(s, e) for s, e in quiet if s > 0.01 and e < duration - 0.05]
    dead = 100 * sum(e - s for s, e in inner) / duration
    assert abs(numbers["dead_air_pct"] - dead) <= 3.0, (numbers, dead, quiet)
    assert row.qc["state"] == "report" and row.status == "edited"


# ---------------------------------------------------------------------------
# Plain lines


def test_a_dash_in_the_reading_or_the_words_never_reaches_his_line():
    said = "It is smart \u2014 and it works every time you call them after the work is done".split()
    said += ["Maple", "come", "here"]
    kept = [
        {"index": i, "text": t, "start": float(i), "end": float(i) + 0.4, "source_start": float(i),
         "source_end": float(i) + 0.4}
        for i, t in enumerate(said)
    ]
    first = len(said) - 3
    answer = {"asides": [{"first": first, "last": first + 2, "heard": "Maple come here",
                          "why": "talk to the dog \u2014 not the viewer -- clearly"}]}
    found = qc.check_asides(kept, answer)
    assert found["state"] == "fail" and len(found["problems"]) == 1
    problems = [*found["problems"],
                qc._problem("caption_mismatch", "the caption at 0:03 says \"smart \u2013 really\" where the word is \"smart\"")]
    checks = {"asides": {**found, "problems": problems}}
    for round_no, mode in ((0, "fix"), (1, "fix"), (0, "report")):
        verdict = qc.decide(checks, round_no=round_no, mode=mode)
        for text in [verdict["line"], *(p["detail"] for p in verdict["problems"])]:
            assert not any(d in text for d in DASHES), text
    assert qc.plain("a \u2014 b \u2013 c -- d e--f") == "a, b, c, d e, f"
    assert not any(d in s for s in qc.fix_sentences(found["problems"]) for d in DASHES)
