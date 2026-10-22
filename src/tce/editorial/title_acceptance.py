"""A reviewed, source-backed title change for the owner's topic cards.

This is deliberately a user action. Computing a suggested title on a read must
never rewrite a candidate, its edited brief, or a recording packet. The request
names both pieces of text the editor reviewed, and the server checks them again
under a row lock before writing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial import briefs, solution_names
from tce.editorial.news_rules import owner_policy
from tce.models.editorial import TopicCandidate


class TitleAcceptanceError(Exception):
    """A refused acceptance with the same HTTP shape as other editorial errors."""

    def __init__(self, code: str, message: str, *, status: int = 409, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


async def accept_suggested_title(
    db: AsyncSession,
    ws: uuid.UUID,
    candidate_id: uuid.UUID,
    *,
    expected_title: str,
    suggested_title: str,
) -> dict[str, Any]:
    """Change only the title the editor reviewed, with an immutable brief copy.

    The current brief is copied only when its topic still equals the title the
    editor saw. A separately edited topic block must be reviewed on its own and
    is never overwritten by this shortcut.
    """
    if not owner_policy(ws):
        raise TitleAcceptanceError(
            "owner_only", "This title suggestion is available only in the owner's workspace.",
            status=403,
        )

    result = await db.execute(
        select(TopicCandidate)
        .where(TopicCandidate.workspace_id == ws, TopicCandidate.id == candidate_id)
        .with_for_update()
    )
    candidate = result.scalar_one_or_none()
    if candidate is None:
        raise TitleAcceptanceError("not_found", "That topic is not here.", status=404)

    old_title = candidate.title
    if old_title != expected_title:
        raise TitleAcceptanceError(
            "stale_title", "This title changed since you opened it. Nothing was changed.",
            current_title=old_title,
        )

    proposal = solution_names.proposed_solution_title(candidate)
    if proposal is None:
        raise TitleAcceptanceError(
            "suggestion_unavailable",
            "There is no verified solution title to accept for this idea now.",
        )
    actual_suggestion = proposal["title"]
    if actual_suggestion != suggested_title:
        raise TitleAcceptanceError(
            "suggestion_changed",
            "The verified suggestion changed since you opened it. Nothing was changed.",
            current_suggested_title=actual_suggestion,
        )

    current_brief = await briefs.latest_version(db, ws, candidate_id)
    if current_brief is not None and (current_brief.brief or {}).get("topic") != expected_title:
        raise TitleAcceptanceError(
            "brief_title_changed",
            "The topic wording in the room was edited separately. "
            "Review it before changing the title.",
            current_brief_topic=(current_brief.brief or {}).get("topic"),
        )

    accepted_at = datetime.now(UTC).isoformat()
    version = None
    if current_brief is not None:
        updated_brief = dict(current_brief.brief or {})
        updated_brief["topic"] = actual_suggestion
        appended = await briefs.write_version(
            db,
            ws,
            candidate_id,
            brief=updated_brief,
            parent_version=current_brief.version,
            origin="manual",
            created_by="ziv",
            note="Accepted a reviewed, source-backed solution title.",
        )
        version = appended.version

    candidate.title = actual_suggestion
    gates = dict(candidate.gates or {})
    previous_audit = gates.get("_title_acceptances")
    audit = list(previous_audit) if isinstance(previous_audit, list) else []
    audit.append(
        {
            "before": old_title,
            "after": actual_suggestion,
            "accepted_at": accepted_at,
            "solution_label": proposal["solution"]["name"],
            "evidence": proposal["solution"]["evidence"],
        }
    )
    gates["_title_acceptances"] = audit
    candidate.gates = gates
    await db.flush()

    return {
        "candidate_id": str(candidate_id),
        "previous_title": old_title,
        "title": actual_suggestion,
        "suggested_title": actual_suggestion,
        "solution_label": proposal["solution"]["name"],
        "accepted_at": accepted_at,
        "brief_version": version,
    }
