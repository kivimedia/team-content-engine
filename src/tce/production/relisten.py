"""A second listen to the stretches the first transcription may have got wrong (29-Sep).

Transcribed as one 9-minute file, a walk loses what the recogniser takes for noise:
"and then that question, and then that question stopped me" came out once, as one
2.78 s "question"; Hebrew said to the dogs ("הולכים משם") came out as an English "A";
a false start ("make") vanished inside a 0.8 s "Bring". The editor cannot remove what
the transcript does not contain, so it kept all three.

Three repairs, in order:

1. Stretches worth hearing again: a short line standing alone between pauses, heard
   with the lines just around it (asides, restarts and false starts live there; "and
   then that" stood alone before "question stopped me cold"). Each is transcribed again
   on its own, which brings back the dropped words. Only these: on the loaded VPS every
   stretch costs about a minute (the recogniser works in 30 s windows however short the
   clip), and stretching the net to every overlong word tripled the count and found
   nothing more on the 28-Sep walk.
2. The language of each such stretch: his English is heard as English with 0.97-1.00
   confidence, Hebrew to the dogs with 0.23. A stretch under ENGLISH_MIN is marked
   `lang` (the editor treats it as talk to the dogs), with what it sounds like in Hebrew.
3. A word that opens a sentence after a pause, measured from where its sound really
   starts, and still far too long with a silence inside, is heard again from that
   start. Only when the recogniser then hears another word before it is that leading
   sound split off: it becomes a `[sound]` pseudo-word, which the edit removes ("make"
   ran straight into "Bring people value" and rode along with it). The cut goes at the
   latest silence from which the rest is still heard as the word itself. Neither the
   levels nor the recogniser's timing can say which silence is the boundary: "make"
   has 60 ms of silence at its "k", the "B" of "Bring" 70 ms before it, and the
   recogniser put its boundary on the "k" while hearing the rest as "bring" from
   either one. The latest keeps none of the false start; a word with a stop inside
   ("may-be") is not heard as itself from there, so the cut moves earlier.

Pure apart from the hearing, which the router passes in.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

SOUND = "[sound]"
PAUSE_S = 0.6  # a pause this long ends an utterance
GROUP_GAP_S = 2.0  # utterances this close are heard together (a repeat spans them)
ISOLATED_PAUSE_S = 1.0
ISOLATED_MAX_WORDS = 6
LONG_FACTOR = 1.8
LONG_MIN_S = 0.6
PAD_S = 0.5  # bounded by the neighbouring words; the Hebrew began 0.4 s before its "A"
MAX_WINDOW_S = 25.0  # the recogniser hears 30 s at a time
SPAN_MAX_S = MAX_WINDOW_S - 2 * PAD_S  # the words, before the pad either side
MAX_WINDOWS = 60
ENGLISH_MIN = 0.5
SPEECH_MIN_S = 0.04  # a word covering less speech than this was not said
KEEP_FIRST_PASS = 0.7  # a stretch heard again must still hold this share of the first pass
LEAD_PAUSE_S = 0.5  # a word opening a sentence after this pause may hide a false start
LEAD_FACTOR = 1.6
LEAD_MIN_S = 0.45
LEAD_SILENCE_S = 0.04
MAX_LEADS = 12
HOP_S = 0.01

_BARE = re.compile(r"[^\w']+")


def expected_s(text: str) -> float:
    """Roughly how long a word takes to say, from its letters."""
    return 0.08 + 0.065 * len(_BARE.sub("", str(text)))


def _dur(w: dict[str, Any]) -> float:
    return float(w["end_s"]) - float(w["start_s"])


def _long(w: dict[str, Any], factor: float = LONG_FACTOR, floor: float = LONG_MIN_S) -> bool:
    return _dur(w) > max(floor, factor * expected_s(w["text"]))


@dataclass
class Window:
    start: float
    end: float
    first: int  # word indices covered (inclusive)
    last: int
    why: list[str] = field(default_factory=list)
    utts: list[tuple[int, int]] = field(default_factory=list)  # its utterances, as word indices

    def as_dict(self) -> dict[str, Any]:
        return {"start": round(self.start, 3), "end": round(self.end, 3), "first": self.first,
                "last": self.last, "why": self.why}


def _utterances(words: list[dict[str, Any]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(words):
        j = i
        while j + 1 < len(words) and float(words[j + 1]["start_s"]) - float(words[j]["end_s"]) < PAUSE_S:
            j += 1
        out.append((i, j))
        i = j + 1
    return out


def windows(words: list[dict[str, Any]]) -> list[Window]:
    """The stretches to hear again, each whole utterances, at most MAX_WINDOW_S long."""
    utts = _utterances(words)
    flagged: list[tuple[int, int, list[str]]] = []
    for n, (i, j) in enumerate(utts):
        before = float(words[i]["start_s"]) - float(words[utts[n - 1][1]]["end_s"]) if n else 99.0
        after = float(words[utts[n + 1][0]]["start_s"]) - float(words[j]["end_s"]) if n + 1 < len(utts) else 99.0
        if j - i + 1 <= ISOLATED_MAX_WORDS and before >= ISOLATED_PAUSE_S and after >= ISOLATED_PAUSE_S:
            said = " ".join(str(w["text"]) for w in words[i : j + 1])
            flagged.append((n, n, [f'"{said[:40]}" stands on its own']))
    # A repeat can straddle a pause: hear a flagged utterance with the ones just before
    # and after it when they are close.
    out: list[Window] = []
    for n, _, why in flagged:
        a = b = n
        while a > 0 and float(words[utts[a][0]]["start_s"]) - float(words[utts[a - 1][1]]["end_s"]) < GROUP_GAP_S:
            if float(words[utts[b][1]]["end_s"]) - float(words[utts[a - 1][0]]["start_s"]) > SPAN_MAX_S:
                break
            a -= 1
        while b + 1 < len(utts) and float(words[utts[b + 1][0]]["start_s"]) - float(words[utts[b][1]]["end_s"]) < GROUP_GAP_S:
            if float(words[utts[b + 1][1]]["end_s"]) - float(words[utts[a][0]]["start_s"]) > SPAN_MAX_S:
                break
            b += 1
        if out and utts[a][0] <= out[-1].last:
            end = _clip_bounds(words, out[-1].first, utts[b][1])[1]
            if end - out[-1].start <= MAX_WINDOW_S:  # overlapping groups are heard once
                out[-1].last = max(out[-1].last, utts[b][1])
                out[-1].end = max(out[-1].end, end)
                out[-1].why += [w for w in why if w not in out[-1].why]
                out[-1].utts = [u for u in utts if out[-1].first <= u[0] and u[1] <= out[-1].last]
                continue
            # Too long to hear at once: this one starts where the last one ended.
            while a <= b and utts[a][0] <= out[-1].last:
                a += 1
            if a > b:
                continue
        first, last = utts[a][0], utts[b][1]
        start, end = _clip_bounds(words, first, last)
        out.append(Window(start, end, first, last, list(why), utts[a : b + 1]))
    return out[:MAX_WINDOWS]


def _clip_bounds(words: list[dict[str, Any]], first: int, last: int) -> tuple[float, float]:
    """Words first..last with up to PAD_S either side, never reaching into a neighbour."""
    prev_end = float(words[first - 1]["end_s"]) if first > 0 else 0.0
    next_start = float(words[last + 1]["start_s"]) if last + 1 < len(words) else float(words[last]["end_s"]) + PAD_S
    return (max(prev_end, float(words[first]["start_s"]) - PAD_S, 0.0),
            min(next_start, float(words[last]["end_s"]) + PAD_S))


def utterance_clips(words: list[dict[str, Any]], win: Window) -> list[tuple[float, float]]:
    """Each utterance of a window on its own, for a language verdict per utterance."""
    return [_clip_bounds(words, i, j) for i, j in win.utts]


def english(heard: dict[str, Any]) -> bool:
    return str(heard.get("language") or "") == "en" and float(heard.get("language_probability") or 0.0) >= ENGLISH_MIN


def _overlap(s: float, e: float, a: float, b: float) -> float:
    return min(e, b) - max(s, a)


def _on_speech(s: float, e: float, regions: list[tuple[float, float]] | None) -> tuple[float, float] | None:
    """A re-heard word moved onto the speech it covers most; None when it covers none.

    Clip timings drift: the second "and" of "and then that question" came back as
    65.50-68.06, stretched over the 2.4 s of silence between the takes, when it is
    said at 67.93; a word heard over pure silence ("Thank you." in a quiet pad) was
    never said."""
    if regions is None:
        return s, e
    best = max(((_overlap(s, e, a, b), a, b) for a, b in regions if _overlap(s, e, a, b) > 0), default=None)
    if best is None or best[0] < SPEECH_MIN_S:
        return None
    return max(s, best[1]), min(e, best[2])


def _spoken(ws: list[dict[str, Any]], regions: list[tuple[float, float]] | None) -> list[str]:
    """The words that are really speech: not a frame-long invention, not over silence."""
    return [
        _bare(w["text"]) for w in ws
        if float(w["end_s"]) - float(w["start_s"]) >= SPEECH_MIN_S
        and (regions is None or any(_overlap(float(w["start_s"]), float(w["end_s"]), a, b) >= SPEECH_MIN_S
                                    for a, b in regions))
    ]


def _tag(ws: list[dict[str, Any]], res: dict[str, Any]) -> None:
    # Over his Hebrew the top guess can still be "en", at 0.23: say "other".
    code = str(res.get("language") or "")
    for w in ws:
        w["lang"] = code if code and code != "en" else "other"
    if res.get("hebrew") and ws:
        ws[0]["heard_as"] = str(res["hebrew"])[:200]


def merge(
    words: list[dict[str, Any]],
    wins: list[Window],
    heard: list[dict[str, Any] | None],
    *,
    main_language: str = "en",
    regions: list[tuple[float, float]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply what each stretch sounded like when heard again. Returns (words, report).

    `heard[k]` is the clip result for `wins[k]`: {"words": [{start, end, word}] with
    times from the clip start, "language", "language_probability", "hebrew": text heard
    when forced to Hebrew, "parts": one result per utterance of the window, each heard
    alone (a non-English window of more than one utterance)}. None = not heard.

    A stretch heard with more spoken words, that still holds most of the first pass's
    words in order, replaces the first pass's words, each moved onto the speech it
    covers (`regions`, the speech regions of the level envelope). A non-English one
    keeps its words and is marked, utterance by utterance when it holds more than one:
    a Hebrew aside 1.5 s from an English line never takes the English line with it.
    Never across stretches, never touching others.
    """
    out = [dict(w) for w in words]
    report: list[dict[str, Any]] = []
    # Last to first, so the indices of earlier windows still hold after a replacement.
    for win, res in sorted(zip(wins, heard, strict=True), key=lambda p: -p[0].first):
        if not res:
            continue
        span = out[win.first : win.last + 1]
        if main_language == "en" and not english(res):
            parts = res.get("parts")
            if parts is None or len(win.utts) <= 1:
                tagged = [(win.first, win.last, res)]
            else:
                tagged = [(i, j, p) for (i, j), p in zip(win.utts, parts, strict=True) if p and not english(p)]
            for i, j, p in tagged:
                _tag(out[i : j + 1], {**p, "hebrew": p.get("hebrew") or (res.get("hebrew") if len(tagged) == 1 else None)})
            report.append({**win.as_dict(), "result": "not English" if tagged else "same",
                           "english": res.get("language_probability"), "language": res.get("language"),
                           "text": " / ".join(" ".join(str(w["text"]) for w in out[i : j + 1]) for i, j, _ in tagged),
                           "hebrew": res.get("hebrew")})
            continue
        again = []
        for w in res.get("words") or []:
            text = str(w.get("word") or w.get("text") or "").strip()
            s, e = win.start + float(w["start"]), win.start + float(w["end"])
            if not (text and e > s and win.start - 0.01 <= (s + e) / 2 <= win.end + 0.01):
                continue
            placed = _on_speech(s, e, regions)
            if placed:
                again.append({"start_s": round(placed[0], 3), "end_s": round(placed[1], 3), "text": text,
                              "precision": "word", "heard_again": True})
        before, after = _spoken(span, regions), [_bare(w["text"]) for w in again]
        kept = sum(m.size for m in SequenceMatcher(None, before, after, autojunk=False).get_matching_blocks())
        if len(after) > len(before) and kept >= KEEP_FIRST_PASS * len(before):
            out[win.first : win.last + 1] = again
            report.append({**win.as_dict(), "result": "more words",
                           "before": " ".join(str(w["text"]) for w in span),
                           "after": " ".join(w["text"] for w in again)})
        else:
            report.append({**win.as_dict(), "result": "same"})
    report.sort(key=lambda r: r["start"])
    return out, report


@dataclass
class Lead:
    """A sentence-opening word that may hide a false start before it."""

    index: int
    start: float  # where the sound running into the word starts
    end: float
    runs: list[tuple[float, float]]  # silences inside it, with speech before them

    @property
    def clip(self) -> tuple[float, float]:
        return max(self.start - 0.1, 0.0), self.end + 0.05


def lead_candidates(
    words: list[dict[str, Any]],
    levels: list[float] | None,
    low_db: float,
    high_db: float,
    regions: list[tuple[float, float]] | None = None,
) -> list[Lead]:
    """Sentence-opening words whose sound (from where the speech running into it starts,
    never reaching back into the word before) lasts far longer than its letters and
    holds a silence after some speech: what to hear again (28-Sep: the recogniser wrote
    "Bring" at 555.68, the sound running into it began at 555.50 with "make")."""
    if not levels:
        return []
    out: list[Lead] = []
    prev_end = -99.0
    for n, w in enumerate(words):
        s0, e = float(w["start_s"]), float(w["end_s"])
        s = s0
        for a, b in regions or []:
            if prev_end + 0.05 <= a < s0 and b >= s0 - 0.1:
                s = min(s, a)
        exp = expected_s(w["text"])
        opener = not w.get("sound") and not w.get("lang") and s0 - prev_end >= LEAD_PAUSE_S
        if opener and e - s > max(LEAD_MIN_S, LEAD_FACTOR * exp):
            # Silences inside, with speech before them and enough of the word after
            # them (a silence running on to the word's end is not inside it: the
            # Hebrew "A" at 3:21 is followed by 1.6 s of it).
            a, b = int(round((s + 0.1) / HOP_S)), int(round((e - 0.5 * exp) / HOP_S))
            end_frame = min(int(round(e / HOP_S)), len(levels))
            runs: list[tuple[float, float]] = []
            k = a
            while k < min(b, len(levels)):
                if levels[k] < low_db:
                    m = k
                    while m + 1 < len(levels) and levels[m + 1] < low_db:
                        m += 1
                    spoken = sum(1 for q in range(int(round(s / HOP_S)), k) if levels[q] > high_db)
                    after = sum(1 for q in range(m + 1, end_frame) if levels[q] > high_db)
                    if (m - k + 1) * HOP_S >= LEAD_SILENCE_S and spoken * HOP_S >= 0.1 and m + 1 < b and after:
                        runs.append((round(k * HOP_S, 3), round((m + 1) * HOP_S, 3)))
                    k = m + 1
                else:
                    k += 1
            if runs:
                out.append(Lead(n, s, e, runs))
        prev_end = e
    return out[:MAX_LEADS]


def _bare(text: Any) -> str:
    return _BARE.sub("", str(text)).lower()


def _heard(res: dict[str, Any] | None) -> list[str]:
    got = [str(x.get("word") or x.get("text") or "").strip() for x in (res or {}).get("words") or []]
    return [g for g in got if _bare(g)]


# (start, end, what the progress note says) -> the clip heard in English, None if not heard
Hear = Callable[[float, float, str], Awaitable[dict[str, Any] | None]]


def _clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"


async def find_cuts(
    words: list[dict[str, Any]], leads: list[Lead], hear: Hear
) -> list[tuple[Lead, tuple[float, float], str]]:
    """Which leads hide a false start, and the silence to cut each at: (lead, silence,
    what the false start was heard as)."""
    cuts: list[tuple[Lead, tuple[float, float], str]] = []
    for n, lead in enumerate(leads, 1):
        text = str(words[lead.index]["text"])
        target = _bare(text)
        a, b = lead.clip
        got = _heard(await hear(a, b, f'Listening again to the start of "{text}" at {_clock(lead.start)} '
                                      f"({n} of {len(leads)}): it runs long and may hide a false start"))
        k = next((k for k in range(1, len(got)) if _bare(got[k]) == target), None)
        if k is None:
            continue  # heard as the word alone, or as something else: leave it whole
        said = " ".join(got[:k])
        for run in reversed(lead.runs):
            rest = _heard(await hear(run[1] - 0.03, lead.end + 0.05,
                                     f'Heard "{said}" before "{text}": checking "{text}" is whole '
                                     f"from {_clock(run[1])}"))
            if rest and _bare(rest[0]) == target:
                cuts.append((lead, run, said))
                break
    return cuts


def split_leading_sounds(
    words: list[dict[str, Any]], cuts: list[tuple[Lead, tuple[float, float], str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split each cut lead's leading sound off as a `[sound]` word. Returns (words, report)."""
    at = {lead.index: (lead, run, said) for lead, run, said in cuts}
    out: list[dict[str, Any]] = []
    report: list[dict[str, Any]] = []
    for n, w in enumerate(words):
        if n not in at:
            out.append(w)
            continue
        lead, (r0, r1), said = at[n]
        out.append({"start_s": round(lead.start, 3), "end_s": round(r0, 3), "text": SOUND,
                    "precision": "word", "sound": True, "heard_as": said[:80]})
        out.append({**w, "start_s": round(r1, 3)})
        report.append({"start": round(lead.start, 3), "end": round(r0, 3), "before": str(w["text"]),
                       "heard_as": said[:80]})
    return out, report
