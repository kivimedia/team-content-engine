"""More ideas, without waiting five hours for another run.

Every selection run validates far more ideas than it proposes. A run over one week
of evidence typically clears twenty-odd finalists through all four gates and then
keeps six, because six is what a week of recording is worth. The rest are stored
with the reason they lost.

So "show me more ideas" does not need a model, a worker or a new run: it needs the
next-best ideas that already passed everything. They come back with their own
citations, their own gates and the week they came from, and they are deduped
against what is already on the list the same way a fresh run is.

When the reserve really is empty, this says so plainly rather than inventing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial.common import (
    ORIGIN_SELECTOR_REJECTED,
    ORIGIN_SELECTOR_RESERVE,
)
from tce.editorial.dedupe import find_duplicate
from tce.models.editorial import TopicCandidate

LIVE_STATUSES = ("proposed", "selected", "recorded", "published")
DEFAULT_LIMIT = 3
MAX_LIMIT = 10
# How deep to look before giving up. A workspace accumulates reserve rows forever;
# the useful ones are the recent ones.
SCAN_LIMIT = 200


def _reserve(row: TopicCandidate) -> bool:
    gates = row.gates if isinstance(row.gates, dict) else {}
    return bool(gates.get("_reserve")) and bool(row.citations_private)


async def available(session: AsyncSession, ws: uuid.UUID) -> list[TopicCandidate]:
    """Reserve ideas not already on the list, best first."""
    rows = (
        (
            await session.execute(
                select(TopicCandidate)
                .where(
                    TopicCandidate.workspace_id == ws,
                    TopicCandidate.status == "rejected",
                    TopicCandidate.origin == ORIGIN_SELECTOR_REJECTED,
                )
                .order_by(TopicCandidate.week_start.desc(), TopicCandidate.created_at.desc())
                .limit(SCAN_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    on_the_list = (
        (
            await session.execute(
                select(TopicCandidate).where(
                    TopicCandidate.workspace_id == ws,
                    TopicCandidate.status.in_(LIVE_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    seen: list[TopicCandidate] = list(on_the_list)
    out: list[TopicCandidate] = []
    for row in sorted(
        (r for r in rows if _reserve(r)),
        key=lambda r: (r.week_start, r.rank_score or 0.0),
        reverse=True,
    ):
        # Deduped against the list AND against the ones picked just now, or asking
        # twice in a row hands him the same near-miss twice.
        if find_duplicate(row, seen) is not None:
            continue
        seen.append(row)
        out.append(row)
    return out


async def offer_more(
    session: AsyncSession, ws: uuid.UUID, limit: int = DEFAULT_LIMIT
) -> dict[str, Any]:
    """Move the best reserve ideas onto the list. Returns what he got and why."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    ready = await available(session, ws)
    picked = ready[:limit]
    now = datetime.now(UTC).replace(tzinfo=None)
    for row in picked:
        was = (row.gates or {}).get("_rejection", {}).get("reason") or ""
        row.status = "proposed"
        row.origin = ORIGIN_SELECTOR_RESERVE
        row.updated_at = now
        row.editor_notes = (
            f"Offered when you asked for more ideas on {now:%d %b}. "
            f"It was validated in its own week and set aside: {was}".strip()
        )
    if picked:
        await session.commit()
    return {
        "added": len(picked),
        "remaining": max(0, len(ready) - len(picked)),
        "candidates": [
            {
                "id": str(r.id),
                "title": r.title,
                "lesson": r.lesson,
                "week_start": r.week_start.date().isoformat(),
            }
            for r in picked
        ],
        "detail": _detail(len(picked), len(ready)),
    }


def _detail(added: int, ready: int) -> str:
    if added:
        left = ready - added
        more = f" {left} more where that came from." if left else " That was the last one."
        return f"{added} more idea{'s' if added != 1 else ''} on the list.{more}"
    return (
        "Nothing new to offer. Every idea this week's evidence produced is already on "
        "your list. New ideas need new evidence: the next weekly run collects it."
    )
