"""TCE edits by itself, on the subscription (25-Sep): the editor's review and editing requests.

"allow tce to do editing by itself on subscription". Two subscription jobs, both run
by the PC worker on the policy model (never a metered API):

- `video_edit_review` (28-Sep, replaced the 25-Sep proofread): after transcription,
  fix words the recogniser clearly misheard (it heard "Not after you've finished your
  service" where Ziv said no "not", flipping his point) and decide what the viewer
  should not hear - retakes (the complete take stays), talk to the dogs, recogniser
  junk. Conservative by design: every correction and every removal must quote the
  exact words by index, or it is dropped.
- `video_edit_request`: carry out what he typed in "Request an editing change" -
  word fixes, cuts, restores - or come back with one question.

This module is pure: prompts, schemas, and applying results to a transcript and an
edit plan. The router owns the background tasks, statuses and rendering.
"""

from __future__ import annotations

import re
from typing import Any

from tce.production.retakes import map_to_edit

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
    words: list[dict[str, Any]],
    keep: list[list[float]] | None = None,
    kept: list[dict[str, Any]] | None = None,
) -> str:
    """One sentence a line, every word tagged with its index.

    With a plan, each line starts with where it lands in the EDITED video (that is the
    clock he watches), and words the edit removed are wrapped in ~~ so a request can
    bring them back. `kept` is the plan's own kept words with their times on the
    speech (28-Sep): the cut follows the audio, so the recogniser's clock alone would
    call some kept words cut.
    """
    timed = {int(w["index"]): float(w["start"]) for w in kept or [] if "index" in w}
    lines: list[str] = []
    cur: list[str] = []
    stamp = ""
    for i, w in enumerate(words):
        start = timed.get(i, float(w["start_s"]))
        if not cur:
            if keep is None:
                stamp = f"[{_clock(start)}] "
            else:
                edited = map_to_edit(start, keep)
                stamp = f"[{_clock(edited)} in the edit] " if edited is not None else "[cut] "
        token = f"{i}:{w['text']}"
        if keep is not None and (
            i not in timed if timed else map_to_edit((start + float(w["end_s"])) / 2, keep) is None
        ):
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

# ---------------------------------------------------------------------------
# The editor's review (28-Sep): proofread and decide what the viewer should not hear,
# in one subscription job. "when I repeat a line twice (even partially) the editor is
# supposed to choose one that is full. If I call my dogs maple, rain bou (בואו) that
# needs to be edited out. if I say no no no rain that needs to be taken out."

REVIEW_JOB = "video_edit_review"
REVIEW_PROMPT_VERSION = "edit-review-v2"
REMOVAL_KINDS = ("retake", "false_start", "aside", "junk")
# Talk to a dog is a few words; a take said again can be a long sentence.
MAX_REMOVAL_WORDS = {"retake": 80, "false_start": 80, "aside": 30, "junk": 40}
MAX_REMOVED_SHARE = 0.6


def review_system(dog_names: list[str]) -> str:
    dogs = " and ".join(dog_names) if dog_names else "his dogs"
    return (
        "You edit Ziv Raviv's walking videos. He films himself on his phone while he walks, "
        f"often with his two dogs, {dogs}, and speaks English with an Israeli accent. You get "
        "the speech-recognition transcript, every word tagged with its index, and the script "
        "he had. Decide what the viewer should NOT hear, and fix words the recogniser clearly "
        "misheard.\n\n"
        "REMOVE:\n"
        "1. Retakes. When he says a line more than once - fully or partly, word for word or "
        "reworded - keep exactly one take: the complete one; if more than one is complete, the "
        "last complete one. Remove every other take, including a start he abandoned and said "
        "again (\"Which ... Which means that the sales call is the first step\"), even when "
        "other words or a long pause sit between the takes. Remove whole takes; never cut words "
        "out of the take you keep.\n"
        "2. Asides: anything said to the dogs, to people around him, or to himself rather than "
        f"to the viewer - the dogs' names ({dogs}), 'come', 'come here', 'this way', 'good boy', "
        "'no, no, no' said to a dog or to reject what he just said, 'wait', 'let me say that "
        "again'. He calls the dogs in Hebrew too (for example בואו, 'come'), "
        "which the recogniser writes as 'boy', 'bo' or 'bow', or translates into English "
        "('from here', 'we're here'). An aside often sits between two takes of a line.\n"
        "3. Junk: words the recogniser invented - many words inside a fraction of a second, or "
        "words that make no sense where they stand, most often at the very end.\n"
        "A line marked NOT ENGLISH was heard as another language when listened to again on its "
        "own: that is Hebrew he says to the dogs or to himself, and the English words on it are "
        "the recogniser's guess. Remove it as an aside unless the English on it plainly belongs to "
        "his point. [sound] is speech the recogniser could not make into words (a false start); it "
        "is cut on its own, leave it out of your removals.\n"
        "Keep everything else, in order. Never remove a sentence that makes a point he does not "
        "make in a take you keep. When unsure whether something is an aside or part of his "
        "point, keep it.\n\n"
        "FIX (corrections): only words that are clearly misheard - they contradict what he "
        "plainly says, are nonsense in context, or garble a name or term from his script. A "
        "misheard word can flip his point: it once heard 'Not after you've finished your "
        "service' where he said 'After you've finished your service'. Never rephrase, never "
        "tidy his spoken style; when unsure, leave it, because a wrong fix puts words in his "
        "mouth. Most transcripts need zero or one correction. Include a neighbouring word when "
        "its capitalisation must change (heard 'Not after', replacement 'After').\n\n"
        "Every removal gives the first and last word index, quotes those words exactly as heard, "
        "names its kind, and for a retake or false_start gives kept_from: the index of the first "
        "word of the take you keep (-1 otherwise). Every correction quotes the exact words it "
        "replaces by index; replacement '' deletes."
    )


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "removals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first": {"type": "integer"},
                    "last": {"type": "integer"},
                    "heard": {"type": "string"},
                    "kind": {"type": "string", "enum": list(REMOVAL_KINDS)},
                    "kept_from": {"type": "integer"},
                    "why": {"type": "string"},
                },
                "required": ["first", "last", "heard", "kind", "kept_from", "why"],
            },
        },
        "corrections": {"type": "array", "items": _CORRECTION},
    },
    "required": ["removals", "corrections"],
}


def review_transcript(words: list[dict[str, Any]]) -> str:
    """One utterance a line with its clock, and the pauses between them: a retake shows
    as the same words again after a pause, an aside as a short line among long ones.

    A stretch the second listen heard as another language gets its own line saying so,
    with what it sounds like in Hebrew; "[sound]" is speech it could not make into words.
    """
    lines: list[str] = []
    cur: list[str] = []
    stamp = ""
    prev_end: float | None = None
    prev_lang: str | None = None
    for i, w in enumerate(words):
        start, end = float(w["start_s"]), float(w["end_s"])
        gap = start - prev_end if prev_end is not None else 0.0
        lang = w.get("lang") or None
        if cur and (gap >= 1.0 or len(cur) >= 24 or lang != prev_lang):
            lines.append(stamp + " ".join(cur))
            cur = []
        if gap >= 1.5:
            lines.append(f"(pause {gap:.1f} s)")
        if not cur:
            stamp = f"[{_clock(start)}] "
            if lang:
                heard = f'; in Hebrew it sounds like "{w["heard_as"]}"' if w.get("heard_as") else ""
                stamp += f"(NOT ENGLISH - heard as '{lang}'{heard}) "
        prev_lang = lang
        cur.append(f"{i}:{w['text']}")
        if str(w["text"])[-1:] in ".?!":
            lines.append(stamp + " ".join(cur))
            cur = []
        prev_end = end
    if cur:
        lines.append(stamp + " ".join(cur))
    return "\n".join(lines)


def review_prompt(words: list[dict[str, Any]], context: str) -> str:
    return (
        f"{context}\n\nTranscript (index:word):\n{review_transcript(words)}\n\n"
        "Return the removals (retakes, asides, junk) and the clearly misheard words to fix. "
        f"At most {MAX_CORRECTIONS} corrections. Empty lists are a normal answer."
    )


def validate_removals(
    words: list[dict[str, Any]], removals: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    """Removals as time ranges, each proven by quoting the words at its indices.

    A misquote, an overlap, an index outside the transcript or a span longer than its
    kind allows (MAX_REMOVAL_WORDS) is dropped. If what is left would remove more than
    MAX_REMOVED_SHARE of the words, None: that is not an edit, it is a
    misunderstanding, and the rules decide instead.
    """
    valid: list[dict[str, Any]] = []
    notes: list[str] = []
    taken: set[int] = set()
    for r in removals or []:
        try:
            first, last = int(r["first"]), int(r["last"])
        except (KeyError, TypeError, ValueError):
            continue
        kind = str(r.get("kind") or "")
        if kind not in REMOVAL_KINDS:
            continue
        if first < 0 or last < first or last >= len(words) or last - first + 1 > MAX_REMOVAL_WORDS[kind]:
            notes.append(f"skipped a removal at {first}-{last}: outside the transcript or too long")
            continue
        span = set(range(first, last + 1))
        if taken & span:
            continue
        heard = " ".join(str(w["text"]) for w in words[first : last + 1])
        if _norm(heard) != _norm(str(r.get("heard") or "")):
            notes.append(f'skipped a removal at {first}-{last}: it quoted "{r.get("heard")}"')
            continue
        taken |= span
        item = {
            "start": float(words[first]["start_s"]),
            "end": float(words[last]["end_s"]),
            "text": heard,
            "kind": kind,
            "why": str(r.get("why") or "")[:200],
        }
        kept_from = r.get("kept_from")
        if kind in ("retake", "false_start") and isinstance(kept_from, int) and 0 <= kept_from < len(words):
            if kept_from not in span:
                item["keeper_start"] = float(words[kept_from]["start_s"])
        valid.append(item)
    if words and len(taken) > MAX_REMOVED_SHARE * len(words):
        notes.append(
            f"the review wanted to remove {len(taken)} of {len(words)} words; used the rules instead"
        )
        return None, notes
    return sorted(valid, key=lambda v: v["start"]), notes


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
    kept: list[dict[str, Any]] | None = None,
) -> str:
    where = ""
    if scope == "timestamp" and start_s is not None and end_s is not None:
        where = f"\nHe pointed at {_clock(start_s)} to {_clock(end_s)} in the edited video."
    return (
        f"{context}\n\nHis request:\n{request.strip()}{where}\n\n"
        f"Transcript (index:word; ~~cut~~ words are not in the edit):\n"
        f"{numbered_transcript(words, keep, kept)}"
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
