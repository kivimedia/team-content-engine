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

Word timings (28-Sep, "the editor is supposed to choose one that is full"): the
decisions are made per word, on sentences rebuilt from fragments ("A" ... "coach is
a person" is one sentence, not a false start). A line said twice keeps its complete
take; talk to the dogs ("Hey, Maple Rain, boy!", "No, no, no, no.") and recogniser
junk are cut; fillers go. The subscription editor's review, when it answered, decides
retakes and asides instead of these rules. With the audio's speech regions, the cut
is tight (tightcut.py); without them, the padded cut below.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from tce.production.tightcut import Activity, apply_holds, pause_stats, retime, tight_keep

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
    "every some more most much many one yes ok okay um uh like well gonna actually basically".split()
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
    words: list[int] = field(default_factory=list)  # transcript indices (word timings)

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


def is_word_level(timings: list[dict[str, Any]], precision: str | None = None) -> bool:
    """One word a row, with its own times (not whole-second segment starts)."""
    if (precision or timing_precision(timings)) == PRECISION_WHOLE_SECOND:
        return False
    rows = _coerce_timings(timings)
    return bool(rows) and sum(len(r[2].split()) for r in rows) / len(rows) < 2


def plan_edit(
    timings: list[dict[str, Any]],
    script_phrases: list[str] | None,
    *,
    pause_threshold_s: float = 1.2,
    pad_s: float = 0.2,
    duration_s: float | None = None,
    precision: str | None = None,
    activity: Activity | None = None,
    removals: list[dict[str, Any]] | None = None,
    overrides: dict[str, Any] | None = None,
    aside_names: Sequence[str] = (),
    protected: Collection[int] = (),
) -> dict[str, Any]:
    """`protected` (an agent talk, 3-Oct): transcript indices of the agent's words. No
    rule and no review removes them; only his own editing request can. The rules look
    for retakes and asides inside one of his turns at a time, never across the agent's
    lines."""
    precision = precision or timing_precision(timings)
    if is_word_level(timings, precision):
        return _plan_words(
            timings,
            script_phrases,
            pause_threshold_s=pause_threshold_s,
            pad_s=pad_s,
            duration_s=duration_s,
            precision=precision,
            activity=activity,
            removals=removals,
            overrides=overrides,
            aside_names=aside_names,
            protected=frozenset(protected),
        )
    coarse = precision == PRECISION_WHOLE_SECOND
    phrases = [sim_tokens(p) for p in (script_phrases or [])]
    units = group_units(timings)
    for u in units:
        _match_phrase(u, phrases)
    if not protected:
        # Segment timings cannot say which words in a line are whose: a talk with them
        # keeps every line.
        _script_retakes(units)

    end_bound = (
        duration_s if duration_s is not None else (max((u.end for u in units), default=0.0) + pad_s)
    )
    notes: list[dict[str, Any]] = []
    coarse_cuts: list[dict[str, Any]] = []
    if coarse:
        coarse_cuts = _coarse_cuts(units, end_bound, notes)

    kept = [u for u in units if u.dropped_reason is None]
    issues = _meaning_issues(units, kept, script_phrases or [])
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


def _script_retakes(units: list[Unit]) -> None:
    """Script phrases said more than once keep their last complete take; a unit that
    repeats or restarts one of the next two units is dropped as a retake of it."""
    by_phrase: dict[int, list[Unit]] = {}
    for u in units:
        if u.phrase is not None and u.dropped_reason is None:
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


def _meaning_issues(
    units: list[Unit], kept: list[Unit], script_phrases: list[str]
) -> list[dict[str, Any]]:
    """A dropped take that says something its kept take does not (a negation, a
    content word, more words) blocks the plan, as do kept script takes whose
    negation differs from the script or that come out of script order."""
    issues: list[dict[str, Any]] = []
    by_index = {u.index: u for u in units}
    for u in units:
        if u.dropped_reason is None or u.superseded_by is None:
            continue
        keeper = by_index.get(u.superseded_by)
        if keeper is None:
            continue
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
    # He speaks freely, and the cut keeps his order: a line said once sits where he said
    # it. Only a take chosen over an earlier take of the same line can move that line
    # later, so only those are checked (28-Sep: the reviewed "Selling" edit was blocked
    # because he had spoken two script points in his own order).
    chosen = {u.superseded_by for u in units if u.dropped_reason and u.superseded_by is not None}
    last_phrase = -1
    for u in kept:
        if u.phrase is None or u.take != "full":
            continue
        if u.phrase < last_phrase and u.index in chosen:
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
    return issues


# ---------------------------------------------------------------------------
# Word timings: decisions per word, cut tight on the audio (28-Sep)

FILLERS = frozenset({"um", "uh", "ah", "er", "erm", "hmm", "mm", "umm", "uhh", "ehh", "uhm"})
# Said to the dogs around a name ("Boy, from here!" is his Hebrew "בואו מפה" as heard).
ASIDE_CALL_WORDS = frozenset(
    "boy bo bou bow come here there from were we go good girl no hey stop wait lets let "
    "this way over sit stay okay ok yes yeah on out".split()
)
ASIDE_NAME_MAX_TOKENS = 8
ASIDE_NEIGHBOUR_S = 8.0
ASIDE_NEIGHBOUR_MAX_TOKENS = 4
JUNK_WORD_S = 0.05  # the recogniser's invented words last a frame or two
JUNK_RUN = 3
JUNK_RATE_WPS = 8.0
PREFIX_RETAKE_TOKENS = 5
PREFIX_RETAKE_GAP_S = 15.0
CONTINUATION_GAP_S = 12.0
_I_FORMS = frozenset({"i", "i'm", "i've", "i'll", "i'd", "im", "ive"})

REASON_WORDS = {
    "retake": "an earlier take of a line you said again",
    "false_start": "a start you said again",
    "aside": "said to the dogs or off camera",
    "junk": "recognition noise, not speech",
    "sound": "a sound with no words (a false start), heard on a second listen",
    "filler": "filler",
    "requested_cut": "you asked to cut it",
}


def _complete(text: str) -> bool:
    t = str(text).rstrip().rstrip("\"')]")
    return t.endswith((".", "?", "!")) and not t.endswith(("...", "…"))


def _continues(a: Unit, b: Unit) -> bool:
    """`b` carries on the sentence `a` left open ("A" ... "coach is a person")."""
    tail = a.text.rstrip()
    if tail[-1:] in ".?!…" or b.start - a.end > CONTINUATION_GAP_S:
        return False
    first = b.text.lstrip()
    head = raw_tokens(first)[:1]
    return bool(first) and (first[0].islower() or (head and head[0] in _I_FORMS))


def _word_units(
    rows: list[tuple[int, float, float, str]],
    other_lang: frozenset[int] | set[int] = frozenset(),
    agent: frozenset[int] | set[int] = frozenset(),
) -> list[Unit]:
    """Utterances (split at a 0.35 s gap or a sentence end), then sentences rebuilt
    from fragments a pause split apart. Words heard as another language (Hebrew to the
    dogs, 29-Sep) are their own utterance and never join an English sentence. In an
    agent talk (3-Oct) a sentence never holds both voices: `agent` is the agent's words."""
    units: list[Unit] = []
    cur: list[tuple[int, float, float, str]] = []

    def close() -> None:
        text = " ".join(r[3] for r in cur)
        units.append(
            Unit(len(units), cur[0][1], cur[-1][2], text, sim_tokens(text), words=[r[0] for r in cur])
        )

    for row in rows:
        if cur and (
            row[1] - cur[-1][2] >= WORD_GROUP_GAP_S
            or cur[-1][3].rstrip()[-1:] in ".?!"
            or (row[0] in other_lang) != (cur[-1][0] in other_lang)
            or (row[0] in agent) != (cur[-1][0] in agent)
        ):
            close()
            cur = []
        cur.append(row)
    if cur:
        close()

    def foreign(u: Unit) -> bool:
        return any(i in other_lang for i in u.words)

    def voice(u: Unit) -> bool:
        return any(i in agent for i in u.words)

    def joined(parts: list[Unit]) -> Unit:
        text = " ".join(p.text for p in parts)
        return Unit(0, parts[0].start, parts[-1].end, text, sim_tokens(text),
                    words=[i for p in parts for i in p.words])

    # A fragment that says again the one before it ("and then that question," /
    # "and then that question stopped me cold.", 29-Sep) starts its own sentence, and
    # the one it restarts leaves the sentence it was glued to: the retake rules then
    # see the pair and keep the complete one.
    groups: list[list[Unit]] = []
    for u in units:
        if (
            groups
            and _continues(joined(groups[-1]), u)
            and not (foreign(joined(groups[-1])) or foreign(u))
            and voice(groups[-1][-1]) == voice(u)
        ):
            if _is_restart_of(groups[-1][-1], u):
                if len(groups[-1]) > 1:
                    groups.append([groups[-1].pop()])
                groups.append([u])
            else:
                groups[-1].append(u)
        else:
            groups.append([u])
    sentences: list[Unit] = []
    for parts in groups:
        s = joined(parts)
        s.index = len(sentences)
        sentences.append(s)
    return sentences


def _shared_prefix(a: list[str], b: list[str]) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


def _prefix_retakes(sentences: list[Unit]) -> None:
    """A line he starts the same way twice ("So go and work for free until you do." /
    "So go and work for free for a while.") keeps one take: the complete one, and of
    two complete takes the later."""
    live = [s for s in sentences if s.dropped_reason is None]
    for a, b in zip(live, live[1:], strict=False):
        if a.dropped_reason or b.dropped_reason or b.start - a.end > PREFIX_RETAKE_GAP_S:
            continue
        if _shared_prefix(a.tokens, b.tokens) < PREFIX_RETAKE_TOKENS:
            continue
        drop, keep = (a, b) if _complete(b.text) or not _complete(a.text) else (b, a)
        # These rules stand in when the editor did not answer: a take that says a word
        # the kept one does not ("before" vs "after") may be a second point, so both stay.
        if lost_content_words(drop.text, keep.text) or [
            n for n in negations_in(drop.text) if n not in negations_in(keep.text)
        ]:
            continue
        drop.dropped_reason = "retake" if _complete(drop.text) else "false_start"
        drop.superseded_by = keep.index


# Words that make a line with a dog's name a call to the dog, not a sentence.
ASIDE_CALLING = frozenset("hey come boy bo bou bow no stop wait sit stay girl good".split())


def _calls_a_dog(text: str, tokens: list[str], names: Sequence[str]) -> bool:
    """A dog's name as written (capitalised, so "rain" in "looks like rain" is not
    one) in a line that calls: a calling word, or the name set off by a comma or an
    exclamation mark ("Hey, Maple Rain, boy!", "No, no, no, Rain", "Maple!")."""
    for name in names:
        for m in re.finditer(r"\b" + re.escape(name) + r"\b", text):
            after = text[m.end() : m.end() + 1]
            before = text[max(0, m.start() - 2) : m.start()]
            if after in (",", "!") or "," in before or ASIDE_CALLING & set(tokens):
                return True
    return False


def _asides(sentences: list[Unit], names: Sequence[str]) -> None:
    """Talk that is not for the viewer: a short line calling a dog by name, the call
    words around it, and a run of "no, no, no"."""
    marked: list[Unit] = []
    for s in sentences:
        if s.dropped_reason:
            continue
        toks = s.tokens
        if toks and len(toks) >= 2 and all(t == "no" for t in toks):
            s.dropped_reason = "aside"
        elif names and len(toks) <= ASIDE_NAME_MAX_TOKENS and _calls_a_dog(s.text, toks, names):
            s.dropped_reason = "aside"
            marked.append(s)
    for s in sentences:
        if s.dropped_reason or not s.tokens or len(s.tokens) > ASIDE_NEIGHBOUR_MAX_TOKENS:
            continue
        if not set(s.tokens) <= ASIDE_CALL_WORDS:
            continue
        if any(
            -ASIDE_NEIGHBOUR_S <= s.start - m.end <= ASIDE_NEIGHBOUR_S
            or -ASIDE_NEIGHBOUR_S <= m.start - s.end <= ASIDE_NEIGHBOUR_S
            for m in marked
        ):
            s.dropped_reason = "aside"
    # A call word next to a call word next to a name: "Boy," then "we're here".
    changed = True
    while changed:
        changed = False
        asides = [s for s in sentences if s.dropped_reason == "aside"]
        for s in sentences:
            if s.dropped_reason or not s.tokens or len(s.tokens) > ASIDE_NEIGHBOUR_MAX_TOKENS:
                continue
            if set(s.tokens) <= ASIDE_CALL_WORDS and any(
                abs(s.start - m.end) <= 3.0 or abs(m.start - s.end) <= 3.0 for m in asides
            ):
                s.dropped_reason = "aside"
                changed = True


def _junk_words(rows: list[tuple[int, float, float, str]]) -> set[int]:
    """Words the recogniser invented: runs of words a frame or two long, or an
    utterance faster than anyone speaks (the 28-Sep walk ended with "don't want
    your sales don't need" in 0.14 s)."""
    junk: set[int] = set()
    run: list[int] = []
    for idx, s, e, _text in rows + [(-1, 0.0, 1.0, "")]:
        if idx >= 0 and e - s <= JUNK_WORD_S:
            run.append(idx)
            continue
        if len(run) >= JUNK_RUN:
            junk.update(run)
        run = []
    return junk


def _turns(sentences: list[Unit], agent: frozenset[int] | set[int]) -> list[list[Unit]]:
    """His sentences in runs between the agent's lines (one run when there is no agent)."""
    if not agent:
        return [sentences]
    turns: list[list[Unit]] = []
    cur: list[Unit] = []
    for s in sentences:
        if any(i in agent for i in s.words):
            if cur:
                turns.append(cur)
            cur = []
        else:
            cur.append(s)
    if cur:
        turns.append(cur)
    return turns


def _removal_units(
    removals: list[dict[str, Any]],
    rows: list[tuple[int, float, float, str]],
    sentences: list[Unit],
    start_index: int,
) -> tuple[dict[int, str], list[Unit]]:
    """The editor review's removals as word reasons, plus a unit per removed take so
    the meaning check can compare it with the take he kept."""
    reasons: dict[int, str] = {}
    units: list[Unit] = []
    for k, r in enumerate(removals):
        s, e = float(r["start"]), float(r["end"])
        kind = str(r.get("kind") or "retake")
        idx = [i for i, ws, we, _t in rows if s - 0.01 <= (ws + we) / 2 <= e + 0.01]
        if not idx:
            continue
        for i in idx:
            reasons[i] = kind
        keeper_at = r.get("keeper_start")
        if kind in ("retake", "false_start") and keeper_at is not None:
            keeper = next(
                (u for u in sentences if u.start - 0.05 <= float(keeper_at) <= u.end + 0.05), None
            )
            text = " ".join(t for i, _s, _e, t in rows if i in set(idx))
            units.append(
                Unit(start_index + k, s, e, text, sim_tokens(text), dropped_reason=kind,
                     superseded_by=keeper.index if keeper else None, words=idx)
            )
    return reasons, units


def _plan_words(
    timings: list[dict[str, Any]],
    script_phrases: list[str] | None,
    *,
    pause_threshold_s: float,
    pad_s: float,
    duration_s: float | None,
    precision: str,
    activity: Activity | None,
    removals: list[dict[str, Any]] | None,
    overrides: dict[str, Any] | None,
    aside_names: Sequence[str],
    protected: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    rows: list[tuple[int, float, float, str]] = []
    for i, t in enumerate(timings or []):
        text = str(t.get("text") or t.get("word") or "").strip()
        start, end = t.get("start_s", t.get("start")), t.get("end_s", t.get("end"))
        if start is None or end is None or not text:
            continue
        s, e = float(start), float(end)
        rows.append((i, min(s, e), max(s, e), text))
    rows.sort(key=lambda r: (r[1], r[2], r[0]))
    # The second listen (29-Sep): stretches heard as another language, and sounds the
    # recogniser folded into a word ("make" inside "Bring") split off as "[sound]".
    other_lang = {i for i, t in enumerate(timings or []) if t.get("lang")}
    sounds = {i for i, t in enumerate(timings or []) if t.get("sound")}
    phrases = [sim_tokens(p) for p in (script_phrases or [])]
    # A sound is cut whoever decides; left in a sentence it would hide the restart it
    # marks from the retake rules and show "[sound]" in unit captions.
    sentences = _word_units([r for r in rows if r[0] not in sounds], other_lang, protected)
    for u in sentences:
        _match_phrase(u, phrases)

    reviewed = removals is not None
    review_units: list[Unit] = []
    reason: dict[int, str | None] = {r[0]: None for r in rows}
    if reviewed:
        # The subscription editor read the whole take and decided retakes and asides.
        by_word, review_units = _removal_units(removals or [], rows, sentences, len(sentences))
        reason.update(by_word)
    else:
        # An agent talk (3-Oct): the rules look inside one of his turns at a time. A line
        # of his that the agent's answer follows is a turn of the conversation, not a
        # take he said again, and the agent's own lines are never a take or an aside.
        for turn in _turns(sentences, protected):
            _script_retakes(turn)
            _prefix_retakes(turn)
            _asides(turn, aside_names)
        for u in sentences:
            # A short line heard as another language is talk to the dogs; a long one
            # may be English the recogniser doubted, and stays for the editor to judge.
            if (
                not u.dropped_reason
                and u.words
                and all(i in other_lang for i in u.words)
                and len(u.tokens) <= ASIDE_NAME_MAX_TOKENS
            ):
                u.dropped_reason = "aside"
        for u in sentences:
            if u.dropped_reason:
                for i in u.words:
                    reason[i] = u.dropped_reason
    # Mechanical, whoever decided the rest.
    for i in sounds:
        reason[i] = reason[i] or "sound"
    for i in _junk_words(rows):
        reason[i] = reason[i] or "junk"
    for u in sentences:
        dur = max(0.01, u.end - u.start)
        if len(u.words) >= JUNK_RUN and len(u.words) / dur > JUNK_RATE_WPS:
            for i in u.words:
                reason[i] = reason[i] or "junk"
    for i, _s, _e, text in rows:
        if re.sub(r"[^\w']+", "", text).lower() in FILLERS:
            reason[i] = reason[i] or "filler"
    # The agent's words are the other half of the conversation: whatever a rule or the
    # review said, they stay. A "[sound]" the second listen split off is not a word and
    # goes as before.
    for i in protected:
        if i in reason and reason[i] not in (None, "sound"):
            reason[i] = None
    # His editing requests win over every rule above.
    for key, value in (("cut", "requested_cut"), ("restore", None)):
        for a, b in (overrides or {}).get(key) or []:
            for i, ws, we, _t in rows:
                if float(a) - 0.01 <= (ws + we) / 2 <= float(b) + 0.01:
                    reason[i] = value

    kept_flags = [reason[r[0]] is None for r in rows]
    for u in sentences:
        live = [i for i in u.words if reason[i] is None]
        if not live:
            u.dropped_reason = u.dropped_reason or next(
                (reason[i] for i in u.words if reason[i]), "retake"
            )
        elif u.dropped_reason and not reviewed:
            u.dropped_reason = None  # a restore brought part of it back
            u.superseded_by = None
    kept_units = [u for u in sentences if u.dropped_reason is None]
    issues = _meaning_issues(sentences + review_units, kept_units, script_phrases or [])
    # The editor chose these takes reading the whole walk: a reworded take losing a word
    # the kept one lacks is a note on the card, not a block. A lost "not" still blocks.
    reviewed_ids = {u.index for u in review_units}
    review_keepers = {u.superseded_by for u in review_units if u.superseded_by is not None}
    notes = [
        i for i in issues
        if (i.get("dropped_index") in reviewed_ids and i["kind"] in ("content_dropped", "truncated_take"))
        or (i["kind"] == "script_order" and i.get("kept_index") in review_keepers)
    ]
    issues = [i for i in issues if i not in notes]

    words_sorted = [
        {"start_s": s, "end_s": e, "text": t, "index": i} for i, s, e, t in rows
    ]
    # Never short of the last word: a stale or wrong duration must not invert a range.
    end_bound = max(duration_s or 0.0, max((r[2] for r in rows), default=0.0) + pad_s)
    if activity is not None:
        audible = [reason[r[0]] != "junk" for r in rows]
        keep, timed = tight_keep(words_sorted, kept_flags, activity, end_bound, audible)
    else:
        # No audio to go by: pad each kept word and join what is closer than a pause.
        keep = []
        previous_kept = True
        for (_i, ws, we, _t), k in zip(rows, kept_flags, strict=True):
            if not k:
                previous_kept = False
                continue
            s = max(0.0, ws - pad_s)
            e = min(end_bound, we + pad_s) if end_bound else we + pad_s
            joinable = previous_kept and keep and s - keep[-1][1] <= max(0.0, pause_threshold_s - 2 * pad_s)
            if joinable or (keep and s <= keep[-1][1]):
                keep[-1][1] = max(keep[-1][1], e)
            else:
                keep.append([s, e])
            previous_kept = True
        keep = [[round(s, 3), round(e, 3)] for s, e in keep]
        timed = retime(words_sorted, kept_flags, keep, [])
    holds = (overrides or {}).get("hold") or []
    if holds:
        keep = apply_holds(keep, holds, end_bound)  # his "give that word more room"
    for w in timed:
        w["index"] = rows[w["index"]][0]  # position in `rows` -> index in the transcript

    # What was taken out, in runs, and the pauses between kept ranges.
    dropped: list[dict[str, Any]] = []
    run: list[tuple[int, float, float, str]] = []
    run_reason: str | None = None

    def flush() -> None:
        if run:
            dropped.append(
                {
                    "start": round(run[0][1], 3),
                    "end": round(run[-1][2], 3),
                    "text": " ".join(r[3] for r in run),
                    "reason": run_reason,
                }
            )

    for r in rows:
        why = reason[r[0]]
        # One run per stretch the cut removes: "Which" ... 11 s ... "means that the sales
        # call..." is one take on the card, not two, however long he paused inside it.
        if why and run and why != run_reason:
            flush()
            run = []
        if why:
            run_reason = why
            run.append(r)
        elif run:
            flush()
            run = []
    flush()
    cursor = 0.0
    for s, e in keep:
        if s - cursor >= 0.05 and not _inside_dropped(cursor, s, dropped):
            dropped.append({"start": round(cursor, 3), "end": s, "text": "", "reason": "pause"})
        cursor = e
    if end_bound and end_bound - cursor >= 0.05 and keep:
        dropped.append({"start": round(cursor, 3), "end": round(end_bound, 3), "text": "", "reason": "pause"})
    dropped.sort(key=lambda d: d["start"])
    removed = [
        {**d, "why": REASON_WORDS.get(str(d["reason"]), str(d["reason"]))}
        for d in dropped
        if d["reason"] not in ("pause", "filler") and d["text"]
    ]

    units_out = []
    for u in sentences:
        item = u.as_dict()
        item["kept"] = u.dropped_reason is None
        units_out.append(item)
    tight = activity is not None
    stats = {
        "units": len(sentences),
        "kept_units": len(kept_units),
        "ranges": len(keep),
        "kept_seconds": round(sum(e - s for s, e in keep), 3),
        "script_phrases": len(phrases),
        "script_phrases_covered": len({u.phrase for u in kept_units if u.phrase is not None}),
        "pause_threshold_s": pause_threshold_s,
        "removed": len(removed),
        "fillers": sum(1 for r in rows if reason[r[0]] == "filler"),
    }
    if tight:
        stats["pauses"] = pause_stats(keep, activity)
    kept_text = " ".join(r[3] for r, k in zip(rows, kept_flags, strict=True) if k and r[0] not in sounds)
    return {
        "keep": keep,
        "dropped": dropped,
        "removed": removed,
        "words": timed,
        "meaning_check": {
            "status": "blocked" if issues else "ok",
            "issues": issues,
            "negations_full": len(negations_in(" ".join(r[3] for r in rows))),
            "negations_kept": len(negations_in(kept_text)),
            "notes": notes,
        },
        "timing": {
            "precision": precision,
            "exact_cuts": False,
            "word_level": True,
            "snapped_to_audio": tight,
            "speech": activity.as_dict() if activity is not None else None,
            "boundary_uncertainty_s": None,
            "pauses_trimmed": True,
            "summary": (
                "Cuts snapped to where the speech starts and stops in the audio; pauses over "
                "0.2 s cut to a breath"
                if tight
                else "Cuts follow the supplied timings, which are not verified; listen before use"
            ),
        },
        "decided_by": "editor_review" if reviewed else "rules",
        "units": units_out,
        "stats": stats,
        "kept_text": kept_text,
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
    # Captions come from the units then: every word he said, not the cut's words.
    return {**plan, "keep": [[0.0, round(end, 3)]] if end else [], "units": units, "words": None}


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


def map_to_source(t: float, keep: list[list[float]]) -> float | None:
    """Where a second of the edited video sits in the recording: map_to_edit backwards.

    30-Sep, talk to the editor: he pauses the edit at 0:38 and the note has to point at
    the recording, because a second on the recording survives a re-render and a word
    index does not. Map with the keep that MADE the file he is watching (the frame keep
    stored with the render), never the current plan.

    At a join the edit shows the next piece, so the second where one piece ends and
    the next begins maps to the start of the next piece. The very end maps to the end
    of the last piece. None outside the edit.
    """
    if t < 0:
        return None
    offset = 0.0
    for s, e in keep:
        length = float(e) - float(s)
        if t < offset + length:
            return float(s) + (t - offset)
        offset += length
    if keep and t - offset <= 1e-9:
        return float(keep[-1][1])
    return None


def edit_join(t: float, keep: list[list[float]]) -> float:
    """Where a second of the recording sits in the edit, even when the edit left it out.

    A second in the edit is its own second (map_to_edit). A second a cut removed sits at
    the join where that cut is: the end of everything kept before it (1-Oct review: a
    note whose second a new render cut kept its old edit second, and the moment it
    pointed at on the new file was another word).
    """
    on_edit = map_to_edit(t, keep)
    if on_edit is not None:
        return on_edit
    return sum(float(e) - float(s) for s, e in keep if float(e) <= t)


def edit_length(keep: list[list[float]]) -> float:
    """How long the edited video is."""
    return sum(float(e) - float(s) for s, e in keep)


# media.FPS: every edit is cut on this frame grid. Kept here too so the pure clock code
# does not import the ffmpeg module; a test holds the two equal.
EDIT_FPS = 30


def frame_keep(keep: list[list[float]], fps: int = EDIT_FPS) -> list[list[float]]:
    """The keep ranges exactly as the render cuts them.

    media.render_edit trims every range by frame number (round(second x 30)) and drops
    a range shorter than one frame, so the file's own clock is this keep, not the plan's.
    """
    out: list[list[float]] = []
    for s, e in keep:
        a, b = round(float(s) * fps), round(float(e) * fps)
        if b > a:
            out.append([a / fps, b / fps])
    return out


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


def words_on_edit(words: list[dict[str, Any]], keep: list[list[float]]) -> list[dict[str, Any]]:
    """Kept words ({text, start, end} on the recording) moved onto the edited clock.

    A word goes with the kept range holding its midpoint and is clamped inside it: a
    word whose recorded end sits a hair past a cut still shows (the subtitles used to
    drop it), and one the recogniser starts early still shows with its speech.
    """
    out: list[dict[str, Any]] = []
    offsets: list[float] = []
    acc = 0.0
    for s, e in keep:
        offsets.append(acc)
        acc += e - s
    for w in words:
        if str(w.get("text") or "") == "[sound]":
            continue  # a restored sound is heard, never captioned
        ws, we = float(w["start"]), float(w["end"])
        mid = (ws + we) / 2
        for (rs, re_), off in zip(keep, offsets, strict=True):
            if rs <= mid <= re_:
                s, e = max(ws, rs), min(we, re_)
                out.append({"text": w["text"], "start": off + s - rs, "end": off + max(e, s) - rs})
                break
    return out


def _cues_from_words(words: list[dict[str, Any]], keep: list[list[float]]) -> list[dict[str, Any]]:
    """Subtitle cues from the kept words (fillers and cut words never appear)."""
    timed = [
        (w["start"], w["end"], str(w["text"]))
        for w in words_on_edit(words, keep)
        if w["end"] > w["start"]
    ]
    cues: list[dict[str, Any]] = []
    cur: list[tuple[float, float, str]] = []

    def close() -> None:
        lines = _wrap(" ".join(t for _s, _e, t in cur))
        cues.append({"start": cur[0][0], "end": cur[-1][1] + 0.3, "lines": lines[:2]})

    for item in timed:
        if cur:
            text = " ".join(t for _s, _e, t in cur + [item])
            if (
                len(_wrap(text)) > 2
                or item[0] - cur[-1][1] > 0.8
                or item[1] - cur[0][0] > 5.0
                or (len(cur) >= 3 and cur[-1][2].rstrip()[-1:] in ".?!")
            ):
                close()
                cur = []
        cur.append(item)
    if cur:
        close()
    for a, b in zip(cues, cues[1:], strict=False):
        a["end"] = min(a["end"], b["start"])
    return [
        {"start": round(c["start"], 3), "end": round(c["end"], 3), "lines": c["lines"]}
        for c in cues
        if c["end"] - c["start"] > 0.01 and c["lines"]
    ]


def build_cues(plan: dict[str, Any]) -> list[dict[str, Any]]:
    keep = plan.get("keep") or []
    if plan.get("words"):
        return _cues_from_words(plan["words"], keep)
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
