"""Hearing a recording to its end (27-Nov).

A walk heard by the recogniser as one file can stop after its first line: the
transcript ended at word 16 (0:07) while the original ran on with the whole script.
Every edit after that worked from the 7 seconds the transcript held, and Jennifer,
reading a note against that transcript, asked him to upload the walk again although
it was on the server all along ("Watch the original" plays it to the end).

So before an edit, the speech on the original's audio is compared with where the
transcript ends. Speech well after the last word means the rest was never heard: those
stretches are cut from the original and heard on their own (the recogniser hears 30 s
at a time, so a stretch is at most CLIP_S), and the words come back at their place on
the recording's clock. Nothing before the last word is touched.

Pure apart from the hearing, which the router passes in.
"""

from __future__ import annotations

from typing import Any

GAP_S = 3.0  # speech starting this long after the last word was not heard
MIN_SPEECH_S = 2.0  # less unheard speech than this is a cough or a car, not a script
PAD_S = 0.3
CLIP_S = 25.0  # the recogniser hears 30 s at a time
MAX_CLIPS = 120  # 50 minutes of unheard speech; the rest waits for another edit


def heard_until(words: list[dict[str, Any]]) -> float:
    """Where the transcript ends on the recording's clock."""
    return max((float(w.get("end_s") or 0.0) for w in words), default=0.0)


def unheard_stretches(
    words: list[dict[str, Any]],
    regions: list[tuple[float, float]],
    duration_s: float | None = None,
    heard_through_s: float = 0.0,
) -> list[tuple[float, float]]:
    """The stretches of the original, after the transcript's last word, that hold speech
    the transcript does not: [(start, end)] seconds, each at most CLIP_S, in order.
    Empty when the transcript reaches the end of the speech. `heard_through_s`: how far
    the original was already heard this way, so a stretch heard once (a laugh, a car,
    nothing the recogniser could write down) is not heard again on every edit."""
    last = max(heard_until(words), float(heard_through_s or 0.0))
    end_of_file = float(duration_s) if duration_s else None
    after = [(max(float(s), last), float(e)) for s, e in regions if float(e) > last + GAP_S]
    after = [(s, e) for s, e in after if e > s]
    if sum(e - s for s, e in after) < MIN_SPEECH_S:
        return []
    clips: list[list[float]] = []
    for s, e in after:
        a, b = max(last, s - PAD_S), e + PAD_S
        if end_of_file is not None:
            b = min(b, end_of_file)
        if clips and b - clips[-1][0] <= CLIP_S:
            clips[-1][1] = b  # the next region joins the stretch
        else:
            clips.append([a, b])
    out: list[tuple[float, float]] = []
    for a, b in clips:
        while b - a > CLIP_S:  # one long region: heard in recogniser-sized pieces
            out.append((round(a, 3), round(a + CLIP_S, 3)))
            a += CLIP_S
        if b > a:
            out.append((round(a, 3), round(b, 3)))
    return out[:MAX_CLIPS]


def place(
    words: list[dict[str, Any]],
    heard: list[tuple[float, float, dict[str, Any] | None]],
) -> list[dict[str, Any]]:
    """The words heard in each stretch, on the recording's clock, after the transcript's
    last word. `heard` is [(start, end, clip result)]; a clip result is the worker's
    answer, {"words": [{"word", "start", "end"}]} with times from the stretch's start.
    A word belongs to the stretch its middle falls in, so a word cut by a piece boundary
    is not counted twice."""
    last = heard_until(words)
    out: list[dict[str, Any]] = []
    for a, b, res in sorted(heard, key=lambda h: h[0]):
        for w in (res or {}).get("words") or []:
            text = str(w.get("word") or w.get("text") or "").strip()
            try:
                s, e = a + float(w["start"]), a + float(w["end"])
            except (KeyError, TypeError, ValueError):
                continue
            mid = (s + e) / 2
            if not text or e <= s or not (a - 0.01 <= mid <= b + 0.01) or mid <= last:
                continue
            if out and s < out[-1]["end_s"] - 0.01:
                continue  # overlaps the word before: heard twice at a piece boundary
            out.append({"start_s": round(s, 3), "end_s": round(e, 3), "text": text,
                        "precision": "word", "heard_to_end": True})
    return out
