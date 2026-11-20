"""Evidence for the exact edit a reviewer asked Jennifer to deliver."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Any

from tce.production.retakes import edit_join
from tce.production.tightcut import HOP_S
from tce.production import frame_text


def requires_change(request: str) -> bool:
    """Allow informational replies; an unexecuted edit instruction is still open."""
    text = request.strip().casefold()
    if re.search(r"\b(?:can|could|would|will) you\b|\b(?:please|then|also|and|so)\s+"
                 r"(?:remove|cut|trim|restore|replace|correct|fix|change|add|delete|keep|"
                 r"tighten|edit|apply|make|show|split)\b", text):
        return True
    if re.search(r"(?:בבקשה|אפשר|תוכל[יו]?|תוכלו|צריך|צריכה|נא)\s|"
                 r"(?:^|\s|[,?!])(?:ו?ת(?:תקנ[יו]?|תקן|וסי[פף][יו]?|חתי?כ[יו]?|חתוך|"
                 r"סיר[יו]?|מחק[יו]?|חליפ[יו]?|שנ[היו]|חזיר[יו]?|קצר[יו]?))\b", text):
        return True
    information = re.match(r"^(?:why|what happened|what did|what was|how did|is that|was that|did you|"
                           r"where (?:is|was)|when (?:is|was)|למה|מדוע|מה קרה|האם|מתי|איפה|איך)\b", text)
    # When the intention is unknown, keep the note for review in every language.
    return not bool(information)


def caption_only(request):
    return bool(re.search(
        r"(?:caption[s]?|subtitle[s]?|on.screen text)\s+only|(?:only|just)\s+(?:the\s+)?"
        r"(?:caption[s]?|subtitle[s]?|on.screen text)|(?:keep|leave)\s+(?:the\s+)?"
        r"(?:audio|speech|voice)\s+(?:unchanged|as is|alone)|(?:רק (?:את |ב)?(?:ה?כתוביות|ה?טקסט))|"
        r"(?:כתוביות|טקסט) בלבד", request or "", re.I
    ))


def request_moment(request):
    match = re.search(r"(?<!\d)(\d{1,3}):([0-5]\d)(?:[.,](\d{1,3}))?(?!\d)", request or "")
    if match:
        return int(match[1]) * 60 + int(match[2]) + float("0." + (match[3] or "0"))
    return None


def correction_targets(words, corrections):
    return [{"heard": c["heard"], "replacement": c["replacement"],
             "source": [words[c["first"]]["start_s"], words[c["last"]]["end_s"]]}
            for c in corrections]


def restored_words(words, ranges):
    return [{"source": [w["start_s"], w["end_s"]], "text": w["text"]}
            for w in words if any(a <= (w["start_s"] + w["end_s"]) / 2 <= b for a, b in ranges)]


def _tokens(text):
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", str(text)).casefold())


def _near(rows, a, b):
    return [r for r in rows if r.get("end") is not None and r.get("start") is not None
            and float(r["end"]) > a and float(r["start"]) < b]


def _contains(rows, phrase):
    want = _tokens(phrase)
    got = [token for row in rows for token in _tokens(row.get("text", ""))]
    return bool(want) and any(got[i:i + len(want)] == want for i in range(len(got) - len(want) + 1))


def clip(at: float | None, duration: float | None):
    if at is None or not duration:
        return None
    at = min(max(0.0, at), duration)
    return {"start_s": round(max(0.0, at - 2), 2), "end_s": round(min(duration, at + 3), 2)}


def unresolved(question, reference=None, moment=None):
    return {"state": "needs_review", "render_ref": reference, "clip": moment, "question": question}


def _cues(e):
    data = e.get("captions") or {}
    return data.get("cues") or data.get("boxes") or []


def _spots(e, a, b):
    # A page is drawn once. Multiple words on the same page share its pixel sample.
    return [round((c["start"] + c["end"]) / 2, 2) for c in _near(_cues(e), a, b)]


def _title_spots(duration):
    return sorted({round(min(duration / 2, .30), 2), round(duration / 2, 2),
                   round(max(duration / 2, duration - .3), 2)})


def _caption_transitions(e, gap):
    words = (e.get("captions") or {}).get("words") or []
    return [(l, r) for l, r in zip(words, words[1:]) if r["start"] - l["end"] >= gap - 1e-5]


def _visible(e, a, b):
    seen = e.get("visible") or {}
    return [{"text": seen.get(("caption", s)) or ""} for s in _spots(e, a, b)]


async def read_samples(path, e, outcomes, language):
    keep, duration = e["keep"], e["duration"]
    targets = set()
    for o in outcomes:
        spans = [c["source"] for c in o.get("correction_targets") or []]
        spans += list(o.get("restore") or [])
        for a, b in spans:
            targets.update(("caption", s) for s in _spots(e, edit_join(a, keep), edit_join(b, keep)))
        for anchor in o.get("caption_anchors") or []:
            at = edit_join(anchor["at_s"], keep)
            targets.add(("caption", round(min(duration - .02, at + .09), 2)))
        if o.get("caption_gap_s") is not None:
            for left, right in _caption_transitions(e, o["caption_gap_s"])[:3]:
                for word in (left, right):
                    targets.update(("caption", s) for s in _spots(e, word["start"], word["end"]))
        if o.get("top_caption") is not None:
            targets.update(("title", s) for s in _title_spots(duration))
    seen = {}
    async def sample(region, seconds):
        crop = "pill" if region == "caption" and e["captions"].get("mode") == "wordbox" else region
        seen[(region, seconds)] = await frame_text.read(path, seconds, language=language, region=crop)

    try:
        async with asyncio.timeout(45):
            await asyncio.gather(*(sample(r, t) for r, t in sorted(targets)[:60]))
    except TimeoutError:
        pass  # Missing samples stay unverified.
    return seen


def verify(outcome: dict[str, Any], evidence: dict[str, Any], *, before_ref, source_s, edit_s):
    ref = evidence.get("render_ref")
    keep = evidence.get("keep") or []
    duration = evidence.get("duration")
    at = edit_join(source_s, keep) if source_s is not None and keep else edit_s
    checked = []

    def review(why, position=None):
        return unresolved(why, ref, clip(position if position is not None else at, duration))

    if not ref or ref == before_ref or not keep or not duration:
        return review("I could not verify a new playable version. Can you confirm which edit you see?")
    if outcome.get("skipped"):
        return review("Part of your note could not be applied. Which remaining change should I make first?")
    captions = evidence.get("captions") or {}
    displayed = captions.get("boxes") if captions.get("mode") == "wordbox" else captions.get("cues")
    displayed = displayed or []
    heard = evidence.get("heard") or []

    def word_proof(target, source, *, needs_audio=True):
        first, last = (edit_join(t, keep) for t in source)
        a, b = first - 0.22, last + 0.22
        if not _contains(_near(displayed, a, b), target):
            return review(f'I could not confirm that the caption shows “{target}” here. What should it say?', first)
        if needs_audio and not _contains(_near(heard, a, b), target):
            return review(f'I could not confirm “{target}” in the finished audio here. Is the full phrase audible?', first)
        if not _contains(_visible(evidence, first, last), target):
            return review(f'I could not read “{target}” on the finished frame. Does the caption display it here?', first)
        return None

    def overlap(a, b):
        return sum(max(0.0, min(b, end) - max(a, start)) for start, end in keep)

    def only_silent_padding(a, b, kept):
        # The planner keeps a small breath around words. Accept it only if the
        # published audio proves that every surviving piece is quiet.
        if kept > .125 or not evidence.get("levels"):
            return False
        for start, end in keep:
            if min(b, end) <= max(a, start):
                continue
            x, y = (edit_join(t, keep) for t in (max(a, start), min(b, end)))
            samples = evidence["levels"][int(x / HOP_S):max(int(x / HOP_S) + 1, round(y / HOP_S))]
            if not samples or max(samples) > -55:
                return False
        return True

    for correction in outcome.get("correction_targets") or outcome.get("corrections") or []:
        source, text = correction.get("source"), correction.get("replacement")
        if not source:
            return review("I could not locate the corrected words in this version. Where do you hear them?")
        if not text:
            a, b = (edit_join(t, keep) for t in source)
            visible = _visible(evidence, a, b)
            if (not any(r["text"] for r in visible) or not displayed or (not heard and not outcome.get("caption_only"))
                    or _contains(visible, correction["heard"])
                    or _contains(_near(displayed, a - .18, b + .18), correction["heard"])
                    or (not outcome.get("caption_only") and _contains(_near(heard, a - .18, b + .18), correction["heard"]))):
                return review("I could not confirm the caption removal against what is spoken. Should these words appear?", a)
        else:
            issue = word_proof(text, source, needs_audio=not outcome.get("caption_only"))
            if issue:
                return issue
            old = correction.get("heard", "")
            if not outcome.get("caption_only") and _tokens(old) != _tokens(text) and len(_tokens(old)) > len(_tokens(text)):
                a, b = (edit_join(t, keep) for t in source)
                if _contains(_near(heard, a - .18, b + .18), old):
                    return review(f'I can still hear “{old}” where the caption says “{text}”. Which wording should stay?', a)
        checked.append("caption_pixels" if outcome.get("caption_only") else "caption_pixels_and_audio")
    for key in ("restore", "hold", "trim", "cut"):
        for spec in outcome.get(key) or []:
            if key == "hold":
                when, edge, seconds = spec
                a, b = (max(0, when - seconds), when) if edge == "start" else (when, when + seconds)
            else:
                a, b = spec
            a, b = float(a), float(b)
            kept = overlap(a, b)
            tol = min(.055, (b - a) * .20)
            want_keep = key in ("restore", "hold")
            matches = kept >= b - a - tol if want_keep else kept <= tol
            if key == "cut" and not matches:
                matches = only_silent_padding(a, b, kept)
            if b <= a or not matches:
                return review("The finished cut does not match the requested timing here. Which sound should stay?", edit_join(a, keep))
            join = edit_join(a, keep)
            if key != "restore":
                # Check one surviving word on each available side, so a planned cut alone
                # cannot hide a displaced audio track or captions from a different edit.
                local = _near(captions.get("words") or displayed, join - 1.5, join + 1.5)
                left = [w for w in local if w["start"] < join]
                right = [w for w in local if w["start"] >= join]
                neighbors = left[-1:] + right[:1]
                if not neighbors or any(
                    not _contains(_near(heard, w["start"] - .25, w["end"] + .25), w["text"])
                    or not _contains(_near(displayed, w["start"] - .25, w["end"] + .25), w["text"])
                    for w in neighbors
                ):
                    return review("I could not match the words across this cut in both the audio and captions. Does this join sound right?", join)
            checked.append(key)
    if outcome.get("restore"):
        if not outcome.get("restore_words"):
            return review("I could not confirm the restored speech against the captions. Is the full phrase back?")
        for target in outcome["restore_words"]:
            issue = word_proof(target["text"], target["source"])
            if issue:
                return issue
        checked.append("restored_speech_and_captions")
    if outcome.get("top_caption") is not None:
        if (evidence.get("top_caption") or "") != outcome["top_caption"] or "top_caption" not in evidence:
            return review("The requested title was not confirmed on this render. Is the title visible?")
        title = outcome["top_caption"]
        for s in _title_spots(duration):
            seen = (evidence.get("visible") or {}).get(("title", s))
            if title and not _contains([{"text": seen or ""}], title):
                return review("I could not read the entire requested title on this frame. Is the full title visible?", s)
            if not title:
                return review("The title overlay was removed from the render settings. Is it gone on screen?", s)
        checked.append("rendered_title_pixels")
    if outcome.get("denoise"):
        if evidence.get("denoise") != outcome["denoise"]:
            return review("I could not confirm the requested noise filter in this render. Is the background still too loud?")
        # Filter receipt confirms it ran, not whether it achieved the requested sound.
        return review("The requested filter ran. Is the voice clear enough over the remaining background noise?")
    if outcome.get("caption_gap_s") is not None:
        gap = outcome["caption_gap_s"]
        if evidence.get("caption_gap_s") != gap or not displayed:
            return review("I could not confirm the requested caption timing here. Which words need more space?")
        transitions = _caption_transitions(evidence, gap)
        if not transitions:
            return review("I could not find a word gap that matches the requested split. Where should the new caption start?")
        for i, (left, right) in enumerate(transitions):
            if any(c["start"] < left["end"] - .035 and c["end"] > right["start"] + .035 for c in _cues(evidence)):
                return review("One caption still bridges the pause here. Should the next phrase start a fresh caption?", right["start"])
            if i < 3 and any(not _contains(_visible(evidence, w["start"], w["end"]), w["text"]) for w in (left, right)):
                return review("I could not read both caption groups on either side of this pause. Is their timing right?", right["start"])
        checked.append("caption_gap")
    for anchor in outcome.get("caption_anchors") or []:
        matched = next((t for t in evidence.get("caption_anchors") or []
                        if t.get("word_s") == anchor.get("word_s") and t.get("at_s") == anchor.get("at_s")), None)
        if not matched or matched.get("edit_s") is None:
            return review("This caption timing change did not reach the final cut. Which word should start the caption?")
        t, text = matched["edit_s"], anchor["text"]
        starts = [c for c in _cues(evidence) if abs(c["start"] - t) <= .075]
        first = _tokens(text)
        seen = (evidence.get("visible") or {}).get(("caption", round(min(duration - .02, t + .09), 2)))
        if not first or not any(_tokens(c["text"])[:1] == first[:1] for c in starts) or not _contains([{"text": seen or ""}], text):
            return review(f'I could not confirm “{text}” starts the rendered caption here. Is this its intended entrance?', t)
        checked.append("caption_anchor_pixels")
    if not checked:
        return review("I could not verify the requested change in this version. What still needs adjusting?")
    return {"state": "verified", "render_ref": ref, "checks": list(dict.fromkeys(checked)),
            "clip": clip(at, duration)}
