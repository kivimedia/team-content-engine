"""Deterministic edit planning for a walking recording. No LLM.

Input: timings [{start_s, end_s, text}] (words or phrases) and the packet's
script_phrases. Output: an edit plan

    {"keep": [[s, e], ...],
     "dropped": [{"start", "end", "text", "reason"}],
     "meaning_check": {"status": "ok" | "blocked", "issues": [...]},
     "units": [...], "stats": {...}}

Rules:
- Long pauses are trimmed (a short pad of silence stays around speech).
- Retakes: a script phrase said more than once keeps the LAST complete take;
  earlier takes and partial false starts are dropped. A spoken unit that is a
  near repeat or a restart of the next unit is also dropped as a retake.
- Free speech that does not match the script is KEPT. Meaning is never dropped
  just because it is off-script.
- Meaning check: a dropped span with a negation token that the kept take does
  not also carry blocks the plan, as does a kept take that is a truncated
  version of an earlier fuller take, a kept take whose negation differs from the
  script phrase, and kept script takes that end up out of script order.
- Timing precision is explicit. The local faster-whisper worker reports whole-second
  (floored) segment starts and no ends; ends are inferred from the next start. With
  that input no cut is exact: every cut edge moves inward by the boundary
  uncertainty so neighbouring kept speech is never clipped, a retake too short to
  cut safely stays in (and is captioned), silences between segments are not
  detectable so no pauses are trimmed, and every cut that does happen blocks the
  plan for a listen. The editor can always render uncut instead.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

EN_NEGATIONS = frozenset(
    {
        "not",
        "no",
        "never",
        "don't",
        "doesn't",
        "isn't",
        "won't",
        "can't",
        "without",
        "nor",
        "cannot",
        "didn't",
        "aren't",
        "wasn't",
        "weren't",
        "shouldn't",
        "wouldn't",
        "couldn't",
        "haven't",
        "hasn't",
        "hadn't",
        "mustn't",
        "dont",
        "doesnt",
        "isnt",
        "wont",
        "cant",
        "didnt",
        "arent",
        "wasnt",
        "werent",
        "shouldnt",
        "wouldnt",
        "couldnt",
        "havent",
        "hasnt",
        "hadnt",
    }
)
HE_NEGATIONS = frozenset({"לא", "אל", "אין", "בלי", "אף"})
_HE_PREFIXES = "והשכבלמ"

MATCH_FULL = 0.62  # token similarity for "this unit is a take of that phrase"
MATCH_PARTIAL = 0.8  # similarity of a unit to the same-length head of a phrase
NEIGHBOUR_REPEAT = 0.85
WORD_GROUP_GAP_S = 0.35
MAX_CAPTION_LINE = 42

# Timing precision labels stored on transcript rows and on the plan.
PRECISION_WHOLE_SECOND = "whole_second_start_inferred_end"
PRECISION_AS_PROVIDED = "as_provided"
BOUNDARY_UNCERTAINTY_S = 1.0  # whole-second floor, plus segment boundary drift
MIN_SAFE_CUT_S = 0.5

_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)


def _strip_marks(text: str) -> str:
    # Remove Hebrew niqqud / combining marks, unify apostrophes.
    text = text.replace("’", "'").replace("׳", "'")
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def raw_tokens(text: str) -> list[str]:
    toks = _TOKEN_RE.findall(_strip_marks(text or "").lower())
    return [t.strip("'") for t in toks if t.strip("'")]


def sim_tokens(text: str) -> list[str]:
    return [t.replace("'", "") for t in raw_tokens(text)]


def negations_in(text: str) -> list[str]:
    found: list[str] = []
    for tok in raw_tokens(text):
        if tok in EN_NEGATIONS or tok.endswith("n't"):
            found.append(tok.replace("'", ""))
            continue
        candidate = tok
        for _ in range(3):
            if candidate in HE_NEGATIONS:
                found.append(candidate)
                break
            if len(candidate) > 2 and candidate[0] in _HE_PREFIXES:
                candidate = candidate[1:]
            else:
                break
    return found


EN_STOPWORDS = frozenset(
    "a an the and or but so to of in on at for with by from as is are was were be been am "
    "it its this that these those i me my we our you your he she they them their his her "
    "do does did done have has had will would can could should just very really then than "
    "also about into over up out if what when where who how which there here all any each "
    "every some more most much many one yes ok okay um uh like well".split()
)
HE_STOPWORDS = frozenset("של את על עם זה זו גם כי אם או הוא היא הם אני אנחנו אתם יש מה".split())


def _content_forms(text: str) -> list[tuple[str, set[str]]]:
    """Content words with their accepted spellings (Hebrew one-letter prefixes stripped)."""
    out = []
    for tok in sim_tokens(text):
        if tok in EN_STOPWORDS or tok in HE_STOPWORDS or len(tok) < 3 or negations_in(tok):
            continue  # negations have their own, more specific check
        forms = {tok}
        cand = tok
        while len(cand) > 2 and cand[0] in _HE_PREFIXES:
            cand = cand[1:]
            forms.add(cand)
        if tok.endswith("s") and len(tok) > 3:
            forms.add(tok[:-1])
        out.append((tok, forms))
    return out


def lost_content_words(dropped: str, kept: str) -> list[str]:
    kept_forms: set[str] = set()
    for _, forms in _content_forms(kept):
        kept_forms |= forms
    lost: list[str] = []
    for tok, forms in _content_forms(dropped):
        if not forms & kept_forms and tok not in lost:
            lost.append(tok)
    return lost


def _ratio(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _covered(small: list[str], big: list[str]) -> float:
    """Fraction of `small` tokens found, in order, inside `big`."""
    if not small:
        return 0.0
    blocks = SequenceMatcher(None, small, big, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks) / len(small)


@dataclass
class Unit:
    index: int
    start: float
    end: float
    text: str
    tokens: list[str] = field(default_factory=list)
    phrase: int | None = None
    take: str | None = None  # full | partial
    score: float = 0.0
    dropped_reason: str | None = None
    superseded_by: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "phrase": self.phrase,
            "take": self.take,
            "kept": self.dropped_reason is None,
            "reason": self.dropped_reason,
        }


def _coerce_timings(timings: list[dict[str, Any]]) -> list[tuple[float, float, str]]:
    rows = []
    for t in timings or []:
        text = str(t.get("text") or t.get("word") or "").strip()
        start = t.get("start_s", t.get("start"))
        end = t.get("end_s", t.get("end"))
        if start is None or end is None or not text:
            continue
        s, e = float(start), float(end)
        if e < s:
            s, e = e, s
        rows.append((s, e, text))
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def group_units(timings: list[dict[str, Any]]) -> list[Unit]:
    """Group word-level timings into utterances; phrase-level timings pass through."""
    rows = _coerce_timings(timings)
    if not rows:
        return []
    avg_words = sum(len(r[2].split()) for r in rows) / len(rows)
    units: list[Unit] = []
    if avg_words >= 2:
        for s, e, text in rows:
            units.append(Unit(len(units), s, e, text, sim_tokens(text)))
        return units
    cur: list[tuple[float, float, str]] = []
    for row in rows:
        if cur and (row[0] - cur[-1][1] >= WORD_GROUP_GAP_S or cur[-1][2].rstrip()[-1:] in ".?!"):
            text = " ".join(r[2] for r in cur)
            units.append(Unit(len(units), cur[0][0], cur[-1][1], text, sim_tokens(text)))
            cur = []
        cur.append(row)
    if cur:
        text = " ".join(r[2] for r in cur)
        units.append(Unit(len(units), cur[0][0], cur[-1][1], text, sim_tokens(text)))
    return units


def _match_phrase(unit: Unit, phrases: list[list[str]]) -> None:
    best = (0.0, None, None)
    for idx, ph in enumerate(phrases):
        if not ph:
            continue
        full = _ratio(unit.tokens, ph)
        if full >= MATCH_FULL and full > best[0]:
            best = (full, idx, "full")
            continue
        # A restart: the unit matches the head of the phrase but stops early.
        n = len(unit.tokens)
        if 0 < n < len(ph) * 0.75:
            head = _ratio(unit.tokens, ph[:n])
            if head >= MATCH_PARTIAL and head * 0.6 > best[0]:
                best = (head * 0.6, idx, "partial")
    if best[1] is not None:
        unit.score, unit.phrase, unit.take = best


def _is_restart_of(a: Unit, b: Unit) -> bool:
    """`a` repeats `b`, or is a false start of it (b begins with a)."""
    if not a.tokens or not b.tokens:
        return False
    if _ratio(a.tokens, b.tokens) >= NEIGHBOUR_REPEAT and len(a.tokens) <= len(b.tokens):
        return True
    n = len(a.tokens)
    return n < len(b.tokens) and _ratio(a.tokens, b.tokens[:n]) >= 0.9


def timing_precision(timings: list[dict[str, Any]]) -> str:
    """Whole-second input is recognised by its label, or by its shape for transcripts
    stored before the label existed: integer starts and each end equal to the next start."""
    rows = [t for t in timings or [] if isinstance(t, dict)]
    if any(t.get("precision") == PRECISION_WHOLE_SECOND for t in rows):
        return PRECISION_WHOLE_SECOND
    coerced = _coerce_timings(rows)
    if len(coerced) >= 2 and all(float(s).is_integer() for s, _, _ in coerced):
        if all(abs(coerced[i][1] - coerced[i + 1][0]) < 1e-6 for i in range(len(coerced) - 1)):
            return PRECISION_WHOLE_SECOND
    return PRECISION_AS_PROVIDED


def plan_edit(
    timings: list[dict[str, Any]],
    script_phrases: list[str] | None,
    *,
    pause_threshold_s: float = 1.2,
    pad_s: float = 0.2,
    duration_s: float | None = None,
    precision: str | None = None,
) -> dict[str, Any]:
    precision = precision or timing_precision(timings)
    coarse = precision == PRECISION_WHOLE_SECOND
    phrases = [sim_tokens(p) for p in (script_phrases or [])]
    units = group_units(timings)
    for u in units:
        _match_phrase(u, phrases)

    # 1. Script retakes: keep the last complete take of each phrase.
    by_phrase: dict[int, list[Unit]] = {}
    for u in units:
        if u.phrase is not None:
            by_phrase.setdefault(u.phrase, []).append(u)
    for takes in by_phrase.values():
        if len(takes) < 2:
            continue
        complete = [t for t in takes if t.take == "full"]
        keeper = complete[-1] if complete else max(takes, key=lambda t: (len(t.tokens), t.index))
        for t in takes:
            if t is keeper:
                continue
            t.dropped_reason = "false_start" if t.take == "partial" else "retake"
            t.superseded_by = keeper.index

    # 2. Neighbour restarts (also catches off-script repeats of the same sentence).
    for i, u in enumerate(units):
        if u.dropped_reason:
            continue
        for j in range(i + 1, min(i + 3, len(units))):
            nxt = units[j]
            if nxt.dropped_reason:
                continue
            if _is_restart_of(u, nxt) and (u.phrase is None or u.phrase == nxt.phrase):
                u.dropped_reason = "false_start" if len(u.tokens) < len(nxt.tokens) else "retake"
                u.superseded_by = nxt.index
                break

    end_bound = (
        duration_s if duration_s is not None else (max((u.end for u in units), default=0.0) + pad_s)
    )
    notes: list[dict[str, Any]] = []
    coarse_cuts: list[dict[str, Any]] = []
    if coarse:
        coarse_cuts = _coarse_cuts(units, end_bound, notes)

    kept = [u for u in units if u.dropped_reason is None]
    issues: list[dict[str, Any]] = []

    # 3. Meaning check.
    for u in units:
        if u.dropped_reason is None or u.superseded_by is None:
            continue
        keeper = units[u.superseded_by]
        lost = [n for n in negations_in(u.text) if n not in negations_in(keeper.text)]
        if lost:
            issues.append(
                {
                    "kind": "negation_dropped",
                    "detail": (
                        f'Dropped take at {fmt_ts(u.start)} says "{u.text}" with '
                        f'"{", ".join(sorted(set(lost)))}" but the kept take at '
                        f'{fmt_ts(keeper.start)} says "{keeper.text}"'
                    ),
                    "dropped_index": u.index,
                    "kept_index": keeper.index,
                }
            )
        missing = lost_content_words(u.text, keeper.text)
        if missing:
            issues.append(
                {
                    "kind": "content_dropped",
                    "detail": (
                        f'Dropped take at {fmt_ts(u.start)} ("{u.text}") says '
                        f'"{", ".join(missing)}", which the kept take at '
                        f'{fmt_ts(keeper.start)} ("{keeper.text}") does not; '
                        "it may be a different idea, not a retake"
                    ),
                    "dropped_index": u.index,
                    "kept_index": keeper.index,
                }
            )
        if len(u.tokens) >= len(keeper.tokens) + 2 and _covered(keeper.tokens, u.tokens) >= 0.9:
            issues.append(
                {
                    "kind": "truncated_take",
                    "detail": (
                        f'Kept take at {fmt_ts(keeper.start)} ("{keeper.text}") is shorter than '
                        f'the earlier take at {fmt_ts(u.start)} ("{u.text}")'
                    ),
                    "dropped_index": u.index,
                    "kept_index": keeper.index,
                }
            )
    for u in kept:
        if u.phrase is None:
            continue
        said = sorted(set(negations_in(u.text)))
        scripted = sorted(set(negations_in(script_phrases[u.phrase])))
        if said != scripted:
            issues.append(
                {
                    "kind": "negation_differs_from_script",
                    "detail": (
                        f'Kept take at {fmt_ts(u.start)} ("{u.text}") and script phrase '
                        f'{u.phrase + 1} ("{script_phrases[u.phrase]}") differ on negation'
                    ),
                    "kept_index": u.index,
                }
            )
    last_phrase = -1
    for u in kept:
        if u.phrase is None or u.take != "full":
            continue
        if u.phrase < last_phrase:
            issues.append(
                {
                    "kind": "script_order",
                    "detail": (
                        f"Kept take at {fmt_ts(u.start)} is script phrase {u.phrase + 1} but comes "
                        f"after phrase {last_phrase + 1}; the cut would reorder the script"
                    ),
                    "kept_index": u.index,
                }
            )
        last_phrase = max(last_phrase, u.phrase)
    full_neg = len(negations_in(" ".join(u.text for u in units)))
    kept_neg = len(negations_in(" ".join(u.text for u in kept)))

    for cut in coarse_cuts:
        issues.append(
            {
                "kind": "uncertain_cut_boundary",
                "detail": (
                    f"Cut {fmt_ts(cut['start'])}-{fmt_ts(cut['end'])} removes "
                    f'"{cut["text"]}" using whole-second transcript timing. Each edge was moved '
                    f"{BOUNDARY_UNCERTAINTY_S:g}s inward to protect the speech around it, so part "
                    "of the dropped take may still be heard. Listen to this cut, or render uncut."
                ),
                "cut": [cut["start"], cut["end"]],
            }
        )

    # 4. Keep ranges. Whole-second input: the complement of the safe cuts, no pause
    # trimming (a gap between inferred ends is not evidence of silence).
    keep: list[list[float]] = _complement(coarse_cuts, end_bound) if coarse and units else []
    for u in [] if coarse else kept:
        s = max(0.0, u.start - pad_s)
        e = min(end_bound, u.end + pad_s) if end_bound else u.end + pad_s
        if keep and s - keep[-1][1] <= max(0.0, pause_threshold_s - 2 * pad_s):
            keep[-1][1] = max(keep[-1][1], e)
        elif keep and s <= keep[-1][1]:
            keep[-1][1] = max(keep[-1][1], e)
        else:
            keep.append([s, e])
    keep = [[round(s, 3), round(e, 3)] for s, e in keep]

    if coarse:
        dropped: list[dict[str, Any]] = [
            {
                "start": c["start"],
                "end": c["end"],
                "text": c["text"],
                "reason": c["reason"],
                "boundary": "uncertain",
            }
            for c in coarse_cuts
        ]
    else:
        dropped = [
            {
                "start": round(u.start, 3),
                "end": round(u.end, 3),
                "text": u.text,
                "reason": u.dropped_reason,
            }
            for u in units
            if u.dropped_reason
        ]
    cursor = 0.0
    for s, e in [] if coarse else keep:
        if s - cursor >= 0.05 and not _inside_dropped(cursor, s, dropped):
            dropped.append({"start": round(cursor, 3), "end": s, "text": "", "reason": "pause"})
        cursor = e
    if not coarse and end_bound and end_bound - cursor >= 0.05 and keep:
        dropped.append({"start": cursor, "end": round(end_bound, 3), "text": "", "reason": "pause"})
    dropped.sort(key=lambda d: d["start"])

    status = "blocked" if issues else "ok"
    return {
        "keep": keep,
        "dropped": dropped,
        "meaning_check": {
            "status": status,
            "issues": issues,
            "negations_full": full_neg,
            "negations_kept": kept_neg,
            "notes": notes,
        },
        "timing": {
            "precision": precision,
            "exact_cuts": False,
            "boundary_uncertainty_s": BOUNDARY_UNCERTAINTY_S if coarse else None,
            "pauses_trimmed": not coarse,
            "summary": (
                "Whole-second transcript timing: cuts are approximate, edges moved "
                f"{BOUNDARY_UNCERTAINTY_S:g}s inward, pauses not trimmed"
                if coarse
                else "Cuts follow the supplied timings, which are not verified; listen before use"
            ),
        },
        "units": [u.as_dict() for u in units],
        "stats": {
            "units": len(units),
            "kept_units": len(kept),
            "ranges": len(keep),
            "kept_seconds": round(sum(e - s for s, e in keep), 3),
            "script_phrases": len(phrases),
            "script_phrases_covered": len({u.phrase for u in kept if u.phrase is not None}),
            "pause_threshold_s": pause_threshold_s,
        },
        "kept_text": " ".join(u.text for u in kept),
    }


def _coarse_cuts(
    units: list[Unit], end_bound: float, notes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Safe removal spans for runs of dropped units when starts are floored seconds.

    A run's true start lies in [start, start + 1) and the next unit's true start in
    [next, next + 1); segment boundaries drift too, so both edges move inward by the
    uncertainty. A span too short to cut safely is not cut: its units are restored as
    kept (they stay audible and captioned) and a note says why.
    """
    margin = BOUNDARY_UNCERTAINTY_S
    cuts: list[dict[str, Any]] = []
    i = 0
    while i < len(units):
        if units[i].dropped_reason is None:
            i += 1
            continue
        j = i
        while j + 1 < len(units) and units[j + 1].dropped_reason is not None:
            j += 1
        run = units[i : j + 1]
        start = run[0].start + margin
        end = (units[j + 1].start - margin) if j + 1 < len(units) else end_bound
        text = " ".join(u.text for u in run)
        if end - start >= MIN_SAFE_CUT_S:
            reasons = {u.dropped_reason for u in run}
            cuts.append(
                {
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": text,
                    "reason": reasons.pop() if len(reasons) == 1 else "retake",
                }
            )
        else:
            for u in run:
                u.dropped_reason = None
                u.superseded_by = None
            notes.append(
                {
                    "kind": "retake_not_removed",
                    "detail": (
                        f'"{text}" at {fmt_ts(run[0].start)} looks like a retake but is too short '
                        "to cut safely with whole-second timing, so it stays in the edit"
                    ),
                }
            )
        i = j + 1
    return cuts


def _complement(cuts: list[dict[str, Any]], end_bound: float) -> list[list[float]]:
    keep: list[list[float]] = []
    cursor = 0.0
    for c in sorted(cuts, key=lambda c: c["start"]):
        if c["start"] - cursor > 0.01:
            keep.append([round(cursor, 3), c["start"]])
        cursor = max(cursor, c["end"])
    if end_bound - cursor > 0.01:
        keep.append([round(cursor, 3), round(end_bound, 3)])
    return keep


def uncut_plan(plan: dict[str, Any], duration_s: float | None) -> dict[str, Any]:
    """The whole recording with every spoken unit captioned. Nothing is removed."""
    units = [dict(u, kept=True, reason=None) for u in plan.get("units") or []]
    end = duration_s or max((u["end"] for u in units), default=0.0)
    return {**plan, "keep": [[0.0, round(end, 3)]] if end else [], "units": units}


def _inside_dropped(s: float, e: float, dropped: list[dict[str, Any]]) -> bool:
    # A gap fully explained by dropped takes is not reported twice as a pause.
    covered = sum(max(0.0, min(e, d["end"]) - max(s, d["start"])) for d in dropped)
    return covered >= (e - s) * 0.8


def fmt_ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


# ---------------------------------------------------------------------------
# Captions


def map_to_edit(t: float, keep: list[list[float]]) -> float | None:
    offset = 0.0
    for s, e in keep:
        if s <= t <= e:
            return offset + (t - s)
        offset += e - s
    return None


def _wrap(text: str, width: int = MAX_CAPTION_LINE) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        while len(word) > width:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:width])
            word = word[width:]
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur = f"{cur} {word}"
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def build_cues(plan: dict[str, Any]) -> list[dict[str, Any]]:
    keep = plan.get("keep") or []
    cues: list[dict[str, Any]] = []
    for unit in plan.get("units") or []:
        if not unit.get("kept"):
            continue
        s = map_to_edit(unit["start"], keep)
        e = map_to_edit(unit["end"], keep)
        if s is None or e is None or e <= s:
            continue
        lines = _wrap(unit["text"])
        chunks = [lines[i : i + 2] for i in range(0, len(lines), 2)] or [[]]
        total = sum(len(" ".join(c)) for c in chunks) or 1
        t = s
        for chunk in chunks:
            share = (e - s) * len(" ".join(chunk)) / total
            cues.append({"start": t, "end": t + share, "lines": chunk})
            t += share
    cues.sort(key=lambda c: c["start"])
    for a, b in zip(cues, cues[1:], strict=False):
        if a["end"] > b["start"]:
            a["end"] = b["start"]
    return [
        {"start": round(c["start"], 3), "end": round(c["end"], 3), "lines": c["lines"]}
        for c in cues
        if c["end"] - c["start"] > 0.01 and c["lines"]
    ]


def _stamp(t: float, sep: str) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(cues: list[dict[str, Any]]) -> str:
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(
            f"{i}\n{_stamp(c['start'], ',')} --> {_stamp(c['end'], ',')}\n" + "\n".join(c["lines"])
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def to_vtt(cues: list[dict[str, Any]]) -> str:
    blocks = ["WEBVTT"]
    for c in cues:
        blocks.append(
            f"{_stamp(c['start'], '.')} --> {_stamp(c['end'], '.')}\n" + "\n".join(c["lines"])
        )
    return "\n\n".join(blocks) + "\n"


def _ass_stamp(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\u29f5").replace("{", "(").replace("}", ")")


def to_ass(cues: list[dict[str, Any]], width: int, height: int) -> str:
    """Burn-in captions sized to the real frame: large, white on a dark box, bottom centre.

    Lines are re-wrapped to what fits the frame width (portrait video fits fewer
    characters than the 42 used for sidecars), at most two lines per cue on screen.
    """
    width, height = max(160, int(width)), max(160, int(height))
    font = max(18, round(min(height * 0.036, width * 0.06)))
    chars = max(12, min(MAX_CAPTION_LINE, int(width * 0.88 / (font * 0.55))))
    margin_v = round(height * 0.08)
    header = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
        "MarginV, Encoding\n"
        f"Style: Caption,DejaVu Sans,{font},&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,"
        f"1,0,0,0,100,100,0,0,3,{max(2, font // 6)},0,2,{round(width * 0.05)},"
        f"{round(width * 0.05)},{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    events = []
    for c in cues:
        lines = _wrap(" ".join(c["lines"]), chars)
        pages = [lines[i : i + 2] for i in range(0, len(lines), 2)] or [[]]
        span = (c["end"] - c["start"]) / len(pages)
        for k, page in enumerate(pages):
            start = c["start"] + k * span
            text = r"\N".join(_ass_escape(line) for line in page)
            events.append(
                f"Dialogue: 0,{_ass_stamp(start)},{_ass_stamp(start + span)},Caption,,0,0,0,,{text}"
            )
    return header + "\n".join(events) + "\n"
