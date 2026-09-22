"""What the selector does differently when a candidate is news-led.

Kept out of `selector.py` on purpose. That module is 1,700 lines and every line
of it is load-bearing for the two lanes that already work; the news rules are
pure functions over citations and scores, so they belong somewhere they can be
read and tested without a database, a pool or a model.

The one rule everything else serves: **news supplies the trigger, Ziv's work
supplies the point of view**. It is enforced twice, deliberately. Once as a hard
check (`needs_anchor`) and once in the arithmetic, where the largest single term
in the score is the support of the NON-news citations, so a candidate resting on
the announcement alone scores zero on 30 percent of the total and cannot clear
the floor even if everything else is perfect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

NEWS_KIND = "news_item"
STANDING_KIND = "standing_fact"

# The floors. A weak evergreen idea costs one mediocre clip; a weak news idea
# costs positioning, so the bar is higher and absolute where evergreen has none.
FIRST_SLOT_FLOOR = 0.70
SECOND_SLOT_FLOOR = 0.80

# A near-tie goes to his own work. Recorded when it happens, so the times the
# lane nearly displaced a call are visible rather than silent.
DISPLACEMENT_MARGIN = 0.05

# One a week. A second only for a major story, per Ziv's 21-Sep decision.
BASE_CEILING = 1
MAJOR_CEILING = 2

# A standing fact is true but undated. It should make a candidate possible, not
# comfortable, so it contributes less than a demonstrated commit (0.9) or a
# measured result (1.0). This number is the difference between "Ziv's correction
# is honoured" and "the easy path stopped being the honest one".
STANDING_SUPPORT_CAP = 0.6

# Reused from the selector so the two never drift apart.
CLAIM_SUPPORT = {
    "measured": 1.0,
    "demonstrated": 0.9,
    "quoted": 0.8,
    "paraphrased": 0.7,
    "inferred": 0.4,
}

# Rejection codes. The gate names are Ziv's four settled ones; these are codes
# underneath them, so a news rejection still reads as "4 of 4 gates" on the card.
CODE_NEEDS_ANCHOR = "news_needs_anchor"
CODE_CEILING = "news_ceiling"
CODE_MARGIN = "news_margin"
CODE_FLOOR = "news_floor"
GATE_NEEDS_ANCHOR = "connects_to_ziv_work"


@dataclass(frozen=True)
class NewsScoreParts:
    """Every term, kept separately so a card can show its working."""

    anchor_support: float
    consequence: float
    distinctiveness: float
    owner_relevance: float
    freshness: float

    @property
    def total(self) -> float:
        return round(
            0.30 * self.anchor_support
            + 0.25 * self.consequence
            + 0.20 * self.distinctiveness
            + 0.15 * self.owner_relevance
            + 0.10 * self.freshness,
            4,
        )

    def explain(self) -> str:
        return (
            f"anchor {self.anchor_support:.2f}, consequence {self.consequence:.2f}, "
            f"distinct {self.distinctiveness:.2f}, relevance {self.owner_relevance:.2f}, "
            f"fresh {self.freshness:.2f} -> {self.total:.3f}"
        )


def _kind(citation: Any) -> str:
    if isinstance(citation, dict):
        return str(citation.get("source_kind") or "")
    return str(getattr(citation, "source_kind", "") or "")


def _claim_type(citation: Any) -> str:
    if isinstance(citation, dict):
        return str(citation.get("claim_type") or "")
    return str(getattr(citation, "claim_type", "") or "")


def _confidence(citation: Any) -> str:
    if isinstance(citation, dict):
        return str(citation.get("speaker_confidence") or "")
    return str(getattr(citation, "speaker_confidence", "") or "")


def is_news_led(citations: list[Any]) -> bool:
    """A candidate is news-led when it cites the announcement at all."""
    return any(_kind(c) == NEWS_KIND for c in citations)


def non_news_citations(citations: list[Any]) -> list[Any]:
    return [c for c in citations if _kind(c) != NEWS_KIND]


def needs_anchor(citations: list[Any]) -> bool:
    """True when this candidate must be rejected for citing only the news.

    The single check the whole lane rests on. A call, a commit or a standing
    fact all satisfy it; the announcement on its own does not.
    """
    return is_news_led(citations) and not non_news_citations(citations)


def anchor_support(citations: list[Any]) -> float:
    """Claim-weighted support of everything that is NOT the announcement.

    Zero when there is nothing else, which is what makes the arithmetic agree
    with the hard check rather than merely coexist with it.
    """
    others = non_news_citations(citations)
    if not others:
        return 0.0
    total = 0.0
    for citation in others:
        weight = CLAIM_SUPPORT.get(_claim_type(citation), 0.3)
        if _kind(citation) == STANDING_KIND:
            weight = min(weight, STANDING_SUPPORT_CAP)
        if _confidence(citation) == "low":
            weight *= 0.7
        total += weight
    return round(total / len(others), 4)


def freshness_value(
    published_at: datetime | None,
    expires_at: datetime | None,
    *,
    now: datetime,
) -> float:
    """The fraction of the perishability window still left.

    Decays from publication rather than spiking near expiry. A bonus for being
    close to expiring would be the system inventing urgency, which the editorial
    rules forbid in copy and should equally forbid in arithmetic.
    """
    if expires_at is None:
        # Durable: not news at all. No freshness credit, and the caller converts
        # the candidate to evergreen anyway.
        return 0.0
    start = published_at or now
    span = (expires_at - start).total_seconds()
    if span <= 0:
        return 0.0
    left = (expires_at - now).total_seconds()
    return round(max(0.0, min(1.0, left / span)), 4)


def score_news(
    *,
    citations: list[Any],
    scores: dict[str, Any],
    published_at: datetime | None,
    expires_at: datetime | None,
    now: datetime,
) -> NewsScoreParts:
    """The news formula. Freshness is 10 percent, and that is not an accident.

    Ziv's strategy file says freshness is a small bonus and never the reason to
    pick a topic, and he did not correct that sentence on 21-Sep. Ten percent is
    the largest weight that stays honest to it.
    """

    def norm(key: str) -> float:
        try:
            value = float(scores.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(5.0, value)) / 5.0

    return NewsScoreParts(
        anchor_support=anchor_support(citations),
        consequence=norm("consequence_specificity"),
        distinctiveness=norm("distinctiveness"),
        owner_relevance=norm("owner_relevance"),
        freshness=freshness_value(published_at, expires_at, now=now),
    )


@dataclass
class SlotDecision:
    """What survived the ceiling, and why the rest did not."""

    kept: list[Any]
    rejected: list[tuple[Any, str, str]]  # (candidate, code, reason)


def apply_slot_rules(
    ranked: list[Any],
    *,
    is_news: Any,
    score_of: Any,
    story_weight_of: Any,
    ceiling_override: int | None = None,
) -> SlotDecision:
    """Apply the floor, the margin and the ceiling, in that order.

    `ranked` is the selected set best-first, mixed news and evergreen. The three
    rules are independent and all apply:

    floor    a news candidate needs 0.70, and a second one in the same week 0.80.
    margin   a news candidate may only displace a call-or-commit candidate by
             beating it by 0.05 or more. A near-tie goes to his own work.
    ceiling  one news idea a week, two when the second is a major story.
    """
    kept: list[Any] = []
    rejected: list[tuple[Any, str, str]] = []
    news_kept = 0

    lowest_evergreen = None
    for candidate in ranked:
        if not is_news(candidate):
            value = score_of(candidate)
            if lowest_evergreen is None or value < lowest_evergreen:
                lowest_evergreen = value

    for candidate in ranked:
        if not is_news(candidate):
            kept.append(candidate)
            continue

        value = score_of(candidate)
        major = story_weight_of(candidate) == "major"
        ceiling = ceiling_override if ceiling_override is not None else (
            MAJOR_CEILING if major else BASE_CEILING
        )

        if news_kept >= ceiling:
            rejected.append(
                (
                    candidate,
                    CODE_CEILING,
                    (
                        f"already {news_kept} news idea(s) this week and this one is "
                        f"{'major' if major else 'not major'}; the ceiling is "
                        f"{ceiling}."
                    ),
                )
            )
            continue

        floor = SECOND_SLOT_FLOOR if news_kept >= 1 else FIRST_SLOT_FLOOR
        if value < floor:
            rejected.append(
                (
                    candidate,
                    CODE_FLOOR,
                    f"scored {value:.3f}, below the {floor:.2f} floor for a "
                    f"{'second' if news_kept else 'first'} news idea this week.",
                )
            )
            continue

        # "The second one has to be major" is part of the ceiling, so an explicit
        # override from Ziv lifts it too. The floors and the margin do not lift:
        # asking for more news is not asking for weaker news, and it is certainly
        # not permission to push his own calls and commits off the list.
        if ceiling_override is None and news_kept >= 1 and not major:
            rejected.append(
                (
                    candidate,
                    CODE_CEILING,
                    "a second news idea in one week has to be a major story, and "
                    "this one is not.",
                )
            )
            continue

        if lowest_evergreen is not None and value < lowest_evergreen + DISPLACEMENT_MARGIN:
            rejected.append(
                (
                    candidate,
                    CODE_MARGIN,
                    (
                        f"scored {value:.3f} against {lowest_evergreen:.3f} for the "
                        f"weakest idea from his own work; a news idea has to beat it "
                        f"by {DISPLACEMENT_MARGIN} to take its place."
                    ),
                )
            )
            continue

        kept.append(candidate)
        news_kept += 1

    return SlotDecision(kept=kept, rejected=rejected)


def should_convert_to_evergreen(perishability: str | None) -> bool:
    """`durable` is a confession that it was never news.

    The idea keeps its lesson, loses the headline, and consumes no news slot.
    """
    return perishability == "durable"


def excluded_from_reserve(source_kind: str) -> bool:
    """News must never enter the evergreen reserve.

    A reserve idea resurfaces weeks later through "more ideas". For a call or a
    commit that is the feature. For an announcement it is a defect: the card
    would come back long after the thing stopped being true.
    """
    return source_kind in (NEWS_KIND, STANDING_KIND)
