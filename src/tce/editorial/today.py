"""Today: the one screen that answers "what should I do now" in three seconds.

Not a dashboard. A dashboard shows everything and decides nothing; this shows the
single next useful action and the few counts that change what that action is.
Infrastructure health lives behind a status line and only speaks up when it
changes what pressing a button will do.

The ordering of `next_action` is the product decision in this file. It walks the
week backwards from the thing closest to a finished video:

    1. a script is ready and the week has a first slot  -> record it
    2. the week is chosen but has no script yet         -> ask for the script
    3. the week is empty and topics are waiting         -> choose this week
    4. nothing is waiting                               -> find more ideas

Each step is skipped when the thing it needs does not exist, so the action he is
offered is always one he can actually take right now.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial import inbox
from tce.editorial import lineup as lineup_service
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import EditorialChangeSet, TopicDecision

# Upload states that mean "the machine still owes me something".
IN_FLIGHT_UPLOADS = ("uploaded", "transcribing", "planned")


async def _waiting_count(db: AsyncSession, ws: uuid.UUID) -> int:
    """Topics with no decision yet. The number he is actually being asked about."""
    decided = select(TopicDecision.candidate_id).where(TopicDecision.workspace_id == ws)
    result = await db.execute(
        select(func.count(TopicCandidate.id)).where(
            TopicCandidate.workspace_id == ws,
            TopicCandidate.status.notin_(("rejected", "recorded", "published", "withdrawn")),
            TopicCandidate.origin.notin_(inbox.HIDDEN_ORIGINS),
            TopicCandidate.id.notin_(decided),
        )
    )
    return int(result.scalar_one() or 0)


async def _editing_count(db: AsyncSession, ws: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(RecordingUpload.id)).where(
            RecordingUpload.workspace_id == ws,
            RecordingUpload.status.in_(IN_FLIGHT_UPLOADS),
        )
    )
    return int(result.scalar_one() or 0)


async def _pending_reviews(db: AsyncSession, ws: uuid.UUID) -> int:
    """Proposals waiting for a yes or no. An unreviewed change is unfinished work."""
    result = await db.execute(
        select(func.count(EditorialChangeSet.id)).where(
            EditorialChangeSet.workspace_id == ws,
            EditorialChangeSet.state == "proposed",
        )
    )
    return int(result.scalar_one() or 0)


def _next_action(
    *,
    week: dict[str, Any],
    waiting: int,
    pending_reviews: int,
) -> dict[str, Any]:
    primary = week.get("primary") or []
    ready = [row for row in primary if row.get("script_state") == "ready"]

    if pending_reviews:
        return {
            "key": "review_changes",
            "label": "Review proposed changes",
            "detail": (
                f"{pending_reviews} change{'s' if pending_reviews != 1 else ''} "
                "are waiting for your yes or no."
            ),
            "href": "/topics?filter=best",
        }
    if ready:
        return {
            "key": "record",
            "label": "Start recording",
            "detail": f"{ready[0]['title']} is first.",
            "href": "/record",
        }
    if primary:
        missing = len(primary) - len(ready)
        return {
            "key": "prepare_scripts",
            "label": "Prepare this week's scripts",
            "detail": (
                f"{missing} of your {len(primary)} topics still needs a script. "
                "Each one is written on your PC worker."
            ),
            "href": "/week",
        }
    if waiting:
        return {
            "key": "choose_week",
            "label": "Choose this week's topics",
            "detail": f"{waiting} ideas are waiting for a decision.",
            "href": "/topics",
        }
    return {
        "key": "find_ideas",
        "label": "Find more ideas",
        "detail": "Nothing is waiting. Every idea this week's evidence produced is decided.",
        "href": "/topics",
    }


async def build(db: AsyncSession, ws: uuid.UUID, *, sessionmaker: Any = None) -> dict[str, Any]:
    """The Today payload.

    `worker` is reported honestly and separately: it is the difference between
    "ask for a script and wait two minutes" and "ask for a script and wait until
    the desktop wakes up", and hiding that turns a slow answer into a broken one.
    """
    week_start = lineup_service.week_start_for(None)
    lineup = await lineup_service.get_lineup(db, ws, week_start)
    week = (
        await lineup_service.lineup_to_json(db, ws, lineup)
        if lineup is not None
        else {
            "lineup_id": None,
            "week_start": week_start.date().isoformat(),
            "revision": 0,
            "primary": [],
            "reserve": [],
            "mix": "",
            "ready_count": 0,
            "primary_slots": lineup_service.DEFAULT_PRIMARY_SLOTS,
            "status": "draft",
        }
    )

    waiting = await _waiting_count(db, ws)
    editing = await _editing_count(db, ws)
    pending_reviews = await _pending_reviews(db, ws)

    worker: dict[str, Any] = {}
    if sessionmaker is not None:
        try:
            from tce.api.routers.content_runs import worker_availability

            worker = await worker_availability(sessionmaker)
        except Exception:  # pragma: no cover - never let a status probe break Today
            worker = {}

    return {
        "week": week,
        "next_action": _next_action(
            week=week, waiting=waiting, pending_reviews=pending_reviews
        ),
        # Only counts that change what he would do next.
        "attention": {
            "waiting": waiting,
            "scripts_ready": week.get("ready_count", 0),
            "editing": editing,
            "pending_reviews": pending_reviews,
        },
        "worker": {
            "online": bool(worker.get("online")),
            # Shown only when it is false, so a healthy engine stays silent.
            "detail": worker.get("detail") or "",
        },
    }
