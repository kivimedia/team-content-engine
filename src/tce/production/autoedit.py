"""TCE edits by itself, on the subscription (25-Sep): proofreading and editing requests.

"allow tce to do editing by itself on subscription". Two subscription jobs, both run
by the PC worker on the policy model (never a metered API):

- `video_proofread`: after transcription, fix words the recogniser clearly misheard.
  On 24-Sep it heard "Not after you've finished your service" where Ziv said no "not",
  flipping his point. Conservative by design: a correction must quote the exact words
  it replaces by index, or it is dropped.
- `video_edit_request`: carry out what he typed in "Request an editing change" -
  word fixes, cuts, restores - or come back with one question.

This module is pure: prompts, schemas, and applying results to a transcript and an
edit plan. The router owns the background tasks, statuses and rendering.
"""

from __future__ import annotations

import re
from typing import Any

from tce.production.retakes import map_to_edit

PROOFREAD_JOB = "video_proofread"
EDIT_REQUEST_JOB = "video_edit_request"
AGENT_NAME = "video_editor"
PROMPT_VERSION = "autoedit-v1"
MAX_CORRECTIONS = 12

_NORM = re.compile(r"[^\w']+")


def _norm(text: str) -> str:
    return " ".join(_NORM.sub(" ", text.lower()).split())


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


# ---------------------------------------------------------------------------
# What the model sees


def numbered_transcript(
    words: list[dict[str, Any]], keep: list[list[float]] | None = None
) -> str:
    """One sentence a line, every word tagged with its index.

    With a plan, each line starts with where it lands in the EDITED video (that is the
    clock he watches), and words the edit removed are wrapped in ~~ so a request can
    bring them back.
    """
    lines: list[str] = []
    cur: list[str] = []
    stamp = ""
    for i, w in enumerate(words):
        start = float(w["start_s"])
        if not cur:
            if keep is None:
                stamp = f"[{_clock(start)}] "
            else:
                edited = map_to_edit(start, keep)
                stamp = f"[{_clock(edited)} in the edit] " if edited is not None else "[cut] "
        token = f"{i}:{w['text']}"
        if keep is not None and map_to_edit((start + float(w['end_s'])) / 2, keep) is None:
            token = f"~~{token}~~"
        cur.append(token)
        if str(w["text"])[-1:] in ".?!" or len(cur) >= 24:
            lines.append(stamp + " ".join(cur))
            cur = []
    if cur:
        lines.append(stamp + " ".join(cur))
    return "\n".join(lines)


def script_context(packet: Any | None, title: str | None) -> str:
    parts = [f"Topic: {title}"] if title else []
    if packet is not None:
        bullets = [str(b) for b in (getattr(packet, "bullets", None) or [])]
        phrases = [str(p) for p in (getattr(packet, "script_phrases", None) or [])]
        if bullets:
            parts.append("His points:\n" + "\n".join(f"- {b}" for b in bullets))
        if phrases:
            parts.append("The script he was reading from (he often speaks freely):\n"
                         + "\n".join(phrases))
    return "\n\n".join(parts) or "(no script for this recording)"


PROOFREAD_SYSTEM = (
    "You proofread an automatic speech-recognition transcript of a walking video by "
    "Ziv Raviv (English, Israeli accent, outdoors). The recogniser sometimes mishears a "
    "word, and a misheard word can flip his meaning - e.g. it once heard 'Not after "
    "you've finished your service' where he said 'After you've finished your service', "
    "contradicting his own point.\n"
    "Fix ONLY words that are clearly misheard: they contradict what he is plainly saying, "
    "are nonsense in context, or garble a name or term from his script. Never rephrase, "
    "never improve grammar, never remove filler, never tidy his spoken style. When unsure, "
    "leave it: a wrong 'fix' puts words in his mouth. Most transcripts need zero or one "
    "correction.\n"
    "Each correction names the first and last word index it replaces, quotes those words "
    "exactly as heard, and gives the replacement text (empty string to delete). Include a "
    "neighbouring word when its capitalisation must change (e.g. heard 'Not after', "
    "replacement 'After')."
)

_CORRECTION = {
    "type": "object",
    "properties": {
        "first": {"type": "integer"},
        "last": {"type": "integer"},
        "heard": {"type": "string"},
        "replacement": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["first", "last", "heard", "replacement", "why"],
}
_RANGE = {
    "type": "object",
    "properties": {"first": {"type": "integer"}, "last": {"type": "integer"}},
    "required": ["first", "last"],
}

PROOFREAD_SCHEMA = {
    "type": "object",
    "properties": {"corrections": {"type": "array", "items": _CORRECTION}},
    "required": ["corrections"],
}


def proofread_prompt(words: list[dict[str, Any]], context: str) -> str:
    return (
        f"{context}\n\nTranscript (index:word):\n{numbered_transcript(words)}\n\n"
        f"Return the clearly misheard words to fix, at most {MAX_CORRECTIONS}. An empty "
        "list is the normal answer for a clean transcript."
    )


EDIT_REQUEST_SYSTEM = (
    "You are the video editor for Ziv Raviv's walking videos. He watched the edited "
    "video and typed a request. Carry it out with these tools only:\n"
    "- corrections: fix transcript words (the captions come from them). Quote the exact "
    "words by index; replacement '' deletes.\n"
    "- cut: remove a range of words (by index) from the video.\n"
    "- restore: put back words the edit removed (shown wrapped in ~~).\n"
    "Times in the transcript are where each line lands in the EDITED video, the clock he "
    "watches. Do exactly what he asked and nothing more. If the request cannot be done "
    "with these tools, or you cannot tell what he means, set needs_you true and ask ONE "
    "short question naming what you checked. reply: one or two plain sentences to him "
    "saying what you changed, quoting the new words where you fixed captions."
)

EDIT_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "needs_you": {"type": "boolean"},
        "question": {"type": "string"},
        "corrections": {"type": "array", "items": _CORRECTION},
        "cut": {"type": "array", "items": _RANGE},
        "restore": {"type": "array", "items": _RANGE},
    },
    "required": ["reply", "needs_you", "corrections", "cut", "restore"],
}


def edit_request_prompt(
    words: list[dict[str, Any]],
    keep: list[list[float]],
    context: str,
    request: str,
    *,
    scope: str,
    start_s: float | None,
    end_s: float | None,
) -> str:
    where = ""
    if scope == "timestamp" and start_s is not None and end_s is not None:
        where = f"\nHe pointed at {_clock(start_s)} to {_clock(end_s)} in the edited video."
    return (
        f"{context}\n\nHis request:\n{request.strip()}{where}\n\n"
        f"Transcript (index:word; ~~cut~~ words are not in the edit):\n"
        f"{numbered_transcript(words, keep)}"
    )


# ---------------------------------------------------------------------------
# Applying what came back


def apply_corrections(
    words: list[dict[str, Any]], corrections: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply corrections whose quote matches the words at those indices exactly.

    Returns (new words, applied). Applied last-to-first so earlier indices hold. A
    correction that misquotes, overlaps another, or falls outside the list is dropped:
    the model must prove it is looking at the words it changes.
    """
    valid: list[dict[str, Any]] = []
    taken: set[int] = set()
    for c in corrections[:MAX_CORRECTIONS]:
        try:
            first, last = int(c["first"]), int(c["last"])
        except (KeyError, TypeError, ValueError):
            continue
        if first < 0 or last < first or last >= len(words):
            continue
        span = range(first, last + 1)
        if taken.intersection(span):
            continue
        heard = " ".join(str(w["text"]) for w in words[first : last + 1])
        if _norm(heard) != _norm(str(c.get("heard") or "")):
            continue
        replacement = str(c.get("replacement") or "").strip()
        if replacement == heard:
            continue
        taken.update(span)
        valid.append({**c, "first": first, "last": last, "heard": heard, "replacement": replacement})

    out = [dict(w) for w in words]
    for c in sorted(valid, key=lambda c: c["first"], reverse=True):
        first, last = c["first"], c["last"]
        start, end = float(out[first]["start_s"]), float(out[last]["end_s"])
        new = replacement_words(c["replacement"], start, end, out[first].get("precision", "word"))
        out[first : last + 1] = new
    return out, sorted(valid, key=lambda c: c["first"])


def replacement_words(text: str, start: float, end: float, precision: str) -> list[dict[str, Any]]:
    tokens = text.split()
    if not tokens:
        return []
    step = (end - start) / len(tokens)
    return [
        {
            "text": t,
            "start_s": round(start + k * step, 3),
            "end_s": round(start + (k + 1) * step, 3),
            "precision": precision,
        }
        for k, t in enumerate(tokens)
    ]


def word_ranges(
    words: list[dict[str, Any]], ranges: list[dict[str, Any]]
) -> list[list[float]]:
    out: list[list[float]] = []
    for r in ranges:
        try:
            first, last = int(r["first"]), int(r["last"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= first <= last < len(words):
            out.append([float(words[first]["start_s"]), float(words[last]["end_s"])])
    return out


def _merge(ranges: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def apply_overrides(plan: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Keep = (planned keep + restored) - cut. Persisted overrides survive re-plans."""
    if not overrides:
        return plan
    keep = _merge([list(r) for r in plan.get("keep") or []] + [list(r) for r in overrides.get("restore") or []])
    keep = _subtract(keep, [list(r) for r in overrides.get("cut") or []])
    keep = [[round(s, 3), round(e, 3)] for s, e in keep if e - s > 0.05]
    units = []
    for u in plan.get("units") or []:
        mid = (float(u["start"]) + float(u["end"])) / 2
        units.append({**u, "kept": any(s <= mid <= e for s, e in keep)})
    stats = dict(plan.get("stats") or {})
    stats["kept_seconds"] = round(sum(e - s for s, e in keep), 2)
    stats["ranges"] = len(keep)
    return {**plan, "keep": keep, "units": units, "stats": stats, "overrides": overrides}


def merge_overrides(
    old: dict[str, Any] | None, cut: list[list[float]], restore: list[list[float]]
) -> dict[str, Any]:
    """The newest instruction wins: restoring what an earlier request cut lifts that cut."""
    old = old or {}
    old_cut = _subtract([list(r) for r in old.get("cut") or []], restore)
    old_restore = _subtract([list(r) for r in old.get("restore") or []], cut)
    return {"cut": _merge(old_cut + cut), "restore": _merge(old_restore + restore)}


def _subtract(ranges: list[list[float]], minus: list[list[float]]) -> list[list[float]]:
    out = _merge(ranges)
    for ms, me in _merge(minus):
        nxt: list[list[float]] = []
        for s, e in out:
            if me <= s or ms >= e:
                nxt.append([s, e])
                continue
            if s < ms:
                nxt.append([s, ms])
            if me < e:
                nxt.append([me, e])
        out = nxt
    return out
