"""Shared helpers for the editorial package: sessions, weeks, JSON views."""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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


# The editorial week is Monday 00:00 to Monday 00:00 in Israel time. Candidate rows keep
# the week as a naive calendar label (Monday 7 Sep stays datetime(2026, 9, 7)); only
# evidence filtering converts that label into a real UTC window.
WEEK_TIMEZONE = "Asia/Jerusalem"


def _week_label_date(week_start: date | datetime | str) -> date:
    if isinstance(week_start, str):
        return date.fromisoformat(week_start[:10])
    if isinstance(week_start, datetime):
        return week_start.date()
    return week_start


def week_bounds(week_start: date | datetime | str) -> tuple[datetime, datetime]:
    """Naive calendar LABEL [start, end) for the week (midnight, no timezone).

    This is the storage/API key for candidates (`TopicCandidate.week_start`). It is not
    an instant: use `week_source_window` to decide which evidence fell inside the week.
    """
    d = _week_label_date(week_start)
    start = datetime(d.year, d.month, d.day)
    return start, start + timedelta(days=7)


def week_source_window(week_start: date | datetime | str) -> tuple[datetime, datetime]:
    """Naive UTC [start, end) instants of the week in WEEK_TIMEZONE, DST-aware.

    Monday 2026-09-07 -> 2026-09-06T21:00Z <= t < 2026-09-13T21:00Z (IDT, UTC+3);
    a winter Monday starts at 22:00Z the day before (IST, UTC+2).
    """
    d = _week_label_date(week_start)
    tz = ZoneInfo(WEEK_TIMEZONE)
    end_d = d + timedelta(days=7)
    local_start = datetime(d.year, d.month, d.day, tzinfo=tz)
    local_end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=tz)
    return (
        local_start.astimezone(UTC).replace(tzinfo=None),
        local_end.astimezone(UTC).replace(tzinfo=None),
    )


def current_week_start(today: date | None = None) -> date:
    today = today or datetime.now(ZoneInfo(WEEK_TIMEZONE)).date()
    return today - timedelta(days=today.weekday())


# ---------------------------------------------------------------------------
# Durable job headers
# ---------------------------------------------------------------------------
# Editorial prompts start with plain header lines. They let a restarted process find
# which week / shard / packet request an llm_jobs row belongs to and rebuild its
# idempotency key, so an interrupted request resumes the SAME job instead of
# enqueueing a duplicate.

_WEEK_HEADER = re.compile(r"^WEEK STARTING: (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
_SHARD_HEADER = re.compile(r"^SELECTION SHARD: (\d+)/(\d+)\s*$", re.MULTILINE)
_MAX_HEADER = re.compile(r"^RETURN AT MOST (\d+) ", re.MULTILINE)
_PACKET_HEADER = re.compile(r"^PACKET REQUEST: ([0-9a-fA-F-]{36})\s*$", re.MULTILINE)
_MOMENT_ID = re.compile(r'"moment_id": "([0-9a-fA-F-]{36})"')


def job_prompt_text(request_json: dict[str, Any] | None) -> str:
    messages = (request_json or {}).get("messages") or []
    if not messages:
        return ""
    content = messages[0].get("content") if isinstance(messages[0], dict) else ""
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return str(content or "")


def selection_key_text(
    workspace_id: uuid.UUID | str,
    run_id: uuid.UUID | str,
    shard: int | None = None,
    shards: int | None = None,
) -> str:
    """Idempotency key text for one selection job. `shard=None` is the v1 single job."""
    base = f"editorial_selection:{workspace_id}:{run_id}"
    return base if shard is None else f"{base}:shard:{shard}/{shards}"


def packet_key_text(workspace_id: uuid.UUID | str, nonce: uuid.UUID | str) -> str:
    return f"recording_packet:{workspace_id}:{nonce}"


def parse_selection_header(prompt: str) -> dict[str, Any] | None:
    week = _WEEK_HEADER.search(prompt)
    if not week:
        return None
    shard = _SHARD_HEADER.search(prompt)
    most = _MAX_HEADER.search(prompt)
    return {
        "week_start": week.group(1),
        # v1 jobs had no shard line: one job covered the whole pool
        "shard": int(shard.group(1)) if shard else None,
        "shards": int(shard.group(2)) if shard else 1,
        "max_candidates": int(most.group(1)) if most else None,
        "moment_ids": list(dict.fromkeys(_MOMENT_ID.findall(prompt))),
    }


def parse_packet_header(prompt: str) -> str | None:
    m = _PACKET_HEADER.search(prompt)
    return m.group(1) if m else None


def replay_request(job: Any, key_text: str) -> Any:
    """Rebuild the LLMRequest of a stored job so `complete()` finds that same row.

    Returns None unless both the stored idempotency key and input hash match exactly;
    a mismatch would otherwise enqueue a new job or raise an idempotency conflict.
    """
    from tce.llm import LLMRequest
    from tce.llm.provider import compute_idempotency_key, compute_input_hash

    request = job.request_json or {}
    req = LLMRequest(
        job_type=job.job_type,
        agent_name=job.agent_name,
        messages=list(request.get("messages") or []),
        system=request.get("system"),
        output_schema=request.get("output_schema"),
        max_tokens=int(request.get("max_tokens") or 4096),
        requested_model=job.requested_model,
        prompt_version=job.prompt_version,
        workspace_id=job.workspace_id,
        run_id=job.run_id,
        idempotency_key=key_text,
    )
    if not req.messages:
        return None
    if compute_idempotency_key(req) != job.idempotency_key:
        return None
    if compute_input_hash(req) != job.input_hash:
        return None
    return req


def job_can_requeue(job: Any) -> bool:
    """Whether the queue will accept `requeue_failed=True` for this failed job."""
    from tce.llm.queue import MAX_REQUEUES_OF_FAILED, NON_RETRYABLE_ERRORS

    if job.status != "failed" or job.error_code in NON_RETRYABLE_ERRORS:
        return False
    return int((job.request_json or {}).get("requeue_count") or 0) < MAX_REQUEUES_OF_FAILED


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
