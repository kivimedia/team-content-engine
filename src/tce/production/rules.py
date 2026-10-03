"""Jennifer learns from his notes (3-Oct).

"Every note to Jennifer becomes a rule applied to every next video; a Jennifer's rules
page lists each rule with its source video; he can delete any rule."

When a note he gave on a video has been applied, one subscription job reads it and
decides: is this a rule for every next video ("Cut any aside to the dogs, even under 2
seconds"), or is it only about this video ("take out the second sentence")? A general
rule is stored (models.jennifer.EditorRule) and from then on goes into the review's
instructions and into the leftover-asides check, after the hand-written skill file.

Pure: the job's prompt and schema, reading its answer, and the rules block with its
size cap. The router owns the job and the rows.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger()

DISTILL_JOB = "editor_rule_distill"
DISTILL_PROMPT_VERSION = "rule-distill-v1"

MAX_RULE_CHARS = 200
# The rules block inside a prompt never grows past this; the newest rules win, and the
# cap is logged when it is hit so a long list never silently drops a rule.
MAX_RULES_BLOCK_CHARS = 3000

KINDS = ("rule", "this_video", "covered")

RULES_HEADING = (
    "RULES YOU LEARNED FROM HIS NOTES ON EARLIER VIDEOS (each one came from a note he "
    "gave; they hold on this video too, unless his note on this video says otherwise). "
    "When something you take out follows one of them, name it in why, like (R2):"
)

DISTILL_SYSTEM = (
    "You are Jennifer, the video editor. He watched an edit of one of his videos and gave "
    "notes, and the notes were applied. For each note, decide what it teaches you for the "
    "videos that come next.\n\n"
    "A note is a RULE when it is about a kind of thing that will come up again: talk to "
    "the dogs, pauses, how tight the cuts are, a word or a name he wants written a "
    "certain way, a habit of speech he wants out, how the captions should look. Write the "
    "rule as one plain sentence that tells you what to do, under 160 characters, with no "
    "time, no word number and nothing quoted from this video except a spelling he asked "
    "for.\n"
    "A note is ONLY ABOUT THIS VIDEO when it points at one sentence, one moment or one "
    "word of this video and says nothing about the next one: 'take out the second "
    "sentence', 'bring that line back', 'the cut at 0:38 is too early'.\n"
    "A note is COVERED when one of the rules you already have says the same thing: give "
    "that rule's number.\n"
    "When you are not sure a note is general, it is only about this video: a wrong rule "
    "is applied to every video after this one, and he has to find it and delete it.\n\n"
    "Answer every note once, by its number: kind (rule, this_video or covered), rule (the "
    "sentence, only for a rule), covered_by (the rule number, only for covered, else 0), "
    "and why in a few words."
)

DISTILL_SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "note": {"type": "integer"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "rule": {"type": "string"},
                    "covered_by": {"type": "integer"},
                    "why": {"type": "string"},
                },
                "required": ["note", "kind", "rule", "covered_by", "why"],
            },
        }
    },
    "required": ["notes"],
}


def _line(text: Any) -> str:
    return " ".join(str(text or "").split())


def distill_prompt(context: str, notes: list[dict[str, Any]], rules: list[str]) -> str:
    """One block a note: his words, how the editor read it back, where it was, and what
    was changed for it. `rules` are the rules she already has, in order (R1, R2, ...)."""
    blocks: list[str] = []
    for n, note in enumerate(notes, 1):
        parts = [f"note {n}"]
        if note.get("where"):
            parts.append(_line(note["where"]))
        said = _line(note.get("said"))
        parts.append(f'he said "{said}"' if said else "his own words were not caught")
        if _line(note.get("understood")):
            parts.append(f'read back as "{_line(note["understood"])}"')
        if _line(note.get("reply")):
            parts.append(f'what was done: "{_line(note["reply"])[:300]}"')
        blocks.append("[" + " | ".join(parts) + "]")
    have = "\n".join(f"R{i}. {r}" for i, r in enumerate(rules, 1)) or "(none yet)"
    return (
        f"{context}\n\nThe rules you already have:\n{have}\n\n"
        "His notes on this video, each one applied:\n" + "\n".join(blocks)
    )


_DASHES = re.compile(r"\s*[‒–—―]\s*|\s+--\s+")
_STAMP = re.compile(r"\b\d{1,2}:\d{2}\b")


def clean_rule(text: Any) -> str | None:
    """A rule as it is stored and shown: one plain sentence. None when it is not one
    (empty, too long, or pinned to a time, which makes it about one video)."""
    rule = _DASHES.sub(", ", _line(text)).strip(" \"'")
    if not rule or len(rule) > MAX_RULE_CHARS or _STAMP.search(rule):
        return None
    if rule[-1] not in ".!?":
        rule += "."
    return rule[0].upper() + rule[1:]


def same_rule(a: str, b: str) -> bool:
    def norm(t: str) -> str:
        return " ".join(re.sub(r"[^\w']+", " ", t.lower()).split())

    return norm(a) == norm(b)


def read_distill(answer: dict[str, Any] | None, count: int, rules: list[str]) -> list[dict[str, Any]]:
    """What the job decided for each of `count` notes, in order.

    Each: {"kind": rule | this_video | covered | unread, "rule": text or None,
    "covered_by": index into `rules` or None, "why"}. A rule that is not a usable
    sentence, or that repeats one she already has, is not stored: the first becomes
    this_video, the second covered. A note the answer skipped is `unread`.
    """
    by_note: dict[int, dict[str, Any]] = {}
    for item in (answer or {}).get("notes") or []:
        try:
            n = int(item.get("note"))
        except (AttributeError, TypeError, ValueError):
            continue
        if 1 <= n <= count and n not in by_note:
            by_note[n] = item
    out: list[dict[str, Any]] = []
    new_rules: list[str] = []
    for n in range(1, count + 1):
        item = by_note.get(n)
        if item is None:
            out.append({"kind": "unread", "rule": None, "covered_by": None, "why": ""})
            continue
        kind = str(item.get("kind") or "")
        why = _line(item.get("why"))[:200]
        if kind == "covered":
            try:
                k = int(item.get("covered_by")) - 1
            except (TypeError, ValueError):
                k = -1
            if 0 <= k < len(rules):
                out.append({"kind": "covered", "rule": rules[k], "covered_by": k, "why": why})
                continue
            kind = "this_video"
        if kind == "rule":
            rule = clean_rule(item.get("rule"))
            if rule is None:
                out.append({"kind": "this_video", "rule": None, "covered_by": None,
                            "why": why or "it could not be said as one rule"})
                continue
            known = next((k for k, r in enumerate(rules) if same_rule(r, rule)), None)
            if known is not None:
                out.append({"kind": "covered", "rule": rules[known], "covered_by": known, "why": why})
                continue
            if any(same_rule(r, rule) for r in new_rules):
                out.append({"kind": "this_video", "rule": None, "covered_by": None,
                            "why": "the same rule as another note of this sitting"})
                continue
            new_rules.append(rule)
            out.append({"kind": "rule", "rule": rule, "covered_by": None, "why": why})
            continue
        out.append({"kind": "this_video", "rule": None, "covered_by": None, "why": why})
    return out


def rules_block(rules: list[str], *, max_chars: int = MAX_RULES_BLOCK_CHARS) -> tuple[str, list[int]]:
    """The rules as they go into a prompt, oldest first, numbered R1, R2, ...

    Returns (block, used): `used[n - 1]` is the index into `rules` of the rule written
    as Rn. When the block would pass `max_chars` the OLDEST rules are left out (a newer
    note is closer to what he wants now) and the cap is logged. Empty when there are no
    rules.
    """
    if not rules:
        return "", []
    used: list[int] = []
    size = len(RULES_HEADING)
    for i in range(len(rules) - 1, -1, -1):
        cost = len(rules[i]) + 8
        if used and size + cost > max_chars:
            break
        used.append(i)
        size += cost
    used.reverse()
    if len(used) < len(rules):
        logger.warning(
            "editor_rules.cap_hit",
            rules=len(rules),
            written=len(used),
            left_out=len(rules) - len(used),
            max_chars=max_chars,
        )
    lines = [f"R{n}. {rules[i]}" for n, i in enumerate(used, 1)]
    return RULES_HEADING + "\n" + "\n".join(lines), used


_NAMED = re.compile(r"\(\s*R\s*(\d{1,3})\s*\)|\bR(\d{1,3})\b")


def rules_named(texts: list[str], count: int) -> list[int]:
    """Which rule numbers (1-based, as written in the block) the answer named in its
    reasons: "(R2)". Numbers outside the block are ignored."""
    seen: list[int] = []
    for text in texts:
        for m in _NAMED.finditer(str(text or "")):
            n = int(m.group(1) or m.group(2))
            if 1 <= n <= count and n not in seen:
                seen.append(n)
    return sorted(seen)
