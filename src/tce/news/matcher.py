"""The gate: does this announcement land on anything of Ziv's?

Deterministic, no model call, and that is the point rather than an optimisation.
If a rejection needed a model call it would be the model's judgement, and a
model's judgement drifts between versions; this one cannot. It also means a quiet
day costs nothing, which is what makes daily discovery honest.

Two checks, in this order, because the first is cheaper and the stronger signal:

1. SHAPE. Funding, valuations, benchmarks, executive moves, earnings,
   partnerships, adoption surveys and "the future of" speculation are rejected on
   what they ARE, before anything is matched. These are the exact shapes the
   retired trend_scout used to return by the dozen.

2. ANCHOR. What is left must match a named thing in `news_anchors`: one strong
   anchor (a vendor, a dependency, a model id, a Kivi Media client solution) or
   two independent recurring client problems. A match on the category name -
   "ai", "agent", "automation" - is a coincidence and never counts.

Anything that fails either check never becomes an EvidenceSource and never costs
a job. It is recorded in the collection ledger with its reason, so the run can
say "41 items read, 0 matched anything in your work" rather than looking like a
broken feed.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from tce.news.anchors import STOP_TERMS, STRONG_KINDS, normalize

# ---------------------------------------------------------------------------
# Shape blocklist
# ---------------------------------------------------------------------------

# Each entry is (shape name, pattern). Matched against the normalised title and
# summary, so word boundaries are spaces and punctuation is already gone.
#
# These are deliberately about the STORY TYPE, not the subject. "Anthropic raises
# money" and "Databricks raises money" are the same non-event for a florist.
_BLOCKED_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "funding",
        re.compile(
            r"\b(raises|raised|raising)\b.{0,24}\b(million|billion|round|\d)"
            r"|\bseries [a-h]\b"
            r"|\b(seed|pre seed|bridge) round\b"
            r"|\bfunding round\b"
            r"|\bled the round\b"
            r"|\braises at a\b"
        ),
    ),
    (
        "valuation",
        re.compile(r"\bvaluation\b|\bvalued at\b|\bworth \$?\d|\bipo\b|\bgoes public\b"),
    ),
    (
        "benchmark",
        re.compile(
            r"\bbenchmark(s|ed|ing)?\b|\bleaderboard\b|\bstate of the art\b|\bsota\b"
            r"|\bmmlu\b|\bswe bench\b|\bgpqa\b|\bhumaneval\b|\barena\b"
            r"|\btops the\b|\bbeats\b.{0,20}\bon\b.{0,20}\b(test|benchmark|eval)\b"
            r"|\boutperforms\b"
        ),
    ),
    (
        "exec_move",
        re.compile(
            r"\bappoints\b|\bsteps down\b|\bstepping down\b|\bnamed (ceo|cto|cfo|president)\b"
            r"|\bjoins as\b|\bhires\b.{0,60}\bas (its |their )?(ceo|cto|cfo|head|chief)\b"
            r"|\bdeparts\b|\bresigns\b|\bnew chief\b|\bchief (scientist|executive)\b"
        ),
    ),
    (
        "earnings",
        re.compile(
            r"\bearnings\b|\bquarterly results\b|\bq[1-4] (results|revenue|earnings)\b"
            r"|\brevenue of\b|\bbeats estimates\b|\bannual recurring revenue\b|\barr\b"
        ),
    ),
    (
        "partnership",
        re.compile(
            r"\bpartners with\b|\bpartnership with\b|\bstrategic partnership\b"
            r"|\bteams up with\b|\bjoins forces\b"
        ),
    ),
    (
        "survey",
        re.compile(
            r"\bsurvey\b|\bstudy (finds|shows)\b|\breport finds\b|\bresearch finds\b"
            r"|\badoption (reaches|hits|grows)\b"
            r"|\b\d+ percent of (enterprises|companies|businesses)\b"
            r"|\bstate of (ai|the industry)\b"
        ),
    ),
    (
        "speculation",
        re.compile(
            r"\bthe future of\b|\bcould (transform|disrupt|replace|kill)\b"
            r"|\bwill (transform|disrupt|replace|kill) \b|\bmay disrupt\b"
            r"|\bwhat .{0,20} means for the industry\b|\bis this the end of\b"
        ),
    ),
)

# Acquisitions are usually corporate noise, with one narrow exception: a vendor
# Ziv DEPENDS ON changing hands or shutting down is a real consequence for a
# business he runs. So this shape is only blocked when nothing in the item is a
# dependency or vendor anchor.
_ACQUISITION = re.compile(
    r"\bacquires\b|\bacquisition\b|\bacquired by\b|\bto buy\b|\bbuys\b"
    r"|\bshutting down\b|\bshuts down\b|\bsunset(ting|s)?\b|\bdiscontinued\b"
)

_CONDITIONAL_SHAPES = frozenset({"acquisition"})


@dataclass
class AnchorMatch:
    """One reason an item was let through, in a form a person can read back."""

    anchor_id: uuid.UUID
    kind: str
    term: str
    matched_span: str
    score: float = 1.0


@dataclass
class MatchResult:
    """The gate's verdict, with everything needed to explain it."""

    matched: bool
    reason: str
    matches: list[AnchorMatch] = field(default_factory=list)
    blocked_shape: str | None = None

    @property
    def strong(self) -> list[AnchorMatch]:
        return [m for m in self.matches if m.kind in STRONG_KINDS]

    @property
    def problems(self) -> list[AnchorMatch]:
        return [m for m in self.matches if m.kind == "problem_pattern"]

    def why(self) -> str:
        """The sentence the terminal prints when Ziv asks about one item."""
        if not self.matched:
            return self.reason
        named = ", ".join(f"{m.term} ({m.kind})" for m in self.matches[:4])
        return f"matches {named}"


def blocked_shape(text: str) -> str | None:
    """Return the shape name if this is a story type Ziv never wants."""
    normalized = normalize(text)
    if not normalized:
        return None
    for name, pattern in _BLOCKED_SHAPES:
        if pattern.search(normalized):
            return name
    if _ACQUISITION.search(normalized):
        return "acquisition"
    return None


# A client_solution or a problem_pattern is a sentence, not a name: "an AI
# receptionist answering a shop's phone". No announcement will ever contain that
# verbatim, so exact-phrase matching would make both kinds dead weight and
# silently undo Ziv's correction. Long anchors match on how much of their
# substance is present instead.
_LONG_ANCHOR_TOKENS = 4
_OVERLAP_REQUIRED = 0.75
_MIN_OVERLAP_TOKENS = 3


def _significant(term: str) -> list[str]:
    """The words in an anchor that actually carry it."""
    return [t for t in term.split(" ") if len(t) >= 3 and t not in STOP_TERMS]


def _phrase_hit(needle: str, haystack: str) -> str | None:
    """Whole-word match on already-normalised text.

    Short anchors ("twilio", "prompt caching") must appear intact: substring
    matching would fire "arc" inside "search" and "clara" inside "declarative",
    which looks clever in a demo and produces nonsense in production.

    Long anchors match on significant-token overlap, and the threshold is high
    enough that a passing mention does not count. What comes back is the tokens
    that actually matched, so the card can show its working.
    """
    if not needle:
        return None

    words = _significant(needle)
    if len(words) < _LONG_ANCHOR_TOKENS:
        pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
        found = re.search(pattern, haystack)
        return found.group(0) if found else None

    present = [w for w in words if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", haystack)]
    if len(present) < _MIN_OVERLAP_TOKENS:
        return None
    if len(present) / len(words) < _OVERLAP_REQUIRED:
        return None
    return " ".join(present)


def match_item(
    *,
    title: str,
    summary: str | None = None,
    body: str | None = None,
    anchors: list[Any],
) -> MatchResult:
    """Decide whether one announcement lands on anything of Ziv's.

    `anchors` are NewsAnchor rows (or anything with kind / term /
    normalized_term / id / weight). Only active anchors should be passed in.
    """
    headline = " ".join(p for p in (title, summary) if p)
    full = " ".join(p for p in (title, summary, body) if p)
    normalized_full = normalize(full)

    # Shape first: it is cheaper, and a funding round stays a funding round even
    # when it mentions a vendor Ziv uses.
    shape = blocked_shape(headline)

    matches: list[AnchorMatch] = []
    seen: set[str] = set()
    for anchor in anchors:
        term = getattr(anchor, "normalized_term", None) or normalize(
            getattr(anchor, "term", "")
        )
        if not term or term in seen:
            continue
        # A bare category word is not a connection even if somebody put one in
        # the index by hand. Belt and braces with anchors.usable().
        parts = term.split(" ")
        if len(parts) == 1 and parts[0] in STOP_TERMS:
            continue
        span = _phrase_hit(term, normalized_full)
        if span is None:
            continue
        seen.add(term)
        matches.append(
            AnchorMatch(
                anchor_id=getattr(anchor, "id", None),
                kind=getattr(anchor, "kind", "unknown"),
                term=getattr(anchor, "term", term),
                matched_span=span,
                score=float(getattr(anchor, "weight", 1.0) or 1.0),
            )
        )

    strong = [m for m in matches if m.kind in STRONG_KINDS]

    if shape:
        # The one exception: a dependency or vendor Ziv runs changing hands or
        # being switched off is a consequence, not corporate noise.
        rescued = shape in _CONDITIONAL_SHAPES and any(
            m.kind in ("dependency", "vendor") for m in matches
        )
        if not rescued:
            return MatchResult(
                matched=False,
                reason=f"blocked shape: {shape}",
                matches=matches,
                blocked_shape=shape,
            )

    if strong:
        return MatchResult(matched=True, reason="strong anchor", matches=matches)

    problems = [m for m in matches if m.kind == "problem_pattern"]
    if len(problems) >= 2:
        return MatchResult(
            matched=True, reason="two independent client problems", matches=matches
        )

    if len(problems) == 1:
        return MatchResult(
            matched=False,
            reason=(
                "one client problem and nothing else; a single broad pattern is not "
                "a connection"
            ),
            matches=matches,
        )

    if matches:
        # capability-only: real but not enough on its own. "Prompt caching got
        # cheaper" matters when it touches something he runs, not in the abstract.
        return MatchResult(
            matched=False,
            reason="only a capability matched; nothing of his is named",
            matches=matches,
        )

    return MatchResult(matched=False, reason="no anchor")
