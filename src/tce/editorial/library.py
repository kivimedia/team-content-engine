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

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
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
    EditSession,
)
from tce.production import autoedit
from tce.production.retakes import edit_length, frame_keep, map_to_edit, map_to_source

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
    def __init__(
        self, code: str, message: str, *, status: int = 409, extra: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        # More for the caller than the sentence: the render the player should be on,
        # the read-back as it is now.
        self.extra = extra or {}


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


async def get_upload(db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID) -> RecordingUpload:
    return await _get_upload(db, ws, upload_id)


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
    waiting_by_upload: dict[uuid.UUID, int] = {}
    for req in requests.scalars().all():
        if req.session_id is not None and req.state in (*WAITING_NOTE_STATES, "rejected"):
            # 30-Sep: a note in a sitting waits for "make it"; it is not a request the
            # editor is working on, and a note he took back is not one at all.
            if req.state != "rejected":
                waiting_by_upload[req.upload_id] = waiting_by_upload.get(req.upload_id, 0) + 1
            continue
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
                # Notes given in a sitting that wait for "Make the new version".
                "waiting_notes": waiting_by_upload.get(upload.id, 0),
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
    sitting: EditSession | None = None,
) -> EditingRequest:
    """A typed request. With `sitting` (he is giving notes on this video) it joins that
    sitting as a held note instead of running on its own: one re-render at the end."""
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
    if scope == "moment" and start_s is None:
        raise LibraryError("bad_range", "a note at a moment needs the second it is at", status=400)

    upload = await _get_upload(db, ws, upload_id)
    source_s = None
    if sitting is not None and start_s is not None and sitting.keep_snapshot:
        source_s = map_to_source(float(start_s), sitting.keep_snapshot)
    row = EditingRequest(
        workspace_id=ws,
        upload_id=upload.id,
        candidate_id=upload.candidate_id,
        packet_id=upload.packet_id,
        session_id=sitting.id if sitting is not None else None,
        scope=scope,
        start_s=start_s,
        end_s=None if scope == "moment" else end_s,
        source_s=round(source_s, 3) if source_s is not None else None,
        section_ref=section_ref,
        request=request.strip(),
        state="held" if sitting is not None else "open",
        created_by=created_by,
    )
    if sitting is not None:
        # Like a pin, to the microsecond: the batch reads the notes in the order he gave
        # them, and a later note wins over an earlier one.
        row.created_at = _now()
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
    elif row.scope == "moment" and row.start_s is not None:
        where = f"at {_clock(row.start_s)}"
    elif row.scope == "section" and row.section_ref:
        where = row.section_ref
    return {
        "id": str(row.id),
        "upload_id": str(row.upload_id),
        "session_id": str(row.session_id) if row.session_id else None,
        "scope": row.scope,
        "where": where,
        "start_s": row.start_s,
        "end_s": row.end_s,
        "source_s": row.source_s,
        "section_ref": row.section_ref,
        "request": row.request,
        "understood": row.understood,
        "created_by": row.created_by,
        "state": row.state,
        "result": row.result,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


def _clock(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def clock(seconds: float) -> str:
    """0:38, the way the player shows a second."""
    return _clock(seconds)


# ---------------------------------------------------------------------------
# Talk to the editor: one sitting of notes on a video (30-Sep)
# ---------------------------------------------------------------------------
#
# He watches the edit, pauses, says what is wrong, plays on. Each pause is a note
# pinned to that second; nothing changes until he says make it, and then one job
# reads every note and the video renders once. The page owns the second (never a
# model), and the sitting remembers which render it was watching, so every pin maps
# through the keep that made that file.

SITTING_ACTIVE_S = 120  # a sheet that checked in this recently is in front of him
WAITING_NOTE_STATES = ("listening", "held")
SITTING_WORKING_STATES = ("thinking", "rendering")  # its own batch is running
SITTING_LIVE_STATES = ("open", *SITTING_WORKING_STATES)
END_SLACK_S = 0.5  # a player a hair past the last frame is still on this edit
MOMENT_WAIT_S = 4.0  # the voice can hand a note over before his words are saved
MOMENT_POLL_S = 0.25
MAX_EARLIER_NOTES = 12

# (upload, keep) -> {word index: what the editor cannot hear for itself}
MarksFor = Callable[[RecordingUpload, list[list[float]]], Awaitable[dict[int, str]]]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def sitting_is_active(sitting: EditSession, now: datetime | None = None) -> bool:
    """In front of him right now: open with a heartbeat in the last 120 s, or its own
    batch running. Nothing else may re-render the video under the player then."""
    if sitting.state in SITTING_WORKING_STATES:
        return True
    if sitting.state != "open" or sitting.last_seen is None:
        return False
    return ((now or _now()) - sitting.last_seen).total_seconds() <= SITTING_ACTIVE_S


async def _sittings(
    db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID, states: tuple[str, ...]
) -> list[EditSession]:
    result = await db.execute(
        select(EditSession)
        .where(
            EditSession.workspace_id == ws,
            EditSession.upload_id == upload_id,
            EditSession.state.in_(states),
        )
        .order_by(EditSession.created_at.desc())
    )
    return list(result.scalars().all())


async def active_sitting(
    db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID
) -> EditSession | None:
    """The sitting in front of him on this video, if there is one (see sitting_is_active)."""
    now = _now()
    for sitting in await _sittings(db, ws, upload_id, SITTING_LIVE_STATES):
        if sitting_is_active(sitting, now):
            return sitting
    return None


async def sitting_notes(
    db: AsyncSession, ws: uuid.UUID, session_id: uuid.UUID
) -> list[EditingRequest]:
    result = await db.execute(
        select(EditingRequest)
        .where(EditingRequest.workspace_id == ws, EditingRequest.session_id == session_id)
        .order_by(EditingRequest.created_at.asc())
    )
    return list(result.scalars().all())


async def sitting_for_typed_note(
    db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID
) -> EditSession | None:
    """The sitting a typed request joins as a held note: open and in front of him, or
    open with notes already waiting for "make it" (the sheet was closed). An old empty
    sitting is not joined: the request would wait for a button nobody is about to press."""
    now = _now()
    for sitting in await _sittings(db, ws, upload_id, ("open",)):
        if sitting_is_active(sitting, now):
            return sitting
        notes = await sitting_notes(db, ws, sitting.id)
        if any(n.state in WAITING_NOTE_STATES for n in notes):
            return sitting
    return None


def watched_render(upload: RecordingUpload) -> tuple[str | None, list[list[float]] | None]:
    """The render he would be watching, and the keep that made it.

    An edit rendered before renders were stamped has no stamp. Its plan's keep is the
    file's own only while the video says edited and the plan was not blocked (a blocked
    plan was rendered uncut, or not at all).
    """
    if not upload.edited_path:
        return None, None
    if upload.render_ref and upload.rendered_keep:
        return upload.render_ref, [list(r) for r in upload.rendered_keep]
    plan = upload.edit_plan or {}
    if (
        upload.status == "edited"
        and plan.get("keep")
        and (plan.get("meaning_check") or {}).get("status") != "blocked"
    ):
        return None, frame_keep(plan["keep"])
    return None, None


def edit_file_url(upload: RecordingUpload, render_ref: str | None) -> str | None:
    """The address the sheet plays: the light copy when there is one, and the render's
    id, so a new render never plays from the old one's cached pieces."""
    if not upload.edited_path:
        return None
    query = []
    if _has_preview(upload):
        query.append("preview=1")
    if render_ref:
        query.append(f"v={render_ref}")
    return f"/api/v1/production/uploads/{upload.id}/edited" + ("?" + "&".join(query) if query else "")


async def open_sitting(
    db: AsyncSession,
    ws: uuid.UUID,
    upload_id: uuid.UUID,
    *,
    busy: Callable[[RecordingUpload], str | None] | None = None,
) -> EditSession:
    """Open a sitting on the edit he is about to watch, or return the one already open.

    `busy` says what else is editing the video right now, in his words. While it does,
    this is refused (409, with that sentence): notes pinned to a file about to be
    replaced would point at the wrong seconds. A sitting whose own batch is running is
    returned as it is, so the sheet shows the live step.
    """
    upload = await _get_upload(db, ws, upload_id)
    now = _now()
    live = await _sittings(db, ws, upload.id, SITTING_LIVE_STATES)
    current = live[0] if live else None
    if current is not None and current.state in SITTING_WORKING_STATES:
        current.last_seen = now
        await db.flush()
        return current
    doing = busy(upload) if busy is not None else None
    if doing:
        raise LibraryError("busy", doing, status=409)
    ref, keep = watched_render(upload)
    if not keep:
        raise LibraryError(
            "no_edit",
            "This edit was made before notes could be pinned to it. Tap Edit it again, then give your notes."
            if upload.edited_path
            else "There is no edit of this video to give notes on yet.",
            status=409,
        )
    if current is None:
        current = EditSession(
            workspace_id=ws,
            upload_id=upload.id,
            state="open",
            render_ref=ref,
            keep_snapshot=keep,
            last_seen=now,
        )
        db.add(current)
    else:
        if current.render_ref != ref or current.keep_snapshot != keep:
            await _move_to_render(db, ws, current, ref, keep)
        current.last_seen = now
    await db.flush()
    return current


async def _move_to_render(
    db: AsyncSession,
    ws: uuid.UUID,
    sitting: EditSession,
    render_ref: str | None,
    keep: list[list[float]],
) -> None:
    """The video was re-rendered while this sitting waited with the sheet closed. Each
    note keeps its second on the recording and gets its place on the new edit."""
    sitting.render_ref = render_ref
    sitting.keep_snapshot = keep
    for note in await sitting_notes(db, ws, sitting.id):
        if note.source_s is None:
            continue
        moved = map_to_edit(float(note.source_s), keep)
        if moved is not None:
            note.start_s = round(moved, 2)


async def get_sitting(
    db: AsyncSession, ws: uuid.UUID, session_id: uuid.UUID, *, seen: bool = False
) -> EditSession:
    """One sitting. `seen` is the sheet's heartbeat."""
    row = (
        await db.execute(
            select(EditSession).where(EditSession.workspace_id == ws, EditSession.id == session_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise LibraryError("not_found", "that sitting is not here", status=404)
    if seen:
        row.last_seen = _now()
        await db.flush()
    return row


def sitting_to_json(
    sitting: EditSession, notes: list[EditingRequest], upload: RecordingUpload
) -> dict[str, Any]:
    keep = sitting.keep_snapshot or []
    return {
        "session_id": str(sitting.id),
        "upload_id": str(sitting.upload_id),
        "state": sitting.state,
        "render_ref": sitting.render_ref,
        "file_url": edit_file_url(upload, sitting.render_ref),
        "edit_length_s": round(edit_length(keep), 3),
        "last_seen": _iso(sitting.last_seen),
        "submitted_at": _iso(sitting.submitted_at),
        "finished_at": _iso(sitting.finished_at),
        "summary": sitting.summary,
        "result": sitting.result,
        "notes": [edit_request_to_json(n) for n in notes],
        "waiting": sum(1 for n in notes if n.state in WAITING_NOTE_STATES),
        # While the new version renders, the video's own live step ("Cutting and burning
        # in your captions", then ffmpeg's progress), so the sheet never shows a bare spinner.
        "video_status": upload.status,
        "video_step": upload.status_detail,
        "can_undo": undo_refusal(sitting, upload) is None,
    }


# ---------------------------------------------------------------------------
# Going back to the version from before a sitting's notes


UNDO_CHANGED = (
    "The video was changed again after these notes, so going back would undo that too. "
    "Nothing was changed."
)


def transcript_fingerprint(words: list[dict[str, Any]] | None) -> str:
    """A short id of the words and their times: equal only when nothing moved."""
    body = json.dumps([[w.get("text"), w.get("start_s"), w.get("end_s")] for w in words or []])
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def undo_refusal(sitting: EditSession, upload: RecordingUpload) -> tuple[str, str] | None:
    """Why the version from before this sitting's notes cannot be put back now, as
    (code, sentence), or None when it can."""
    before = sitting.before or {}
    undo = (sitting.result or {}).get("undo") or {}
    if undo.get("state") in ("queued", "rendering"):
        return "busy", "The version from before these notes is being put back right now."
    if sitting.state == "open":
        return "not_made", "These notes have not been made into a new version yet."
    if sitting.state in SITTING_WORKING_STATES:
        return "busy", "The new version from these notes is still being made."
    if not before:
        if undo.get("state") == "done":
            return "undone", "The version from before these notes was already put back."
        return "nothing", "These notes did not change the video, so there is nothing to go back from."
    if transcript_fingerprint(upload.transcript) != before.get("after") or (upload.edit_plan or {}).get(
        "overrides"
    ) != before.get("after_overrides"):
        return "changed", UNDO_CHANGED
    return None


def _undo_read_back(sitting: EditSession) -> str:
    changed = [
        o for o in (sitting.result or {}).get("outcomes") or [] if o.get("outcome") == "change"
    ]
    n = len(changed)
    return (
        f"Put back the version from before your {n} note{'s' if n != 1 else ''}"
        + (f" ({sitting.summary.strip().rstrip('.')})" if (sitting.summary or "").strip() else "")
        + ". One re-render."
    )


async def undo_preview(
    db: AsyncSession,
    ws: uuid.UUID,
    session_id: uuid.UUID,
    *,
    busy: Callable[[RecordingUpload], str | None] | None = None,
) -> dict[str, Any]:
    """The read-back before going back, and whether it can be done now. Nothing changes."""
    sitting = await get_sitting(db, ws, session_id)
    upload = await _get_upload(db, ws, sitting.upload_id)
    refusal = undo_refusal(sitting, upload)
    doing = busy(upload) if busy is not None and refusal is None else None
    if doing:
        refusal = ("busy", doing)
    return {
        "session_id": str(sitting.id),
        "possible": refusal is None,
        "code": refusal[0] if refusal else None,
        "reason": refusal[1] if refusal else None,
        "read_back": _undo_read_back(sitting) if refusal is None else refusal[1],
    }


async def start_undo(
    db: AsyncSession,
    ws: uuid.UUID,
    session_id: uuid.UUID,
    *,
    busy: Callable[[RecordingUpload], str | None] | None = None,
) -> EditSession:
    """Mark the undo queued; the caller starts it. 409 with the reason when it cannot be done."""
    sitting = await get_sitting(db, ws, session_id)
    upload = await _get_upload(db, ws, sitting.upload_id)
    refusal = undo_refusal(sitting, upload)
    if refusal is None and busy is not None and (doing := busy(upload)):
        refusal = ("busy", doing)
    if refusal is not None:
        raise LibraryError(refusal[0], refusal[1], status=409)
    sitting.result = {
        **(sitting.result or {}),
        "undo": {
            "state": "queued",
            "status": "Putting back the version from before your notes",
            "at": _now().isoformat(),
        },
    }
    await db.flush()
    return sitting


def _must_take_notes(sitting: EditSession) -> None:
    if sitting.state != "open":
        raise LibraryError(
            "not_open",
            "These notes were already handed to the editor. Open the notes again for new ones.",
            status=409,
            extra={"state": sitting.state},
        )


async def _note_of(
    db: AsyncSession, ws: uuid.UUID, sitting: EditSession, note_id: uuid.UUID
) -> EditingRequest:
    note = (
        await db.execute(
            select(EditingRequest).where(
                EditingRequest.workspace_id == ws,
                EditingRequest.session_id == sitting.id,
                EditingRequest.id == note_id,
            )
        )
    ).scalar_one_or_none()
    if note is None:
        raise LibraryError("not_found", "that note is not in this sitting", status=404)
    return note


async def pin_note(
    db: AsyncSession,
    ws: uuid.UUID,
    session_id: uuid.UUID,
    *,
    edit_s: float,
    render_ref: str | None,
    by: str = "ziv",
) -> EditingRequest:
    """The pin, the moment he presses: the paused second, on the edit he is watching.

    No model is asked anything: this answers at once, and his words follow (PATCH
    heard). Refused (409) when the player is on another render than the sitting, or the
    video was re-rendered under it: the sheet reloads the new one and he pauses again.
    """
    sitting = await get_sitting(db, ws, session_id)
    _must_take_notes(sitting)
    upload = await _get_upload(db, ws, sitting.upload_id)
    current_ref, _ = watched_render(upload)
    if (render_ref or None) != (sitting.render_ref or None) or current_ref != sitting.render_ref:
        raise LibraryError(
            "stale_render",
            "The player is on another edit of this video. Load the new one and pause again.",
            status=409,
            extra={"render_ref": current_ref},
        )
    keep = sitting.keep_snapshot or []
    total = edit_length(keep)
    source_s = None
    if 0 <= edit_s <= total + END_SLACK_S:
        edit_s = min(float(edit_s), total)
        source_s = map_to_source(edit_s, keep)
    if source_s is None:
        raise LibraryError(
            "bad_second",
            f"{_clock(max(0.0, edit_s))} is not in this edit, which is {_clock(total)} long",
            status=400,
        )
    now = _now()
    note = EditingRequest(
        workspace_id=ws,
        upload_id=upload.id,
        candidate_id=upload.candidate_id,
        packet_id=upload.packet_id,
        session_id=sitting.id,
        scope="moment",
        start_s=round(edit_s, 2),
        end_s=None,
        source_s=round(source_s, 3),
        request="",
        state="listening",
        created_by=by,
        # Set here, to the microsecond: notes pinned in the same second keep their order.
        created_at=now,
    )
    db.add(note)
    sitting.last_seen = now
    await db.flush()
    return note


async def update_note(
    db: AsyncSession,
    ws: uuid.UUID,
    session_id: uuid.UUID,
    note_id: uuid.UUID,
    *,
    heard: str | None = None,
    understood: str | None = None,
    drop: bool = False,
) -> EditingRequest:
    """His words (`heard`, from the page), the editor's reading (`understood`, from the
    voice's backend), or taking the note back (`drop`). A note with either is held."""
    sitting = await get_sitting(db, ws, session_id)
    _must_take_notes(sitting)
    note = await _note_of(db, ws, sitting, note_id)
    if note.state not in WAITING_NOTE_STATES:
        raise LibraryError(
            "not_waiting",
            "That note was taken back." if note.state == "rejected" else "That note is already being worked on.",
            status=409,
        )
    now = _now()
    if drop:
        note.state = "rejected"
        note.resolved_at = now
    else:
        if heard is None and understood is None:
            raise LibraryError("empty", "say what the note is", status=400)
        if heard is not None:
            if not heard.strip():
                raise LibraryError("empty", "the note has no words", status=400)
            note.request = heard.strip()
        if understood is not None:
            note.understood = understood.strip() or None
        if note.state == "listening" and (note.request.strip() or note.understood):
            note.state = "held"
    note.updated_at = now
    sitting.last_seen = now
    await db.flush()
    return note


async def _await_words(
    db: AsyncSession, note: EditingRequest, wait_s: float
) -> EditingRequest:
    """The voice can hand a note to its backend mid-sentence, before the page has
    saved his words (30-Sep). Wait a few seconds for them."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, wait_s)
    while loop.time() < deadline:
        await asyncio.sleep(MOMENT_POLL_S)
        await db.refresh(note)
        if note.request.strip() or note.state != "listening":
            break
    return note


async def _earlier_notes(
    db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID, *, exclude: uuid.UUID | None
) -> list[dict[str, Any]]:
    """Every earlier note and request on this video, oldest first, with what came of it."""
    rows = await list_edit_requests(db, ws, upload_id)
    out = []
    for r in rows:
        if r.id == exclude or (r.session_id is not None and r.state == "rejected"):
            continue
        result = r.result or {}
        out.append(
            {
                "where": edit_request_to_json(r)["where"],
                "said": r.request,
                "understood": r.understood,
                "state": r.state,
                "reply": str(result.get("reply") or "") or None,
                "question": str(result.get("question") or "") or None,
                "sitting": str(r.session_id) if r.session_id else None,
            }
        )
    return out[-MAX_EARLIER_NOTES:]


async def moment(
    db: AsyncSession,
    ws: uuid.UUID,
    session_id: uuid.UUID,
    *,
    note_id: uuid.UUID | None = None,
    at: float | None = None,
    window: float = 8.0,
    rules: bool = False,
    marks_for: MarksFor | None = None,
    wait_s: float | None = None,
) -> dict[str, Any]:
    """What the editor needs to understand one note, for the voice's backend.

    The note (the one named, else the newest one not understood yet, else the second
    `at`), his words, the numbered words `window` seconds either side on the edit clock
    with the cut words (~~) and the joins (/cut Ns/), what the phone or the edit did to
    a word, the earlier notes on this video, and his standing rules when `rules`.
    """
    sitting = await get_sitting(db, ws, session_id)
    note: EditingRequest | None = None
    if note_id is not None:
        note = await _note_of(db, ws, sitting, note_id)
    elif at is None:
        pending = [
            n
            for n in await sitting_notes(db, ws, sitting.id)
            if n.state in WAITING_NOTE_STATES and not n.understood
        ]
        note = pending[-1] if pending else None
    waited = False
    if note is not None and note.state == "listening" and not note.request.strip():
        waited = True
        note = await _await_words(db, note, MOMENT_WAIT_S if wait_s is None else wait_s)
    edit_s = float(note.start_s) if note is not None and note.start_s is not None else at
    if note is None and edit_s is None:
        raise LibraryError(
            "no_moment", "There is no note waiting in this sitting, and no second was given.", status=404
        )

    upload = await _get_upload(db, ws, sitting.upload_id)
    keep = [list(r) for r in sitting.keep_snapshot or []]
    words = list(upload.transcript or [])
    transcript, items, marked = "", [], []
    at_json: dict[str, Any] | None = None
    span_json: dict[str, Any] | None = None
    if edit_s is not None and keep:
        total = edit_length(keep)
        edit_s = max(0.0, min(float(edit_s), total))
        source = map_to_source(edit_s, keep)
        at_json = {
            "edit_s": round(edit_s, 2),
            "source_s": round(source, 3) if source is not None else None,
            "clock": _clock(edit_s),
        }
        lo, hi = max(0.0, edit_s - window), min(total, edit_s + window)
        span_json = {"from_edit_s": round(lo, 2), "to_edit_s": round(hi, 2)}
        src_lo, src_hi = map_to_source(lo, keep) or 0.0, map_to_source(hi, keep) or 0.0
        first = next((i for i, w in enumerate(words) if float(w["end_s"]) >= src_lo), None)
        last = max((i for i, w in enumerate(words) if float(w["start_s"]) <= src_hi), default=None)
        if first is not None and last is not None and first <= last:
            plan = upload.edit_plan or {}
            # The plan's kept words carry the times the cut follows, but only while the
            # plan is still the one that made this file.
            kept = plan.get("words") if frame_keep(plan.get("keep") or []) == keep else None
            marks = await marks_for(upload, keep) if marks_for is not None else {}
            transcript = autoedit.numbered_transcript(words, keep, kept, marks, span=(first, last))
            timed = {int(w["index"]) for w in kept or [] if "index" in w}
            for i in range(first, last + 1):
                w = words[i]
                s, e = float(w["start_s"]), float(w["end_s"])
                cut = (i not in timed) if kept else map_to_edit((s + e) / 2, keep) is None
                on_edit = None if cut else map_to_edit(s, keep)
                if on_edit is None and not cut:
                    on_edit = map_to_edit((s + e) / 2, keep)
                item: dict[str, Any] = {
                    "index": i,
                    "text": str(w["text"]),
                    "source_s": round(s, 2),
                    "edit_s": round(on_edit, 2) if on_edit is not None else None,
                    "cut": cut,
                }
                if i in marks:
                    item["mark"] = marks[i]
                    marked.append({"index": i, "text": str(w["text"]), "mark": marks[i]})
                items.append(item)

    payload: dict[str, Any] = {
        "session_id": str(sitting.id),
        "video": str(upload.id),
        "state": sitting.state,
        "note": edit_request_to_json(note) if note is not None else None,
        "heard": note.request if note is not None and note.request.strip() else None,
        "waited_for_words": waited,
        "at": at_json,
        "window": span_json,
        "transcript": transcript,
        "words": items,
        "marks": marked,
        "earlier": await _earlier_notes(
            db, ws, upload.id, exclude=note.id if note is not None else None
        ),
    }
    if rules:
        payload["rules"] = autoedit.editor_skill()
    return payload


def _ready_notes(notes: list[EditingRequest]) -> list[EditingRequest]:
    """Notes that go to the editor at "make it": waiting, with his words or a reading."""
    return [
        n
        for n in notes
        if n.state in WAITING_NOTE_STATES and (n.request.strip() or (n.understood or "").strip())
    ]


def _note_line(note: EditingRequest) -> str:
    where = edit_request_to_json(note)["where"]
    what = (note.understood or "").strip() or f'you said "{note.request.strip()}"'
    return f"{where}: {what.rstrip(' .;')}"


def read_back(notes: list[EditingRequest], left_out: int = 0) -> str:
    """The sentence he hears before anything renders."""
    n = len(notes)
    text = f"{n} note{'s' if n != 1 else ''}: " + "; ".join(_note_line(x) for x in notes)
    text += ". One re-render."
    if left_out:
        text += (
            f" {left_out} note{'s' if left_out != 1 else ''} with no words yet "
            f"{'are' if left_out != 1 else 'is'} left out."
        )
    return text


def check_code(notes: list[EditingRequest]) -> str:
    """The read-back's fingerprint: a note added, taken back, re-said or re-read since
    the read-back changes it, so a yes only ever makes what he heard."""
    body = json.dumps(
        [[str(n.id), n.request.strip(), (n.understood or "").strip(), n.start_s] for n in notes]
    )
    return hashlib.sha256(body.encode()).hexdigest()[:12]


async def submit_preview(db: AsyncSession, ws: uuid.UUID, session_id: uuid.UUID) -> dict[str, Any]:
    """The read-back and its check code. Nothing changes."""
    sitting = await get_sitting(db, ws, session_id, seen=True)
    _must_take_notes(sitting)
    notes = await sitting_notes(db, ws, sitting.id)
    ready = _ready_notes(notes)
    left_out = [n for n in notes if n.state in WAITING_NOTE_STATES and n not in ready]
    if not ready:
        raise LibraryError("no_notes", "There are no notes to make a new version from yet.", status=409)
    return {
        "session_id": str(sitting.id),
        "read_back": read_back(ready, len(left_out)),
        "check": check_code(ready),
        "count": len(ready),
        "notes": [edit_request_to_json(n) for n in ready],
        "left_out": [str(n.id) for n in left_out],
    }


async def submit(
    db: AsyncSession, ws: uuid.UUID, session_id: uuid.UUID, *, check: str, by: str = "ziv"
) -> tuple[EditSession, dict[str, Any]]:
    """He said yes to the read-back. The sitting starts thinking with exactly the notes
    he heard; the caller starts the one batch job."""
    preview = await submit_preview(db, ws, session_id)
    if (check or "").strip() != preview["check"]:
        raise LibraryError(
            "changed",
            "The notes changed since the read-back, or no check code was given. Read them back again: "
            + preview["read_back"],
            status=409,
            extra={"check": preview["check"], "read_back": preview["read_back"]},
        )
    sitting = await get_sitting(db, ws, session_id)
    now = _now()
    count = preview["count"]
    sitting.state = "thinking"
    sitting.submitted_at = now
    sitting.last_seen = now
    sitting.summary = preview["read_back"]
    sitting.result = {
        "status": f"Reading your {count} note{'s' if count != 1 else ''} on the subscription",
        "notes": [n["id"] for n in preview["notes"]],
        "by": by,
    }
    await db.flush()
    return sitting, preview
