"""Bridges between the editorial candidate pool and the legacy planner agents.

weekly_planner and story_strategist keep their JSON output shapes (KMHub and
km-worker consume them through the pipeline API) but source topics from
evidence-backed TopicCandidates when those exist for the workspace and week.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial.common import ORIGIN_SELECTOR_REJECTED, current_week_start, week_bounds
from tce.models.editorial import TopicCandidate

PLANNABLE_STATUSES = ("selected", "proposed")


def planner_candidate_view(c: TopicCandidate) -> dict[str, Any]:
    """Public-safe view for planner prompts: no excerpts, no private links."""
    return {
        "candidate_id": str(c.id),
        "status": c.status,
        "rank": c.rank,
        "title": c.title,
        "lesson": c.lesson,
        "audience": c.audience,
        "public_angle": c.public_angle,
        "reasons_to_care": list(c.reasons_to_care or []),
        "public_safety_notes": c.public_safety_notes,
        "freshness_role": c.freshness_role,
        "claim_types": sorted(
            {
                str(ci.get("claim_type"))
                for ci in (c.citations_private or [])
                if ci.get("claim_type")
            }
        ),
        "moment_ids": list(c.moment_ids or []),
    }


async def load_week_candidates(
    db: AsyncSession | None,
    workspace_id: uuid.UUID | str | None,
    week_start: date | datetime | str | None = None,
    *,
    limit: int = 7,
) -> list[dict[str, Any]]:
    """Selected first, then proposed, by rank. Empty when unavailable."""
    if db is None or not workspace_id:
        return []
    try:
        ws = workspace_id if isinstance(workspace_id, uuid.UUID) else uuid.UUID(str(workspace_id))
    except ValueError:
        return []
    start, _ = week_bounds(week_start or current_week_start())
    try:
        # savepoint so a missing table cannot abort the caller's transaction
        async with db.begin_nested():
            rows = (
                (
                    await db.execute(
                        select(TopicCandidate).where(
                            TopicCandidate.workspace_id == ws,
                            TopicCandidate.week_start == start,
                            TopicCandidate.status.in_(PLANNABLE_STATUSES),
                            TopicCandidate.origin != ORIGIN_SELECTOR_REJECTED,
                        )
                    )
                )
                .scalars()
                .all()
            )
    except Exception:
        # editorial tables not migrated in this environment: legacy behaviour
        return []
    rows = sorted(
        rows,
        key=lambda c: (0 if c.status == "selected" else 1, c.rank if c.rank is not None else 999),
    )
    return [planner_candidate_view(c) for c in rows[:limit]]
