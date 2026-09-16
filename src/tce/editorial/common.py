"""Shared helpers for the editorial package: sessions, weeks, JSON views."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.editorial import EditorialFeedback, RecordingPacket, TopicCandidate

SessionSource = Any  # AsyncSession | async_sessionmaker[AsyncSession]

CANDIDATE_STATUSES = ("proposed", "selected", "rejected", "recorded", "published", "withdrawn")
ORIGIN_SELECTOR = "selector"
ORIGIN_SELECTOR_REJECTED = "selector_rejected"
ORIGIN_CALIBRATION = "calibration"


@asynccontextmanager
async def open_session(source: SessionSource) -> AsyncIterator[AsyncSession]:
    """Yield a session from either an AsyncSession or a sessionmaker.

    A passed-in session is not closed here (the caller owns it).
    """
    if isinstance(source, AsyncSession):
        yield source
        return
    async with source() as session:
        yield session


def week_bounds(week_start: date | datetime | str) -> tuple[datetime, datetime]:
    """Naive UTC [start, end) for a week starting at `week_start` (midnight)."""
    if isinstance(week_start, str):
        week_start = date.fromisoformat(week_start[:10])
    if isinstance(week_start, datetime):
        start = datetime(week_start.year, week_start.month, week_start.day)
    else:
        start = datetime(week_start.year, week_start.month, week_start.day)
    return start, start + timedelta(days=7)


def current_week_start(today: date | None = None) -> date:
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def candidate_to_json(
    c: TopicCandidate, feedback: list[EditorialFeedback] | None = None
) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "week_start": _iso(c.week_start),
        "selection_run_id": str(c.selection_run_id) if c.selection_run_id else None,
        "rank": c.rank,
        "rank_score": c.rank_score,
        "title": c.title,
        "lesson": c.lesson,
        "audience": c.audience,
        "reasons_to_care": list(c.reasons_to_care or []),
        "public_angle": c.public_angle,
        "public_safety_notes": c.public_safety_notes,
        "gates": c.gates or {},
        "freshness_role": c.freshness_role,
        "status": c.status,
        "editor_notes": c.editor_notes,
        "moment_ids": list(c.moment_ids or []),
        "citations_private": list(c.citations_private or []),
        "origin": c.origin,
        "prompt_version": c.prompt_version,
        "job_id": str(c.job_id) if c.job_id else None,
        "created_at": _iso(c.created_at),
        "feedback": [feedback_to_json(f) for f in (feedback or [])],
    }


def feedback_to_json(f: EditorialFeedback) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "candidate_id": str(f.candidate_id),
        "kind": f.kind,
        "rating": f.rating,
        "gate": f.gate,
        "note": f.note,
        "preference_version": f.preference_version,
        "created_by": f.created_by,
        "created_at": _iso(f.created_at),
    }


def packet_to_json(p: RecordingPacket) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "candidate_id": str(p.candidate_id),
        "version": p.version,
        "bullets": list(p.bullets or []),
        "script_phrases": list(p.script_phrases or []),
        "facebook_post": p.facebook_post,
        "linkedin_post": p.linkedin_post,
        "interviewer_prompt": p.interviewer_prompt,
        "citations_private": list(p.citations_private or []),
        "public_safety": p.public_safety or {},
        "google_doc_url": p.google_doc_url,
        "google_doc_access": p.google_doc_access,
        "status": p.status,
        "prompt_version": p.prompt_version,
        "job_id": str(p.job_id) if p.job_id else None,
        "created_at": _iso(p.created_at),
    }
