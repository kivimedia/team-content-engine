"""The topic inbox and the topic room.

The old queue asked one question with two answers: write the script, or put it
away. Both are commitments - one spends a worker job and a recording slot, the
other buries the idea - and there was nowhere to stand between them. This is that
place.

Four first decisions, none of which pays for anything:

    this_week   put it in the week's list
    discuss     I want to think about this one
    later       not now, keep it
    away        not for me

Asking for the script happens *after* the topic is worth pursuing, from the topic
room. That separation is the whole point of this module.

Listing is a pure read. Seeding a brief writes rows, so the inbox computes
eligibility in memory and only persists a version 1 when a room is actually
opened. A GET that writes to the database is a GET that cannot be cached, retried
or polled, and this one is polled.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial import briefs
from tce.editorial.common import (
    ORIGIN_SELECTOR_REJECTED,
    ORIGIN_TECHNICAL_VALIDATION,
)
from tce.editorial.lineup import LANE_LABELS, lane_for
from tce.models.editorial import RecordingPacket, TopicCandidate
from tce.models.editorial_workspace import TOPIC_DECISIONS, TopicDecision

# Filter keys the inbox offers, in the order the chips are shown.
#
# `timely` from the plan is not a separate filter: `freshness_role` is the only
# timeliness signal TCE has, and it is the same field that makes a topic AI news.
# Two chips that select identical rows would be a lie about how the engine works.
FILTERS = ("best", "calls", "code", "news", "evergreen", "later", "away")

FILTER_LABELS = {
    "best": "Best matches",
    "calls": "From my calls",
    "code": "From my code",
    "news": "AI news",
    "evergreen": "Evergreen",
    "later": "Saved for later",
    "away": "Put away",
}

# Origins that are engine bookkeeping, never topics for a human to decide on.
HIDDEN_ORIGINS = (ORIGIN_SELECTOR_REJECTED, ORIGIN_TECHNICAL_VALIDATION)


class InboxError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


async def _decisions_for(
    db: AsyncSession, ws: uuid.UUID, candidate_ids: list[uuid.UUID]
) -> dict[uuid.UUID, TopicDecision]:
    if not candidate_ids:
        return {}
    result = await db.execute(
        select(TopicDecision).where(
            TopicDecision.workspace_id == ws,
            TopicDecision.candidate_id.in_(candidate_ids),
        )
    )
    return {d.candidate_id: d for d in result.scalars().all()}


async def _briefs_for(
    db: AsyncSession, ws: uuid.UUID, candidate_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Newest stored brief per candidate. Absent means "never opened"."""
    if not candidate_ids:
        return {}
    result = await db.execute(
        select(briefs.CandidateBriefVersion)
        .where(
            briefs.CandidateBriefVersion.workspace_id == ws,
            briefs.CandidateBriefVersion.candidate_id.in_(candidate_ids),
        )
        .order_by(briefs.CandidateBriefVersion.version.asc())
    )
    newest: dict[uuid.UUID, dict[str, Any]] = {}
    for row in result.scalars().all():
        newest[row.candidate_id] = dict(row.brief or {})
    return newest


async def _packet_counts(
    db: AsyncSession, ws: uuid.UUID, candidate_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not candidate_ids:
        return {}
    result = await db.execute(
        select(RecordingPacket.candidate_id, func.count(RecordingPacket.id))
        .where(
            RecordingPacket.workspace_id == ws,
            RecordingPacket.candidate_id.in_(candidate_ids),
        )
        .group_by(RecordingPacket.candidate_id)
    )
    return {row[0]: row[1] for row in result.all()}


def _matches(
    filter_key: str,
    candidate: TopicCandidate,
    decision: TopicDecision | None,
) -> bool:
    decided = decision.decision if decision else None

    if filter_key == "later":
        return decided == "later"
    if filter_key == "away":
        return decided == "away"

    # Every other filter is a view of what is still undecided. A topic already
    # put in the week or put away does not belong in a list of things to decide.
    if decided in ("away", "later", "this_week"):
        return False

    kinds = {
        c.get("source_kind")
        for c in (candidate.citations_private or [])
        if isinstance(c, dict)
    }
    if filter_key == "calls":
        return "fathom_meeting" in kinds
    if filter_key == "code":
        return "github_commit_group" in kinds
    if filter_key == "news":
        return candidate.freshness_role == "news"
    if filter_key == "evergreen":
        return candidate.freshness_role != "news"
    return True  # best


def _provenance(candidate: TopicCandidate) -> str:
    """Where it came from, in the words the old queue used. He reads this first."""
    cites = [c for c in (candidate.citations_private or []) if isinstance(c, dict)]
    titles: list[str] = []
    for cite in cites:
        title = (cite.get("title") or "").strip()
        if title and title not in titles:
            titles.append(title)
    if not titles:
        return ""
    # The old surface truncated to two and dropped the rest silently. Say the count.
    if len(titles) <= 2:
        return "From " + " and ".join(titles)
    return f"From {titles[0]}, {titles[1]} and {len(titles) - 2} more"


def _row_to_json(
    candidate: TopicCandidate,
    brief: dict[str, Any],
    decision: TopicDecision | None,
    packet_count: int,
) -> dict[str, Any]:
    lane = lane_for(candidate)
    return {
        "candidate_id": str(candidate.id),
        "title": candidate.title,
        # The point he would make, in full. The old row showed this and it is
        # what makes a two-second decision possible.
        "big_idea": candidate.lesson,
        "why_this_is_yours": brief.get("why_this_is_yours", ""),
        "provenance": _provenance(candidate),
        "lane": lane,
        "lane_label": LANE_LABELS.get(lane, lane),
        "timely": candidate.freshness_role == "news",
        "freshness_note": (
            "Timely · worth more this week than next" if candidate.freshness_role == "news" else ""
        ),
        "decision": decision.decision if decision else None,
        "note": decision.note if decision else None,
        "has_script": packet_count > 0,
        "rank": candidate.rank,
        "week_start": candidate.week_start.date().isoformat() if candidate.week_start else None,
    }


async def list_topics(
    db: AsyncSession,
    ws: uuid.UUID,
    *,
    filter_key: str = "best",
    limit: int = 30,
    offset: int = 0,
) -> dict[str, Any]:
    """The inbox. Read-only: no brief row is written by looking at the list."""
    if filter_key not in FILTERS:
        raise InboxError("bad_filter", f"unknown filter {filter_key}", status=400)

    result = await db.execute(
        select(TopicCandidate)
        .where(
            TopicCandidate.workspace_id == ws,
            TopicCandidate.status.notin_(("rejected", "recorded", "published")),
            TopicCandidate.origin.notin_(HIDDEN_ORIGINS),
        )
        .order_by(
            TopicCandidate.rank.is_(None).asc(),
            TopicCandidate.rank.asc(),
            TopicCandidate.created_at.desc(),
        )
    )
    candidates = list(result.scalars().all())
    ids = [c.id for c in candidates]
    decisions = await _decisions_for(db, ws, ids)
    stored = await _briefs_for(db, ws, ids)
    counts = await _packet_counts(db, ws, ids)

    rows: list[dict[str, Any]] = []
    withheld = 0
    for candidate in candidates:
        decision = decisions.get(candidate.id)
        # A stored brief wins: he may have written the connection himself.
        brief = stored.get(candidate.id) or briefs.seed_brief(candidate)
        if not briefs.is_inbox_eligible(brief) and (
            not decision or decision.decision not in ("later", "away")
        ):
            withheld += 1
            continue
        if not _matches(filter_key, candidate, decision):
            continue
        rows.append(_row_to_json(candidate, brief, decision, counts.get(candidate.id, 0)))

    total = len(rows)
    page = rows[offset : offset + limit]
    return {
        "filter": filter_key,
        "filter_label": FILTER_LABELS[filter_key],
        "filters": [{"key": k, "label": FILTER_LABELS[k]} for k in FILTERS],
        "topics": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < total,
        # Radical transparency: say that ideas were held back and why, rather
        # than quietly showing a shorter list.
        "withheld": withheld,
        "withheld_note": (
            f"{withheld} ideas are not shown because the engine could not say how they "
            "connect to your work."
            if withheld
            else ""
        ),
    }


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------


async def get_candidate(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> TopicCandidate:
    result = await db.execute(
        select(TopicCandidate).where(
            TopicCandidate.workspace_id == ws, TopicCandidate.id == candidate_id
        )
    )
    candidate = result.scalar_one_or_none()
    if candidate is None:
        raise InboxError("not_found", "that topic is not here", status=404)
    return candidate


async def get_decision(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> TopicDecision | None:
    result = await db.execute(
        select(TopicDecision).where(
            TopicDecision.workspace_id == ws, TopicDecision.candidate_id == candidate_id
        )
    )
    return result.scalar_one_or_none()


async def decide(
    db: AsyncSession,
    ws: uuid.UUID,
    candidate_id: uuid.UUID,
    *,
    decision: str,
    note: str | None = None,
    decided_by: str | None = None,
) -> TopicDecision:
    """Record the editor's decision. Reversible, and it never destroys the note.

    `previous_decision` is kept so "Save for later" then "Bring it back" returns
    the topic to where it was rather than to a default, and so a note written
    while deciding survives a change of mind.
    """
    if decision not in TOPIC_DECISIONS:
        raise InboxError("bad_decision", f"unknown decision {decision}", status=400)

    candidate = await get_candidate(db, ws, candidate_id)
    if candidate.status == "recorded" and decision == "away":
        raise InboxError("recorded", "that one is already recorded", status=409)

    row = await get_decision(db, ws, candidate_id)
    now = datetime.now(UTC).replace(tzinfo=None)
    if row is None:
        row = TopicDecision(
            workspace_id=ws,
            candidate_id=candidate_id,
            decision=decision,
            note=note,
            decided_by=decided_by,
            decided_at=now,
        )
        db.add(row)
    else:
        if row.decision != decision:
            row.previous_decision = row.decision
        row.decision = decision
        # An empty note must not wipe one he already wrote.
        if note is not None:
            row.note = note
        row.decided_by = decided_by
        row.decided_at = now

    # The engine's own status still moves, so the rest of TCE keeps working. It
    # is a mirror of the decision, never the source of truth for it.
    if decision == "away":
        candidate.status = "withdrawn"
    elif candidate.status == "withdrawn":
        candidate.status = "proposed"

    await db.flush()
    return row


async def topic_room(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> dict[str, Any]:
    """Everything the topic room shows. This one does seed a brief, on purpose."""
    candidate = await get_candidate(db, ws, candidate_id)
    brief = await briefs.ensure_brief(db, ws, candidate)
    decision = await get_decision(db, ws, candidate_id)
    versions = await briefs.list_versions(db, ws, candidate_id)

    packets = await db.execute(
        select(RecordingPacket)
        .where(
            RecordingPacket.workspace_id == ws,
            RecordingPacket.candidate_id == candidate_id,
        )
        .order_by(RecordingPacket.version.desc())
    )
    packet_rows = list(packets.scalars().all())
    current = next((p for p in packet_rows if p.status != "superseded"), None)
    lane = lane_for(candidate)

    return {
        "candidate_id": str(candidate.id),
        "title": candidate.title,
        "lane": lane,
        "lane_label": LANE_LABELS.get(lane, lane),
        "timely": candidate.freshness_role == "news",
        "provenance": _provenance(candidate),
        "decision": decision.decision if decision else None,
        "note": decision.note if decision else None,
        "brief": briefs.brief_to_json(brief),
        "history": [
            {
                "version": v.version,
                "origin": v.origin,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "note": v.note,
                "is_current": v.version == brief.version,
            }
            for v in versions
        ],
        "script": (
            {
                "packet_id": str(current.id),
                "version": current.version,
                "status": current.status,
                "has_hooks": bool(current.hook_options),
                "selected_hook_id": current.selected_hook_id,
            }
            if current
            else None
        ),
        # The room never hides that asking for a script costs a worker job.
        "script_note": (
            "The script is written on your PC worker and takes a few minutes."
            if current is None
            else ""
        ),
    }
