"""Show the writer how Ziv talks about THIS subject.

A rule list makes a model obedient. It does not make it sound like anyone, which is
why a packet written against 36 correct patterns still came out reading like every
other AI script.

What changes that is his own words next to the task: for the idea being written, the
stretches where he talked about that subject, in his register, with his metaphors and
his way of conceding a point before disagreeing with it. Not to copy - his own rule 1
forbids verbatim quoting and the packet already refuses to put call words on camera -
but so the writer has heard him before it writes.

Retrieval is lexical on purpose. Content-word overlap is deterministic, costs nothing,
needs no embedding service, and is inspectable: he can see why a sample was chosen.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial.dedupe import tokens
from tce.models.voice_sample import VoiceSample

logger = structlog.get_logger()

# Call housekeeping: greetings, scheduling, status updates to a team. Real speech,
# and nothing to do with how he opens an idea.
_CHATTER = re.compile(
    r"^\s*(hi|hey|hello|thanks|thank you|welcome|good morning|good evening|"
    r"i'?m on it|i'?ll get back|let me know|sorry|excuse me|one more thing|"
    r"can you hear|are you there|i think that you should|we need to schedule|"
    # Discourse hedges. An opening takes a position; these are how a person eases
    # into a conversation, and reading them as hooks is how a script goes limp.
    r"well|i mean|plus|honestly|basically|for example|actually|obviously|"
    r"i'?m trying|i guess|maybe|probably|kind of|sort of|by the way|anyway)\b",
    re.IGNORECASE,
)

# How many stretches reach the prompt. Enough to show range, few enough that the
# packet prompt stays about the idea rather than about the corpus.
SAMPLE_COUNT = 6
# Openings shown alongside, as the bank his hooks are drawn from.
OPENING_COUNT = 12
# Never send the whole of a long stretch: the register is in the first part.
SAMPLE_CHARS = 1100
# Scanned before ranking. The corpus is hundreds of rows, not millions.
SCAN_LIMIT = 1200
# Below this the overlap is generic words, not the subject. Two stretches where he
# really talked about this beat six where one did: the other five teach the writer
# the register of whatever they happened to be about.
MIN_SCORE = 0.12


# Exact tokens miss the obvious: "price" never matches "pricing", "decide" never
# matches "decision", "book" never matches "bookings" - and those are the words the
# subject actually lives in. Four characters is enough of a stem to join them and
# short enough to stay honest about what it is.
_STEM = 4


def stems(words) -> set[str]:
    return {w[:_STEM] for w in words if w}


def score(sample_keywords: list[str], wanted: frozenset[str]) -> float:
    """Share of the idea's subject this stretch also talks about.

    Deliberately not symmetric: a long stretch is not penalised for covering more
    ground than the idea, it is rewarded for covering the idea's ground.
    """
    if not wanted or not sample_keywords:
        return 0.0
    have, want = stems(sample_keywords), stems(wanted)
    return len(have & want) / len(want)


async def for_idea(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    title: str | None,
    lesson: str | None,
    limit: int = SAMPLE_COUNT,
) -> list[VoiceSample]:
    """His mini speeches closest to this idea, best first."""
    wanted = tokens(f"{title or ''} {lesson or ''}")
    if not wanted:
        return []
    rows = (
        (
            await session.execute(
                select(VoiceSample)
                .where(
                    VoiceSample.workspace_id == workspace_id,
                    VoiceSample.kind == "teaching",
                )
                .order_by(VoiceSample.occurred_at.desc().nullslast())
                .limit(SCAN_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    ranked = sorted(
        ((score(row.keywords or [], wanted), row) for row in rows),
        key=lambda pair: (pair[0], pair[1].word_count),
        reverse=True,
    )
    # A sample that barely touches the idea is noise dressed as evidence.
    return [row for value, row in ranked[:limit] if value >= MIN_SCORE]


async def opening_bank(
    session: AsyncSession, workspace_id: uuid.UUID, *, limit: int = OPENING_COUNT
) -> list[str]:
    """Real first sentences of his, as the shape a hook should take.

    Drawn from the whole corpus rather than the idea's neighbourhood: what is wanted
    here is the SHAPE of how he starts, not what he started about.
    """
    rows = (
        (
            await session.execute(
                select(VoiceSample.opening)
                .where(
                    VoiceSample.workspace_id == workspace_id,
                    VoiceSample.kind == "teaching",
                    VoiceSample.opening.isnot(None),
                    VoiceSample.opening != "",
                )
                .order_by(VoiceSample.occurred_at.desc().nullslast())
                .limit(SCAN_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    seen: set[str] = set()
    out: list[str] = []
    for opening in rows:
        text = (opening or "").strip()
        if not usable_opening(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def usable_opening(text: str) -> bool:
    """Is this a sentence someone could start a video with?

    A transcript is full of fragments that only look like sentences because the
    punctuation landed there: "have that we updated my user to include the DJ
    stuff", "I'm on it, I'm on I'm on it from here". None of that is an opening.
    """
    if not text:
        return False
    words = text.split()
    # Six words is a sentence; thirty is already a paragraph nobody opens with.
    if not 6 <= len(words) <= 30:
        return False
    # A fragment picked up mid-sentence does not start with a capital.
    if not text[0].isupper():
        return False
    # His rule: an opening takes a position. A question is the shape he rejected.
    if text.rstrip().endswith("?"):
        return False
    # Housekeeping and chatter, not the start of a lesson.
    return not _CHATTER.match(text)


def render(samples: list[VoiceSample], openings: list[str]) -> str:
    """The prompt block. Empty string when there is nothing, so the caller can skip it."""
    if not samples and not openings:
        return ""
    parts: list[str] = [
        "HOW ZIV TALKS (transcribed from his own calls, private).\n"
        "This is the register to write in: his sentence shapes, his metaphors, the way "
        "he concedes a point before disagreeing with it. Do NOT quote any of it, do not "
        "reuse its examples, and never put a client's words or situation on camera. It "
        "is here so you have heard him before you write."
    ]
    for index, sample in enumerate(samples, start=1):
        when = sample.occurred_at.date().isoformat() if sample.occurred_at else "undated"
        parts.append(f"[{index}] {when}, {sample.word_count} words:\n{sample.text[:SAMPLE_CHARS]}")
    if openings:
        parts.append(
            "HOW HE STARTS (real first sentences of his). A hook should have this "
            "shape: a plain statement that takes a position, not a question and not a "
            "tease.\n" + "\n".join(f"- {o}" for o in openings)
        )
    return "\n\n".join(parts)


async def block_for_idea(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    title: str | None,
    lesson: str | None,
) -> tuple[str, dict[str, Any]]:
    """(prompt block, provenance). Provenance so a packet can say what it heard.

    The corpus is an improvement to a script, never a precondition for one. If it
    cannot be read - not built yet, migration not run, database unhappy - the packet
    is still written, and the reason is reported rather than swallowed.
    """
    try:
        samples = await for_idea(session, workspace_id, title=title, lesson=lesson)
        openings = await opening_bank(session, workspace_id)
    except SQLAlchemyError as exc:
        logger.warning("voice_corpus_unavailable", error=type(exc).__name__)
        # The session is dirty after a failed statement; later writes need it clean.
        await session.rollback()
        return "", {"samples": [], "sample_words": 0, "openings": 0, "error": type(exc).__name__}
    return render(samples, openings), {
        "samples": [str(s.id) for s in samples],
        "sample_words": sum(s.word_count for s in samples),
        "openings": len(openings),
    }
