"""Does this idea already exist on the list?

The ranker is told never to pick two finalists that teach the same lesson, and it
does that job well - inside one run. It only ever sees one run's finalists, so two
runs over neighbouring weeks can each propose the same lesson from different
evidence and both are right. That is how the list ended up holding "Before you
blame the marketing, find the stage where people drop off" and "Before you fix the
marketing, find the stage that is actually losing people" at the same time.

Moment exclusion cannot catch it either: a different sentence from the same call
carries the same lesson.

So the check is on the words of the idea itself, deterministic and cheap, and it
runs against everything already on his list. It is deliberately conservative: a
missed duplicate costs one scroll, a false one silently loses an idea he would
have recorded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Words that carry no subject. "Before you decide" and "before you give" share two
# of these and nothing that matters, so they must not count towards similarity.
_STOP = frozenset(
    """
a about after all also am an and any are as at be because been before being but by can cannot
could did do does doing done down each even every for from get gets go goes got had has have
having he her here hers him his how i if in into is it its just let like make makes me more
most much must my never no nor not now of off on once one only or other our out over own put
same she should so some such than that the their them then there these they this those through
to too under until up use used uses very was way we well were what when where which while who
whom why will with would you your yours
""".split()
)

_WORD = re.compile(r"[a-z0-9']+")

# Tuned against the real list (see tests). The title pair above scores 0.62 on titles
# alone; the closest genuine non-pair on the same list scores 0.33.
TITLE_THRESHOLD = 0.5
# A weaker title echo only counts as a repeat when the lesson repeats too.
TITLE_SUPPORT_THRESHOLD = 0.3
LESSON_THRESHOLD = 0.45
# A ratio alone is treacherous on short titles: "Weakest of the three" and "Strongest
# of the three" share one word out of two each and score 0.5 without being remotely
# the same idea. Real repeats share a subject, so they share several words.
MIN_SHARED_TITLE_WORDS = 3
MIN_SHARED_TITLE_WORDS_WITH_LESSON = 2


def tokens(text: str | None) -> frozenset[str]:
    """Content words of a phrase, lowercased, without the scaffolding."""
    return frozenset(w for w in _WORD.findall((text or "").lower()) if w not in _STOP)


def dice(left: frozenset[str], right: frozenset[str]) -> float:
    """Overlap of two token sets, 0 to 1. Dice rather than Jaccard: it does not
    punish one idea for being phrased at greater length than the other."""
    if not left or not right:
        return 0.0
    return 2 * len(left & right) / (len(left) + len(right))


@dataclass(frozen=True)
class Similarity:
    title: float
    lesson: float
    shared_title_words: int = 0

    @property
    def repeat(self) -> bool:
        if self.title >= TITLE_THRESHOLD and self.shared_title_words >= MIN_SHARED_TITLE_WORDS:
            return True
        return (
            self.title >= TITLE_SUPPORT_THRESHOLD
            and self.lesson >= LESSON_THRESHOLD
            and self.shared_title_words >= MIN_SHARED_TITLE_WORDS_WITH_LESSON
        )

    def reason(self, other_title: str) -> str:
        how = "says the same thing as" if self.title >= TITLE_THRESHOLD else "teaches the lesson of"
        return f"It {how} an idea already on the list: {other_title}"


def compare(
    title: str | None, lesson: str | None, other_title: str | None, other_lesson: str | None
) -> Similarity:
    left, right = tokens(title), tokens(other_title)
    return Similarity(
        title=dice(left, right),
        lesson=dice(tokens(lesson), tokens(other_lesson)),
        shared_title_words=len(left & right),
    )


def _field(row: Any, name: str) -> str | None:
    """Rows arrive both as ORM objects and as the dicts the selector passes around."""
    if isinstance(row, dict):
        value = row.get(name)
    else:
        value = getattr(row, name, None)
    return value if isinstance(value, str) else None


def find_duplicate(candidate: Any, existing: list[Any]) -> tuple[Any, Similarity] | None:
    """The idea on the list that this candidate repeats, and how close it is.

    The strongest match wins, so the reason names the idea he would actually
    recognise rather than whichever happened to be checked first.
    """
    title, lesson = _field(candidate, "title"), _field(candidate, "lesson")
    best: tuple[Any, Similarity] | None = None
    for row in existing:
        score = compare(title, lesson, _field(row, "title"), _field(row, "lesson"))
        if not score.repeat:
            continue
        if best is None or score.title > best[1].title:
            best = (row, score)
    return best
