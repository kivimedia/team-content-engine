"""Today: the one screen that answers "what should I do now" in three seconds.

Not a dashboard. A dashboard shows everything and decides nothing; this shows the
single next useful action and the few counts that change what that action is.
Infrastructure health lives behind a status line and only speaks up when it
changes what pressing a button will do.

The ordering of `next_action` is the product decision in this file. It walks the
week backwards from the thing closest to a finished video:

    1. a script is ready and the week has a first slot  -> record it
    2. the week is chosen but has no script yet         -> ask for the script
       (every missing one already asked for             -> say when they come)
    3. the week is empty and topics are waiting         -> choose this week
    4. nothing is waiting                               -> find more ideas

Each step is skipped when the thing it needs does not exist, so the action he is
offered is always one he can actually take right now.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial import inbox
from tce.editorial import lineup as lineup_service
from tce.editorial.library import LIBRARY_FILTERS, technical_candidate_ids
from tce.editorial.status import israel_time
from tce.models.editorial import RecordingUpload
from tce.models.editorial_workspace import EditorialChangeSet


async def _waiting_count(db: AsyncSession, ws: uuid.UUID) -> int:
    """The number the Topics page shows under Best matches, taken from that page.

    27-Sep: Today said 18 and Topics said 25, because each had its own query. The
    card links to that list, so it counts that list and nothing else.
    """
    listing = await inbox.list_topics(db, ws, filter_key="best", limit=1)
    return int(listing["total"])


async def _editing_count(db: AsyncSession, ws: uuid.UUID) -> int:
    """The number the Library shows under "Being edited", counted the way that list is.

    28-Sep: Today said 12 being edited while nothing was. It counted "uploaded", a
    take resting on the server with nothing run on it (the Library lists those
    under Uploading), and archived and synthetic takes the Library never shows.
    The card opens that list, so it counts that list: its states, read from the
    Library itself, without archived takes or the pipeline's own test takes.
    """
    result = await db.execute(
        select(func.count(RecordingUpload.id)).where(
            RecordingUpload.workspace_id == ws,
            RecordingUpload.status.in_(LIBRARY_FILTERS["editing"]),
            RecordingUpload.archived_at.is_(None),
            RecordingUpload.candidate_id.notin_(technical_candidate_ids(ws)),
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
    # A topic he has filmed stays in the week, so the week shows what he did, but
    # it is done (28-Sep): never offered for recording again, and never counted
    # as still needing a script.
    primary = [row for row in week.get("primary") or [] if not row.get("filmed")]
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
            # Straight to the idea, not to the list he already chose from. The
            # studio takes `?candidate=` and opens it.
            "href": f"/record?candidate={ready[0]['candidate_id']}",
        }
    if primary:
        # A script already asked for finishes by itself (28-Sep-2026: asked
        # during his Claude limit, it said "prepare" while it waited two days).
        coming = [
            row
            for row in primary
            if row.get("script_state") != "ready"
            and (row.get("script_request") or {}).get("pending")
        ]
        missing = len(primary) - len(ready) - len(coming)
        one = len(coming) == 1
        if missing:
            return {
                "key": "prepare_scripts",
                "label": "Prepare this week's scripts",
                "detail": (
                    f"{missing} of your {len(primary)} topics still needs a script. "
                    + (
                        f"{len(coming)} more {'is' if one else 'are'} on the way and "
                        f"{'saves itself' if one else 'save themselves'}. "
                        if coming
                        else ""
                    )
                    + "Each one is written on your PC worker."
                ),
                "href": "/week",
            }
        resets = [
            datetime.fromisoformat(row["script_request"]["retry_at"].rstrip("Z"))
            for row in coming
            if row["script_request"].get("state") == "waiting_capacity"
            and row["script_request"].get("retry_at")
        ]
        if resets:
            detail = (
                f"{'Your script waits' if one else f'{len(coming)} scripts wait'} for your "
                f"Claude limit to reset on {israel_time(max(resets))}. "
                f"{'It is' if one else 'They are'} written then and "
                f"{'saves itself' if one else 'save themselves'}; nothing to ask again."
            )
        else:
            detail = (
                f"{'Your script is' if one else f'{len(coming)} scripts are'} being written on "
                f"your PC worker and {'saves itself' if one else 'save themselves'}; "
                "nothing to do until then."
            )
        return {
            "key": "scripts_coming",
            "label": "Your script is on the way" if one else "Your scripts are on the way",
            "detail": detail,
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
    # The probe opens a session of its own. It runs before this session writes
    # anything below: where both share one connection (the in-memory test
    # database) its close would roll back the week's first read.
    worker: dict[str, Any] = {}
    if sessionmaker is not None:
        try:
            from tce.api.routers.content_runs import worker_availability

            worker = await worker_availability(sessionmaker)
        except Exception:  # pragma: no cover - never let a status probe break Today
            worker = {}

    # 28-Sep: "0 scripts ready" on the Monday the week turned over, with eight
    # chosen topics not filmed yet. This week's list is read the one way that
    # brings last week's unrecorded topics into it; the caller commits that.
    lineup = await lineup_service.current_lineup(db, ws)
    week = await lineup_service.lineup_to_json(db, ws, lineup)

    waiting = await _waiting_count(db, ws)
    editing = await _editing_count(db, ws)
    pending_reviews = await _pending_reviews(db, ws)

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
