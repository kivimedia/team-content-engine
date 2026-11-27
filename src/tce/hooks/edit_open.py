"""The edit opens with the hook picked for the video (T-25711).

When a video was recorded for a topic that carries a hook from the library, the
Creatorz edit is told so and its first moment is that hook. Three of the ten are
drawn by the editor today, exactly as their proof clips show them:

    whip-in      a fast blurred slide into the first line
    big-number   the number he says first fills the screen, with a ding
    proof-pop    his first attached picture pops in on the claim

The writer of the moments is asked for it first; when its answer does not open
with the hook, the opening is put in by rule (the whip at the first line, the first
number said in the opening lines, the first picture). When even that cannot be done
(no number said early, no picture attached), the edit goes on without it and the
video's status says why in one line. The other seven hooks are named on the status
line as not drawn by the editor yet.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from tce.hooks import library
from tce.hooks.catalog import BY_ID, Hook

DRAWN = ("whip-in", "big-number", "proof-pop")
OPENING_S = 4.0  # the hook has to land inside the first four seconds of the edit
EARLY_LINES = 3

_NUMBER = re.compile(r"^\$?\d[\d,.]*(?:%|x|k|m)?$", re.I)


def hook_on(ws: uuid.UUID, candidate_id: Any) -> Hook | None:
    """The hook picked onto this topic, from the newest week that has one."""
    if candidate_id is None:
        return None
    weeks = library.read_store(ws)["weeks"]
    for week in sorted(weeks, reverse=True):
        for entry in weeks[week]:
            if entry.get("candidate_id") == str(candidate_id):
                hook = BY_ID.get(entry.get("hook_id"))
                if hook is not None:
                    return hook
    return None


def directive(hook: Hook | None, pictures: list[dict[str, Any]] = ()) -> str:
    """The lines added to the moments prompt, or "" when the editor cannot draw it."""
    if hook is None or hook.id not in DRAWN:
        return ""
    head = f"\n\nThis video opens with the visual hook “{hook.name}”: {hook.what} Your FIRST moment must be it:"
    if hook.id == "whip-in":
        return head + ' a whip at {"pick": <the first line>, "at": "start"}.'
    if hook.id == "big-number":
        return head + (
            " a card_stat on the first number he says in the opening lines, its text that number exactly as said"
            " (like \"80%\"), its label 2 to 4 words."
        )
    if not pictures:
        return ""
    return head + " an insert of his first picture, on the word in the opening lines where he makes the claim it proves."


def _number_token(text: str) -> str | None:
    for raw in str(text or "").split():
        word = raw.strip(".,;:!?\"'()")
        if _NUMBER.match(word) and len(word) <= 6:
            return raw
    return None


def _cue_line(moment: dict[str, Any]) -> int | None:
    at = moment.get("at")
    return at.get("pick") if isinstance(at, dict) else None


def ensure_opening(
    moments: list[dict[str, Any]], shots: list[dict[str, Any]], hook: Hook | None,
    pictures: list[dict[str, Any]] = (),
) -> tuple[list[dict[str, Any]], str]:
    """The moments with the hook first, and one plain sentence on how the video opens."""
    if hook is None:
        return moments, ""
    if hook.id not in DRAWN:
        return moments, f"The hook \u201c{hook.name}\u201d is not drawn by the editor yet, so this edit opens without it."
    spoken = [s for s in shots if s.get("text")]
    early = [s for s in spoken if s["out_in"] < OPENING_S][:EARLY_LINES] or spoken[:1]
    if not early:
        return moments, f"The edit could not open with {hook.name}: it has no lines."
    picks = {s["pick"] for s in early}
    kind = {"whip-in": "whip", "big-number": "card_stat", "proof-pop": "insert"}[hook.id]
    for index, moment in enumerate(moments):
        if moment.get("type") == kind and _cue_line(moment) in picks:
            rest = moments[:index] + moments[index + 1:]
            return [moment, *rest], f"Opens with {hook.name}."
    if hook.id == "whip-in":
        first = {"type": "whip", "at": {"pick": early[0]["pick"], "at": "start"}}
        # one whip at the very start, none other within the first line
        rest = [m for m in moments if not (m.get("type") == "whip" and _cue_line(m) == early[0]["pick"])]
        return [first, *rest], f"Opens with {hook.name}."
    if hook.id == "big-number":
        for shot in early:
            token = _number_token(shot["text"])
            if token:
                card = {
                    "type": "card_stat", "text": token.strip(".,;:!?\"'()"), "label": "",
                    "at": {"pick": shot["pick"], "word": token},
                }
                rest = [m for m in moments if m.get("type") != "card_stat"][:]
                kept_stats = [m for m in moments if m.get("type") == "card_stat"][:1]
                return [card, *rest, *kept_stats], f"Opens with {hook.name}: {card['text']}."
        return moments, f"The edit could not open with {hook.name}: no number is said in the opening lines."
    if not pictures:
        return moments, f"The edit could not open with {hook.name}: no picture is attached to this video."
    pid = str(pictures[0]["id"])
    rest = [m for m in moments if not (m.get("type") == "insert" and str(m.get("picture")) == pid)]
    return [{"type": "insert", "picture": pid, "at": {"pick": early[0]["pick"], "at": "start"}}, *rest], f"Opens with {hook.name}."
