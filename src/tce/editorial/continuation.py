"""Continue recording: a take he stopped partway through, sent back to be finished.

25-Nov: "sometimes a user doesn't finish recording a video. When I see on the library
that it is unfinished, I want a button ... it will be out of the library, sent back for
the user to record today, as a tab of 'to continue recording', with the original
script shown, where they left off, and Jennifer pieces back the initial recording and
the continued one."

The flow, end to end:

1. Library, "Send back to finish recording". `preview` reads what he said (the
   transcript) against the script and finds the last line he finished; the team sees
   that line and can tap another before sending. `send_back` records the choice on the
   video (`continuation`, state "waiting"). The video leaves the Library; nothing is
   deleted, and "Take it back" (`take_back`) returns it.
2. Studio, "To continue recording" (`waiting_list`, read by /recording-queue). The
   original script, the lines already said marked done, the reader on the line he
   says again first. Opening it makes a take set linked to the video
   (`sessions.create_session(continues_upload_id=...)`, state "recording").
3. Finish (`sessions.finalize_session`) joins the original file and the new clips into
   one video. The original is superseded (kept for history), the joined video carries
   where the seam is, and Jennifer edits it as one video, told about the seam
   (`jennifer_context`).

A video that has gone out (a post posted or scheduled, or the topic published) never
comes back: the rule that a posted video never returns to the client's list holds here.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.editorial import (
    RecordingPacket,
    RecordingUpload,
    TopicCandidate,
    VideoPublication,
)
from tce.models.recording_session import RecordingSession
from tce.production import agent_talks

# States in which the video is out of the Library and in the studio's tab.
CONTINUING_STATES = ("waiting", "recording")

TAB_LABEL = "To continue recording"
BUTTON_LABEL = "Send back to finish recording"

# A video that is being transcribed, cut, rendered or checked is not sent back mid-step.
_BUSY_STATUSES = ("transcribing", "transcribed", "proofreading", "planned", "rendering", "checking")
_OUT_STATUSES = ("posted", "scheduled")
# A take with no script (or a filmed call) has no script to continue from.
_NO_SCRIPT_SOURCES = (agent_talks.SOURCE, agent_talks.SOLO_SOURCE)

# A script line counts as said when this share of its words is heard, in a run of the
# transcript about as long as the line, AND its last word is heard in that run: a line
# he stopped in the middle of ("but the client is...") is the line he did not finish.
# Loose otherwise on purpose: the recogniser mishears words and he rephrases; the team
# confirms the line before anything is sent.
_SAID_SHARE = 0.6
_WORD = re.compile(r"[\w']+")


class ContinuationError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra: dict[str, Any] = {}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _words(text: str | None) -> list[str]:
    return [w.strip("'") for w in _WORD.findall((text or "").lower()) if w.strip("'")]


def is_continuing(upload: RecordingUpload) -> bool:
    return str((upload.continuation or {}).get("state") or "") in CONTINUING_STATES


# --------------------------------------------------------------- where he stopped


def resume_point(
    script_phrases: list[str] | None, transcript: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """The last script line he finished, read from what was heard.

    Walks the script in order with a pointer through the transcript's words. A line is
    said when a run of words after the pointer, as long as the line, holds at least
    `_SAID_SHARE` of its words; the pointer then moves past that run, so a later line
    is only found after an earlier one. A line he skipped does not stop the walk. A line
    whose last word was never heard is one he stopped in the middle of: not said.

    Returns {"resume_index": first line still to say, "last_said_index": -1 for none,
    "detected": False when there was nothing heard to read}.
    """
    lines = [str(p or "") for p in (script_phrases or [])]
    heard = [w for seg in (transcript or []) for w in _words(str(seg.get("text") or ""))]
    if not heard or not lines:
        return {"resume_index": 0, "last_said_index": -1, "detected": False}
    pointer = 0
    last = -1
    for index, line in enumerate(lines):
        want = _words(line)
        if not want:
            continue
        need = set(want)
        ending = want[-1]
        span = max(len(want), 3)
        best, best_end = 0.0, -1
        for start in range(pointer, len(heard)):
            run = heard[start : start + span + 2]
            if ending not in run:
                continue
            share = len(need & set(run)) / len(need)
            if share > best:
                best, best_end = share, start + run.index(ending) + 1
            if share >= 1.0:
                break
        if best >= _SAID_SHARE:
            last = index
            pointer = best_end
    return {"resume_index": last + 1, "last_said_index": last, "detected": True}


# ------------------------------------------------------------------ who may go back


async def _is_out(db: AsyncSession, ws: uuid.UUID, upload: RecordingUpload) -> bool:
    """Posted, scheduled, or its topic published: then it never comes back."""
    if upload.candidate_id:
        status = (
            await db.execute(
                select(TopicCandidate.status).where(
                    TopicCandidate.id == upload.candidate_id, TopicCandidate.workspace_id == ws
                )
            )
        ).scalar_one_or_none()
        if status == "published":
            return True
        takes = select(RecordingUpload.id).where(
            RecordingUpload.workspace_id == ws, RecordingUpload.candidate_id == upload.candidate_id
        )
    else:
        takes = select(RecordingUpload.id).where(RecordingUpload.id == upload.id)
    out = (
        await db.execute(
            select(VideoPublication.id).where(
                VideoPublication.workspace_id == ws,
                VideoPublication.upload_id.in_(takes),
                VideoPublication.status.in_(_OUT_STATUSES),
            ).limit(1)
        )
    ).scalar_one_or_none()
    return out is not None


def can_offer(upload: RecordingUpload) -> bool:
    """Whether the card shows the button (the server checks `_is_out` on the tap)."""
    return bool(
        upload.storage_path
        and upload.packet_id
        and upload.source not in _NO_SCRIPT_SOURCES
        and upload.status not in (*_BUSY_STATUSES, "superseded")
        and upload.archived_at is None
        and not is_continuing(upload)
        and str((upload.continuation or {}).get("state") or "") != "joined"
    )


async def _load(db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID) -> RecordingUpload:
    row = (
        await db.execute(
            select(RecordingUpload).where(
                RecordingUpload.id == upload_id, RecordingUpload.workspace_id == ws
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ContinuationError("not_found", "That recording was not found.", status=404)
    return row


async def _packet(db: AsyncSession, ws: uuid.UUID, upload: RecordingUpload) -> RecordingPacket:
    packet = None
    if upload.packet_id:
        packet = (
            await db.execute(
                select(RecordingPacket).where(
                    RecordingPacket.id == upload.packet_id, RecordingPacket.workspace_id == ws
                )
            )
        ).scalar_one_or_none()
    if packet is None or not (packet.script_phrases or []):
        raise ContinuationError(
            "no_script", "This recording has no script to continue from.", status=422
        )
    return packet


async def _must_offer(db: AsyncSession, ws: uuid.UUID, upload: RecordingUpload) -> None:
    if is_continuing(upload):
        raise ContinuationError("already_sent", "This video is already waiting to be finished.")
    if not can_offer(upload):
        raise ContinuationError(
            "not_now",
            "This video cannot be sent back right now: it is being edited, archived, or "
            "has no script.",
        )
    if await _is_out(db, ws, upload):
        raise ContinuationError(
            "already_out", "This video has been posted or scheduled, so it stays where it is."
        )


# ---------------------------------------------------------------------- the actions


async def preview(db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID) -> dict[str, Any]:
    """What the confirm sheet shows: the script, and the line we think he stopped on."""
    upload = await _load(db, ws, upload_id)
    await _must_offer(db, ws, upload)
    packet = await _packet(db, ws, upload)
    point = resume_point(packet.script_phrases, upload.transcript)
    return {
        "upload_id": str(upload.id),
        "lines": list(packet.script_phrases or []),
        **point,
    }


async def send_back(
    db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID, *, last_said_index: int | None = None
) -> RecordingUpload:
    """Out of the Library, into the studio's "To continue recording" tab.

    `last_said_index` is the line the team confirmed (or tapped instead): -1 for none,
    so he starts at the top. Left out, the detected line is used.
    """
    upload = await _load(db, ws, upload_id)
    await _must_offer(db, ws, upload)
    packet = await _packet(db, ws, upload)
    lines = list(packet.script_phrases or [])
    point = resume_point(lines, upload.transcript)
    detected = point["last_said_index"]
    last = detected if last_said_index is None else int(last_said_index)
    if last < -1 or last >= len(lines):
        raise ContinuationError("bad_line", "That line is not in the script.", status=422)
    if last == len(lines) - 1:
        raise ContinuationError(
            "nothing_left",
            "Every line of the script was said, so there is nothing left to record.",
            status=422,
        )
    upload.continuation = {
        "state": "waiting",
        "sent_at": _now().isoformat(),
        "resume_index": last + 1,
        "repeat_line": lines[last] if last >= 0 else None,
        "detected": point["detected"] and last == detected,
        "session_id": None,
        "joined_upload_id": None,
    }
    await db.flush()
    return upload


async def take_back(db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID) -> RecordingUpload:
    """Sent back by mistake: the video returns to the Library as it was."""
    upload = await _load(db, ws, upload_id)
    if not is_continuing(upload):
        raise ContinuationError("not_sent", "This video is not waiting to be finished.")
    session_id = (upload.continuation or {}).get("session_id")
    if session_id:
        session = await db.get(RecordingSession, uuid.UUID(str(session_id)))
        if session is not None and session.status in ("finalizing", "uploaded"):
            raise ContinuationError(
                "already_joined", "The rest is already recorded and being joined to it."
            )
    upload.continuation = {**(upload.continuation or {}), "state": "cancelled"}
    await db.flush()
    return upload


def library_json(upload: RecordingUpload, title: str) -> dict[str, Any]:
    """The Library's "Sent back to finish" strip, one row per video."""
    cont = upload.continuation or {}
    return {
        "upload_id": str(upload.id),
        "title": title,
        "sent_at": cont.get("sent_at"),
        "state": cont.get("state"),
        "repeat_line": cont.get("repeat_line"),
    }


async def waiting_list(db: AsyncSession, ws: uuid.UUID) -> list[dict[str, Any]]:
    """The studio's "To continue recording" tab: oldest sent first."""
    uploads = [
        u
        for u in (
            await db.execute(
                select(RecordingUpload)
                .where(RecordingUpload.workspace_id == ws, RecordingUpload.continuation.is_not(None))
                .order_by(RecordingUpload.created_at.asc())
            )
        ).scalars()
        if is_continuing(u)
    ]
    uploads.sort(key=lambda u: str((u.continuation or {}).get("sent_at") or ""))
    items: list[dict[str, Any]] = []
    for upload in uploads:
        candidate = await db.get(TopicCandidate, upload.candidate_id) if upload.candidate_id else None
        packet = await db.get(RecordingPacket, upload.packet_id) if upload.packet_id else None
        if candidate is None or packet is None or packet.workspace_id != ws:
            continue
        cont = upload.continuation or {}
        session_id = cont.get("session_id")
        session = await db.get(RecordingSession, uuid.UUID(str(session_id))) if session_id else None
        active = session if session is not None and session.status not in ("uploaded", "failed") else None
        items.append(
            {
                "continue_upload_id": str(upload.id),
                "candidate_id": str(candidate.id),
                "packet_id": str(packet.id),
                "packet_version": packet.version,
                "title": candidate.title,
                "big_idea": candidate.lesson,
                "bullets": packet.bullets or [],
                "script_phrases": packet.script_phrases or [],
                # The opening was already chosen and said: the rest has no hook step.
                "hook_options": [],
                "selected_hook_id": packet.selected_hook_id,
                "beats": packet.beats or [],
                "interviewer_prompt": packet.interviewer_prompt,
                "packet_format": "v2" if packet.hook_options and packet.beats else "legacy",
                "resume_index": int(cont.get("resume_index") or 0),
                "repeat_line": cont.get("repeat_line"),
                "sent_at": cont.get("sent_at"),
                "recorded_s": upload.duration_s,
                "active_session_id": str(active.id) if active else None,
                "active_session_status": active.status if active else None,
            }
        )
    return items


def jennifer_context(upload: RecordingUpload) -> str:
    """What the editor is told about a video recorded in two parts."""
    cont = upload.continuation or {}
    if cont.get("state") != "joined_result":
        return ""
    seam = float(cont.get("seam_s") or 0)
    minutes, seconds = divmod(int(round(seam)), 60)
    text = (
        f"This video was recorded in two parts and joined at {minutes}:{seconds:02d}: he "
        "stopped partway through, and recorded the rest of the script later. Edit it as "
        "one video. The picture or light may change at the join; that is expected."
    )
    if cont.get("repeat_line"):
        text += (
            f' He starts the second part by saying his last line again ("{cont["repeat_line"]}"). '
            "Keep the complete take after the join and cut the earlier one, so the line is "
            "heard once and the video flows across the join. This restart is not a meaning "
            "problem."
        )
    return text
