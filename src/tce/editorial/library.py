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
from pathlib import Path
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial.common import ORIGIN_TECHNICAL_VALIDATION
from tce.models.editorial import (
    RecordingPacket,
    RecordingUpload,
    TopicCandidate,
    VideoPublication,
)
from tce.models.editorial_workspace import (
    EDIT_REQUEST_SCOPES,
    EditingRequest,
)

# Library filters, in the order the chips are shown. Each maps to upload states.
# 28-Sep: "Still to do" is the list the page opens on - everything not yet out and
# not archived - and published videos have their own chip instead of crowding it.
LIBRARY_FILTERS: dict[str, tuple[str, ...]] = {
    "todo": (),
    "uploading": ("uploaded",),
    "editing": ("transcribing", "transcribed", "proofreading", "planned", "rendering"),
    "needs_review": ("needs_review",),
    "ready": ("edited",),
    "published": (),
    "all": (),
    "archived": (),
}

# A post in one of these states has gone out, or will without anyone touching it.
_OUT_STATUSES = ("posted", "scheduled")

_LIVE_STATUSES = ("transcribing", "transcribed", "proofreading", "planned", "rendering")

FILTER_LABELS = {
    "todo": "Still to do",
    "uploading": "Uploading",
    "editing": "Being edited",
    "needs_review": "Needs your review",
    "ready": "Ready",
    "published": "Published",
    "all": "Everything",
    "archived": "Archived",
}

# What each stored state means in his words, not the pipeline's.
STATE_SENTENCES = {
    "uploaded": "On the server. Nothing has been done to it yet.",
    "transcribing": "Being transcribed.",
    "transcribed": "Transcribed. Proofreading and the cut come next.",
    "proofreading": "Being proofread on your subscription.",
    "rendering": "Being cut and captioned.",
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


def technical_candidate_ids(ws: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """The topics of synthetic takes that prove the pipeline works, as a subquery.

    Not something he recorded, so it never sits in his library, and nothing that
    counts his recordings (Today's "being edited", whether a topic is filmed) may
    count it either. One definition, so those counts cannot drift from the list.
    """
    return select(TopicCandidate.id).where(
        TopicCandidate.workspace_id == ws,
        TopicCandidate.origin == ORIGIN_TECHNICAL_VALIDATION,
    )


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
    if upload.edited_path and upload.transcript and upload.status not in _LIVE_STATUSES:
        # 28-Sep: the tight cut and the word-box captions, for an edit made before them.
        actions.append({"key": "edit_again", "label": "Edit it again"})
    if open_requests:
        actions.append(
            {
                "key": "open_requests",
                "label": f"{open_requests} open request{'s' if open_requests != 1 else ''}",
            }
        )
    actions.append({"key": "re_record", "label": "Record it again"})
    return actions


PUBLISH_ORDER = ("instagram", "facebook", "youtube", "linkedin")
PUBLISH_LABELS = {
    "instagram": "Instagram Reel",
    "facebook": "Facebook Page",
    "youtube": "YouTube Short",
    "linkedin": "LinkedIn",
}


def _publishing_json(pubs: dict[str, VideoPublication]) -> list[dict[str, Any]]:
    """The four posts, in a fixed order; empty until they are written."""
    if not pubs:
        return []
    out = []
    for platform in PUBLISH_ORDER:
        pub = pubs.get(platform)
        if pub is None:
            continue
        out.append(
            {
                "platform": platform,
                "label": PUBLISH_LABELS[platform],
                "status": pub.status,
                "copy": pub.copy or {},
                "url": pub.url,
                "detail": pub.detail,
                "scheduled_for": pub.scheduled_for.isoformat() if pub.scheduled_for else None,
                "posted_at": pub.posted_at.isoformat() if pub.posted_at else None,
            }
        )
    return out


def _has_preview(upload: RecordingUpload) -> bool:
    """The light copy the player streams exists and is not older than the edit."""
    if not upload.edited_path:
        return False
    edited = Path(upload.edited_path)
    light = edited.with_name(f"{edited.stem}-preview{edited.suffix}")
    try:
        return light.exists() and light.stat().st_mtime >= edited.stat().st_mtime
    except OSError:
        return False


REVIEW_SENTENCES = {
    "waiting": "Your editor has not answered yet, so this edit used the rules. "
    "It edits itself again when the review lands.",
    "unavailable": "Your editor could not review this one, so the rules decided what to cut.",
    "rules": "Your editor's answer was not usable, so the rules decided what to cut.",
    "blocked": "Your editor's review wants a cut that would change what you said, so the "
    "edit you have stays. Edit it again to see the review's cut and decide.",
    "stale": "You changed the words after your editor started reading, so that review was "
    "not used. Edit it again for a fresh one.",
}


def _removed(upload: RecordingUpload) -> list[dict[str, Any]]:
    """What the edit took out besides pauses, so nothing disappears unseen (28-Sep)."""
    plan = upload.edit_plan or {}
    return [
        {
            "start": r.get("start"),
            "text": str(r.get("text") or "")[:160],
            "reason": r.get("reason"),
            "why": r.get("why"),
        }
        for r in (plan.get("removed") or [])[:30]
    ]


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
    result = await db.execute(
        select(RecordingUpload)
        .where(
            RecordingUpload.workspace_id == ws,
            RecordingUpload.candidate_id.notin_(technical_candidate_ids(ws)),
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
        # A topic he recorded a receipt for by hand is out, whichever take it was.
        rows = await db.execute(
            select(TopicCandidate.id).where(
                TopicCandidate.workspace_id == ws,
                TopicCandidate.id.in_(candidate_ids),
                TopicCandidate.status == "published",
            )
        )
        out_candidates = {row[0] for row in rows.all()}
    else:
        out_candidates = set()

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
        select(EditingRequest)
        .where(EditingRequest.workspace_id == ws)
        .order_by(EditingRequest.created_at.asc())
    )
    open_by_upload: dict[uuid.UUID, int] = {}
    last_by_upload: dict[uuid.UUID, EditingRequest] = {}
    for req in requests.scalars().all():
        last_by_upload[req.upload_id] = req
        if req.state in ("open", "in_progress"):
            open_by_upload[req.upload_id] = open_by_upload.get(req.upload_id, 0) + 1

    # 26-Sep: the posts for each edited video, and whether they went out.
    pubs = await db.execute(select(VideoPublication).where(VideoPublication.workspace_id == ws))
    pubs_by_upload: dict[uuid.UUID, dict[str, VideoPublication]] = {}
    for pub in pubs.scalars().all():
        pubs_by_upload.setdefault(pub.upload_id, {})[pub.platform] = pub

    # 28-Sep: a video is published once any of its posts went out or is scheduled.
    # The other takes of that topic are finished with it, so they leave "Still to do"
    # too rather than sitting there for ever.
    out_uploads = {
        upload_id
        for upload_id, by_platform in pubs_by_upload.items()
        if any(p.status in _OUT_STATUSES for p in by_platform.values())
    }
    out_candidates |= {u.candidate_id for u in uploads if u.id in out_uploads and u.candidate_id}

    def is_published(upload: RecordingUpload) -> bool:
        return upload.id in out_uploads or upload.candidate_id in out_candidates

    wanted = LIBRARY_FILTERS[filter_key]
    # "I need a way to find the edited video" (25-Sep): a replaced take is kept on
    # the server for history, never shown, and an edit sits above the raw takes.
    uploads = [u for u in uploads if u.status != "superseded"]
    # 27-Sep: archived recordings live only under the Archived filter.
    if filter_key == "archived":
        uploads = [u for u in uploads if u.archived_at is not None]
    else:
        uploads = [u for u in uploads if u.archived_at is None]
    uploads.sort(key=lambda u: not u.edited_path)
    items: list[dict[str, Any]] = []
    for upload in uploads:
        if wanted and upload.status not in wanted:
            continue
        published = is_published(upload)
        if filter_key == "published" and not published:
            continue
        if published and filter_key not in ("published", "all", "archived"):
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
                # While a step runs, say exactly what it is doing (3-second rule).
                "state_sentence": (
                    upload.status_detail
                    if upload.status in _LIVE_STATUSES and upload.status_detail
                    else STATE_SENTENCES.get(upload.status, upload.status_detail or "")
                ),
                # What the subscription proofread changed, so no word moves unseen.
                "proofread": list((upload.edit_plan or {}).get("proofread") or []),
                "removed": _removed(upload),
                # 30-Sep: words the phone cut short ("cou" for "course"); no cut can fix them.
                "phone_cut": list((upload.edit_plan or {}).get("phone_cut") or []),
                "review_note": REVIEW_SENTENCES.get(
                    str(((upload.edit_plan or {}).get("review") or {}).get("state") or "")
                ),
                "has_preview": _has_preview(upload),
                # 30-Sep: the render he would be watching; the player puts it on the address.
                "render_ref": upload.render_ref if upload.edited_path else None,
                "publishing": _publishing_json(pubs_by_upload.get(upload.id, {})),
                "last_request": (
                    edit_request_to_json(last_by_upload[upload.id])
                    if upload.id in last_by_upload
                    else None
                ),
                "packet_id": str(upload.packet_id) if upload.packet_id else None,
                "packet_version": packet_versions.get(upload.packet_id),
                "has_edit": bool(upload.edited_path),
                "archived": upload.archived_at is not None,
                "published": published,
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


async def set_archived(
    db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID, archived: bool
) -> RecordingUpload:
    """Archive or bring back a recording. Nothing is deleted either way."""
    upload = await _get_upload(db, ws, upload_id)
    upload.archived_at = datetime.now(UTC).replace(tzinfo=None) if archived else None
    await db.flush()
    return upload


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
