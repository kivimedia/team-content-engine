"""The decision pack: what he needs to decide on an idea without asking a question.

On the 18 Nov call 6 of 11 ideas could not be decided as they were put to him,
because the call read only the big idea: the takeaway was empty on all 11, why
now on 8, and the evidence was a bare label ("From your call"). Everything a
decision needs was already in TCE (the dated moments behind the idea, the
lessons drawn from them, the script's points), just never put in front of him.

This arranges what is stored. It invents nothing and calls no model: why now
comes from a date that is on record, the evidence lines are the stored lessons
of the cited moments, a takeaway not yet written is offered from the script's
closing point and marked as proposed, and anything still missing is named, so
the call says "not ready yet: no why now" instead of skipping the block.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# The seed brief writes this for every news idea. It says nothing about the
# idea, so it does not count as a reason it matters now.
NEWS_TEMPLATE_PREFIX = "This is tied to something that just changed"

_SOURCE_WORDS = {
    "fathom_meeting": "your call",
    "meeting": "your call",
    "github_commit_group": "your code",
    "github_commit": "your code",
    "news_item": "the news",
    "standing_fact": "your notes",
}

EVIDENCE_LINES = 2
POINTS = 3

MISSING_WORDS = {
    "why_now": "why now",
    "evidence": "what the source said",
    "takeaway": "a takeaway",
    "points": "the points the video would make",
    "angle": "your angle",
}

# Without these three he cannot decide on the spot.
REQUIRED = ("why_now", "evidence", "takeaway")


def _clip(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "..."


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _day(when: datetime) -> str:
    return f"{when.day} {when.strftime('%b')}"


def _first_sentence(text: str) -> str:
    text = _clip(text, 400).rstrip(".")
    match = re.match(r"(.+?[.!?])(\s|$)", text + ".")
    return (match.group(1) if match else text).strip()


def _source_words(kind: Any) -> str:
    return _SOURCE_WORDS.get(str(kind or ""), "a source")


def _why_now(values: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    written = str(values.get("why_now") or "").strip()
    if written and not written.startswith(NEWS_TEMPLATE_PREFIX):
        return written
    dated = [(e, _when(e.get("occurred_at"))) for e in evidence]
    dated = [(e, w) for e, w in dated if w is not None]
    news = [(e, w) for e, w in dated if str(e.get("source_kind")) == "news_item"]
    if news:
        e, w = max(news, key=lambda pair: pair[1])
        title = _clip(e.get("title"), 90)
        return f"In the news on {_day(w)}: {title}." if title else f"In the news on {_day(w)}."
    calls = [(e, w) for e, w in dated if _source_words(e.get("source_kind")) == "your call"]
    if calls:
        _, w = max(calls, key=lambda pair: pair[1])
        count = len({e.get("title") for e, _ in calls})
        many = f" and {count - 1} other call{'s' if count > 2 else ''}" if count > 1 else ""
        return f"It came up on your call on {_day(w)}{many}."
    return ""


def _evidence_lines(evidence: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for e in evidence:
        said = _clip(e.get("lesson") or e.get("excerpt"), 220)
        if not said or said in seen:
            continue
        seen.add(said)
        where = _source_words(e.get("source_kind"))
        w = _when(e.get("occurred_at"))
        head = f"From {where} on {_day(w)}" if w else f"From {where}"
        lines.append(f"{head}: {said}")
        if len(lines) == EVIDENCE_LINES:
            break
    return lines


def build(detail: dict[str, Any], evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The pack for one topic, from topic_detail's own dict.

    `evidence` is the research's evidence when a research pass finished, else what
    gather_evidence read for this topic just now (his own calls and commits).
    """
    values = dict(((detail.get("brief") or {}).get("values")) or {})
    script = detail.get("script") or {}
    evidence = list(evidence or [])

    takeaway = str(values.get("takeaway") or "").strip()
    takeaway_proposed = False
    points = [str(p).strip() for p in (script.get("points") or []) if str(p).strip()]
    if not takeaway:
        # The closing point, unless it is the question to the viewer ("Your turn:
        # which questions...?"), which is a call to action, not a takeaway.
        statements = [
            p for p in points if not p.rstrip().endswith("?") and not p.lower().startswith("your turn")
        ]
        if statements:
            takeaway = _first_sentence(statements[-1])
        else:
            lesson = next((e.get("lesson") for e in evidence if e.get("lesson")), "")
            takeaway = _first_sentence(lesson) if lesson else ""
        takeaway_proposed = bool(takeaway)

    pack = {
        "why_now": _why_now(values, evidence),
        "evidence": _evidence_lines(evidence),
        "angle": str(values.get("distinctive_perspective") or "").strip(),
        "takeaway": takeaway,
        "takeaway_proposed": takeaway_proposed,
        "points": points[:POINTS],
    }
    missing = [key for key in MISSING_WORDS if not pack[key]]
    pack["missing"] = [MISSING_WORDS[key] for key in missing]
    pack["ready"] = not any(key in missing for key in REQUIRED)
    return pack
