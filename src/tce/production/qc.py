"""Jennifer checks every edit (3-Oct).

"Jennifer is the editor and QCs every edit: gaps, dog asides, every word audible,
captions present and matching, loudness; fixes what she can and re-renders; holds only
what she cannot fix, with a one-line reason."

After every render she measures the file the viewer gets, not the plan that made it:

- gaps: the longest quiet stretch and the share of dead air on the RENDERED audio
  (the same 10 ms level reading the tight cut uses, taken from the finished file);
- asides: one subscription job reads the words still in the video for talk to the
  dogs, to people around him, or off the topic;
- audibility: words a cut clipped (the level reading at each cut edge), words the
  phone cut short, and words that cannot be heard at all: the render is transcribed
  again by the local recogniser and compared with the words that were kept;
- captions: every kept spoken word has its caption box, with the same text, in the
  caption data the render was drawn from;
- loudness: integrated loudness and true peak of the file (ffmpeg ebur128).

Fix or hold. Loudness is corrected inside the render itself (media.render_edit). A gap
becomes a `trim` override, a leftover aside a `cut` override, a clipped word a `hold`
override: the same overrides his own notes write. Then ONE re-render and one re-check,
never more. What is still wrong after that, or was never fixable by a cut (a word that
cannot be heard, a caption that does not match), holds the video with one plain line.

This module is pure apart from the two ffmpeg readers: checks, the decision, and the
sentences. The router owns the jobs, the statuses and the re-render.
"""

from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from typing import Any

from tce.production import tightcut, wordbox
from tce.production.media import LOUDNESS_LUFS, LOUDNESS_PEAK_DB

QC_VERSION = "qc-v1"
MODES = ("off", "report", "fix")

MAX_GAP_S = 1.2  # a quiet stretch longer than this is a gap (the setting overrides it)
BREATH_AFTER_SPEECH_S = tightcut.POST_SENTENCE_S  # air left after the words before a gap
BREATH_BEFORE_SPEECH_S = tightcut.PRE_S  # ... and before the words after it
MIN_TRIM_S = 0.2  # a trim shorter than this is not worth a cut
WORD_PAD_S = 0.06  # a kept word owns this much quiet around itself
MAX_WORD_S = 1.2  # ... and no more than this from its start, however long its stamp

LOUDNESS_TOLERANCE_LU = 1.0
PEAK_TOLERANCE_DB = 0.3
MIN_LOUDNESS_S = 3.0  # shorter than this, integrated loudness is not a real number

CLIPPED_HOLD_S = 0.15  # the room a clipped word gets on the side the cut took
CAPTION_DRIFT_S = 1.0  # a box this far from its word is on the wrong word

MAX_ASIDE_WORDS = 30
MAX_ASIDE_SHARE = 0.25  # more than this "left in" is a misreading, not a check

ASIDES_JOB = "video_qc_asides"
ASIDES_PROMPT_VERSION = "qc-asides-v1"

_BARE = re.compile(r"[^\w']+")
_NORM = re.compile(r"[^\w']+")


def _norm(text: str) -> str:
    return " ".join(_NORM.sub(" ", str(text).lower()).split())


def _token(text: str) -> str:
    return _BARE.sub("", str(text)).lower()


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _problem(kind: str, detail: str, fix: dict[str, Any] | None = None, **more: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": kind, "detail": detail}
    if fix:
        out["fix"] = fix
    out.update(more)
    return out


def _check(problems: list[dict[str, Any]], **data: Any) -> dict[str, Any]:
    return {"state": "fail" if problems else "pass", "problems": problems, **data}


def skipped(why: str, **data: Any) -> dict[str, Any]:
    """A check that could not be made, said plainly. Never a failure on its own."""
    return {"state": "skipped", "why": why, "problems": [], **data}


# ---------------------------------------------------------------------------
# The words the viewer gets


def kept_on_edit(plan_words: list[dict[str, Any]], keep: list[list[float]]) -> list[dict[str, Any]]:
    """The plan's kept words on the edited clock, each with its transcript index and
    its place on the recording: [{index, text, start, end, source_start, source_end}].

    The same placing as the captions (retakes.words_on_edit): a word goes with the kept
    range holding its midpoint. A "[sound]" is heard, never a word.
    """
    out: list[dict[str, Any]] = []
    offsets: list[float] = []
    acc = 0.0
    for s, e in keep:
        offsets.append(acc)
        acc += float(e) - float(s)
    for w in plan_words or []:
        if str(w.get("text") or "") == "[sound]":
            continue
        ws, we = float(w["start"]), float(w["end"])
        mid = (ws + we) / 2
        for (rs, re_), off in zip(keep, offsets, strict=True):
            rs, re_ = float(rs), float(re_)
            if rs <= mid <= re_:
                s, e = max(ws, rs), min(we, re_)
                out.append(
                    {
                        "index": int(w["index"]) if "index" in w else None,
                        "text": str(w["text"]),
                        "start": round(off + s - rs, 3),
                        "end": round(off + max(e, s) - rs, 3),
                        "source_start": ws,
                        "source_end": we,
                    }
                )
                break
    return out


def spoken(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The words that get a caption: everything but fillers (the captions leave them out)."""
    return [w for w in words if str(w.get("text") or "").strip() and _token(w["text"]) not in wordbox.FILLERS]


# ---------------------------------------------------------------------------
# Gaps, on the rendered audio


def quiet_runs(
    levels: list[float], activity: tightcut.Activity, hop: float = tightcut.HOP_S
) -> list[tuple[float, float]]:
    """Every stretch of the rendered audio under the speech level, as (start, end) on
    the edit clock, the lead-in and the tail included. The threshold is the one
    tightcut.pause_stats uses: halfway between where speech starts and where it ends."""
    if not levels:
        return []
    quiet_db = (activity.high_db + activity.low_db) / 2
    runs: list[tuple[float, float]] = []
    start: int | None = None
    for i, level in enumerate(levels):
        if level < quiet_db:
            if start is None:
                start = i
        elif start is not None:
            runs.append((round(start * hop, 3), round(i * hop, 3)))
            start = None
    if start is not None:
        runs.append((round(start * hop, 3), round(len(levels) * hop, 3)))
    return runs


def _minus_words(
    run: tuple[float, float], words: list[dict[str, Any]]
) -> list[tuple[float, float]]:
    """The parts of a quiet stretch where no kept word sits: a word too quiet for the
    level reading is his speech, never dead air to cut. A word owns at most MAX_WORD_S
    from its start: no spoken word is longer, and the rest of a longer stamp is the
    recogniser stretching a word over the silence after it."""
    pieces = [run]
    for w in words:
        a = float(w["start"]) - WORD_PAD_S
        b = min(float(w["end"]), float(w["start"]) + MAX_WORD_S) + WORD_PAD_S
        if b <= run[0] or a >= run[1]:
            continue
        nxt: list[tuple[float, float]] = []
        for s, e in pieces:
            if b <= s or a >= e:
                nxt.append((s, e))
                continue
            if s < a:
                nxt.append((s, a))
            if b < e:
                nxt.append((b, e))
        pieces = nxt
    return pieces


def check_gaps(
    levels: list[float] | None,
    words: list[dict[str, Any]],
    *,
    max_gap_s: float = MAX_GAP_S,
    keep: list[list[float]] | None = None,
    heard: list[dict[str, Any]] | None = None,
    hop: float = tightcut.HOP_S,
) -> dict[str, Any]:
    """The longest gap and the dead-air share of the rendered audio.

    `words` are the kept words on the edit clock. A gap is a quiet stretch with no kept
    word in it, longer than `max_gap_s`; each becomes a trim that leaves a breath on
    both sides (`keep`, the keep that made the file, turns it into ranges on the
    recording). Dead air is measured as the tight cut measures it: quiet between two
    stretches of speech, 0.2 s or more, as a share of the runtime.

    `heard` (the render transcribed again, with times on the edit clock) finds the gap a
    level reading cannot: a stretch that is not quiet (wind, a car, a bark) where nobody
    says anything. It counts only when both witnesses agree: no kept word there, and
    the recogniser heard no word there either. Without `heard`, only quiet counts.
    """
    if not levels:
        return skipped("the rendered audio could not be read")
    activity = tightcut.find_activity(levels, hop)
    total = len(levels) * hop
    runs = quiet_runs(levels, activity, hop)
    inner = [r for r in runs if r[0] > 0 and r[1] < total - hop / 2]
    dead = sum(e - s for s, e in inner if e - s >= tightcut.MAX_NATURAL_GAP_S)
    problems: list[dict[str, Any]] = []
    longest = 0.0
    for run in runs:
        for s, e in _minus_words(run, words):
            longest = max(longest, e - s)
            if e - s <= max_gap_s:
                continue
            lead, tail = s <= 0, e >= total - hop / 2
            a = s if lead else s + BREATH_AFTER_SPEECH_S
            b = e if tail else e - BREATH_BEFORE_SPEECH_S
            trim = edit_to_source(a, b, keep or []) if b - a >= MIN_TRIM_S else []
            where = "at the start" if lead else "at the end" if tail else f"at {clock(s)}"
            problems.append(
                _problem(
                    "gap",
                    f"a {e - s:.1f} second gap {where}",
                    {"trim": trim} if trim else None,
                    edit_start=round(s, 2),
                    edit_end=round(e, 2),
                    seconds=round(e - s, 2),
                )
            )
    for s, e in _wordless(words, heard, total, max_gap_s):
        if any(p["edit_start"] < e and p["edit_end"] > s for p in problems):
            continue  # the level reading found this one already
        longest = max(longest, e - s)
        a, b = s + BREATH_AFTER_SPEECH_S, e - BREATH_BEFORE_SPEECH_S
        trim = edit_to_source(a, b, keep or []) if b - a >= MIN_TRIM_S else []
        problems.append(
            _problem(
                "gap",
                f"nobody says anything for {e - s:.1f} seconds at {clock(s)} (only background sound)",
                {"trim": trim} if trim else None,
                edit_start=round(s, 2),
                edit_end=round(e, 2),
                seconds=round(e - s, 2),
            )
        )
    return _check(
        problems,
        longest_gap_s=round(longest, 2),
        dead_air_pct=round(100 * dead / total, 1) if total else 0.0,
        max_gap_s=max_gap_s,
        gaps=len(problems),
    )


def _wordless(
    words: list[dict[str, Any]],
    heard: list[dict[str, Any]] | None,
    total: float,
    max_gap_s: float,
) -> list[tuple[float, float]]:
    """Stretches between two kept words, longer than `max_gap_s`, where the recogniser
    listening to the render heard no word either. Empty without `heard` or its times."""
    timed = [
        (float(h["start"]), float(h["end"]))
        for h in heard or []
        if h.get("start") is not None and h.get("end") is not None
    ]
    if not timed or len(words) < 2:
        return []
    ordered = sorted(words, key=lambda w: float(w["start"]))
    out: list[tuple[float, float]] = []
    for a, b in zip(ordered, ordered[1:], strict=False):
        s = min(float(a["end"]), float(a["start"]) + MAX_WORD_S)
        e = min(float(b["start"]), total)
        if e - s <= max_gap_s:
            continue
        if any(s + WORD_PAD_S < (hs + he) / 2 < e - WORD_PAD_S for hs, he in timed):
            continue  # something is said there that the transcript does not hold
        out.append((s, e))
    return out


def edit_to_source(a: float, b: float, keep: list[list[float]]) -> list[list[float]]:
    """A stretch of the edited video as ranges on the recording (one per kept range it
    crosses), through the keep that made the file."""
    out: list[list[float]] = []
    offset = 0.0
    for s, e in keep:
        s, e = float(s), float(e)
        length = e - s
        lo, hi = max(a, offset), min(b, offset + length)
        if hi - lo > 1e-6:
            out.append([round(s + lo - offset, 3), round(s + hi - offset, 3)])
        offset += length
    return out


# ---------------------------------------------------------------------------
# Loudness


def ebur128_filter() -> str:
    """ffmpeg's EBU R128 meter with true peak; per-frame lines kept out of the log."""
    return "ebur128=peak=true:framelog=verbose"


_EBU_I = re.compile(r"\bI:\s*(-?\d+(?:\.\d+)?|-?inf|nan)\s*LUFS", re.I)
_EBU_PEAK = re.compile(r"\bPeak:\s*(-?\d+(?:\.\d+)?|-?inf|nan)\s*dBFS", re.I)


def _number(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def parse_ebur128(log: str) -> dict[str, float | None] | None:
    """Integrated loudness (LUFS) and true peak (dBTP) from the meter's summary. None
    when there is no summary; a value is None when the meter read silence."""
    _, found, summary = (log or "").rpartition("Summary:")
    if not found:
        return None
    i, peak = _EBU_I.search(summary), _EBU_PEAK.search(summary)
    if i is None:
        return None
    lufs = _number(i.group(1))
    if lufs is not None and lufs <= -70.0:
        lufs = None  # the meter's floor: nothing was heard
    return {"lufs": lufs, "true_peak_db": _number(peak.group(1)) if peak else None}


async def measure_loudness(path: str, ffmpeg: str) -> dict[str, float | None] | None:
    """The finished file's loudness, read by ffmpeg (a few seconds for a ten-minute
    video; audio only). None when ffmpeg cannot read it."""
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", ebur128_filter(),
        "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        return None
    return parse_ebur128(err.decode(errors="replace"))


def check_loudness(measured: dict[str, float | None] | None, duration_s: float) -> dict[str, Any]:
    if measured is None:
        return skipped("the loudness could not be measured")
    if duration_s < MIN_LOUDNESS_S:
        return skipped(f"too short to measure a loudness ({duration_s:.1f} s)", **measured)
    lufs, peak = measured.get("lufs"), measured.get("true_peak_db")
    problems: list[dict[str, Any]] = []
    if lufs is None:
        problems.append(_problem("silent", "there is no sound in this video"))
    else:
        if abs(lufs - LOUDNESS_LUFS) > LOUDNESS_TOLERANCE_LU:
            problems.append(
                _problem(
                    "loudness",
                    f"the loudness is {lufs:.1f} LUFS where {LOUDNESS_LUFS:g} is the target, "
                    "and the render could not correct it",
                )
            )
        if peak is not None and peak > LOUDNESS_PEAK_DB + PEAK_TOLERANCE_DB:
            problems.append(
                _problem(
                    "peak",
                    f"the loudest peak is {peak:.1f} dB where {LOUDNESS_PEAK_DB:g} is the ceiling",
                )
            )
    return _check(problems, lufs=lufs, true_peak_db=peak)


# ---------------------------------------------------------------------------
# Captions, from the data the render was drawn from


def caption_data(
    words: list[dict[str, Any]],
    pages: list[wordbox.Page] | None,
    cues: list[dict[str, Any]],
) -> dict[str, Any]:
    """What the render's captions hold, written beside the edit when it is rendered.

    Word-box captions (`pages`): every box state (the word it sits on, and when) and
    every word drawn on a page. Plain captions: the cue lines. `words` is what the
    captions were made from, on the edit clock, so a later check never depends on a plan
    that has moved on since.
    """
    said = [{"text": str(w["text"]), "start": float(w["start"]), "end": float(w["end"])} for w in words]
    if pages is None:
        return {
            "mode": "plain",
            "words": said,
            "cues": [
                {"start": c["start"], "end": c["end"], "text": " ".join(c.get("lines") or [])}
                for c in cues
            ],
        }
    boxes: list[dict[str, Any]] = []
    for start, end, p_index, boxed in wordbox.timeline(pages):
        if p_index is None or boxed is None:
            continue
        word = pages[p_index].words[boxed]
        if boxes and boxes[-1]["page"] == p_index and boxes[-1]["word"] == boxed:
            boxes[-1]["end"] = round(end, 3)  # the same box, carried across a state change
            continue
        boxes.append(
            {"text": wordbox.shown(word["text"]), "start": round(start, 3), "end": round(end, 3),
             "page": p_index, "word": boxed}
        )
    return {"mode": "wordbox", "words": said, "boxes": boxes, "pages": len(pages)}


def _quote(words: list[str], limit: int = 4) -> str:
    shown = ", ".join(f'"{w}"' for w in words[:limit])
    return shown + (f" and {len(words) - limit} more" if len(words) > limit else "")


def check_captions(
    data: dict[str, Any] | None, expected: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Every kept spoken word has a caption, and the caption says that word.

    `expected` are the words the edit keeps ({text, start} on the edit clock), from the
    plan and not from the caption data: a word the captions dropped on their way is
    then missing here. Without it (a render whose plan has moved on) the caption
    data's own word list is used, which still proves the boxes against it.

    Word boxes: the boxes in order against the spoken words in order. A word with no
    box is missing; a box with other text is a mismatch; a box more than a second from
    its word is on the wrong word. Plain captions: the cue words against the spoken
    words. Fillers are never captioned and are not counted.
    """
    if not data or not isinstance(data.get("words"), list):
        return skipped("this render has no caption data to check")
    words = spoken(expected if expected is not None else data["words"])
    if not words:
        return skipped("there are no spoken words to caption", words=0, captioned=0)
    want = [wordbox.shown(str(w["text"])) for w in words]
    if data.get("mode") == "wordbox":
        boxes = list(data.get("boxes") or [])
        have = [str(b.get("text") or "") for b in boxes]
    else:
        boxes = []
        have = [t for c in data.get("cues") or [] for t in str(c.get("text") or "").split()]
        want = [str(w["text"]) for w in words]
    missing: list[dict[str, Any]] = []
    wrong: list[dict[str, Any]] = []
    extra: list[str] = []
    captioned = 0
    for op, a0, a1, b0, b1 in SequenceMatcher(a=want, b=have, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(a1 - a0):
                word = words[a0 + k]
                box = boxes[b0 + k] if boxes else None
                if box is not None and abs(float(box["start"]) - float(word["start"])) > CAPTION_DRIFT_S:
                    wrong.append({"text": want[a0 + k], "at": word["start"], "caption": "shown at the wrong time"})
                else:
                    captioned += 1
        elif op == "delete":
            missing += [{"text": want[k], "at": words[k]["start"]} for k in range(a0, a1)]
        elif op == "replace":
            shown = " ".join(have[b0:b1])
            wrong += [{"text": want[k], "at": words[k]["start"], "caption": shown} for k in range(a0, a1)]
        else:
            extra += have[b0:b1]
    problems: list[dict[str, Any]] = []
    if missing:
        first = missing[0]
        problems.append(
            _problem(
                "caption_missing",
                f"{len(missing)} word{'s have' if len(missing) != 1 else ' has'} no caption: "
                f"{_quote([m['text'] for m in missing])}, the first at {clock(first['at'])}",
            )
        )
    if wrong:
        first = wrong[0]
        problems.append(
            _problem(
                "caption_mismatch",
                f'the caption at {clock(first["at"])} says "{first["caption"]}" where the word is '
                f'"{first["text"]}"'
                + (f", and {len(wrong) - 1} more do not match" if len(wrong) > 1 else ""),
            )
        )
    if extra:
        problems.append(
            _problem("caption_extra", f"the captions show words that are not in the video: {_quote(extra)}")
        )
    return _check(
        problems,
        mode=data.get("mode"),
        words=len(words),
        captioned=captioned,
        missing=missing[:20],
        mismatched=wrong[:20],
    )


# ---------------------------------------------------------------------------
# Audibility


def _peak(levels: list[float], a: float, b: float, hop: float) -> float | None:
    frames = levels[max(0, int(round(a / hop))) : max(0, int(round(b / hop)))]
    return max(frames) if frames else None


def check_audibility(
    kept: list[dict[str, Any]],
    marks: dict[int, str] | None,
    heard: list[dict[str, Any]] | None,
    levels: list[float] | None,
    *,
    why_not_heard: str | None = None,
    hop: float = tightcut.HOP_S,
) -> dict[str, Any]:
    """Every kept word is heard whole.

    - clipped: `marks` (autoedit.word_marks on the recording, with the keep that made
      the file) says a cut starts or ends inside a kept word. Fixable: that word gets
      more room on that side, the same hold his own "sounds clipped" note writes.
    - cut short by the phone: the recording itself lost the end. No cut brings it back.
    - not heard: `heard` is the render transcribed again. A kept word the recogniser
      did not hear at all, whose stretch of the rendered audio never reaches speech
      level either, cannot be heard. A word it only heard differently is not a
      failure: the recogniser mishears; the level reading is the second witness.
    """
    marks = marks or {}
    words = spoken(kept)
    problems: list[dict[str, Any]] = []
    clipped = phone = 0
    for w in words:
        mark = marks.get(w["index"]) if w.get("index") is not None else None
        if not mark:
            continue
        at = clock(w["start"])
        if mark == "phone cut its end short":
            phone += 1
            problems.append(
                _problem("phone_cut", f'the phone cut the end of "{w["text"]}" at {at}, and no edit can bring it back')
            )
        elif "ends inside" in mark:
            clipped += 1
            problems.append(
                _problem(
                    "clipped",
                    f'the cut at {at} ends inside "{w["text"]}"',
                    {"hold": [[round(float(w["source_end"]), 3), "end", CLIPPED_HOLD_S]]},
                )
            )
        elif "starts inside" in mark:
            clipped += 1
            problems.append(
                _problem(
                    "clipped",
                    f'the cut at {at} starts inside "{w["text"]}"',
                    {"hold": [[round(float(w["source_start"]), 3), "start", CLIPPED_HOLD_S]]},
                )
            )
    unheard: list[dict[str, Any]] = []
    differently = 0
    if heard is not None:
        want = [_token(w["text"]) for w in words]
        have = [
            t
            for h in heard
            for t in (_token(part) for part in str(h.get("text") or h.get("word") or "").split())
            if t
        ]
        activity = tightcut.find_activity(levels, hop) if levels else None
        for op, a0, a1, _b0, _b1 in SequenceMatcher(a=want, b=have, autojunk=False).get_opcodes():
            if op == "replace":
                differently += a1 - a0
            if op != "delete":
                continue
            for w in words[a0:a1]:
                peak = _peak(levels or [], float(w["start"]) - WORD_PAD_S, float(w["end"]) + WORD_PAD_S, hop)
                if activity is None:
                    differently += 1  # no second witness: never hold on the recogniser alone
                elif peak is None or peak < activity.high_db:
                    unheard.append(w)
                else:
                    differently += 1
        if unheard:
            first = unheard[0]
            problems.append(
                _problem(
                    "inaudible",
                    f"{len(unheard)} word{'s' if len(unheard) != 1 else ''} cannot be heard in the video: "
                    f"{_quote([str(u['text']) for u in unheard])}, the first at {clock(first['start'])}",
                )
            )
    return _check(
        problems,
        words=len(words),
        heard=len(words) - len(unheard) if heard is not None else None,
        listened=heard is not None,
        why_not_listened=None if heard is not None else (why_not_heard or "the recogniser was not asked"),
        clipped=clipped,
        phone_cut=phone,
        heard_differently=differently,
        inaudible=[{"text": u["text"], "at": u["start"]} for u in unheard[:20]],
    )


# ---------------------------------------------------------------------------
# Leftover asides: one subscription job over the words still in the video


ASIDES_SCHEMA = {
    "type": "object",
    "properties": {
        "asides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first": {"type": "integer"},
                    "last": {"type": "integer"},
                    "heard": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["first", "last", "heard", "why"],
            },
        }
    },
    "required": ["asides"],
}


def asides_system(dog_names: list[str], *, skill: str = "", rules: str = "", talk: str = "") -> str:
    """Jennifer's instructions for the leftover-asides check. `skill` is the hand-written
    skill file, `rules` the block of rules she learned from his notes (after it), `talk`
    the conversation rules of an agent talk."""
    dogs = " and ".join(dog_names) if dog_names else "his dogs"
    text = (
        "You are Jennifer, the video editor. You are checking an edit that is already cut. "
        "Below is every word the viewer hears in the finished video, in order, each tagged "
        "with its number. He films himself on his phone while he walks, often with his dogs, "
        f"{dogs}, and speaks English with an Israeli accent.\n\n"
        "Your one job in this check: find anything still in the video that is not said to "
        "the viewer.\n"
        f"1. Talk to the dogs: their names ({dogs}), 'come', 'come here', 'this way', 'good "
        "boy', 'no, no, no' said to a dog. He calls them in Hebrew too, which the recogniser "
        "writes as 'boy', 'bo' or 'bow', or as English that makes no sense where it stands.\n"
        "2. Talk to people around him or to himself: 'wait', 'let me say that again', "
        "'where was I'.\n"
        "3. Remarks that have nothing to do with what this video is about.\n"
        "Do not look for retakes, wording or misheard words: that was done before you. A "
        "sentence that makes a point belongs to the video, even a casual one. When unsure, "
        "leave it in. An empty list is the normal answer.\n\n"
        "For each one give the first and last word number, quote exactly the words shown "
        "between them, and say why in a few words."
    )
    if skill:
        text += f"\n\nHIS STANDING RULES (the editor's skill file):\n{skill}"
    if rules:
        text += f"\n\n{rules}"
    if talk:
        text += f"\n\n{talk}"
    return text


def rendered_transcript(kept: list[dict[str, Any]], speakers: dict[int, str] | None = None) -> str:
    """The words still in the video, one sentence a line with its place in the edit,
    every word tagged with its number in the transcript."""
    lines: list[str] = []
    cur: list[str] = []
    stamp = ""
    prev_who: str | None = None
    prev_end: float | None = None
    for w in kept:
        if w.get("index") is None:
            continue
        who = speakers.get(w["index"]) if speakers else None
        gap = float(w["start"]) - prev_end if prev_end is not None else 0.0
        if cur and (who != prev_who or len(cur) >= 24 or gap >= 1.0):
            lines.append(stamp + " ".join(cur))
            cur = []
        if not cur:
            stamp = f"[{clock(w['start'])}] " + (f"{who}: " if who else "")
        prev_who, prev_end = who, float(w["end"])
        cur.append(f"{w['index']}:{w['text']}")
        if str(w["text"])[-1:] in ".?!":
            lines.append(stamp + " ".join(cur))
            cur = []
    if cur:
        lines.append(stamp + " ".join(cur))
    return "\n".join(lines)


def asides_prompt(kept: list[dict[str, Any]], context: str, speakers: dict[int, str] | None = None) -> str:
    return (
        f"{context}\n\nThe finished video (number:word, times in the edit):\n"
        f"{rendered_transcript(kept, speakers)}\n\n"
        "Return what is still in the video that is not said to the viewer. An empty list "
        "is a normal answer."
    )


def check_asides(
    kept: list[dict[str, Any]],
    answer: dict[str, Any] | None,
    *,
    protected: frozenset[int] | set[int] | None = None,
) -> dict[str, Any]:
    """What the job found, proven by quoting. Each aside becomes a cut on the recording.

    An aside that misquotes its words, reaches outside the video, is longer than
    MAX_ASIDE_WORDS or holds only the agent's words (`protected`, an agent talk) is
    dropped. If what is left is more than MAX_ASIDE_SHARE of the video the answer is a
    misreading, not a check, and nothing is cut.
    """
    if answer is None:
        return skipped("Jennifer's reading of the words did not come back")
    by_index = {w["index"]: w for w in kept if w.get("index") is not None}
    order = sorted(by_index)
    guarded = frozenset(protected or ())
    problems: list[dict[str, Any]] = []
    dropped: list[str] = []
    taken: set[int] = set()
    for a in answer.get("asides") or []:
        try:
            first, last = int(a["first"]), int(a["last"])
        except (KeyError, TypeError, ValueError):
            continue
        inside = [i for i in order if first <= i <= last]
        if not inside or first not in by_index or last not in by_index or len(inside) > MAX_ASIDE_WORDS:
            dropped.append(f"an aside at {first}-{last} pointed outside the video or was too long")
            continue
        said = " ".join(str(by_index[i]["text"]) for i in inside)
        if _norm(said) != _norm(str(a.get("heard") or "")):
            dropped.append(f'an aside at {first}-{last} quoted "{a.get("heard")}"')
            continue
        mine = [i for i in inside if i not in guarded and i not in taken]
        if not mine:
            continue
        taken |= set(mine)
        # One cut per run of his own words: the agent's words inside it stay.
        runs: list[list[int]] = []
        for i in mine:
            if runs and order.index(i) == order.index(runs[-1][-1]) + 1:
                runs[-1].append(i)
            else:
                runs.append([i])
        cut = [
            [round(float(by_index[r[0]]["source_start"]), 3), round(float(by_index[r[-1]]["source_end"]), 3)]
            for r in runs
        ]
        text = " ".join(str(by_index[i]["text"]) for i in mine)
        why = str(a.get("why") or "").strip().rstrip(".")[:120]
        problems.append(
            _problem(
                "aside",
                f'"{text[:80]}" at {clock(by_index[mine[0]]["start"])} is not said to the viewer'
                + (f" ({why})" if why else ""),
                {"cut": cut},
                words=len(mine),
                why=why,
            )
        )
    if order and len(taken) > MAX_ASIDE_SHARE * len(order):
        return skipped(
            f"the reading wanted to take out {len(taken)} of {len(order)} words, which is not a check",
            dropped=dropped,
        )
    return _check(problems, asides=len(problems), dropped=dropped)


# ---------------------------------------------------------------------------
# Fix or hold


def merged_fixes(problems: list[dict[str, Any]]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {"trim": [], "cut": [], "hold": []}
    for p in problems:
        for key, value in (p.get("fix") or {}).items():
            out[key].extend(value)
    return {k: v for k, v in out.items() if v}


def numbers(checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The numbers the card shows, from the checks that could be made."""
    gaps, loud = checks.get("gaps") or {}, checks.get("loudness") or {}
    caps, aud, asides = checks.get("captions") or {}, checks.get("audibility") or {}, checks.get("asides") or {}
    return {
        "longest_gap_s": gaps.get("longest_gap_s"),
        "dead_air_pct": gaps.get("dead_air_pct"),
        "lufs": loud.get("lufs"),
        "true_peak_db": loud.get("true_peak_db"),
        "words": caps.get("words") if caps.get("words") is not None else aud.get("words"),
        "captioned": caps.get("captioned"),
        "heard": aud.get("heard"),
        "listened": bool(aud.get("listened")),
        "asides": asides.get("asides") if asides.get("state") != "skipped" else None,
    }


def numbers_line(n: dict[str, Any], checks: dict[str, dict[str, Any]]) -> str:
    parts: list[str] = []
    if n.get("longest_gap_s") is not None:
        parts.append(f"longest pause {n['longest_gap_s']:.1f} s")
    if n.get("dead_air_pct") is not None:
        parts.append(f"dead air {n['dead_air_pct']:.0f}%")
    if n.get("lufs") is not None:
        peak = f", peak {n['true_peak_db']:.1f} dB" if n.get("true_peak_db") is not None else ""
        parts.append(f"loudness {n['lufs']:.1f} LUFS{peak}")
    if n.get("captioned") is not None and n.get("words"):
        parts.append(f"{n['captioned']} of {n['words']} words captioned")
    if n.get("listened") and n.get("heard") is not None and n.get("words"):
        parts.append("every word heard" if n["heard"] >= n["words"] else f"{n['heard']} of {n['words']} words heard")
    if n.get("asides") == 0:
        parts.append("nothing off topic left in")
    not_made = [
        NOT_CHECKED[name] for name, c in checks.items() if c.get("state") == "skipped" and name in NOT_CHECKED
    ]
    if not (checks.get("audibility") or {}).get("listened") and "audibility" in checks:
        not_made.append("not listened to again")
    line = ", ".join(parts) or "nothing could be measured"
    if not_made:
        line += ". Not checked this time: " + ", ".join(dict.fromkeys(not_made))
    return line


NOT_CHECKED = {
    "gaps": "the pauses",
    "asides": "leftover asides",
    "captions": "the captions",
    "loudness": "the loudness",
}


def decide(
    checks: dict[str, dict[str, Any]], *, round_no: int, mode: str = "fix", fixed: list[str] | None = None
) -> dict[str, Any]:
    """Fix or hold, from what the checks found.

    - nothing wrong: `passed` on the first check, `fixed` on the re-check after her fix;
    - something a cut can fix, on the first check: `fixing` (the caller writes the
      overrides and renders ONCE more), with what cannot be fixed kept for the re-check;
    - anything wrong on the re-check, or only things no cut can fix: `held`, with one
      plain line saying why;
    - mode "report": never a fix and never a hold, only the line.
    `fixed` names what the one fix did, for the line of a re-check.
    """
    problems = [p for name in checks for p in checks[name].get("problems") or []]
    fixable = [p for p in problems if p.get("fix")]
    n = numbers(checks)
    measured = numbers_line(n, checks)
    more = f" (and {len(problems) - 1} more)" if len(problems) > 1 else ""
    if not problems:
        state = "fixed" if round_no else "passed"
        done = f", after one fix ({'; '.join(fixed)})" if round_no and fixed else ""
        line = f"Checked by Jennifer{done}: {measured}."
        fixes: dict[str, list[Any]] = {}
    elif mode == "report":
        state, fixes = "report", {}
        line = (
            f"Jennifer found {len(problems)} thing{'s' if len(problems) != 1 else ''} and changed "
            f"nothing (checking only): {problems[0]['detail']}{more}."
        )
    elif round_no == 0 and fixable:
        state, fixes = "fixing", merged_fixes(fixable)
        line = (
            f"Jennifer is fixing {len(fixable)} thing{'s' if len(fixable) != 1 else ''} and rendering "
            f"once more: {fixable[0]['detail']}"
            + (f" (and {len(fixable) - 1} more)" if len(fixable) > 1 else "")
            + "."
        )
    else:
        state, fixes = "held", {}
        # What no cut can fix is the reason; a fixable thing still there after the one
        # fix is the reason only when nothing else is.
        first = next((p for p in problems if not p.get("fix")), problems[0])
        still = " after one fix" if round_no and first.get("fix") else ""
        line = f"Jennifer is holding this video: {first['detail']}{still}{more}."
    return {
        "version": QC_VERSION,
        "state": state,
        "round": round_no,
        "line": line[:500],
        "numbers": n,
        "problems": [{k: v for k, v in p.items() if k != "fix"} for p in problems][:40],
        "fixes": fixes,
        "fixed": list(fixed or []),
        "checks": {
            name: {k: v for k, v in c.items() if k != "problems"} | {"problems": len(c.get("problems") or [])}
            for name, c in checks.items()
        },
    }


def fix_sentences(problems: list[dict[str, Any]]) -> list[str]:
    """What the one fix does, in a few words each, for the card."""
    out: list[str] = []
    for p in problems:
        if not p.get("fix"):
            continue
        if p["kind"] == "gap":
            out.append(f"cut {p['detail']}")
        elif p["kind"] == "aside":
            out.append(f"took out {p['detail'].split(' is not said')[0]}")
        elif p["kind"] == "clipped":
            out.append("gave a clipped word more room")
    return out[:6]
