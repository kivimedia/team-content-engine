"""The weekly recording lineup: three slots, a reserve, and a reason beside each.

The old queue answered "what has a script". This answers "what am I recording
this week, in what order, and why that one first" - which is the decision Ziv
actually makes, and the one the interface never had a place for.

Two deliberate refusals:

*No numeric score in the interface.* The selector has `rank_score` and it stays
internal. "87 points" looks precise and helps nobody choose; a sentence naming
what makes a topic urgent does.

*No quota enforcement.* Lane labels (build / coaching / ai news) are shown so an
unbalanced week is visible, never to refuse a third build topic. It is his week.

Concurrency: `WeeklyLineup.revision` is the token. Every mutation states the
revision it read and a stale write is refused with the newer state, because the
phone in his pocket and the tab on his desk are the same week.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial.common import current_week_start, week_bounds
from tce.models.editorial import RecordingPacket, TopicCandidate
from tce.models.editorial_workspace import (
    LINEUP_SLOTS,
    TopicDecision,
    WeeklyLineup,
    WeeklyLineupItem,
)

DEFAULT_PRIMARY_SLOTS = 3

LANE_LABELS = {
    "build": "Build",
    "coaching": "Coaching",
    # Ziv's own name for the lane (21-Sep). The key stays "ai_news" because other
    # code and stored lineups read it; only what he sees changes.
    "ai_news": "News that excites Ziv",
    "other": "Other",
}


class LineupError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


def week_start_for(value: date | datetime | str | None) -> datetime:
    """Normalise any week reference to the Monday datetime the rest of TCE uses."""
    return week_bounds(value if value is not None else current_week_start())[0]


def lane_for(candidate: TopicCandidate) -> str:
    """Which of the three content lanes this topic belongs to.

    Read from the evidence that produced it, so the label is a fact about the
    idea rather than a guess: news is flagged by the selector, code citations
    mean it came out of something built, and the rest is coaching.
    """
    if candidate.freshness_role == "news":
        return "ai_news"
    kinds = {
        c.get("source_kind")
        for c in (candidate.citations_private or [])
        if isinstance(c, dict)
    }
    if "github_commit_group" in kinds:
        return "build"
    if candidate.audience in ("coaches", "both"):
        return "coaching"
    return "other"


def reason_for(candidate: TopicCandidate, *, rank: int, slot: str) -> str:
    """The sentence shown beside the item. Composed from stored facts only."""
    clauses: list[str] = []
    if candidate.freshness_role == "news":
        clauses.append("it is timely")
    kinds = [
        c.get("source_kind")
        for c in (candidate.citations_private or [])
        if isinstance(c, dict)
    ]
    if "github_commit_group" in kinds:
        clauses.append("it connects to something you built")
    if "fathom_meeting" in kinds:
        clauses.append("it came out of a real conversation")
    reasons = [r for r in (candidate.reasons_to_care or []) if isinstance(r, str) and r.strip()]
    if reasons:
        clauses.append(reasons[0].strip().rstrip("."))

    if not clauses:
        return "In reserve." if slot == "reserve" else "In this week's list."
    lead = "Record first because" if (slot == "primary" and rank == 1) else "Here because"
    if len(clauses) == 1:
        body = clauses[0]
    else:
        body = ", ".join(clauses[:-1]) + " and " + clauses[-1]
    return f"{lead} {body}."


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


async def get_lineup(
    db: AsyncSession, ws: uuid.UUID, week_start: datetime
) -> WeeklyLineup | None:
    result = await db.execute(
        select(WeeklyLineup).where(
            WeeklyLineup.workspace_id == ws, WeeklyLineup.week_start == week_start
        )
    )
    return result.scalar_one_or_none()


async def ensure_lineup(
    db: AsyncSession, ws: uuid.UUID, week_start: datetime
) -> WeeklyLineup:
    """Get or create this week's lineup. Idempotent under two simultaneous opens."""
    existing = await get_lineup(db, ws, week_start)
    if existing is not None:
        return existing
    row = WeeklyLineup(
        workspace_id=ws,
        week_start=week_start,
        status="draft",
        revision=1,
        primary_slots=DEFAULT_PRIMARY_SLOTS,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        again = await get_lineup(db, ws, week_start)
        if again is None:  # pragma: no cover
            raise
        return again
    return row


async def list_items(
    db: AsyncSession, ws: uuid.UUID, lineup_id: uuid.UUID
) -> list[WeeklyLineupItem]:
    result = await db.execute(
        select(WeeklyLineupItem)
        .where(
            WeeklyLineupItem.workspace_id == ws,
            WeeklyLineupItem.lineup_id == lineup_id,
        )
        .order_by(WeeklyLineupItem.slot.asc(), WeeklyLineupItem.rank.asc())
    )
    return list(result.scalars().all())


async def _candidates_by_id(
    db: AsyncSession, ws: uuid.UUID, ids: list[uuid.UUID]
) -> dict[uuid.UUID, TopicCandidate]:
    if not ids:
        return {}
    result = await db.execute(
        select(TopicCandidate).where(
            TopicCandidate.workspace_id == ws, TopicCandidate.id.in_(ids)
        )
    )
    return {c.id: c for c in result.scalars().all()}


async def _latest_packets(
    db: AsyncSession, ws: uuid.UUID, candidate_ids: list[uuid.UUID]
) -> dict[uuid.UUID, RecordingPacket]:
    """Newest non-superseded packet per candidate, so the week can say 'script ready'."""
    if not candidate_ids:
        return {}
    result = await db.execute(
        select(RecordingPacket)
        .where(
            RecordingPacket.workspace_id == ws,
            RecordingPacket.candidate_id.in_(candidate_ids),
        )
        .order_by(RecordingPacket.version.asc())
    )
    newest: dict[uuid.UUID, RecordingPacket] = {}
    for packet in result.scalars().all():
        if packet.status == "superseded":
            continue
        newest[packet.candidate_id] = packet
    return newest


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _check_revision(lineup: WeeklyLineup, expected: int | None) -> None:
    if expected is not None and expected != lineup.revision:
        raise LineupError(
            "conflict",
            (
                f"This week changed somewhere else (you had revision {expected}, it is "
                f"now {lineup.revision}). Nothing was moved."
            ),
            status=409,
            current_revision=lineup.revision,
        )


async def _renumber(db: AsyncSession, ws: uuid.UUID, lineup_id: uuid.UUID) -> None:
    """Keep ranks contiguous from 1 inside each slot.

    Gaps are how "Move up" starts behaving unpredictably three taps in, so they
    are closed after every mutation rather than tolerated.
    """
    for slot in LINEUP_SLOTS:
        result = await db.execute(
            select(WeeklyLineupItem)
            .where(
                WeeklyLineupItem.workspace_id == ws,
                WeeklyLineupItem.lineup_id == lineup_id,
                WeeklyLineupItem.slot == slot,
            )
            .order_by(WeeklyLineupItem.rank.asc(), WeeklyLineupItem.created_at.asc())
        )
        for index, item in enumerate(result.scalars().all(), start=1):
            if item.rank != index:
                item.rank = index
    await db.flush()


async def add_topic(
    db: AsyncSession,
    ws: uuid.UUID,
    lineup: WeeklyLineup,
    candidate: TopicCandidate,
    *,
    slot: str = "primary",
    added_by: str | None = None,
    rank: int | None = None,
) -> WeeklyLineupItem:
    """Put a topic in the week. Overflowing the primary slots lands in reserve.

    The overflow is deliberate and silent-free: the caller is told which slot it
    landed in, so the UI can say "this week is full, it went to reserve" instead
    of refusing the tap.

    `rank` puts it back at a known place (the one it was taken out of) instead of
    at the end, moving the ones below it down one. It is ignored when the topic
    overflows into reserve, because that place was in the other list.
    """
    if slot not in LINEUP_SLOTS:
        raise LineupError("bad_slot", f"unknown slot {slot}", status=400)

    existing = await db.execute(
        select(WeeklyLineupItem).where(
            WeeklyLineupItem.workspace_id == ws,
            WeeklyLineupItem.lineup_id == lineup.id,
            WeeklyLineupItem.candidate_id == candidate.id,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found

    items = await list_items(db, ws, lineup.id)
    primary_count = sum(1 for i in items if i.slot == "primary")
    wanted_slot = slot
    if slot == "primary" and primary_count >= lineup.primary_slots:
        slot = "reserve"

    siblings = [i for i in items if i.slot == slot]
    at = len(siblings) + 1
    if rank is not None and slot == wanted_slot and 1 <= rank < at:
        for sibling in siblings:
            if sibling.rank >= rank:
                sibling.rank += 1
        at = rank
    item = WeeklyLineupItem(
        workspace_id=ws,
        lineup_id=lineup.id,
        candidate_id=candidate.id,
        rank=at,
        slot=slot,
        lane=lane_for(candidate),
        reason=reason_for(candidate, rank=at, slot=slot),
        status="planned",
        added_by=added_by,
    )
    db.add(item)
    lineup.revision += 1
    lineup.updated_by = added_by
    await db.flush()
    if at != len(siblings) + 1:
        await _renumber(db, ws, lineup.id)
    return item


async def remove_topic(
    db: AsyncSession,
    ws: uuid.UUID,
    lineup: WeeklyLineup,
    candidate_id: uuid.UUID,
    *,
    removed_by: str | None = None,
) -> None:
    result = await db.execute(
        select(WeeklyLineupItem).where(
            WeeklyLineupItem.workspace_id == ws,
            WeeklyLineupItem.lineup_id == lineup.id,
            WeeklyLineupItem.candidate_id == candidate_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        return
    if item.status == "recorded":
        raise LineupError(
            "recorded",
            "that one is already recorded, so it stays in the week",
            status=409,
        )
    await db.delete(item)
    lineup.revision += 1
    lineup.updated_by = removed_by
    await db.flush()
    await _renumber(db, ws, lineup.id)


async def _live_candidate(
    db: AsyncSession, ws: uuid.UUID, candidate_id: Any
) -> TopicCandidate | None:
    """A topic that may be put (back) in a week: this workspace's, and neither
    rejected nor put away since."""
    try:
        cid = uuid.UUID(str(candidate_id))
    except (TypeError, ValueError):
        return None
    result = await db.execute(
        select(TopicCandidate).where(
            TopicCandidate.workspace_id == ws,
            TopicCandidate.id == cid,
            TopicCandidate.status.notin_(("rejected", "withdrawn")),
        )
    )
    return result.scalar_one_or_none()


async def apply_order(
    db: AsyncSession,
    ws: uuid.UUID,
    lineup: WeeklyLineup,
    order: list[dict[str, Any]],
    *,
    create_missing: bool = False,
    added_by: str | None = None,
) -> None:
    """Set slot and rank for every named item. Unnamed items keep their place.

    Called by the change-set engine for `reorder_week` and by the direct reorder
    endpoint. It does not bump `revision`; the caller owns that, so one user
    action is one revision even when it moves three items.

    `create_missing` is for undo only: an order recorded before a topic was taken
    out names that topic, and putting the order back has to put the topic back
    too. Without it a named topic that is not in the week is skipped, which is
    what the direct reorder endpoint wants. A topic rejected or put away since is
    never brought back; the caller checks the result and says so.
    """
    items = {str(i.candidate_id): i for i in await list_items(db, ws, lineup.id)}
    for entry in order:
        if not isinstance(entry, dict):
            continue
        item = items.get(str(entry.get("candidate_id")))
        if item is None:
            if not create_missing:
                continue
            candidate = await _live_candidate(db, ws, entry.get("candidate_id"))
            if candidate is None:
                continue
            slot = entry.get("slot") if entry.get("slot") in LINEUP_SLOTS else "primary"
            rank = entry.get("rank")
            rank = rank if isinstance(rank, int) and rank > 0 else len(items) + 1
            item = WeeklyLineupItem(
                workspace_id=ws,
                lineup_id=lineup.id,
                candidate_id=candidate.id,
                rank=rank,
                slot=slot,
                lane=lane_for(candidate),
                reason=reason_for(candidate, rank=rank, slot=slot),
                status="planned",
                added_by=added_by,
            )
            db.add(item)
            items[str(candidate.id)] = item
            continue
        slot = entry.get("slot")
        if slot in LINEUP_SLOTS:
            item.slot = slot
        rank = entry.get("rank")
        if isinstance(rank, int) and rank > 0:
            item.rank = rank
    await db.flush()
    await _renumber(db, ws, lineup.id)


async def apply_move(
    db: AsyncSession, ws: uuid.UUID, lineup: WeeklyLineup, move: dict[str, Any]
) -> None:
    """One relative move: first / up / down / slot change / remove.

    Relative verbs exist because the phone has buttons, not a drag surface, and
    "Make first" has to mean the same thing whether the list has two items or
    seven.
    """
    if not isinstance(move, dict):
        return
    candidate_id = move.get("candidate_id")
    if not candidate_id:
        return
    items = await list_items(db, ws, lineup.id)
    target = next((i for i in items if str(i.candidate_id) == str(candidate_id)), None)
    if target is None:
        raise LineupError("not_in_week", "that topic is not in this week", status=404)

    action = move.get("action") or "rank"
    if action == "remove":
        await remove_topic(db, ws, lineup, target.candidate_id)
        return

    if action == "slot":
        slot = move.get("slot")
        if slot not in LINEUP_SLOTS:
            raise LineupError("bad_slot", f"unknown slot {slot}", status=400)
        if slot != target.slot:
            target.slot = slot
            target.rank = sum(1 for i in items if i.slot == slot) + 1
        await db.flush()
        await _renumber(db, ws, lineup.id)
        return

    siblings = sorted(
        (i for i in items if i.slot == target.slot), key=lambda i: i.rank
    )
    position = siblings.index(target)
    if action == "first":
        new_position = 0
    elif action == "up":
        new_position = max(0, position - 1)
    elif action == "down":
        new_position = min(len(siblings) - 1, position + 1)
    elif action == "rank":
        wanted = move.get("rank")
        if not isinstance(wanted, int):
            raise LineupError("bad_rank", "a position is required", status=400)
        new_position = max(0, min(len(siblings) - 1, wanted - 1))
    else:
        raise LineupError("bad_action", f"unknown move {action}", status=400)

    siblings.insert(new_position, siblings.pop(position))
    for index, item in enumerate(siblings, start=1):
        item.rank = index
    await db.flush()


async def move(
    db: AsyncSession,
    ws: uuid.UUID,
    lineup: WeeklyLineup,
    move_spec: dict[str, Any],
    *,
    expected_revision: int | None = None,
    moved_by: str | None = None,
) -> WeeklyLineup:
    """Guarded single move: the endpoint path, with the conflict check."""
    _check_revision(lineup, expected_revision)
    await apply_move(db, ws, lineup, move_spec)
    lineup.revision += 1
    lineup.updated_by = moved_by
    await db.flush()
    return lineup


# ---------------------------------------------------------------------------
# The week follows the decision
# ---------------------------------------------------------------------------


async def follow_decision(
    db: AsyncSession,
    ws: uuid.UUID,
    candidate: TopicCandidate,
    decision: TopicDecision | None,
    *,
    by: str | None = None,
) -> dict[str, Any]:
    """Keep this week's list in step with the topic's decision.

    Choosing a topic for this week and listing it are one act from his side, so
    un-choosing it (later, discuss, away, or back to undecided) takes it off the
    list as well; otherwise "saved for later" and "in this week" are both true at
    once. Where it stood is kept on the decision, so choosing it again this week
    (a restore, an undo) puts it back at that place rather than at the end.

    A recorded item stays: `remove_topic` refuses, and the caller's decision is
    refused with it, so nothing is half done.

    Returns {"placed": {slot, rank, revision} | None, "added": bool,
    "removed": {slot, rank} | None}.
    """
    week_start = week_start_for(None)
    week_label = week_start.date().isoformat()
    now = decision.decision if decision is not None else None

    if now == "this_week":
        lineup = await ensure_lineup(db, ws, week_start)
        listed = {i.candidate_id for i in await list_items(db, ws, lineup.id)}
        place = dict((decision.week_place if decision is not None else None) or {})
        here = place.get("week_start") == week_label
        slot = place.get("slot") if here and place.get("slot") in LINEUP_SLOTS else "primary"
        rank = place.get("rank") if here and isinstance(place.get("rank"), int) else None
        item = await add_topic(db, ws, lineup, candidate, slot=slot, rank=rank, added_by=by)
        added = candidate.id not in listed
        if added and decision is not None:
            decision.week_place = None
            await db.flush()
        return {
            "placed": {"slot": item.slot, "rank": item.rank, "revision": lineup.revision},
            "added": added,
            "removed": None,
        }

    lineup = await get_lineup(db, ws, week_start)
    if lineup is None:
        return {"placed": None, "added": False, "removed": None}
    item = next(
        (i for i in await list_items(db, ws, lineup.id) if i.candidate_id == candidate.id),
        None,
    )
    if item is None:
        return {"placed": None, "added": False, "removed": None}
    removed = {"slot": item.slot, "rank": item.rank}
    await remove_topic(db, ws, lineup, candidate.id, removed_by=by)
    if decision is not None:
        decision.week_place = {"week_start": week_label, **removed}
        await db.flush()
    return {"placed": None, "added": False, "removed": removed}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _item_to_json(
    item: WeeklyLineupItem,
    candidate: TopicCandidate | None,
    packet: RecordingPacket | None,
) -> dict[str, Any]:
    return {
        "candidate_id": str(item.candidate_id),
        "packet_id": str(packet.id) if packet else None,
        "packet_version": packet.version if packet else None,
        "title": candidate.title if candidate else "(missing topic)",
        "big_idea": candidate.lesson if candidate else "",
        "rank": item.rank,
        "slot": item.slot,
        "lane": item.lane,
        "lane_label": LANE_LABELS.get(item.lane, item.lane),
        "reason": item.reason,
        "status": item.status,
        # The one thing the week has to be honest about: is there a script yet.
        "script_state": _script_state(packet),
    }


def _script_state(packet: RecordingPacket | None) -> str:
    if packet is None:
        return "none"
    if packet.status in ("ready", "exported"):
        return "ready"
    return packet.status or "draft"


async def lineup_to_json(
    db: AsyncSession, ws: uuid.UUID, lineup: WeeklyLineup
) -> dict[str, Any]:
    items = await list_items(db, ws, lineup.id)
    candidate_ids = [i.candidate_id for i in items]
    candidates = await _candidates_by_id(db, ws, candidate_ids)
    packets = await _latest_packets(db, ws, candidate_ids)

    rendered = [
        _item_to_json(item, candidates.get(item.candidate_id), packets.get(item.candidate_id))
        for item in items
    ]
    primary = [r for r in rendered if r["slot"] == "primary"]
    reserve = [r for r in rendered if r["slot"] == "reserve"]

    counts: dict[str, int] = {}
    for row in primary:
        counts[row["lane"]] = counts.get(row["lane"], 0) + 1
    mix = " · ".join(
        f"{count} {LANE_LABELS.get(lane, lane).lower()}" for lane, count in sorted(counts.items())
    )

    return {
        "lineup_id": str(lineup.id),
        "week_start": lineup.week_start.date().isoformat(),
        "status": lineup.status,
        "revision": lineup.revision,
        "primary_slots": lineup.primary_slots,
        "primary": primary,
        "reserve": reserve,
        # Information, not a rule. An unbalanced week is visible and allowed.
        "mix": mix,
        "ready_count": sum(1 for r in primary if r["script_state"] == "ready"),
    }
