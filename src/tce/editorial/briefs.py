"""Versioned conceptual briefs for a topic.

A `TopicCandidate` is what the selector produced. A brief is what the editor
thinks, and the two must not be the same row: editing the brief is how he shapes
an idea before spending a recording slot on it, and that has to be possible
without regenerating anything or paying for a script.

Version 1 is derived from the candidate's own columns and is therefore never new
content: it is the same idea, arranged into the blocks the topic room edits. It is
created on first read (`ensure_brief`) so no migration has to rewrite data, and it
is idempotent, so the backfill script and a first page view cannot race into two
version 1 rows.

Every later version is written by `write_version`, only ever from an applied
change set. Nothing here mutates a row that already exists.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.editorial import TopicCandidate
from tce.models.editorial_workspace import BRIEF_FIELDS, CandidateBriefVersion

# Blocks the editor writes himself. Seeding leaves them absent rather than
# inventing a takeaway he did not choose, and the room renders an invitation.
EDITOR_OWNED = ("takeaway", "cta")

_AUDIENCE_LABELS = {
    "coaches": "Coaches",
    "event_owners": "Event and service business owners",
    "both": "Coaches, and the service owners they work with",
}

_SOURCE_LABELS = {
    "fathom_meeting": "your call",
    "github_commit_group": "your code",
}


def seed_brief(candidate: TopicCandidate) -> dict[str, str]:
    """Arrange a candidate's own words into brief blocks. Invents nothing.

    Every value here already exists on the candidate row. The only composed
    strings are `why_now` and `why_this_is_yours`, and both are assembled from
    stored fields rather than generated, so seeding never needs a model call.
    """
    brief: dict[str, str] = {
        "topic": candidate.title or "",
        "audience": _AUDIENCE_LABELS.get(candidate.audience or "", candidate.audience or ""),
        "big_idea": candidate.lesson or "",
        "distinctive_perspective": candidate.public_angle or "",
    }

    if candidate.freshness_role == "news":
        brief["why_now"] = (
            "This is tied to something that just changed, so it is worth more this week "
            "than next."
        )
    else:
        brief["why_now"] = ""

    brief["why_this_is_yours"] = _why_this_is_yours(candidate)
    brief["evidence"] = _evidence_summary(candidate)
    brief["claims_to_avoid"] = _readable(candidate.public_safety_notes or "")

    # Absent, not empty: the room shows "Nothing written yet" and an invitation,
    # which reads as a prompt instead of as a field he already answered blank.
    for key in EDITOR_OWNED:
        brief.pop(key, None)

    return {k: v for k, v in brief.items() if k in BRIEF_FIELDS}


_UUID_PATTERN = re.compile(
    r"\s*\b(?:for|in|on|at)?\s*(?:moment|source|packet|phrase)?\s*"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b:?",
    re.IGNORECASE,
)


def _readable(text: str) -> str:
    """Strip the engine's internal ids out of anything he reads.

    The selector writes notes like "Translation ... for moment 45586105-e117-...:
    paraphrase, do not quote." The instruction is useful; the uuid is noise he
    explicitly asked never to see ("no phrase ids visible - useless and
    distracting"). The sentence survives, the id does not.
    """
    cleaned = _UUID_PATTERN.sub("", text)
    # Tidy the punctuation the removal leaves behind.
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.:;])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    return cleaned.strip().lstrip(":").strip()


def _why_this_is_yours(candidate: TopicCandidate) -> str:
    """The sentence that earns a topic its place in the inbox.

    Built from where the evidence came from, not from a claim about Ziv. An idea
    whose evidence is empty produces an empty string, and `is_inbox_eligible`
    then keeps it out of the inbox entirely.
    """
    cites = candidate.citations_private or []
    kinds = [c.get("source_kind") for c in cites if isinstance(c, dict)]
    calls = sum(1 for k in kinds if k == "fathom_meeting")
    commits = sum(1 for k in kinds if k == "github_commit_group")
    # Third lane. A news idea may rest on a standing fact alone - a system Kivi
    # Media runs, or a problem his clients keep bringing - which is the route
    # Ziv's 21-Sep correction opened. Without counting it here this sentence came
    # back EMPTY, and an empty sentence makes is_inbox_eligible keep the idea out
    # of the inbox entirely: it would pass every gate and still never be seen.
    standing = sum(1 for k in kinds if k == "standing_fact")
    news = next(
        (c for c in cites if isinstance(c, dict) and c.get("source_kind") == "news_item"),
        None,
    )

    parts: list[str] = []
    if calls:
        parts.append(f"{calls} of your own conversations" if calls > 1 else "one of your calls")
    if commits:
        parts.append(
            f"{commits} pieces of your code" if commits > 1 else "something you built"
        )
    if standing:
        parts.append(
            "the work you run for clients" if standing == 1 else "work you run for clients"
        )
    if not parts:
        return ""

    if news is not None:
        # The news is the trigger, never the reason: the sentence still leads with
        # his work, and the announcement is named as what changed.
        what = str(news.get("source_title") or "an announcement").strip()
        return f"{what} touches {' and '.join(parts)}.".strip()

    reasons = [r for r in (candidate.reasons_to_care or []) if isinstance(r, str) and r.strip()]
    tail = f" {reasons[0].strip()}" if reasons else ""
    return f"It came out of {' and '.join(parts)}.{tail}".strip()


def _evidence_summary(candidate: TopicCandidate) -> str:
    """Source labels only.

    `citations_private` carries `url_private` and span offsets. Those stay out of
    the brief: a brief is editable text that can end up in an export, and a
    tokenized Fathom link in an exported document is a leaked credential.
    """
    lines: list[str] = []
    for cite in candidate.citations_private or []:
        if not isinstance(cite, dict):
            continue
        label = _SOURCE_LABELS.get(str(cite.get("source_kind")), "a source")
        title = (cite.get("title") or "").strip()
        lines.append(f"From {label}: {title}" if title else f"From {label}")
    # Same source cited twice is one line; the editor is reading, not auditing.
    seen: set[str] = set()
    unique = [x for x in lines if not (x in seen or seen.add(x))]
    return "\n".join(unique)


def is_inbox_eligible(brief: dict[str, Any]) -> bool:
    """A topic with no stated connection to Ziv's work never reaches the inbox.

    The plan's rule, enforced at the one place the inbox is built rather than
    trusted to the selector: if we cannot say why this belongs to him, it is not
    a topic for him, however good the idea is.
    """
    return bool(str(brief.get("why_this_is_yours") or "").strip())


async def latest_version(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> CandidateBriefVersion | None:
    result = await db.execute(
        select(CandidateBriefVersion)
        .where(
            CandidateBriefVersion.workspace_id == ws,
            CandidateBriefVersion.candidate_id == candidate_id,
        )
        .order_by(CandidateBriefVersion.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_version(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID, version: int
) -> CandidateBriefVersion | None:
    result = await db.execute(
        select(CandidateBriefVersion).where(
            CandidateBriefVersion.workspace_id == ws,
            CandidateBriefVersion.candidate_id == candidate_id,
            CandidateBriefVersion.version == version,
        )
    )
    return result.scalar_one_or_none()


async def list_versions(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> list[CandidateBriefVersion]:
    result = await db.execute(
        select(CandidateBriefVersion)
        .where(
            CandidateBriefVersion.workspace_id == ws,
            CandidateBriefVersion.candidate_id == candidate_id,
        )
        .order_by(CandidateBriefVersion.version.asc())
    )
    return list(result.scalars().all())


async def ensure_brief(
    db: AsyncSession, ws: uuid.UUID, candidate: TopicCandidate
) -> CandidateBriefVersion:
    """Return the current brief, seeding version 1 from the candidate if needed.

    Idempotent under concurrency: the unique constraint on
    (workspace, candidate, version) is the arbiter, and a loser re-reads rather
    than raising. Two tabs opening the same topic room must not produce two
    version 1 rows with different provenance.
    """
    existing = await latest_version(db, ws, candidate.id)
    if existing is not None:
        return existing

    row = CandidateBriefVersion(
        workspace_id=ws,
        candidate_id=candidate.id,
        version=1,
        parent_version=None,
        brief=seed_brief(candidate),
        origin="seed",
        created_by="tce",
        note="Arranged from the idea as the engine proposed it. No content was changed.",
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        again = await latest_version(db, ws, candidate.id)
        if again is None:  # pragma: no cover - only if the row vanished mid-flight
            raise
        return again
    return row


async def write_version(
    db: AsyncSession,
    ws: uuid.UUID,
    candidate_id: uuid.UUID,
    *,
    brief: dict[str, Any],
    parent_version: int,
    origin: str,
    change_set_id: uuid.UUID | None = None,
    created_by: str | None = None,
    note: str | None = None,
) -> CandidateBriefVersion:
    """Append a new immutable version. The caller has already validated the base."""
    current = await latest_version(db, ws, candidate_id)
    next_version = (current.version + 1) if current else 1
    row = CandidateBriefVersion(
        workspace_id=ws,
        candidate_id=candidate_id,
        version=next_version,
        parent_version=parent_version,
        brief={k: v for k, v in brief.items() if k in BRIEF_FIELDS},
        origin=origin,
        change_set_id=change_set_id,
        created_by=created_by,
        note=note,
    )
    db.add(row)
    await db.flush()
    return row


def brief_to_json(row: CandidateBriefVersion) -> dict[str, Any]:
    """Render in BRIEF_FIELDS order, telling the UI which blocks are unwritten.

    `written: false` is not the same as an empty string, and the room draws them
    differently: one is an invitation, the other is an answer.
    """
    stored = row.brief or {}
    blocks = []
    for field in BRIEF_FIELDS:
        value = stored.get(field)
        blocks.append(
            {
                "field": field,
                "value": value if isinstance(value, str) else "",
                "written": isinstance(value, str) and bool(value.strip()),
            }
        )
    return {
        "candidate_id": str(row.candidate_id),
        "version": row.version,
        "parent_version": row.parent_version,
        "origin": row.origin,
        "change_set_id": str(row.change_set_id) if row.change_set_id else None,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "note": row.note,
        "blocks": blocks,
        "values": {b["field"]: b["value"] for b in blocks},
    }
