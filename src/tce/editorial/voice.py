"""Ziv's voice, enforced rather than requested.

His 36 patterns, the banned vocabulary and the meta-rule live in
`docs/super-coaching-strategy.md`. They reached the Facebook and LinkedIn writer and
never reached the thing that writes his hooks and his script: the strategy loader
takes `include_voice` and it defaulted to false everywhere. The complete voice
instruction the packet writer received was one clause, "Tell it from Ziv's own
first-person experience", while the hook rule told it to name "the unresolved viewer
question" - an instruction to write the curiosity gap he recognised as AI house style.

A rule in a prompt is a request. The banned vocabulary is the part that can be
checked exactly, so here it is code: a packet carrying one of these phrases fails
validation the way a giveaway CTA already does.

The list is kept in sync with the doc by `test_editorial_voice.py`, which reads the
doc's own banned section and fails if the two drift.
"""

from __future__ import annotations

import re

# Zero tolerance, from the doc's "Banned vocabulary" section. Matched case-insensitively
# on word boundaries, so "smart money" catches "Smart Money" and not "smartphone".
BANNED_PHRASES: tuple[str, ...] = (
    "smart money",
    "smart coaches who",
    "smart founders who",
    "competitive landscape",
    "structural advantage",
    "the math is compelling",
    "the math just works",
    "the roi is clear",
    "window is closing",
    "before everyone else figures it out",
    "maximize roi",
    "ai-powered solutions",
    "leverage synergies",
    "seamlessly integrates",
    "scalable solutions",
    "best-in-class",
    "in today's fast-paced world",
    "now more than ever",
    "in an era where",
    "gone are the days",
    "game-changer",
    "game-changing",
    "paradigm shift",
    "translation:",
)

_BANNED_RE = re.compile(
    "|".join(rf"(?<!\w){re.escape(p)}(?!\w)" for p in BANNED_PHRASES), re.IGNORECASE
)
# The doc bans long dashes and double dashes outright: "Use a single dash with spaces".
_DASH_RE = re.compile(r"[–—―]|--")


def banned_hits(text: str) -> list[str]:
    """Every banned phrase or dash in a piece of text, in the order they appear."""
    if not text:
        return []
    hits = [m.group(0) for m in _BANNED_RE.finditer(text)]
    hits += [m.group(0) for m in _DASH_RE.finditer(text)]
    return hits


def first_banned(texts: list[str]) -> str | None:
    """The first offending phrase across several pieces, or None."""
    for text in texts:
        hits = banned_hits(text)
        if hits:
            return hits[0]
    return None


# The hook instruction that replaces "names the unresolved viewer question". His rule 20
# is the whole point: tension comes from disagreeing with something the viewer believes,
# not from withholding what the video is about.
HOOK_RULE = """\
- hook_options: exactly three openings, ranked best first, written the way Ziv opens when \
he starts explaining something to a coach. An opening is a flat, plain statement that \
disagrees with what the viewer currently believes, or names the mistake they are making \
right now. It is not a question, not a tease, not "here is why", not "the truth about", \
not a promise of a secret, and it never withholds the subject to create curiosity. Say the \
contentious thing first and let the tension come from disagreement, not from a gap. Each \
option names the belief it contradicts, the phrase ID that pays it off, the evidence moment \
IDs behind it, and a private ranking rationale. The first option is selected by default and \
its text must be the first spoken script phrase."""
