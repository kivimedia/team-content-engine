"""Tight cuts placed by the audio, not by the recogniser's clock (28-Sep).

"the editing is not as punchy as the TJ digital video editing (inaccurate cuts that
leave more silent space that is boring)". Measured on "Selling is the first step":
TJ's reels never pause longer than 0.34-0.58 s and carry 1-6 % dead air; our edit
paused up to 1.77 s with 10.5 % dead air. Two causes:

- faster-whisper word times are off by 0.1-0.4 s at phrase edges ("Which" stamped
  0.38 s before he speaks, "It" running 0.5 s into silence), so a cut placed on them
  either keeps silence or clips a word;
- the planner kept 0.2 s of pad on each side and every pause under 0.8 s whole.

So every edge is snapped to where speech actually starts and stops in the audio
(a 10 ms level envelope from ffmpeg), pauses inside kept speech longer than
MAX_NATURAL_GAP_S are cut down to a short breath, and every edge lands on the 1/30 s
frame grid so the audio and video of each piece are exactly the same length (no
drift, no padded silence at the joins).
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Any

HOP_S = 0.01  # one level reading per 10 ms
FPS = 30  # output frame grid: every cut edge lands on it
SILENT_DB = -120.0  # digital zero

# How much air is left around speech at a join.
PRE_S = 0.05  # before a word starts (onsets are fast)
POST_S = 0.09  # after a word ends (tails decay)
POST_SENTENCE_S = 0.12  # a breath more at the end of a sentence
MAX_NATURAL_GAP_S = 0.2  # a pause up to this stays whole; longer ones are cut down
SEARCH_S = 0.35  # how far from the recogniser's time an edge may move
SEARCH_FAR_S = 0.6  # ... when the next thing said is a pause away (it was 0.4 s late on "A")
NEAR_S = 1.0  # a dropped word closer than this shares a boundary with the kept one
TOUCH_GAP_S = 0.08  # the recogniser has two words touching when they are this close
TOUCH_SLACK_S = 0.04  # ... and its boundary is trusted to within this
WORD_REACH_S = 0.25  # speech this close to a kept word belongs to it
MERGE_REGIONS_S = 0.08
MIN_REGION_S = 0.05
MIN_PIECE_FRAMES = 2


def levels_filter() -> str:
    """ffmpeg audio filter printing one RMS level (dB) per 10 ms of mono 8 kHz audio."""
    return (
        "aresample=8000,pan=mono|c0=c0,asetnsamples=n=80:p=0,"
        "astats=metadata=1:reset=1:measure_overall=RMS_level:measure_perchannel=none,"
        "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-"
    )


def parse_levels(text: str) -> list[float]:
    out: list[float] = []
    for line in text.splitlines():
        key, _, value = line.partition("RMS_level=")
        if not _:
            continue
        try:
            level = float(value.strip())
        except ValueError:
            level = SILENT_DB
        out.append(SILENT_DB if math.isnan(level) or level < SILENT_DB else level)
    return out


async def measure_levels(path: str, ffmpeg: str) -> list[float]:
    """10 ms RMS levels of the whole recording (about 5 s for a 10-minute walk)."""
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-v", "error", "-i", str(path), "-vn", "-af", levels_filter(), "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        tail = err.decode(errors="replace").strip().splitlines()[-1:] or ["no output"]
        raise RuntimeError(f"ffmpeg could not read the audio levels: {tail[0][:200]}")
    return parse_levels(out.decode(errors="replace"))


@dataclass
class Activity:
    """Where speech is, as [start, end] seconds, plus the thresholds that found it."""

    regions: list[tuple[float, float]]
    high_db: float
    low_db: float
    levels: list[float] | None = None  # the 10 ms readings, for measuring the result

    def as_dict(self) -> dict[str, Any]:
        return {"regions": len(self.regions), "high_db": round(self.high_db, 1),
                "low_db": round(self.low_db, 1)}


def _percentile(sorted_values: list[float], q: float) -> float:
    return sorted_values[int(q * (len(sorted_values) - 1))]


def find_activity(levels: list[float], hop: float = HOP_S) -> Activity:
    """Speech regions by hysteresis: a region needs a frame above `high` and runs
    while the level stays above `low`.

    The thresholds follow the recording: 28/38 dB under its loud speech, and never
    within 12/6 dB of its noise floor. His phone gates the mic to digital zero
    between words (53 % of the 28-Sep walk is exact silence); a recording with
    real room tone gets thresholds above that tone instead.
    """
    if not levels:
        return Activity([], 0.0, 0.0)
    ordered = sorted(levels)
    floor, loud = _percentile(ordered, 0.10), _percentile(ordered, 0.90)
    high = max(loud - 28.0, floor + 12.0)
    low = min(max(loud - 38.0, floor + 6.0), high - 4.0)
    n = len(levels)
    regions: list[list[int]] = []
    i = 0
    while i < n:
        if levels[i] <= high:
            i += 1
            continue
        s = i
        while s > 0 and levels[s - 1] > low:
            s -= 1
        e = i
        while e + 1 < n and levels[e + 1] > low:
            e += 1
        regions.append([s, e + 1])
        i = e + 1
    merged: list[list[int]] = []
    gap = round(MERGE_REGIONS_S / hop)
    for r in regions:
        if merged and r[0] - merged[-1][1] <= gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    shortest = round(MIN_REGION_S / hop)
    return Activity(
        [(round(s * hop, 3), round(e * hop, 3)) for s, e in merged if e - s >= shortest],
        high,
        low,
        levels,
    )


def _grid(t: float, up: bool) -> float:
    frames = t * FPS
    k = math.ceil(frames - 1e-6) if up else math.floor(frames + 1e-6)
    return k / FPS


def _ends_sentence(text: str) -> bool:
    return str(text).rstrip().rstrip("\"')]").endswith((".", "?", "!"))


def _dip(levels: list[float], t0: float, t1: float, prefer: float, hop: float = HOP_S) -> float:
    """The cut point between two words: among the quietest frames in [t0, t1] (within
    6 dB of the quietest), the one nearest `prefer` (the recogniser's boundary),
    snapped to the frame grid."""
    a, b = max(0, int(t0 / hop)), min(len(levels), int(math.ceil(t1 / hop)))
    if b <= a:
        return round(prefer * FPS) / FPS
    floor = min(levels[a:b])
    candidates = [k for k in range(a, b) if levels[k] <= floor + 6.0]
    best = min(candidates, key=lambda k: abs(k * hop + hop / 2 - prefer))
    return round((best * hop + hop / 2) * FPS) / FPS


def _edges(
    words: list[dict[str, Any]],
    kept: list[bool],
    audible: list[bool],
    i: int,
    j: int,
    levels: list[float] | None,
    end_bound: float,
) -> tuple[float, float]:
    """How far the run words[i..j] may reach into the audio on each side.

    A neighbour far away (a pause of NEAR_S or more) leaves room to follow the speech
    up to SEARCH_FAR_S past the recogniser's time. A dropped neighbour that runs into
    the run is cut at the dip between them. Words the recogniser invented are not
    neighbours: there is no speech of theirs to avoid.
    """
    start, end = float(words[i]["start_s"]), float(words[j]["end_s"])

    def middle(k: int) -> float:
        return (float(words[k]["start_s"]) + float(words[k]["end_s"])) / 2

    # Two words the recogniser has touching are cut on its boundary, give or take
    # TOUCH_SLACK_S: the deepest dip nearby is usually a consonant inside a word, not
    # the gap between two. 28-Sep: a dip 0.2 s before the boundary was the stop inside
    # "coa-ched", and the edit said "coa". With a gap between them, the cut goes in
    # its quietest frame, never past the middle of either word (a dropped "um" stayed
    # in, a kept "is" was cut out when the search reached further; review, 28-Sep).
    def between(left: float, right: float, left_mid: float, right_mid: float) -> float:
        if right - left < TOUCH_GAP_S:
            return _dip(levels, right - TOUCH_SLACK_S, right + TOUCH_SLACK_S, right)
        return _dip(levels, max(left, left_mid), min(right, right_mid), (left + right) / 2)

    prev = next((k for k in range(i - 1, -1, -1) if audible[k]), None)
    if prev is None:
        lo = start - SEARCH_FAR_S
    else:
        pe = float(words[prev]["end_s"])
        if kept[prev]:
            lo = pe - PRE_S
        elif start - pe >= NEAR_S:
            lo = max(pe, start - SEARCH_FAR_S)
        elif levels:
            lo = between(pe, start, middle(prev), middle(i))
        else:
            lo = max(start - SEARCH_S, pe - PRE_S)
    nxt = next((k for k in range(j + 1, len(words)) if audible[k]), None)
    if nxt is None:
        hi = end + SEARCH_FAR_S
    else:
        ns = float(words[nxt]["start_s"])
        if kept[nxt]:
            hi = ns + PRE_S
        elif ns - end >= NEAR_S:
            hi = min(ns, end + SEARCH_FAR_S)
        elif levels:
            hi = between(end, ns, middle(j), middle(nxt))
        else:
            hi = min(end + SEARCH_S, ns + PRE_S)
    return max(0.0, lo), min(end_bound, hi)


def tight_keep(
    words: list[dict[str, Any]],
    kept: list[bool],
    activity: Activity,
    duration_s: float | None,
    audible: list[bool] | None = None,
) -> tuple[list[list[float]], list[dict[str, Any]]]:
    """Keep ranges for the kept words, and each kept word re-timed onto its speech.

    Words are grouped into runs of consecutive kept words (a dropped word always
    means a cut). Inside a run, audio between the first onset and the last offset is
    kept except pauses longer than MAX_NATURAL_GAP_S, which are cut down to
    PRE_S + POST_S. A kept word the envelope cannot hear keeps its recogniser span,
    so nothing he said is ever dropped for being quiet. `audible` marks the words
    that are real speech (False for recogniser junk).
    """
    end_bound = float(duration_s) if duration_s else max(
        (float(w["end_s"]) for w in words), default=0.0
    ) + 1.0
    regions = activity.regions
    audible = audible if audible is not None else [True] * len(words)
    pieces: list[list[float]] = []
    n = len(words)
    i = 0
    while i < n:
        if not kept[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and kept[j + 1]:
            j += 1
        lo, hi = _edges(words, kept, audible, i, j, activity.levels, end_bound)
        run_pieces: list[list[float]] = []
        reach = [
            (float(w["start_s"]) - WORD_REACH_S, float(w["end_s"]) + WORD_REACH_S, w)
            for w in words[i : j + 1]
        ]
        for rs, re_ in regions:
            if re_ <= lo or rs >= hi:
                continue
            owner = next((w for a, b, w in reach if rs < b and re_ > a), None)
            if owner is None:
                continue  # a sound in a pause (a bark, a car) is not his speech
            # The breath after the region belongs to the last word it touches.
            tail_word = next(
                (w for a, b, w in reversed(reach) if rs < b and re_ > a), owner
            )
            post = POST_SENTENCE_S if _ends_sentence(tail_word["text"]) else POST_S
            run_pieces.append([max(lo, rs - PRE_S), min(hi, re_ + post)])
        for w in words[i : j + 1]:
            ws, we = float(w["start_s"]), float(w["end_s"])
            # Measured against the speech found, not the padded pieces: a quiet word
            # right after a loud one touched the loud word's breath and was lost.
            if not any(a < we and b > ws for a, b in regions):
                run_pieces.append([max(lo, ws), min(hi, max(we, ws + 0.1))])
        pieces.extend(run_pieces)
        i = j + 1

    pieces.sort()
    merge_gap = MAX_NATURAL_GAP_S - PRE_S - POST_S
    merged: list[list[float]] = []
    for s, e in pieces:
        if merged and s - merged[-1][1] <= merge_gap:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    gridded: list[list[float]] = []
    for s, e in merged:
        s, e = _grid(max(0.0, s), up=False), _grid(min(end_bound, e), up=True)
        if gridded and s <= gridded[-1][1] + 1e-9:
            gridded[-1][1] = max(gridded[-1][1], e)
        elif e > s:
            gridded.append([s, e])
    mids = [
        (float(w["start_s"]) + float(w["end_s"])) / 2 for w, k in zip(words, kept, strict=True) if k
    ]
    keep = [
        [round(s, 6), round(e, 6)]
        for s, e in gridded
        if (e - s) * FPS >= MIN_PIECE_FRAMES - 1e-6 or any(s <= m <= e for m in mids)
    ]
    return keep, retime(words, kept, keep, regions)


def retime(
    words: list[dict[str, Any]],
    kept: list[bool],
    keep: list[list[float]],
    regions: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """Kept words with times clamped into the kept ranges and snapped to speech.

    The captions highlight a word while it is said. The recogniser starts a word
    that follows a pause up to 0.4 s early, so a word that opens a kept range starts
    where its speech does, and one that closes a range ends where its speech does.
    """
    out: list[dict[str, Any]] = []
    for index, (w, k) in enumerate(zip(words, kept, strict=True)):
        if not k:
            continue
        ws, we = float(w["start_s"]), float(w["end_s"])
        mid = (ws + we) / 2
        home = next((r for r in keep if r[0] <= mid <= r[1]), None)
        if home is None:
            home = min(keep, key=lambda r: min(abs(r[0] - mid), abs(r[1] - mid)), default=None)
        if home is None:
            continue
        rs, re_ = home
        s, e = min(max(ws, rs), re_), max(min(we, re_), rs)
        inside = [(a, b) for a, b in regions if a < re_ and b > rs]
        # A word that opens a spoken stretch starts on its first sound.
        before = [(a, b) for a, b in inside if b <= s + 0.02]
        onset = next((a for a, b in inside if a <= e and b >= s), None)
        if onset is not None and onset > s and not before:
            s = min(onset, e - 0.06)
        after = [(a, b) for a, b in inside if a >= e - 0.02]
        offset = next((b for a, b in reversed(inside) if a <= e and b >= s), None)
        if offset is not None and offset < e and not after:
            e = max(offset + 0.04, s + 0.06)
        # Rounded, then clamped: rounding alone put a word ending on a cut just outside
        # its range, and the subtitles dropped it (review, 28-Sep).
        s = min(max(round(s, 6), rs), re_)
        e = min(max(round(min(e, re_), 6), s), re_)
        out.append({"index": index, "text": str(w["text"]), "start": s, "end": e})
    for a, b in zip(out, out[1:], strict=False):
        if a["end"] > b["start"]:
            a["end"] = max(a["start"], b["start"])
    return out


def pause_stats(keep: list[list[float]], activity: Activity, hop: float = HOP_S) -> dict[str, float]:
    """The pauses the viewer will hear: quiet stretches of the edited audio (the kept
    ranges played back to back), measured on the audio, not on word times.

    TJ's reels, measured the same way on 28-Sep: longest pause 0.34-0.58 s, dead air
    (pauses of 0.25 s or more) 1-6 % of the runtime.
    """
    levels = activity.levels or []
    if not levels or not keep:
        return {}
    quiet_db = (activity.high_db + activity.low_db) / 2
    inner: list[float] = []  # quiet between two stretches of speech; lead-in and tail excluded
    run = 0
    heard = False
    for s, e in keep:
        for i in range(int(round(s / hop)), min(int(round(e / hop)), len(levels))):
            if levels[i] < quiet_db:
                run += 1
                continue
            if run and heard:
                inner.append(run * hop)
            run = 0
            heard = True
    total = sum(e - s for s, e in keep) or 1.0
    return {
        "max_pause_s": round(max(inner, default=0.0), 2),
        "pauses_over_half_second": sum(1 for g in inner if g >= 0.5),
        "dead_air_pct": round(100 * sum(g for g in inner if g >= MAX_NATURAL_GAP_S) / total, 2),
    }
