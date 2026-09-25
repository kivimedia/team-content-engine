"""The library: recorded work, and the changes he wants made to it.

Recorded videos used to live in a collapsed `<details>` at the bottom of a long
scroll, which meant a man who had just recorded something could not find it. This
gives them a place.

One rule runs through the whole module, and it is the one the old surface already
got right: **only render an action that leads somewhere.** No captions button
before captions exist, no "watch the edit" before there is an edit. A button that
does nothing is worse than an absent one, because he taps it while walking.

Second rule, from the plan: the raw recording is never replaced. An edit is a new
file beside it, and an editing request is a record of what was asked, not a
mutation of what was captured.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial.common import ORIGIN_TECHNICAL_VALIDATION
from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import (
    EDIT_REQUEST_SCOPES,
    EditingRequest,
)

# Library filters, in the order the chips are shown. Each maps to upload states.
LIBRARY_FILTERS: dict[str, tuple[str, ...]] = {
    "all": (),
    "uploading": ("uploaded",),
    "editing": ("transcribing", "planned"),
    "needs_review": ("needs_review",),
    "ready": ("edited",),
}

FILTER_LABELS = {
    "all": "Everything",
    "uploading": "Uploading",
    "editing": "Being edited",
    "needs_review": "Needs your review",
    "ready": "Ready",
}

# What each stored state means in his words, not the pipeline's.
STATE_SENTENCES = {
    "uploaded": "On the server. Nothing has been done to it yet.",
    "transcribing": "Being transcribed.",
    "planned": "The cut is planned and waiting to be rendered.",
    "needs_review": "The cut would change what you said. It needs your eyes.",
    "edited": "Edited and ready.",
    "failed": "Something went wrong. The original recording is safe.",
}


class LibraryError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


async def _get_upload(
    db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID
) -> RecordingUpload:
    result = await db.execute(
        select(RecordingUpload).where(
            RecordingUpload.workspace_id == ws, RecordingUpload.id == upload_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise LibraryError("not_found", "that recording is not here", status=404)
    return row


def _actions(upload: RecordingUpload, open_requests: int) -> list[dict[str, str]]:
    """Only actions with a real destination.

    Ordered by what he most likely wants: watch it, then change it, then start
    again. `re_record` is last because it is the expensive one.
    """
    actions: list[dict[str, str]] = []
    if upload.edited_path:
        actions.append({"key": "watch_edit", "label": "Watch the edit"})
    if upload.storage_path:
        actions.append(
            {
                "key": "watch_raw",
                "label": "Watch the original" if upload.edited_path else "Watch it",
            }
        )
    if upload.captions_path:
        actions.append({"key": "captions", "label": "Captions"})
    if upload.transcript:
        actions.append({"key": "transcript", "label": "Transcript"})
    actions.append({"key": "request_edit", "label": "Request an editing change"})
    if open_requests:
        actions.append(
            {
                "key": "open_requests",
                "label": f"{open_requests} open request{'s' if open_requests != 1 else ''}",
            }
        )
    actions.append({"key": "re_record", "label": "Record it again"})
    return actions


def _issues(upload: RecordingUpload) -> list[str]:
    """Problems the pipeline found, in plain words. Empty when there are none."""
    plan = upload.edit_plan or {}
    check = plan.get("meaning_check") or {}
    if check.get("status") == "blocked":
        return [str(i) for i in (check.get("issues") or [])] or [
            "The planned cut would change what you said."
        ]
    return []


async def list_library(
    db: AsyncSession, ws: uuid.UUID, *, filter_key: str = "all"
) -> dict[str, Any]:
    if filter_key not in LIBRARY_FILTERS:
        raise LibraryError("bad_filter", f"unknown filter {filter_key}", status=400)

    # A synthetic take proving the pipeline works is not something he recorded,
    # and it must not sit in his library looking like one. The older /recorded
    # endpoint has always excluded these; the library is the surface replacing it,
    # so it has to agree rather than quietly re-introduce the artifact.
    technical = select(TopicCandidate.id).where(
        TopicCandidate.workspace_id == ws,
        TopicCandidate.origin == ORIGIN_TECHNICAL_VALIDATION,
    )
    result = await db.execute(
        select(RecordingUpload)
        .where(
            RecordingUpload.workspace_id == ws,
            RecordingUpload.candidate_id.notin_(technical),
        )
        .order_by(RecordingUpload.created_at.desc())
    )
    uploads = list(result.scalars().all())
    if not uploads:
        return {
            "filter": filter_key,
            "filter_label": FILTER_LABELS[filter_key],
            "filters": [{"key": k, "label": FILTER_LABELS[k]} for k in LIBRARY_FILTERS],
            "items": [],
            "total": 0,
        }

    candidate_ids = [u.candidate_id for u in uploads if u.candidate_id]
    titles: dict[uuid.UUID, str] = {}
    if candidate_ids:
        rows = await db.execute(
            select(TopicCandidate.id, TopicCandidate.title).where(
                TopicCandidate.workspace_id == ws, TopicCandidate.id.in_(candidate_ids)
            )
        )
        titles = {row[0]: row[1] for row in rows.all()}

    packet_ids = [u.packet_id for u in uploads if u.packet_id]
    packet_versions: dict[uuid.UUID, int] = {}
    if packet_ids:
        rows = await db.execute(
            select(RecordingPacket.id, RecordingPacket.version).where(
                RecordingPacket.workspace_id == ws, RecordingPacket.id.in_(packet_ids)
            )
        )
        packet_versions = {row[0]: row[1] for row in rows.all()}

    requests = await db.execute(
        select(EditingRequest).where(
            EditingRequest.workspace_id == ws,
            EditingRequest.state.in_(("open", "in_progress")),
        )
    )
    open_by_upload: dict[uuid.UUID, int] = {}
    for req in requests.scalars().all():
        open_by_upload[req.upload_id] = open_by_upload.get(req.upload_id, 0) + 1

    wanted = LIBRARY_FILTERS[filter_key]
    # "I need a way to find the edited video" (25-Sep): a replaced take is kept on
    # the server for history, never shown, and an edit sits above the raw takes.
    uploads = [u for u in uploads if u.status != "superseded"]
    uploads.sort(key=lambda u: not u.edited_path)
    items: list[dict[str, Any]] = []
    for upload in uploads:
        if wanted and upload.status not in wanted:
            continue
        open_count = open_by_upload.get(upload.id, 0)
        items.append(
            {
                "upload_id": str(upload.id),
                "candidate_id": str(upload.candidate_id) if upload.candidate_id else None,
                "title": titles.get(upload.candidate_id, "(untitled recording)"),
                "recorded_at": upload.created_at.isoformat() if upload.created_at else None,
                "duration_s": upload.duration_s,
                "status": upload.status,
                "state_sentence": STATE_SENTENCES.get(
                    upload.status, upload.status_detail or ""
                ),
                "packet_id": str(upload.packet_id) if upload.packet_id else None,
                "packet_version": packet_versions.get(upload.packet_id),
                "has_edit": bool(upload.edited_path),
                "has_captions": bool(upload.captions_path),
                "has_transcript": bool(upload.transcript),
                "issues": _issues(upload),
                "open_requests": open_count,
                "actions": _actions(upload, open_count),
            }
        )

    return {
        "filter": filter_key,
        "filter_label": FILTER_LABELS[filter_key],
        "filters": [{"key": k, "label": FILTER_LABELS[k]} for k in LIBRARY_FILTERS],
        "items": items,
        "total": len(items),
    }


# ---------------------------------------------------------------------------
# Editing requests
# ---------------------------------------------------------------------------


async def create_edit_request(
    db: AsyncSession,
    ws: uuid.UUID,
    upload_id: uuid.UUID,
    *,
    request: str,
    scope: str = "whole",
    start_s: float | None = None,
    end_s: float | None = None,
    section_ref: str | None = None,
    created_by: str | None = None,
) -> EditingRequest:
    if scope not in EDIT_REQUEST_SCOPES:
        raise LibraryError("bad_scope", f"unknown scope {scope}", status=400)
    if not request.strip():
        raise LibraryError("empty", "say what you want changed", status=400)
    if scope == "timestamp" and (start_s is None or end_s is None):
        raise LibraryError(
            "bad_range", "a timestamp request needs a start and an end", status=400
        )
    if scope == "timestamp" and start_s is not None and end_s is not None and end_s <= start_s:
        raise LibraryError("bad_range", "the end must come after the start", status=400)

    upload = await _get_upload(db, ws, upload_id)
    row = EditingRequest(
        workspace_id=ws,
        upload_id=upload.id,
        candidate_id=upload.candidate_id,
        packet_id=upload.packet_id,
        scope=scope,
        start_s=start_s,
        end_s=end_s,
        section_ref=section_ref,
        request=request.strip(),
        state="open",
        created_by=created_by,
    )
    db.add(row)
    await db.flush()
    return row


async def list_edit_requests(
    db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID
) -> list[EditingRequest]:
    result = await db.execute(
        select(EditingRequest)
        .where(
            EditingRequest.workspace_id == ws,
            EditingRequest.upload_id == upload_id,
        )
        .order_by(EditingRequest.created_at.asc())
    )
    return list(result.scalars().all())


async def resolve_edit_request(
    db: AsyncSession,
    ws: uuid.UUID,
    request_id: uuid.UUID,
    *,
    state: str,
    result: dict[str, Any] | None = None,
) -> EditingRequest:
    row = await db.execute(
        select(EditingRequest).where(
            EditingRequest.workspace_id == ws, EditingRequest.id == request_id
        )
    )
    found = row.scalar_one_or_none()
    if found is None:
        raise LibraryError("not_found", "that request is not here", status=404)
    found.state = state
    found.result = result
    if state in ("done", "rejected"):
        found.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    await db.flush()
    return found


def edit_request_to_json(row: EditingRequest) -> dict[str, Any]:
    where = "the whole video"
    if row.scope == "timestamp" and row.start_s is not None:
        where = f"{_clock(row.start_s)} to {_clock(row.end_s or row.start_s)}"
    elif row.scope == "section" and row.section_ref:
        where = row.section_ref
    return {
        "id": str(row.id),
        "upload_id": str(row.upload_id),
        "scope": row.scope,
        "where": where,
        "start_s": row.start_s,
        "end_s": row.end_s,
        "section_ref": row.section_ref,
        "request": row.request,
        "state": row.state,
        "result": row.result,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


def _clock(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"
