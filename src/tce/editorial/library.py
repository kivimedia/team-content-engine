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
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
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
from tce.production import agent_talks, autoedit
from tce.production.retakes import edit_join, edit_length, frame_keep, map_to_edit, map_to_source

# Library filters, in the order the chips are shown. Each maps to upload states.
# 28-Sep: "Still to do" is the list the page opens on - everything not yet out and
# not archived - and published videos have their own chip instead of crowding it.
LIBRARY_FILTERS: dict[str, tuple[str, ...]] = {
    "todo": (),
    "uploading": ("uploaded",),
    "editing": ("transcribing", "transcribed", "proofreading", "planned", "rendering", "checking"),
    "needs_review": ("needs_review",),
    "ready": ("edited",),
    "published": (),
    "all": (),
    "archived": (),
}

# A post in one of these states has gone out, or will without anyone touching it.
_OUT_STATUSES = ("posted", "scheduled")

# 3-Oct: "checking" is Jennifer's check of a finished render (it may re-render once).
_LIVE_STATUSES = ("transcribing", "transcribed", "proofreading", "planned", "rendering", "checking")

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
    "checking": "Jennifer is checking the edit.",
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


ARCHIVED_UNEDITED = "Archived without an edit. Nothing is done to it until you tap Edit this now."
# production.AUTO_MARK (production imports this module): an automatic edit holds the video.
AUTO_EDIT_MARK = "auto-edit"


def _idle_and_never_edited(upload: RecordingUpload) -> bool:
    return (
        not upload.edited_path
        and bool(upload.storage_path)
        and upload.status not in _LIVE_STATUSES
        and AUTO_EDIT_MARK not in (upload.job_ids or [])
    )


def never_edited_archive(upload: RecordingUpload) -> bool:
    """An archived recording that was never edited and is not being edited now: the one
    the Archived list offers "Edit this now" for."""
    return upload.archived_at is not None and _idle_and_never_edited(upload)


def offers_edit_now(upload: RecordingUpload) -> bool:
    """Archived without an edit, or (4-Oct review) a talk he brought back from Archived
    without one: Bring it back used to leave a card in Still to do that nothing would
    ever edit, with no button that does."""
    if never_edited_archive(upload):
        return True
    return (
        upload.archived_at is None
        and upload.source == agent_talks.SOURCE
        and upload.status == "uploaded"
        and _idle_and_never_edited(upload)
    )


def _actions(upload: RecordingUpload, open_requests: int) -> list[dict[str, str]]:
    """Only actions with a real destination.

    Ordered by what he most likely wants: watch it, then change it, then start
    again. `re_record` is last because it is the expensive one.
    """
    actions: list[dict[str, str]] = []
    if offers_edit_now(upload):
        # 4-Oct (C4.1): archived without an edit, by his choice after Stop, or brought
        # back without one. One tap starts the normal edit (and takes it out of Archived).
        actions.append({"key": "edit_now", "label": "Edit this now"})
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
    if upload.edited_path:
        # 1-Oct: watch the edit, pause, say what is wrong; one new version at the end.
        # 3-Oct: the editor is Jennifer.
        actions.append({"key": "talk_edit", "label": f"Talk to {EDITOR_NAME}"})
    actions.append({"key": "request_edit", "label": "Request an editing change"})
    if upload.edited_path and upload.transcript and upload.status not in _LIVE_STATUSES:
        # 28-Sep: the tight cut and the word-box captions, for an edit made before them.
        actions.append({"key": "edit_again", "label": "Edit it again"})
    if upload.edited_path and (upload.status == "edited" or qc_hold(upload)):
        # 3-Oct: Jennifer's check, on demand; and his way past a hold of hers. Not while
        # a cut the meaning check blocked waits for his eyes (that is settled first).
        if qc_hold(upload):
            actions.append({"key": "release_hold", "label": "It is fine, let it through"})
        actions.append({"key": "check_again", "label": "Ask Jennifer to check it again"})
    if open_requests:
        actions.append(
            {
                "key": "open_requests",
                "label": f"{open_requests} open request{'s' if open_requests != 1 else ''}",
            }
        )
    # A talk with an agent was a conversation, not a script: there is nothing to record
    # again, so the button would lead nowhere.
    if upload.source != agent_talks.SOURCE:
        actions.append({"key": "re_record", "label": "Record it again"})
    return actions


def source_json(upload: RecordingUpload) -> dict[str, Any]:
    """Where a video came from, for the card: a walk he recorded (no label), or an agent
    talk: "Agent talk with Atlas" and a line saying what it is."""
    if upload.source != agent_talks.SOURCE:
        return {"source": upload.source, "source_label": None, "agent": None, "source_line": None}
    agent = upload.agent_name or "an agent"
    return {
        "source": agent_talks.SOURCE,
        "source_label": agent_talks.SOURCE_LABEL,
        "agent": upload.agent_name,
        "source_line": f"{agent_talks.SOURCE_LABEL} with {agent}: a voice call you filmed. "
        f"Jennifer keeps {agent}'s lines and cuts the dead air.",
    }


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


# 3-Oct: the editor has a name. "Talk to the video editor" is Jennifer, who also checks
# every edit; every sentence he reads about the editor says Jennifer. Internal names
# (autoedit.AGENT_NAME "video_editor", the routes) stay as they are.
EDITOR_NAME = "Jennifer"

REVIEW_SENTENCES = {
    "waiting": "Jennifer has not answered yet, so this edit used the rules. "
    "It edits itself again when her review lands.",
    "unavailable": "Jennifer could not review this one, so the rules decided what to cut.",
    "rules": "Jennifer's answer was not usable, so the rules decided what to cut.",
    "blocked": "Jennifer's review wants a cut that would change what you said, so the "
    "edit you have stays. Edit it again to see her cut and decide.",
    "stale": "You changed the words after Jennifer started reading, so that review was "
    "not used. Edit it again for a fresh one.",
}


# What her check ended as, for the card's tag. A check that is still running has none.
QC_LABELS = {
    "passed": "Checked by Jennifer",
    "fixed": "Checked and fixed by Jennifer",
    "held": "Jennifer is holding this",
    "report": "Jennifer found something",
    "released": "You let it through",
    "unchecked": "Not checked",
}


def qc_hold(upload: Any) -> str | None:
    """Jennifer's one line when she is holding this video, else None.

    A hold is hers only while it is about the file he would watch (the render she
    checked is the render he has) and the video says needs_review for it. A plan the
    meaning check blocked is not her hold: that one is edit_waits_for_him's."""
    found = getattr(upload, "qc", None) or {}
    if found.get("state") != "held" or getattr(upload, "status", None) != "needs_review":
        return None
    if found.get("render_ref") != getattr(upload, "render_ref", None) or not getattr(upload, "edited_path", None):
        return None
    return str(found.get("line") or "Jennifer is holding this video.")


def qc_json(upload: Any) -> dict[str, Any] | None:
    """What Jennifer found on the render he would be watching, for the card and her
    voice seat: the verdict, her one line, the numbers. None when this render was never
    checked (an edit from before 3-Oct, or a newer render than the one she checked)."""
    found = getattr(upload, "qc", None) or {}
    state = str(found.get("state") or "")
    if not state or not getattr(upload, "edited_path", None):
        return None
    if state != "checking" and found.get("render_ref") != getattr(upload, "render_ref", None):
        return None
    return {
        "state": state,
        "label": QC_LABELS.get(state),
        "line": found.get("line"),
        "numbers": found.get("numbers") or {},
        "problems": [str(p.get("detail") or "") for p in (found.get("problems") or [])[:8]],
        "fixed": list(found.get("fixed") or []),
        "round": found.get("round"),
        "at": found.get("at"),
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
    # 1-Oct review: only a sitting that takes notes has notes waiting for "make it". The
    # notes of one being made are not waiting (the card would offer Make again).
    taking_notes = set(
        (
            await db.execute(
                select(EditSession.id).where(EditSession.workspace_id == ws, EditSession.state == "open")
            )
        ).scalars()
    )
    # 1-Oct: the newest sitting whose notes were made (or are being made), per video, so
    # the card shows every note and what came of it, not only the last one.
    made_by_upload: dict[uuid.UUID, EditSession] = {}
    for made in (
        await db.execute(
            select(EditSession)
            .where(EditSession.workspace_id == ws, EditSession.state.in_(SITTING_MADE_STATES))
            .order_by(EditSession.created_at.asc())
        )
    ).scalars():
        made_by_upload[made.upload_id] = made
    made_ids = {s.id for s in made_by_upload.values()}
    notes_by_sitting: dict[uuid.UUID, list[EditingRequest]] = {}
    for req in requests.scalars().all():
        if req.session_id in made_ids and req.state != "rejected":
            notes_by_sitting.setdefault(req.session_id, []).append(req)
        if req.session_id is not None and req.state in (*WAITING_NOTE_STATES, "rejected"):
            # 30-Sep: a note in a sitting waits for "make it"; it is not a request the
            # editor is working on, and a note he took back is not one at all.
            # A pin nobody spoke into is not a note waiting (1-Oct review: the card said
            # "1 note waiting" for one a closed sheet left).
            if req.state != "rejected" and req.session_id in taking_notes and has_words(req):
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
                # 3-Oct: a video Jennifer is holding says her one line, not the sentence of
                # a blocked cut.
                "state_sentence": (
                    upload.status_detail
                    if upload.status in _LIVE_STATUSES and upload.status_detail
                    # 4-Oct: archived without an edit says so, and what brings it back.
                    else ARCHIVED_UNEDITED
                    if never_edited_archive(upload) and upload.status == "uploaded"
                    else qc_hold(upload) or STATE_SENTENCES.get(upload.status, upload.status_detail or "")
                ),
                # What her check found on this render: "Checked by Jennifer" and its numbers.
                "qc": qc_json(upload),
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
                # The last notes made into a new version, each with its own result.
                "notes_made": (
                    _notes_made_json(made_by_upload[upload.id], notes_by_sitting.get(made_by_upload[upload.id].id, []))
                    if upload.id in made_by_upload
                    else None
                ),
                "actions": _actions(upload, open_count),
                # 3-Oct: "Agent talk" and who it was with, for a filmed voice call.
                **source_json(upload),
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
# Notes handed to the editor: being made, or made (the card shows each one's result).
SITTING_MADE_STATES = (*SITTING_WORKING_STATES, "done", "needs_you")
END_SLACK_S = 0.5  # a player a hair past the last frame is still on this edit
MOMENT_WAIT_S = 4.0  # the voice can hand a note over before his words are saved
MOMENT_POLL_S = 0.25
MAX_EARLIER_NOTES = 12

# 1-Oct review: a typed request made while a sitting's notes were being made ran on its
# own, rendered a second time and wrote back words from before the batch.
NOTES_BEING_MADE = (
    "Your notes on this video are being made into a new version right now. "
    "Add this once it is done."
)
# A pin with no words when he said make it: the read-back told him it was left out.
LEFT_OUT = "No words were caught for this note, so it was left out of the new version."
# The new version cut the second a waiting note was pinned to: it now sits at that cut.
NOTE_CUT_IN_NEW_VERSION = "The new version cut this moment; the note now sits where that cut is."

# 1-Oct final review: every hold on the sheet is pinned, so his "that's all, make it",
# his "yes", "no, I meant...", "scratch that" and "go back" each arrived as a note too.
# They went into the read-back, every spoken yes changed its check code (Make never
# started), and the batch got "make it" as a note. A hold that carried an instruction
# is taken back by the tool that acts on it (take_command), and a yes given after the
# read-back is never a note of that read-back (submit's `as_of`).
COMMAND_TAKEN = "This hold was an instruction to Jennifer, not a note."
AFTER_READ_BACK = "Given after the read-back you said yes to, so it was taken as your answer, not a note."
# A pin nobody spoke into, left when the notes closed: it carries nothing of his.
NO_WORDS_ON_CLOSE = "No words were caught for this note, so it was taken back when the notes closed."
NOTES_CLOSED = "These notes were closed. Open the notes again to give new ones."
# How alike his words for a hold and the words the editor was handed must be (shared
# words over all words) to be the same hold. Both come from the same transcript of
# the call, so the right hold scores near 1.
SAME_HOLD = 0.4
_WORD = re.compile(r"[\w']+")

# 1-Oct final review: notes made while an earlier re-edit's plan waits for his eyes were
# re-planned with that blocked cut still in, stopped on it, and were blamed for it.
EDIT_WAITS = (
    "Jennifer's last re-edit wants a cut that is waiting for your eyes ({reason}), so no "
    "new version can be made from notes until that is settled. Your notes are kept. On the "
    "card, use Request an editing change to keep or drop that cut, then make the new version."
)

# (upload, keep) -> {word index: what the editor cannot hear for itself}
MarksFor = Callable[[RecordingUpload, list[list[float]]], Awaitable[dict[int, str]]]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def has_words(note: EditingRequest) -> bool:
    """His words or the editor's reading: a note that says something. A pin with
    neither (nobody spoke into it) is not a note waiting for anything (1-Oct review)."""
    return bool((note.request or "").strip() or (note.understood or "").strip())


def edit_waits_for_him(upload: RecordingUpload) -> str | None:
    """Why no new version can be made from notes right now, or None.

    An earlier re-edit (Edit it again, a typed request) planned a cut the meaning check
    blocked, so nothing rendered and the file he watches is the render before it. A
    batch re-plans from that blocked plan and would stop on the same cut, so it is not
    started until he settles that cut."""
    if upload.status != "needs_review" or not upload.edited_path:
        return None
    if qc_hold(upload) is not None:
        # 3-Oct: Jennifer is holding a finished render for something her check found.
        # No cut waits for his eyes, and a note is exactly how he gets it fixed.
        return None
    reason = (upload.status_detail or "").strip()
    reason = re.sub(r"^needs review:\s*", "", reason, flags=re.I).rstrip(" .") or "the cut would change what you said"
    return EDIT_WAITS.format(reason=reason)[:500]


def _word_set(text: str | None) -> set[str]:
    return {w.strip("'") for w in _WORD.findall((text or "").lower())} - {""}


def _alike(said: str | None, heard: str | None) -> float:
    """Shared words over all words: 1 for the same words, 0 for none in common."""
    a, b = _word_set(said), _word_set(heard)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _hold_saying(notes: list[EditingRequest], said: str | None) -> EditingRequest | None:
    """The note whose words are the ones he said (`said`, as the call heard them), or
    None. A tie goes to the newer hold."""
    best, score = None, 0.0
    for n in notes:  # oldest first
        s = _alike(said, n.request)
        if s >= SAME_HOLD and s >= score:
            best, score = n, s
    return best


def _voice_unread(notes: list[EditingRequest]) -> list[EditingRequest]:
    """Holds the editor has not read yet, oldest first. A typed note, or a typed request
    that joined the sitting, is never read on the call (1-Oct review: it stayed the
    oldest unread note and took every spoken note's reading)."""
    return [
        n
        for n in notes
        if n.state in WAITING_NOTE_STATES and n.created_by == "voice" and not (n.understood or "").strip()
    ]


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


async def working_sitting(
    db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID
) -> EditSession | None:
    """The sitting whose notes are being made into a new version on this video, if any."""
    working = await _sittings(db, ws, upload_id, SITTING_WORKING_STATES)
    return working[0] if working else None


async def joinable_sitting(
    db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID
) -> EditSession | None:
    """The sitting a typed request joins as a held note: open and in front of him, or
    open with notes already waiting for "make it" (the sheet was closed). An old empty
    sitting is not joined: the request would wait for a button nobody is about to press,
    and neither is one holding only a pin nobody spoke into.

    Nor is any while an earlier re-edit waits for his eyes (edit_waits_for_him): no
    notes can be made until that is settled, and a typed request is how he settles it."""
    upload = await _get_upload(db, ws, upload_id)
    if edit_waits_for_him(upload):
        return None
    now = _now()
    for sitting in await _sittings(db, ws, upload_id, ("open",)):
        if sitting_is_active(sitting, now):
            return sitting
        notes = await sitting_notes(db, ws, sitting.id)
        if any(n.state in WAITING_NOTE_STATES and has_words(n) for n in notes):
            return sitting
    return None


async def sitting_for_typed_note(
    db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID
) -> EditSession | None:
    """Where a request he types now goes: into the sitting he is giving notes in (see
    joinable_sitting), or None to run on its own. Refused (409) while a sitting's notes
    are being made: it cannot join them any more, and run on its own it would render a
    second time over words the batch is about to change."""
    if await working_sitting(db, ws, upload_id) is not None:
        raise LibraryError("notes_being_made", NOTES_BEING_MADE, status=409)
    return await joinable_sitting(db, ws, upload_id)


async def join_sitting(db: AsyncSession, request: EditingRequest, sitting: EditSession) -> EditingRequest:
    """A request that was going to run on its own becomes one more note of the sitting
    he is giving notes in: made with the others, in one re-render (1-Oct review: it
    re-rendered under his player instead)."""
    request.session_id = sitting.id
    request.state = "held"
    if request.start_s is not None and sitting.keep_snapshot:
        source = map_to_source(float(request.start_s), sitting.keep_snapshot)
        request.source_s = round(source, 3) if source is not None else None
    request.updated_at = _now()
    await db.flush()
    return request


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
        try:
            async with db.begin_nested():
                db.add(current)
                await db.flush()
            return current
        except IntegrityError:
            # Another open of this video got there first (a double tap, a retried
            # request): one live sitting per video, so use that one.
            if current in db:
                db.expunge(current)
            live = await _sittings(db, ws, upload.id, SITTING_LIVE_STATES)
            if not live:
                raise
            current = live[0]
            if current.state in SITTING_WORKING_STATES:
                current.last_seen = now
                await db.flush()
                return current
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
    note keeps its second on the recording and gets its place on the new edit. A note
    whose second the new version cut sits at that cut, and says so, rather than keep a
    second of the old file's clock (which on the new file is another word)."""
    sitting.render_ref = render_ref
    sitting.keep_snapshot = keep
    for note in await sitting_notes(db, ws, sitting.id):
        if note.source_s is None:
            continue
        source = float(note.source_s)
        result = {k: v for k, v in (note.result or {}).items() if k != "moved"}
        if map_to_edit(source, keep) is None:
            result["moved"] = NOTE_CUT_IN_NEW_VERSION
        note.start_s = round(edit_join(source, keep), 2)
        note.result = result or None


async def get_sitting(
    db: AsyncSession,
    ws: uuid.UUID,
    session_id: uuid.UUID,
    *,
    seen: bool = False,
    for_update: bool = False,
) -> EditSession:
    """One sitting. `seen` is the sheet's heartbeat. `for_update` locks the row until the
    caller commits, so two taps at once cannot both start the same thing."""
    query = select(EditSession).where(EditSession.workspace_id == ws, EditSession.id == session_id)
    if for_update:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise LibraryError("not_found", "that sitting is not here", status=404)
    if seen:
        row.last_seen = _now()
        await db.flush()
    return row


async def close_sitting(db: AsyncSession, ws: uuid.UUID, session_id: uuid.UUID) -> EditSession:
    """A sitting nobody is giving notes in any more becomes `closed`: nothing joins it
    and its gates on the video lapse at once (1-Oct review: the voice test call's
    sitting stayed "active" for two minutes after it was done, and a request he typed
    meanwhile joined it as a note). Refused (409) while a note waits there, so his
    notes are never closed away; refused once its notes are being made. Closing a
    closed sitting changes nothing.

    A pin nobody spoke into is not a note: it is taken back with the close (1-Oct
    final review: one left by a sheet closed right after an empty hold kept the
    sitting open for good, and later typed requests waited in it)."""
    sitting = await get_sitting(db, ws, session_id)
    if sitting.state == "closed":
        return sitting
    if sitting.state != "open":
        raise LibraryError(
            "not_open",
            "These notes were already handed to the editor, so they cannot be closed.",
            status=409,
            extra={"state": sitting.state},
        )
    open_notes = [n for n in await sitting_notes(db, ws, sitting.id) if n.state in WAITING_NOTE_STATES]
    waiting = [n for n in open_notes if has_words(n)]
    if waiting:
        raise LibraryError(
            "notes_waiting",
            f"{len(waiting)} note{'s are' if len(waiting) != 1 else ' is'} still waiting here, so these notes stay open.",
            status=409,
            extra={"waiting": len(waiting)},
        )
    now = _now()
    for empty in open_notes:
        empty.state = "rejected"
        empty.result = {**(empty.result or {}), "left_out": NO_WORDS_ON_CLOSE}
        empty.updated_at = empty.resolved_at = now
    sitting.state = "closed"
    sitting.finished_at = now
    await db.flush()
    return sitting


async def _reopen_if_closed(db: AsyncSession, ws: uuid.UUID, sitting: EditSession) -> None:
    """A hold on notes another screen closed (1-Oct final review: the desk closed the
    sitting the phone was using, and the phone's next hold was refused as "already
    handed to the editor"). The sitting opens again when it is still the video's newest
    and no other takes notes on it; otherwise it stays closed and says so."""
    if sitting.state != "closed":
        return
    newer = (
        await db.execute(
            select(EditSession.id).where(
                EditSession.workspace_id == ws,
                EditSession.upload_id == sitting.upload_id,
                EditSession.id != sitting.id,
                (EditSession.created_at > sitting.created_at)
                | EditSession.state.in_(SITTING_LIVE_STATES),
            )
        )
    ).first()
    if newer is not None:
        return
    sitting.state = "open"
    sitting.finished_at = None
    await db.flush()


def learned_json(learned: Any) -> dict[str, Any] | None:
    """What Jennifer took from an applied note, as the card says it: a rule for every
    next video, a rule she already had, or only about this video. None while nothing
    was decided (never asked, or the worker has not answered)."""
    if not isinstance(learned, dict):
        return None
    state = learned.get("state")
    if state == "rule":
        return {"state": "rule", "line": f"Jennifer learned a rule from this: {learned.get('text')}",
                "rule_id": learned.get("rule_id")}
    if state == "covered":
        return {"state": "covered", "line": f"Jennifer already has a rule for this: {learned.get('text')}",
                "rule_id": learned.get("rule_id")}
    if state == "this_video":
        return {"state": "this_video", "line": "Jennifer took this as only about this video.", "rule_id": None}
    if state == "asking":
        return {"state": "asking", "line": "Jennifer is working out whether this is a rule for every video.",
                "rule_id": None}
    return None


def _notes_made_json(sitting: EditSession, notes: list[EditingRequest]) -> dict[str, Any]:
    """The Library card's account of the last notes made into a new version (1-Oct):
    while they are being made, the batch's own step; after, every note with its result."""
    result = sitting.result or {}
    out = []
    for n in notes:
        res = n.result or {}
        out.append(
            {
                "id": str(n.id),
                "where": edit_request_to_json(n)["where"],
                "said": n.request,
                "understood": n.understood,
                "state": n.state,
                "reply": str(res.get("reply") or "") or None,
                "question": str(res.get("question") or "") or None,
                "undone": bool(res.get("undone_at")),
                # 3-Oct: what Jennifer took from this note for the next videos.
                "learned": learned_json(res.get("learned")),
            }
        )
    return {
        "session_id": str(sitting.id),
        "state": sitting.state,
        "status": str(result.get("status") or "") or None,
        "finished_at": _iso(sitting.finished_at),
        "notes": out,
    }


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
        # Why no new version can be made from notes now (an earlier re-edit waits for his
        # eyes), said when the sheet opens rather than first at Make.
        "blocked": edit_waits_for_him(upload),
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
    """Mark the undo queued; the caller starts it. 409 with the reason when it cannot be
    done. The row is locked while this reads it, so a second tap waits for the first and
    then finds the undo queued (409)."""
    sitting = await get_sitting(db, ws, session_id, for_update=True)
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
            NOTES_CLOSED
            if sitting.state == "closed"
            else "These notes were already handed to the editor. Open the notes again for new ones.",
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
    A hold on notes another screen closed opens them again (_reopen_if_closed).
    """
    sitting = await get_sitting(db, ws, session_id)
    await _reopen_if_closed(db, ws, sitting)
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
    voice's backend), or taking the note back (`drop`). A note with either is held.

    His words for a hold that was taken back as an instruction, or left out, can land
    after that (the editor acts on "make it" as the sheet saves the words, 1-Oct final
    review): they are kept on that row and nothing else changes, never a refusal."""
    sitting = await get_sitting(db, ws, session_id)
    note = await _note_of(db, ws, sitting, note_id)
    late = note.state == "rejected" and {"command", "left_out"} & set(note.result or {})
    if late and heard is not None and understood is None and not drop:
        if heard.strip():
            note.request = heard.strip()
            note.updated_at = _now()
            await db.flush()
        return note
    _must_take_notes(sitting)
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


def _take_back_as_his_answer(note: EditingRequest, said: str | None, why: str, now: datetime) -> None:
    note.state = "rejected"
    note.result = {**(note.result or {}), "command": (said or note.request or "").strip()[:300], "taken": why}
    note.updated_at = note.resolved_at = now


async def take_command(
    db: AsyncSession,
    ws: uuid.UUID,
    session_id: uuid.UUID,
    *,
    said: str | None = None,
    keep: uuid.UUID | None = None,
) -> EditingRequest | None:
    """Take back the hold that carried an instruction to the editor, not a note (1-Oct
    final review): "that's all, make it", his "yes", "go back", and with `keep` (the
    note it is about) "no, I meant..." or "scratch that".

    Which hold: the one whose words are `said` (his words, as the call heard them).
    When that hold was read as a note (he gave a note and said make it in one breath),
    it is a note and nothing is taken back. When no saved words match, the newest hold
    whose words are still on their way. With no words given, the newest unread hold.
    With `keep`, only holds after that note count. Returns the hold taken back, or
    None. Changes nothing on notes that are not taking notes."""
    sitting = await get_sitting(db, ws, session_id)
    if sitting.state != "open":
        return None
    notes = await sitting_notes(db, ws, sitting.id)
    holds = [n for n in notes if n.state in WAITING_NOTE_STATES and n.created_by == "voice" and n.id != keep]
    if keep is not None:
        kept = next((n for n in notes if n.id == keep), None)
        if kept is not None:
            holds = [n for n in holds if n.created_at > kept.created_at]
    unread = _voice_unread(holds)
    if (said or "").strip():
        hit = _hold_saying(holds, said)
        if hit is not None and hit not in unread:
            return None  # read as a note: the instruction rode on a real note
        if hit is None:
            on_the_way = [n for n in unread if not n.request.strip()]
            hit = on_the_way[-1] if on_the_way else None
    else:
        hit = unread[-1] if unread else None
    if hit is None:
        return None
    # The call's brain asked: the sheet's heartbeat is left alone, as with every tool.
    _take_back_as_his_answer(hit, said, COMMAND_TAKEN, _now())
    await db.flush()
    return hit


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
                # So the editor can reach a note it answered out of order (1-Oct review).
                "id": str(r.id),
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


def watched_plan_words(plan: dict[str, Any] | None, keep: list[list[float]]) -> list[dict[str, Any]] | None:
    """The plan's kept words (the times the cut follows), but only while the plan is
    still the one that made the file he watched (`keep`). After an uncut render, a
    blocked re-plan or an earlier batch whose render failed, the plan has moved on and
    its words would mark as cut what he heard, or stamp times of an edit he never saw."""
    plan = plan or {}
    if plan.get("words") and frame_keep(plan.get("keep") or []) == [list(r) for r in keep]:
        return list(plan["words"])
    return None


def _note_to_read(notes: list[EditingRequest], said: str | None = None) -> EditingRequest | None:
    """Which hold the voice's backend is asking about when it names no note.

    By the words it was handed (`said`, his words on the call): the hold whose words
    are those, so a slow brain turn answering note 1 never reads note 2. When no saved
    words match, the newest hold whose words are still on their way (the voice handed
    it over mid-sentence, see _await_words), else nothing. With no words given, the
    newest hold with words, else the newest pin.

    1-Oct final review: this used to take the OLDEST unread note, and a note no voice
    ever reads (typed, joined from a typed request, one Live answered by itself, a
    correction the brain wrote onto the earlier note) stayed the oldest for good and
    took every later note's reading. Only holds count (_voice_unread), newest first."""
    pending = _voice_unread(notes)
    if (said or "").strip():
        hit = _hold_saying(pending, said)
        if hit is not None:
            return hit
        on_the_way = [n for n in pending if not n.request.strip()]
        return on_the_way[-1] if on_the_way else None
    spoken = [n for n in pending if n.request.strip()]
    if spoken:
        return spoken[-1]
    return pending[-1] if pending else None


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
    said: str | None = None,
) -> dict[str, Any]:
    """What the editor needs to understand one note, for the voice's backend.

    The note (the one named, else the hold whose words are `said`, see _note_to_read,
    else the second `at`), his words, every hold still waiting for a reading (with
    ids, so it can take the right one), the numbered words `window`
    seconds either side on the edit clock with the cut words (~~) and the joins
    (/cut Ns/), what the phone or the edit did to a word, the earlier notes on this
    video, and his standing rules when `rules`.

    A note is placed by its second on the RECORDING, which survives a re-render: when
    the version he now has cut that second, `at.in_edit` is false and the note sits at
    the join where the cut is.
    """
    sitting = await get_sitting(db, ws, session_id)
    note: EditingRequest | None = None
    if note_id is not None:
        note = await _note_of(db, ws, sitting, note_id)
    elif at is None:
        note = _note_to_read(await sitting_notes(db, ws, sitting.id), said)
    waited = False
    if note is not None and note.state == "listening" and not note.request.strip():
        waited = True
        note = await _await_words(db, note, MOMENT_WAIT_S if wait_s is None else wait_s)
    edit_s = float(note.start_s) if note is not None and note.start_s is not None else at
    if note is None and edit_s is None:
        raise LibraryError(
            "no_moment",
            "No hold of his waiting for a reading has those words."
            if (said or "").strip()
            else "There is no note waiting in this sitting, and no second was given.",
            status=404,
            extra={"said": bool((said or "").strip())},
        )

    upload = await _get_upload(db, ws, sitting.upload_id)
    keep = [list(r) for r in sitting.keep_snapshot or []]
    words = list(upload.transcript or [])
    transcript, items, marked = "", [], []
    at_json: dict[str, Any] | None = None
    span_json: dict[str, Any] | None = None
    if edit_s is not None and keep:
        total = edit_length(keep)
        in_edit = True
        if note is not None and note.source_s is not None:
            source: float | None = float(note.source_s)
            in_edit = map_to_edit(source, keep) is not None
            pinned = map_to_source(float(edit_s), keep)
            if not (in_edit and pinned is not None and abs(pinned - source) <= 0.01):
                # Its second is from another render's clock: place it by the recording.
                edit_s = edit_join(source, keep)
        else:
            edit_s = max(0.0, min(float(edit_s), total))
            source = map_to_source(edit_s, keep)
        edit_s = max(0.0, min(float(edit_s), total))
        at_json = {
            "edit_s": round(edit_s, 2),
            "source_s": round(source, 3) if source is not None else None,
            "clock": _clock(edit_s),
            "in_edit": in_edit,
        }
        lo, hi = max(0.0, edit_s - window), min(total, edit_s + window)
        span_json = {"from_edit_s": round(lo, 2), "to_edit_s": round(hi, 2)}
        src_lo, src_hi = map_to_source(lo, keep) or 0.0, map_to_source(hi, keep) or 0.0
        first = next((i for i, w in enumerate(words) if float(w["end_s"]) >= src_lo), None)
        last = max((i for i, w in enumerate(words) if float(w["start_s"]) <= src_hi), default=None)
        if first is not None and last is not None and first <= last:
            kept = watched_plan_words(upload.edit_plan, keep)
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
        # Every hold still waiting for a reading, oldest first: when he gave two before
        # the editor read the first, it matches what it was handed to the right one. A
        # typed note is already written down and never waits for a reading on the call.
        "waiting": [
            {
                "id": str(n.id),
                "where": edit_request_to_json(n)["where"],
                "heard": n.request.strip() or None,
            }
            for n in _voice_unread(await sitting_notes(db, ws, sitting.id))
        ],
        "earlier": await _earlier_notes(
            db, ws, upload.id, exclude=note.id if note is not None else None
        ),
    }
    # 3-Oct: what Jennifer's own check found on the render he is watching, so on the
    # call she can say why she is holding it, or what she measured.
    found = qc_json(upload)
    if found is not None:
        payload["check"] = {"state": found["state"], "line": found["line"]}
    if rules:
        payload["rules"] = autoedit.editor_skill() + await learned_rules_text(db, ws)
    return payload


async def learned_rules_text(db: AsyncSession, ws: uuid.UUID) -> str:
    """The rules she learned from his notes on earlier videos, as her voice seat reads
    them: after the skill file, one a line. Empty when there are none."""
    from tce.editorial import editor_rules

    learned = editor_rules.in_block([[str(r.id), r.text] for r in await editor_rules.active_rules(db, ws)])
    if not learned:
        return ""
    # The same cap as her prompts (3-Oct review): the newest rules that fit, never all.
    return (
        "\n\n## Rules you learned from his notes on earlier videos\n"
        + "\n".join(f"- {text}" for _id, text in learned)
    )


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


STALE_SITTING = (
    "The video was edited again after you gave these notes. Open your notes again: they move "
    "to the new version, and then you can make it."
)


async def _must_be_the_video_he_watched(
    db: AsyncSession,
    ws: uuid.UUID,
    sitting: EditSession,
    busy: Callable[[RecordingUpload], str | None] | None,
) -> None:
    """Nothing renders from notes while something else is editing the video, or once
    the file changed under them (1-Oct review: a still-loaded sheet made a batch beside
    an "Edit it again", two renders, and notes pinned on the old file were applied to
    the re-edited one without him hearing that it changed)."""
    upload = await _get_upload(db, ws, sitting.upload_id)
    doing = busy(upload) if busy is not None else None
    if doing:
        raise LibraryError("busy", doing, status=409)
    current_ref, _ = watched_render(upload)
    if current_ref != sitting.render_ref:
        raise LibraryError("stale_render", STALE_SITTING, status=409, extra={"render_ref": current_ref})
    waits = edit_waits_for_him(upload)
    if waits:
        # 1-Oct final review: refused before any job is spent, and it says whose cut it is.
        raise LibraryError("edit_needs_you", waits, status=409)


def _as_of(notes: list[EditingRequest]) -> str | None:
    """The newest pin a read-back covers: a hold pinned after it came after he heard it."""
    times = [n.created_at for n in notes if n.created_at is not None]
    return max(times).isoformat() if times else None


def _parse_as_of(as_of: str | None) -> datetime | None:
    if not (as_of or "").strip():
        return None
    try:
        when = datetime.fromisoformat(str(as_of).strip())
    except ValueError as exc:
        raise LibraryError("bad_as_of", "as_of is not a time this read-back gave", status=400) from exc
    return when.astimezone(UTC).replace(tzinfo=None) if when.tzinfo else when


async def submit_preview(
    db: AsyncSession,
    ws: uuid.UUID,
    session_id: uuid.UUID,
    *,
    busy: Callable[[RecordingUpload], str | None] | None = None,
) -> dict[str, Any]:
    """The read-back and its check code. Nothing changes. Refused (409) while something
    else is editing the video (`busy`, as open_sitting), the file changed under the
    notes, or an earlier re-edit waits for his eyes (edit_waits_for_him).

    `as_of` is the newest pin the read-back saw. Said back with his yes, it lets a yes
    he gave by holding the button (pinned after it) be taken as his answer, not a note."""
    sitting = await get_sitting(db, ws, session_id, seen=True)
    _must_take_notes(sitting)
    await _must_be_the_video_he_watched(db, ws, sitting, busy)
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
        "as_of": _as_of(notes),
    }


async def submit(
    db: AsyncSession,
    ws: uuid.UUID,
    session_id: uuid.UUID,
    *,
    check: str,
    by: str = "ziv",
    busy: Callable[[RecordingUpload], str | None] | None = None,
    as_of: str | None = None,
) -> tuple[EditSession, dict[str, Any]]:
    """He said yes to the read-back. The sitting starts thinking with exactly the notes
    he heard; the caller starts the one batch job.

    A pin with no words at this point was left out (the read-back said so): it is taken
    back now, so it never waits on a sitting that is no longer taking notes (1-Oct
    review: it stayed "listening" for ever, counted as waiting, and could not be dropped).

    `as_of` (the read-back's own, sent with a spoken yes): a hold pinned after the
    read-back that the editor never read is his answer, most likely the yes itself, so
    it is taken back and never changes the check (1-Oct final review: every spoken yes
    was a new note, so the check never matched). Those stay taken back even when the
    check still differs (a note he gave after the read-back and the editor read), and
    the route keeps that when it refuses. Without `as_of` (the sheet's Yes button) any
    note added since the read-back changes the check.
    """
    after = _parse_as_of(as_of)
    if after is not None:
        sitting = await get_sitting(db, ws, session_id)
        _must_take_notes(sitting)
        now = _now()
        for note in _voice_unread(await sitting_notes(db, ws, sitting.id)):
            if note.created_at is not None and note.created_at > after:
                _take_back_as_his_answer(note, None, AFTER_READ_BACK, now)
        await db.flush()
    preview = await submit_preview(db, ws, session_id, busy=busy)
    if (check or "").strip() != preview["check"]:
        raise LibraryError(
            "changed",
            "The notes changed since the read-back, or no check code was given. Read them back again: "
            + preview["read_back"],
            status=409,
            extra={"check": preview["check"], "read_back": preview["read_back"], "as_of": preview["as_of"]},
        )
    sitting = await get_sitting(db, ws, session_id)
    now = _now()
    count = preview["count"]
    left_out = set(preview["left_out"])
    for note in await sitting_notes(db, ws, sitting.id):
        if str(note.id) in left_out:
            note.state = "rejected"
            note.result = {"left_out": LEFT_OUT}
            note.updated_at = note.resolved_at = now
    sitting.state = "thinking"
    sitting.submitted_at = now
    sitting.last_seen = now
    sitting.summary = preview["read_back"]
    sitting.result = {
        "status": f"Reading your {count} note{'s' if count != 1 else ''} on the subscription",
        "notes": [n["id"] for n in preview["notes"]],
        "by": by,
        # Each "make it" is its own job: after a failed one, the same notes ask afresh
        # instead of meeting the failed job again (1-Oct review).
        "attempt": int((sitting.result or {}).get("attempt") or 0) + 1,
    }
    await db.flush()
    return sitting, preview
