"""/production routes: recording docs, uploads, edit plans, render, publications, activity.

Every route depends on `require_private_workspace` and filters
`Model.workspace_id == ws` explicitly.

Nothing here publishes, posts or calls a metered API:
- export: Google Doc via the server's `gws` CLI when enabled, else a private .docx
- transcription: local faster-whisper worker, else `unavailable` with the reason
- render: local ffmpeg, else `unavailable`
- steps never auto-run after upload; the editor starts each one
- a running transcribe/render step holds a lease in `job_ids` (attempt, owning process,
  heartbeat). A step whose process died (restart, crash) is marked `interrupted` once
  its lease is provably dead: never while this process still runs it, and never while
  another process keeps heartbeating it. The original upload is kept and the editor
  retries with the same button. A superseded attempt can no longer write its result.

Publication receipts dedupe on (workspace, platform, external_post_id): a repeat POST
returns HTTP 200 with `{"duplicate": true, "publication": <existing row>}`; a new
receipt returns 201 with `"duplicate": false`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.api.private_access import require_private_workspace
from tce.db.session import get_db
from tce.editorial import library as library_service
from tce.editorial.common import ORIGIN_TECHNICAL_VALIDATION
from tce.models.editorial import (
    EvidenceCollectionRun,
    PublicationReceipt,
    RecordingPacket,
    RecordingUpload,
    TopicCandidate,
    VideoPublication,
)
from tce.models.llm_job import LLMJob
from tce.models.recording_session import RecordingClip, RecordingSession
from tce.production import agent_talks, autoedit, media, publishing, relisten, tightcut, wordbox
from tce.production import sessions as recording_sessions
from tce.production.export import GoogleDocsClient, GwsDocsClient, export_packet_durable
from tce.production.retakes import (
    build_cues,
    fmt_ts,
    frame_keep,
    is_word_level,
    map_to_edit,
    plan_edit,
    to_ass,
    to_srt,
    to_vtt,
    uncut_plan,
)
from tce.settings import settings

router = APIRouter(prefix="/production", tags=["production"])

PLATFORMS = ("facebook", "linkedin", "instagram", "youtube", "tiktok", "newsletter", "other")
_CHUNK = 1024 * 1024
_background: set[asyncio.Task] = set()

BUSY_STATUSES = ("transcribing", "rendering")
# Sitting notes that never became a change: taken back (rejected), or still waiting for
# "make it". A typed request's history on the video leaves them out (1-Oct review).
SITTING_NOTES_NEVER_MADE = ("rejected", "listening", "held")
PROCESS_OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
LEASE_PREFIX = "media-lease|"
LEASE_HEARTBEAT_S = 20.0
LEASE_TTL_S = 120.0
_active_attempts: set[str] = set()  # attempts running in THIS process
_STEP_LABEL = {
    "transcribing": ("transcription", "Transcribe"),
    "rendering": ("the render", "Render edit"),
}


class RecordingSessionCreate(BaseModel):
    candidate_id: uuid.UUID
    packet_id: uuid.UUID
    device_meta: dict[str, Any] = Field(default_factory=dict)


class RecordingClipCreate(BaseModel):
    local_clip_id: str = Field(min_length=1, max_length=120)
    mime_type: str = Field(min_length=1, max_length=120)
    extension: str = Field(min_length=1, max_length=12)


class RecordingClipFinish(BaseModel):
    active_duration_s: float = Field(ge=0)
    take_markers: list[dict[str, Any]] = Field(default_factory=list)


class RecordingSessionFinish(BaseModel):
    selected_clip_ids: list[uuid.UUID] = Field(min_length=1)


def _recording_root() -> Path:
    return Path(settings.evidence_upload_dir) / "sessions"


def _clip_json(row: RecordingClip) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "session_id": str(row.session_id),
        "local_clip_id": row.local_clip_id,
        "position": row.position,
        "status": row.status,
        "mime_type": row.mime_type,
        "duration_s": row.duration_s,
        "active_duration_s": row.active_duration_s,
        "chunk_count": row.chunk_count,
        "take_markers": row.take_markers or [],
        "timing_meta": row.timing_meta or {},
        "error_detail": row.error_detail,
    }


async def _recording_session_json(db: AsyncSession, row: RecordingSession) -> dict[str, Any]:
    clips = list(
        (
            await db.execute(
                select(RecordingClip)
                .where(
                    RecordingClip.workspace_id == row.workspace_id,
                    RecordingClip.session_id == row.id,
                )
                .order_by(RecordingClip.position)
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": str(row.id),
        "candidate_id": str(row.candidate_id),
        "packet_id": str(row.packet_id),
        "packet_version": row.packet_version,
        "retake_index": row.retake_index,
        "status": row.status,
        "active_duration_s": row.active_duration_s,
        "selected_clip_ids": row.selected_clip_ids or [],
        "timeline_map": row.timeline_map or [],
        "canonical_upload_id": str(row.canonical_upload_id) if row.canonical_upload_id else None,
        "device_meta": row.device_meta or {},
        "error_detail": row.error_detail,
        "clips": [_clip_json(clip) for clip in clips],
    }


# ---------------------------------------------------------------------------
# Injection points (tests replace these)


def session_factory():
    from tce.db.session import async_session

    return async_session


def google_client() -> GoogleDocsClient | None:
    if settings.production_google_export.strip().lower() == "gws":
        return GwsDocsClient(settings.production_gws_binary)
    return None


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


# ---------------------------------------------------------------------------
# Step leases and restart recovery


def _lease_entry(step: str, attempt: str, at: datetime) -> str:
    return f"{LEASE_PREFIX}{step}|{attempt}|{PROCESS_OWNER}|{at.isoformat()}"


def parse_lease(job_ids: list[Any] | None) -> dict[str, Any] | None:
    for entry in reversed(job_ids or []):
        if isinstance(entry, str) and entry.startswith(LEASE_PREFIX):
            try:
                step, attempt, owner, at = entry[len(LEASE_PREFIX) :].split("|")
                return {
                    "step": step,
                    "attempt": attempt,
                    "owner": owner,
                    "heartbeat_at": datetime.fromisoformat(at),
                }
            except ValueError:
                return None
    return None


def _with_lease(job_ids: list[Any] | None, entry: str | None) -> list[Any]:
    kept = [j for j in job_ids or [] if not (isinstance(j, str) and j.startswith(LEASE_PREFIX))]
    return kept + ([entry] if entry else [])


def _lease_is_dead(row: RecordingUpload, now: datetime, *, startup: bool) -> bool:
    lease = parse_lease(row.job_ids)
    if lease is None:
        # Started before leases existed. At startup no process can still own it (the
        # previous server is gone); later, only a long silence proves it.
        if startup:
            return True
        return row.updated_at is not None and now - row.updated_at > timedelta(seconds=LEASE_TTL_S)
    if lease["attempt"] in _active_attempts:
        return False
    if lease["owner"] == PROCESS_OWNER:
        return True  # this process started it and no longer runs it
    return now - lease["heartbeat_at"] > timedelta(seconds=LEASE_TTL_S)


def _remove_partial_render(row: RecordingUpload) -> None:
    src = Path(row.storage_path)
    for part in src.parent.glob(f".{src.stem}-edited.rendering*"):
        part.unlink(missing_ok=True)
    for band in src.parent.glob(f".{src.stem}-captions*"):  # caption images of a dead render
        shutil.rmtree(band, ignore_errors=True)


async def reconcile_interrupted_uploads(
    db: AsyncSession, ws: uuid.UUID | None = None, *, startup: bool = False
) -> list[uuid.UUID]:
    """Turn busy uploads whose step died into a visible, retryable `interrupted` state."""
    now = _utcnow()
    stmt = select(RecordingUpload).where(RecordingUpload.status.in_(BUSY_STATUSES))
    if ws is not None:
        stmt = stmt.where(RecordingUpload.workspace_id == ws)
    changed: list[uuid.UUID] = []
    for row in (await db.execute(stmt)).scalars().all():
        if not _lease_is_dead(row, now, startup=startup):
            continue
        lease = parse_lease(row.job_ids)
        what, button = _STEP_LABEL.get(row.status, ("the step", "the step button"))
        if row.status == "rendering":
            _remove_partial_render(row)
        beat = f" (last heartbeat {lease['heartbeat_at']:%H:%M} UTC)" if lease else ""
        if Path(row.storage_path).exists():
            row.status = "interrupted"
            row.status_detail = (
                f"Interrupted: {what} stopped when the server restarted{beat}. "
                f"The original upload is kept. Click {button} to retry."
            )[:500]
        else:
            row.status = "failed"
            row.status_detail = (
                f"Interrupted: {what} stopped when the server restarted{beat}, and the "
                "original upload is missing from storage. Upload the file again."
            )[:500]
        row.job_ids = _with_lease(row.job_ids, None)
        changed.append(row.id)
    if changed:
        await db.commit()
    return changed


async def recover_media_on_startup() -> None:
    """Startup wiring: sweep now, then once more after a lease can have expired."""
    import structlog

    log = structlog.get_logger()
    for delay, startup in ((0.0, True), (LEASE_TTL_S + 5, False)):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with session_factory()() as db:
                ids = await reconcile_interrupted_uploads(db, startup=startup)
            if ids:
                log.info("production.media_interrupted", count=len(ids), ids=[str(i) for i in ids])
        except Exception:
            log.warning("production.media_recovery_failed", exc_info=True)
        if startup:
            # After the sweep has marked dead steps: pick up edits and requests the
            # restart cut short, so nothing he asked for waits for a click.
            await resume_auto_work()


# ---------------------------------------------------------------------------
# Lookups


async def _candidate(db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID) -> TopicCandidate:
    row = (
        await db.execute(
            select(TopicCandidate).where(
                TopicCandidate.id == candidate_id, TopicCandidate.workspace_id == ws
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return row


async def _packet(db: AsyncSession, ws: uuid.UUID, packet_id: uuid.UUID) -> RecordingPacket:
    row = (
        await db.execute(
            select(RecordingPacket).where(
                RecordingPacket.id == packet_id, RecordingPacket.workspace_id == ws
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Packet not found")
    return row


async def _upload(db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID) -> RecordingUpload:
    row = (
        await db.execute(
            select(RecordingUpload).where(
                RecordingUpload.id == upload_id, RecordingUpload.workspace_id == ws
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    return row


def upload_json(u: RecordingUpload) -> dict[str, Any]:
    plan = u.edit_plan or None
    return {
        "id": str(u.id),
        "candidate_id": str(u.candidate_id),
        "packet_id": str(u.packet_id) if u.packet_id else None,
        "original_filename": u.original_filename,
        "sha256": u.sha256,
        "duration_s": u.duration_s,
        "status": u.status,
        "status_detail": u.status_detail,
        "has_transcript": bool(u.transcript),
        "transcript": u.transcript,
        "edit_plan": plan,
        "captions_available": bool(plan and plan.get("keep")),
        "captions_srt_url": f"/api/v1/production/uploads/{u.id}/captions.srt" if plan else None,
        "captions_vtt_url": f"/api/v1/production/uploads/{u.id}/captions.vtt" if plan else None,
        "video_url": f"/api/v1/production/uploads/{u.id}/video" if u.storage_path else None,
        "edited_url": f"/api/v1/production/uploads/{u.id}/edited" if u.edited_path else None,
        "render_ref": u.render_ref,
        # 3-Oct: "agent_talk" for a filmed voice call with an agent, null for a walk.
        "source": u.source,
        "agent_name": u.agent_name,
        "created_at": _iso(u.created_at),
        "updated_at": _iso(u.updated_at),
    }


def publication_json(p: PublicationReceipt) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "candidate_id": str(p.candidate_id),
        "packet_id": str(p.packet_id) if p.packet_id else None,
        "platform": p.platform,
        "external_post_id": p.external_post_id,
        "url": p.url,
        "published_at": _iso(p.published_at),
        "final_text": p.final_text,
        "outcome": p.outcome or {},
        "recorded_by": p.recorded_by,
        "created_at": _iso(p.created_at),
    }


# ---------------------------------------------------------------------------
# Export


@router.post("/packets/{packet_id}/export")
async def export_packet_route(
    packet_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    packet = await _packet(db, ws, packet_id)
    candidate = (
        await db.execute(
            select(TopicCandidate).where(
                TopicCandidate.id == packet.candidate_id, TopicCandidate.workspace_id == ws
            )
        )
    ).scalar_one_or_none()
    try:
        result = await export_packet_durable(
            db,
            packet,
            candidate,
            client=google_client(),
            docx_dir=Path(settings.evidence_upload_dir) / str(ws) / "exports",
            docx_url=f"/api/v1/production/packets/{packet.id}/docx",
            team_emails=settings.production_doc_team_emails.split(","),
        )
    except Exception as exc:  # Google call failed mid-way: record it honestly
        packet.google_doc_access = {
            "intended": "restricted: owner only, no link sharing",
            "verified": False,
            "detail": f"Google export failed: {str(exc)[:300]}",
            "status": "failed",
        }
        await db.commit()
        raise HTTPException(status_code=502, detail=packet.google_doc_access["detail"]) from exc
    await db.commit()
    return result


@router.get("/packets/{packet_id}/docx")
async def packet_docx(
    packet_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    packet = await _packet(db, ws, packet_id)
    path = (
        Path(settings.evidence_upload_dir)
        / str(ws)
        / "exports"
        / f"packet-{packet.id}-v{packet.version}.docx"
    )
    if not path.exists():
        raise HTTPException(
            status_code=404, detail="No .docx generated yet; export the packet first"
        )
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
    )


# ---------------------------------------------------------------------------
# Recording upload


def _allowed(upload: UploadFile) -> bool:
    allowed = {
        t.strip().lower() for t in settings.production_allowed_media_types.split(",") if t.strip()
    }
    ctype = (upload.content_type or "").split(";")[0].strip().lower()
    return ctype in allowed


@router.post("/candidates/{candidate_id}/recording", status_code=201)
async def upload_recording(
    candidate_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    candidate = await _candidate(db, ws, candidate_id)
    limit = settings.production_max_upload_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + 1_000_000:
        raise HTTPException(
            status_code=413, detail=f"File is larger than the {limit // 1_000_000} MB limit"
        )
    if not _allowed(file):
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported media type {file.content_type or 'unknown'}; "
                "upload a video or audio file"
            ),
        )

    folder = Path(settings.evidence_upload_dir) / str(ws) / str(candidate.id)
    folder.mkdir(parents=True, exist_ok=True)
    upload_id = uuid.uuid4()
    suffix = Path(file.filename or "").suffix.lower()[:10] or ".bin"
    tmp = folder / f".{upload_id}.part"
    digest = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as fh:
            while chunk := await file.read(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is larger than the {limit // 1_000_000} MB limit",
                    )
                digest.update(chunk)
                fh.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty file")
    sha = digest.hexdigest()

    existing = (
        await db.execute(
            select(RecordingUpload).where(
                RecordingUpload.workspace_id == ws, RecordingUpload.sha256 == sha
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        tmp.unlink(missing_ok=True)
        if existing.candidate_id != candidate.id:
            raise HTTPException(
                status_code=409,
                detail="This exact file is already attached to a different idea",
            )
        return JSONResponse(
            status_code=200, content={**upload_json(existing), "deduplicated": True}
        )

    final = folder / f"{upload_id}{suffix}"
    os.replace(tmp, final)

    previous = (
        (
            await db.execute(
                select(RecordingUpload).where(
                    RecordingUpload.workspace_id == ws,
                    RecordingUpload.candidate_id == candidate.id,
                    RecordingUpload.status != "superseded",
                )
            )
        )
        .scalars()
        .all()
    )
    packet = (
        await db.execute(
            select(RecordingPacket)
            .where(RecordingPacket.workspace_id == ws, RecordingPacket.candidate_id == candidate.id)
            .order_by(RecordingPacket.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    row = RecordingUpload(
        id=upload_id,
        workspace_id=ws,
        candidate_id=candidate.id,
        packet_id=packet.id if packet else None,
        original_filename=(file.filename or "recording")[:300],
        storage_path=str(final),
        sha256=sha,
        status="uploaded",
        status_detail=(
            f"Uploaded {size // 1_000_000} MB. Retake set {len(previous) + 1}. "
            "Click Transcribe to start (nothing runs automatically)."
        ),
        job_ids=[],
    )
    db.add(row)
    now = _utcnow()
    for prev in previous:
        prev.status = "superseded"
        prev.status_detail = (
            f"Superseded by retake set {len(previous) + 1} ({row.original_filename}) "
            f"at {now:%Y-%m-%d %H:%M} UTC; kept for history"
        )
    if candidate.status not in ("published",):
        candidate.status = "recorded"
    await db.commit()
    await db.refresh(row)
    duration = await media.probe_duration(final)
    if duration:
        row.duration_s = duration
        await db.commit()
        await db.refresh(row)
    return {
        **upload_json(row),
        "deduplicated": False,
        "superseded_ids": [str(p.id) for p in previous],
    }


@router.get("/candidates/{candidate_id}/recordings")
async def list_recordings(
    candidate_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _candidate(db, ws, candidate_id)
    await reconcile_interrupted_uploads(db, ws)
    rows = (
        (
            await db.execute(
                select(RecordingUpload)
                .where(
                    RecordingUpload.workspace_id == ws, RecordingUpload.candidate_id == candidate_id
                )
                .order_by(RecordingUpload.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"uploads": [upload_json(r) for r in rows]}


@router.get("/uploads/{upload_id}")
async def get_upload(
    upload_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    await reconcile_interrupted_uploads(db, ws)
    return upload_json(await _upload(db, ws, upload_id))


# ---------------------------------------------------------------------------
# Transcribe, plan, render


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _load(s: AsyncSession, upload_id: uuid.UUID, ws: uuid.UUID) -> RecordingUpload:
    return (
        await s.execute(
            select(RecordingUpload).where(
                RecordingUpload.id == upload_id, RecordingUpload.workspace_id == ws
            )
        )
    ).scalar_one()


def _owns(row: RecordingUpload, attempt: str) -> bool:
    lease = parse_lease(row.job_ids)
    return lease is not None and lease["attempt"] == attempt and row.status in BUSY_STATUSES


async def _set_status(
    upload_id: uuid.UUID, ws: uuid.UUID, status: str | None, detail: str, attempt: str
) -> bool:
    """Write progress or an outcome only while this attempt still holds the lease."""
    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        if not _owns(row, attempt):
            return False
        if status:
            row.status = status
        row.status_detail = detail[:500]
        if status not in BUSY_STATUSES:
            row.job_ids = _with_lease(row.job_ids, None)
        await s.commit()
        return True


async def _heartbeat(upload_id: uuid.UUID, ws: uuid.UUID, step: str, attempt: str) -> None:
    while True:
        await asyncio.sleep(LEASE_HEARTBEAT_S)
        async with session_factory()() as s:
            row = await _load(s, upload_id, ws)
            if not _owns(row, attempt):
                return
            row.job_ids = _with_lease(row.job_ids, _lease_entry(step, attempt, _utcnow()))
            await s.commit()


def _claim(row: RecordingUpload, status: str, detail: str) -> str:
    attempt = uuid.uuid4().hex[:12]
    _active_attempts.add(attempt)  # before commit: a concurrent read must see it as alive
    row.status = status
    row.status_detail = detail
    row.job_ids = _with_lease(row.job_ids, _lease_entry(status, attempt, _utcnow()))
    return attempt


async def _run_leased(upload_id: uuid.UUID, ws: uuid.UUID, step: str, attempt: str, work) -> None:
    # `work` is a factory, so a step that never starts leaves no unawaited coroutine
    beat = asyncio.create_task(_heartbeat(upload_id, ws, step, attempt))
    try:
        await work()
    finally:
        beat.cancel()
        _active_attempts.discard(attempt)


async def _run_transcription(upload_id: uuid.UUID, ws: uuid.UUID, attempt: str) -> None:
    async def report(text: str) -> None:
        await _set_status(upload_id, ws, "transcribing", text, attempt)

    try:
        async with session_factory()() as s:
            row = await _load(s, upload_id, ws)
            path, duration = row.storage_path, row.duration_s
        timings = await media.transcribe_local(
            path,
            ws_url=settings.production_transcribe_ws_url,
            language=settings.production_transcribe_language or None,
            duration_s=duration,
            on_status=report,
        )
        async with session_factory()() as s:
            row = await _load(s, upload_id, ws)
            if not _owns(row, attempt):
                return  # superseded by a retry; its result is the one that counts
            _new_transcript(row, timings)
            row.status = "transcribed"
            precise = bool(timings) and all(item.get("precision") == "word" for item in timings)
            row.status_detail = (
                f"Transcribed {len(timings)} {'words' if precise else 'segments'} locally. "
                + (
                    "Word timestamps are available. "
                    if precise
                    else "Timing uses whole-second segment starts, so cuts are approximate. "
                )
                + "Click Plan edit to find retakes."
            )
            row.job_ids = _with_lease(row.job_ids, None)
            await s.commit()
    except media.StepUnavailableError as exc:
        await _set_status(upload_id, ws, "unavailable", str(exc), attempt)
    except Exception as exc:
        await _set_status(
            upload_id, ws, "failed", f"Transcription failed: {str(exc)[:400]}", attempt
        )


@router.post("/uploads/{upload_id}/transcribe", status_code=202)
async def transcribe_upload(
    upload_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    await reconcile_interrupted_uploads(db, ws)
    row = await _upload(db, ws, upload_id)
    if row.status in BUSY_STATUSES:
        return upload_json(row)
    if not Path(row.storage_path).exists():
        raise HTTPException(
            status_code=409, detail="The original upload is missing from storage; upload it again"
        )
    if not settings.production_transcribe_ws_url:
        row.status = "unavailable"
        row.status_detail = (
            "Transcription unavailable: no local transcription worker is configured "
            "on this server. "
            "Paid transcription is intentionally not used."
        )
        await db.commit()
        await db.refresh(row)
        return upload_json(row)
    attempt = _claim(
        row,
        "transcribing",
        f"Queued for local transcription ({media.fmt_duration(row.duration_s)} file)",
    )
    try:
        await db.commit()
    except BaseException:
        _active_attempts.discard(attempt)
        raise
    await db.refresh(row)
    _spawn(
        _run_leased(
            row.id, ws, "transcribing", attempt, lambda: _run_transcription(row.id, ws, attempt)
        )
    )
    return upload_json(row)


def _new_transcript(row: RecordingUpload, words: list[dict[str, Any]]) -> None:
    """A transcript from the recogniser or from outside: not heard a second time yet."""
    row.transcript = words
    if (row.edit_plan or {}).get("second_listen"):
        plan = dict(row.edit_plan)
        plan.pop("second_listen")
        row.edit_plan = plan


class PlanEditRequest(BaseModel):
    # Optional externally produced timings [{start_s, end_s, text}] (e.g. a manual transcript)
    transcript: list[dict[str, Any]] | None = None
    pause_threshold_s: float | None = Field(default=None, ge=0.2, le=10)


@router.post("/uploads/{upload_id}/plan-edit")
async def plan_edit_route(
    upload_id: uuid.UUID,
    body: PlanEditRequest | None = None,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    row = await _upload(db, ws, upload_id)
    body = body or PlanEditRequest()
    if body.transcript is not None:
        _new_transcript(row, body.transcript)
    if not row.transcript:
        raise HTTPException(
            status_code=409, detail="No transcript yet. Transcribe the recording first."
        )
    await _compute_plan(db, ws, row, pause_threshold_s=body.pause_threshold_s)
    await db.commit()
    await db.refresh(row)
    return upload_json(row)


def aside_names() -> list[str]:
    return [n.strip() for n in settings.production_aside_names.split(",") if n.strip()]


async def _levels(path: str | Path | None, hiss: bool = False) -> list[float] | None:
    """10 ms levels of the recording, read once per file (about 5 s for a 10-minute walk)
    and kept beside it, keyed by size and time, so re-planning after an editing request is
    instant. `hiss`: only the band above 3.5 kHz, where an "s" shows. None when the audio
    cannot be read."""
    ff = media.ffmpeg_path()
    src = Path(path) if path else None
    if not ff or src is None or not src.exists():
        return None
    cache = src.with_name(f".{src.stem}-{'hiss' if hiss else 'levels'}.txt")
    stat = src.stat()
    key = f"{stat.st_size}:{int(stat.st_mtime)}"
    levels: list[float] | None = None
    try:
        if cache.exists():
            head, _, body = cache.read_text(encoding="utf-8").partition("\n")
            if head == key:
                levels = [float(x) for x in body.split()]
    except (OSError, ValueError):
        levels = None
    if levels is None:
        try:
            levels = await tightcut.measure_levels(str(src), ff, hiss=hiss)
        except RuntimeError:
            return None
        try:  # written aside and renamed: a crash never leaves a short envelope behind
            part = cache.with_name(cache.name + ".part")
            part.write_text(key + "\n" + " ".join(f"{v:.1f}" for v in levels), encoding="utf-8")
            os.replace(part, cache)
        except OSError:
            pass
    return levels or None


async def _speech_activity(path: str | Path | None) -> tightcut.Activity | None:
    """Where he speaks in the recording, from a 10 ms level reading (28-Sep). None when
    the audio cannot be read: the plan then falls back to the padded cut."""
    levels = await _levels(path)
    return tightcut.find_activity(levels) if levels else None


async def talk_voices(
    row: RecordingUpload, words: list[dict[str, Any]] | None = None
) -> agent_talks.Voices | None:
    """Who says each word of an agent talk (3-Oct), from the call's own transcript; None
    for a walk. Lining up a long talk takes a moment, so it runs off the event loop."""
    if row.source != agent_talks.SOURCE:
        return None
    heard = list(words if words is not None else row.transcript or [])
    return await asyncio.to_thread(
        agent_talks.voices, heard, list(row.call_transcript or []), row.agent_name or "the agent"
    )


async def _compute_plan(
    db: AsyncSession, ws: uuid.UUID, row: RecordingUpload, *, pause_threshold_s: float | None = None
) -> None:
    """Plan the cut from the transcript. Cuts and restores an editing request made
    (edit_plan.overrides), the editor's review and the proofread record survive every
    re-plan. Word timings are cut tight on the audio (28-Sep)."""
    previous = dict(row.edit_plan or {})
    phrases: list[str] = []
    if row.packet_id:
        packet = (
            await db.execute(
                select(RecordingPacket).where(
                    RecordingPacket.id == row.packet_id, RecordingPacket.workspace_id == ws
                )
            )
        ).scalar_one_or_none()
        if packet is not None:
            phrases = list(packet.script_phrases or [])
    review = previous.get("review") or {}
    word_level = is_word_level(row.transcript or [])
    activity = await _speech_activity(row.storage_path) if word_level else None
    # 3-Oct, an agent talk: the agent's words are content, never cut by a rule or the
    # review (only his own request can cut them).
    voices = await talk_voices(row)
    # A long walk takes a second or more to plan: off the event loop.
    plan = await asyncio.to_thread(
        plan_edit,
        row.transcript,
        phrases,
        pause_threshold_s=pause_threshold_s or settings.production_pause_threshold_s,
        duration_s=row.duration_s,
        activity=activity,
        removals=review.get("removals") if review.get("state") == "done" else None,
        overrides=previous.get("overrides"),
        aside_names=aside_names(),
        protected=voices.agent_words if voices is not None else (),
    )
    if voices is not None:
        plan["voices"] = {
            "agent": voices.agent,
            "agent_words": len(voices.agent_words),
            "words": len(row.transcript or []),
            "known": voices.known,
            "matched": voices.matched,
            "offset_s": voices.offset_s,
        }
    if word_level:
        if previous.get("overrides"):
            plan["overrides"] = previous["overrides"]
    else:
        plan = autoedit.apply_overrides(plan, previous.get("overrides"))
    if previous.get("proofread") is not None:
        plan["proofread"] = previous["proofread"]
    if review:
        plan["review"] = review
    if previous.get("second_listen"):
        # Once per transcript: a re-plan must not send every stretch to be heard again
        # (and undo a correction he asked for on the words it would hear).
        plan["second_listen"] = previous["second_listen"]
    if activity is not None:
        # 30-Sep: kept words whose end the phone cut ("cou" for "course"). No cut can
        # bring the sound back, so the card says so before he finds it by ear.
        hiss = await _levels(row.storage_path, hiss=True)
        kept = {int(w["index"]) for w in plan.get("words") or [] if "index" in w}
        marks = autoedit.word_marks(row.transcript or [], None, activity.levels, activity.low_db, hiss=hiss)
        plan["phone_cut"] = [
            {
                "index": i,
                "text": str(row.transcript[i]["text"]),
                "source_s": round(float(row.transcript[i]["start_s"]), 2),
                "edit_s": round(map_to_edit(float(row.transcript[i]["start_s"]), plan["keep"]) or 0.0, 2),
            }
            for i, m in sorted(marks.items())
            if m == "phone cut its end short" and i in kept
        ]
    row.edit_plan = plan
    mc = plan["meaning_check"]
    drops = [d for d in plan["dropped"] if d["reason"] != "pause"]
    pauses = [d for d in plan["dropped"] if d["reason"] == "pause"]
    if mc["status"] == "blocked":
        row.status = "needs_review"
        row.status_detail = f"Needs review: {mc['issues'][0]['detail']}"[:500]
    else:
        row.status = "planned"
        row.status_detail = (
            f"Plan ready: keep {len(plan['keep'])} ranges ({plan['stats']['kept_seconds']:.0f}s), "
            f"drop {len(drops)} retakes and {len(pauses)} pauses. Meaning check passed. "
            f"{plan['timing']['summary']}."
        )


def _caption_text(row: RecordingUpload, fmt: str) -> str:
    if not row.edit_plan:
        raise HTTPException(status_code=409, detail="No edit plan yet")
    cues = build_cues(row.edit_plan)
    return to_srt(cues) if fmt == "srt" else to_vtt(cues)


@router.get("/uploads/{upload_id}/captions.{fmt}")
async def captions(
    upload_id: uuid.UUID,
    fmt: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    if fmt not in ("srt", "vtt"):
        raise HTTPException(status_code=404, detail="Unknown caption format")
    row = await _upload(db, ws, upload_id)
    media_type = "application/x-subrip" if fmt == "srt" else "text/vtt"
    return PlainTextResponse(
        _caption_text(row, fmt),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="captions-{row.id}.{fmt}"'},
    )


def render_ref(rendered_keep: list[list[float]], captions: str, attempt: str) -> str:
    """A short id for one render: its frame keep, its captions and the attempt.

    The keep alone is not enough: a caption fix re-renders with the same keep, and the
    player must still see a new address. The attempt makes every render its own.
    """
    body = "\x1f".join([json.dumps(rendered_keep), captions, attempt])
    return hashlib.sha256(body.encode()).hexdigest()[:16]


async def _run_render(upload_id: uuid.UUID, ws: uuid.UUID, attempt: str, mode: str) -> None:
    async def report(text: str) -> None:
        await _set_status(upload_id, ws, "rendering", text, attempt)

    try:
        async with session_factory()() as s:
            row = await _load(s, upload_id, ws)
            src, plan, duration = Path(row.storage_path), dict(row.edit_plan or {}), row.duration_s
            words = list(row.transcript or [])
        if mode == "uncut":
            if not duration:
                duration = await media.probe_duration(src)
            plan = uncut_plan(plan, duration)
        keep = plan.get("keep") or []
        cues = build_cues(plan)
        audio_only = src.suffix.lower() in media.AUDIO_EXTS
        size = media.AUDIO_ONLY_CANVAS if audio_only else await media.probe_video_size(src)
        if size is None:
            raise RuntimeError("could not read the video frame size with ffprobe")
        srt_text = to_srt(cues)
        out = src.with_name(f"{src.stem}-edited.mp4")
        # TJ's look (28-Sep): the word being said on an orange box, when every caption
        # word has its own timing and Roboto can draw it; the plain captions otherwise.
        band_dir = src.with_name(f".{src.stem}-captions-{attempt}")
        band = None
        if mode == "uncut":  # every word he said, on the recording's own clock
            spoken = [
                {"text": w["text"], "start": float(w["start_s"]), "end": float(w["end_s"])}
                for w in words
            ] if is_word_level(words) else []
        else:
            spoken = list(plan.get("words") or [])
        on_edit = wordbox.on_edit_timeline(spoken, keep)
        if not audio_only and on_edit and wordbox.usable(on_edit):
            await report(f"Drawing {len(on_edit)} caption words, each boxed while you say it")
            # Hundreds of images: drawn off the event loop so the API keeps answering.
            band = await asyncio.to_thread(
                wordbox.render_band,
                wordbox.pages(on_edit), size[0], size[1], band_dir, sum(e - s for s, e in keep),
            )
        try:
            await media.render_edit(
                src,
                keep,
                out,
                on_status=report,
                ass_text=None if band else to_ass(cues, *size),
                srt_text=srt_text,
                caption_band=band,
                make_preview=not audio_only,
            )
        finally:
            shutil.rmtree(band_dir, ignore_errors=True)
        srt = src.with_name(f"{src.stem}-edited.srt")
        srt.write_text(srt_text, encoding="utf-8")
        src.with_name(f"{src.stem}-edited.vtt").write_text(to_vtt(cues), encoding="utf-8")
        async with session_factory()() as s:
            row = await _load(s, upload_id, ws)
            if not _owns(row, attempt):
                return
            row.edited_path = str(out)
            row.captions_path = str(srt)
            row.status = "edited"
            # 30-Sep, talk to the editor: the keep that made THIS file, on its own frame
            # clock, and a short id for it. Only here: a plan that never renders must not
            # say it is the file he watches.
            row.rendered_keep = frame_keep(keep)
            row.render_ref = render_ref(row.rendered_keep, srt_text, attempt)
            kept_s = sum(e - b for b, e in keep)
            what = (
                "Uncut captioned MP4 ready (nothing removed)"
                if mode == "uncut"
                else f"Captioned MP4 ready: {len(keep)} ranges"
            )
            pauses = (plan.get("stats") or {}).get("pauses") or {}
            row.status_detail = (
                f"{what}, {fmt_ts(kept_s)} long"
                + (f", longest pause {pauses['max_pause_s']:.2f} s" if pauses and mode != "uncut" else "")
                + (", word-box captions" if band else f", {len(cues)} captions burned in")
                + ", plus a subtitle track and SRT and VTT sidecars"
            )
            row.job_ids = _with_lease(row.job_ids, None)
            await s.commit()
    except media.StepUnavailableError as exc:
        await _set_status(upload_id, ws, "unavailable", str(exc), attempt)
    except Exception as exc:
        await _set_status(upload_id, ws, "failed", f"Render failed: {str(exc)[:400]}", attempt)


# 30-Sep, talk to the editor: while he is giving notes on a video, nothing else may
# swap the file under his player, or every second he pins would point somewhere else.
SITTING_REFUSAL = (
    "You are giving notes on this video right now. Make the new version from your notes, "
    "or close the notes and try again in two minutes."
)


async def _refuse_while_sitting(db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID) -> None:
    if await library_service.active_sitting(db, ws, upload_id) is not None:
        raise HTTPException(status_code=409, detail=SITTING_REFUSAL)


# 1-Oct review: a typed request being carried out is editing the video too. It reads the
# words, waits on the subscription worker (up to 15 minutes), then rewrites them and
# renders: a sitting opened meanwhile would have the file change under its player.
# upload id -> {request id: what that request is doing now}, for the requests running
# in this process (like the render lock). A request parked until a restart (the worker
# was away) is not running; when it carries on it joins or waits for his notes instead.
_requests_running: dict[uuid.UUID, dict[uuid.UUID, str]] = {}


def request_busy_sentence(status: str) -> str:
    return f"An editing request you typed is being made right now ({status}). Give your notes once it is done."


def _request_running(upload_id: uuid.UUID, request_id: uuid.UUID, status: str) -> None:
    _requests_running.setdefault(upload_id, {})[request_id] = status


def _request_stopped(request_id: uuid.UUID) -> None:
    for upload_id, running in list(_requests_running.items()):
        running.pop(request_id, None)
        if not running:
            _requests_running.pop(upload_id, None)


def upload_busy(row: RecordingUpload) -> str | None:
    """What is editing this video right now, in his words; None when nothing is."""
    if row.status in BUSY_STATUSES or AUTO_MARK in (row.job_ids or []) or _render_lock(row.id).locked():
        return row.status_detail or "This video is being edited right now."
    running = _requests_running.get(row.id)
    if running:
        return request_busy_sentence(list(running.values())[-1])
    return None


async def word_marks_for(
    src: str | Path | None, words: list[dict[str, Any]], keep: list[list[float]]
) -> dict[int, str]:
    """What the editor cannot hear for itself, word by word (autoedit.word_marks), from
    the recording's levels (read once per file, then cached beside it)."""
    activity = await _speech_activity(src) if src and Path(src).exists() else None
    if activity is None:
        return {}
    return autoedit.word_marks(words, keep, activity.levels, activity.low_db, hiss=await _levels(src, hiss=True))


class RenderRequest(BaseModel):
    # The editor must explicitly accept a plan the meaning check blocked
    override_meaning_check: bool = False
    # "uncut" keeps the whole recording and only adds captions; it never needs an override
    mode: Literal["cut", "uncut"] = "cut"


@router.post("/uploads/{upload_id}/auto-edit", status_code=202)
async def auto_edit_again(
    upload_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Edit a recording again the way a finished session is edited: the editor's
    review, the tight cut, the captions. The transcript and his editing requests
    stay; the review is reused only while the words and the editor's brief are
    unchanged."""
    await reconcile_interrupted_uploads(db, ws)
    row = await _upload(db, ws, upload_id)
    if row.status in BUSY_STATUSES or AUTO_MARK in (row.job_ids or []) or _render_lock(row.id).locked():
        return upload_json(row)
    await _refuse_while_sitting(db, ws, row.id)
    if not row.storage_path or not Path(row.storage_path).exists():
        raise HTTPException(status_code=409, detail="The recording is not on this server")
    plan = dict(row.edit_plan or {})
    if plan.pop("review", None) is not None:
        row.edit_plan = plan
    # A live status straight away, so the Library keeps refreshing the card.
    row.status = "proofreading"
    row.status_detail = "Editing it again: Jennifer's review, then the cut and the captions"
    await db.commit()
    await db.refresh(row)
    _spawn(auto_edit(row.id, ws))
    return upload_json(row)


@router.post("/uploads/{upload_id}/render", status_code=202)
async def render_upload(
    upload_id: uuid.UUID,
    body: RenderRequest | None = None,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    await reconcile_interrupted_uploads(db, ws)
    row = await _upload(db, ws, upload_id)
    body = body or RenderRequest()
    if not row.edit_plan:
        raise HTTPException(status_code=409, detail="Plan the edit before rendering")
    await _refuse_while_sitting(db, ws, row.id)
    if (
        body.mode == "cut"
        and row.edit_plan.get("meaning_check", {}).get("status") == "blocked"
        and not body.override_meaning_check
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The meaning check blocked this plan. Review the issues before rendering, "
                "or render uncut with captions."
            ),
        )
    if row.status in BUSY_STATUSES:
        return upload_json(row)
    if not Path(row.storage_path).exists():
        raise HTTPException(
            status_code=409, detail="The original upload is missing from storage; upload it again"
        )
    if not media.ffmpeg_path():
        row.status = "unavailable"
        row.status_detail = "Render unavailable: ffmpeg is not installed on this server"
        await db.commit()
        await db.refresh(row)
        return upload_json(row)
    detail = (
        "Queued: captioning the whole recording with ffmpeg (nothing removed)"
        if body.mode == "uncut"
        else f"Queued: cutting {len(row.edit_plan.get('keep') or [])} ranges with ffmpeg"
    )
    attempt = _claim(row, "rendering", detail)
    try:
        await db.commit()
    except BaseException:
        _active_attempts.discard(attempt)
        raise
    await db.refresh(row)
    _spawn(
        _run_leased(
            row.id, ws, "rendering", attempt, lambda: _run_render(row.id, ws, attempt, body.mode)
        )
    )
    return upload_json(row)


STREAM_PART_BYTES = 32 * 1024 * 1024


def serve_video(
    request: Request, path: Path, media_type: str, filename: str, *, download: bool
) -> Response:
    """A video to PLAY by default, or to save with ?download=1.

    Every Watch button used to download the file, because FileResponse with a
    filename says "attachment" ("when I click watch it - it downloads the
    video", 23-Sep). And the server's Starlette (0.38) answers no Range
    requests, so an in-page player could not seek. This answers both: inline or
    attachment by choice, and byte ranges for scrubbing.

    28-Sep: "after watching it on my app for a minute and 4 sec it got stuck". His
    phone's first request ran as one open-ended response that ended after 61.9 MB, the
    first 63 s of a 7.8 Mbps file, on a line slower than the file. The Library now
    plays a 1.5 Mbps copy; a player gets at most STREAM_PART_BYTES per answer, so a
    raw recording or a full edit (100-250 MB) comes in parts it can re-ask for. Small
    parts cost a stall at every boundary on a thin line (4 MiB: 7.2 s stalled in 90 s
    at 2.5 Mbps, one stream: 1.1 s), so the part is large enough that the phone copy
    streams whole. A download (?download=1) is unchanged.
    """
    size = path.stat().st_size
    # No quotes or line breaks in a header value.
    safe_name = "".join(ch for ch in filename if ch not in '"\r\n')
    disposition = f'{"attachment" if download else "inline"}; filename="{safe_name}"'
    headers = {"Accept-Ranges": "bytes", "Content-Disposition": disposition}
    spec = request.headers.get("range", "")
    if not spec.startswith("bytes="):
        return FileResponse(path, media_type=media_type, headers=headers)
    first = spec[len("bytes="):].split(",")[0].strip()
    start_text, _, end_text = first.partition("-")
    try:
        if start_text == "":
            start = max(0, size - int(end_text))
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    end = min(end, size - 1)
    if start > end or start >= size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    if not download:
        end = min(end, start + STREAM_PART_BYTES - 1)

    def body(start: int = start, end: int = end):
        with path.open("rb") as handle:
            handle.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = handle.read(min(1 << 20, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk

    headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
    return StreamingResponse(body(), status_code=206, media_type=media_type, headers=headers)


@router.get("/uploads/{upload_id}/video")
async def recorded_file(
    upload_id: uuid.UUID,
    request: Request,
    download: bool = False,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    """The recording itself, as it came off the phone.

    An edited cut only exists after a render, so without this there was no way to
    watch back a video that had just been recorded.
    """
    row = await _upload(db, ws, upload_id)
    path = Path(row.storage_path) if row.storage_path else None
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="The video file is not on this server")
    return serve_video(
        request, path, _video_media_type(path), row.original_filename or path.name, download=download
    )


def _video_media_type(path: Path) -> str:
    return {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".m4v": "video/mp4",
    }.get(path.suffix.lower(), "application/octet-stream")


@router.get("/uploads/{upload_id}/edited")
async def edited_file(
    upload_id: uuid.UUID,
    request: Request,
    download: bool = False,
    preview: bool = False,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    """The edit. ?preview=1 is the light 720p copy the Library plays on his phone
    (about 1.5 Mbps instead of 5-6); the full edit is what gets downloaded and
    posted. An edit rendered before the preview existed plays in full."""
    row = await _upload(db, ws, upload_id)
    if not row.edited_path or not Path(row.edited_path).exists():
        raise HTTPException(status_code=404, detail="No edited file yet")
    edited = Path(row.edited_path)
    light = media.preview_path(edited)
    if preview and not download and light.exists() and light.stat().st_mtime >= edited.stat().st_mtime:
        edited = light
    return serve_video(request, edited, "video/mp4", edited.name, download=download)


# ---------------------------------------------------------------------------
# Publication receipts


class PublicationCreate(BaseModel):
    platform: str
    external_post_id: str = Field(min_length=1, max_length=300)
    url: str | None = Field(default=None, max_length=1000)
    published_at: datetime | None = None
    final_text: str | None = None
    packet_id: uuid.UUID | None = None
    outcome: dict[str, Any] | None = None


class Outcome(BaseModel):
    qualified_conversations: int | None = Field(default=None, ge=0)
    strategy_sessions_booked: int | None = Field(default=None, ge=0)
    mentions: list[str] | None = None
    notes: str | None = None


class PublicationPatch(BaseModel):
    outcome: Outcome


@router.post("/candidates/{candidate_id}/publications", status_code=201)
async def create_publication(
    candidate_id: uuid.UUID,
    body: PublicationCreate,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Record a publication a human already made. This never publishes anything."""
    candidate = await _candidate(db, ws, candidate_id)
    platform = body.platform.strip().lower()
    if platform not in PLATFORMS:
        raise HTTPException(
            status_code=422, detail=f"platform must be one of {', '.join(PLATFORMS)}"
        )
    if body.packet_id is not None:
        # A receipt cites the packet the post came from; another candidate's (or another
        # workspace's) packet would attribute the publication to work that never fed it.
        packet = await _packet(db, ws, body.packet_id)
        if packet.candidate_id != candidate.id:
            raise HTTPException(status_code=422, detail="packet_id belongs to a different idea")
    ext_id = body.external_post_id.strip()
    existing = (
        await db.execute(
            select(PublicationReceipt).where(
                PublicationReceipt.workspace_id == ws,
                PublicationReceipt.platform == platform,
                PublicationReceipt.external_post_id == ext_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return JSONResponse(
            status_code=200, content={"duplicate": True, "publication": publication_json(existing)}
        )
    outcome = (
        Outcome(**(body.outcome or {})).model_dump(exclude_none=True) if body.outcome else None
    )
    published_at = body.published_at
    if published_at is not None and published_at.tzinfo is not None:
        published_at = published_at.astimezone(UTC).replace(tzinfo=None)
    row = PublicationReceipt(
        workspace_id=ws,
        candidate_id=candidate.id,
        packet_id=body.packet_id,
        platform=platform,
        external_post_id=ext_id,
        url=body.url,
        published_at=published_at,
        final_text=body.final_text,
        outcome=outcome,
        recorded_by="editor",
    )
    db.add(row)
    candidate.status = "published"
    await db.commit()
    await db.refresh(row)
    return {"duplicate": False, "publication": publication_json(row)}


@router.get("/candidates/{candidate_id}/publications")
async def list_publications(
    candidate_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _candidate(db, ws, candidate_id)
    rows = (
        (
            await db.execute(
                select(PublicationReceipt)
                .where(
                    PublicationReceipt.workspace_id == ws,
                    PublicationReceipt.candidate_id == candidate_id,
                )
                .order_by(PublicationReceipt.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"publications": [publication_json(r) for r in rows]}


@router.patch("/publications/{publication_id}")
async def patch_publication(
    publication_id: uuid.UUID,
    body: PublicationPatch,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(PublicationReceipt).where(
                PublicationReceipt.id == publication_id, PublicationReceipt.workspace_id == ws
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    merged = dict(row.outcome or {})
    merged.update(body.outcome.model_dump(exclude_none=True))
    merged["updated_at"] = _utcnow().isoformat() + "Z"
    row.outcome = merged
    await db.commit()
    await db.refresh(row)
    return publication_json(row)


# ---------------------------------------------------------------------------
# Mobile recording sessions. Source chunks are append-only and never published.


@router.get("/recording-queue")
async def recording_queue(
    candidate: uuid.UUID | None = None,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The ideas Today counts as ready, and only those.

    This used to list every selected or recorded idea that ever got a script,
    from any week: Today said "1 script ready" and the studio showed 3 (an old
    week's idea, a technical test and one already recorded) while missing the
    one Today meant. One source now: this week's lineup, primary slots, in the
    lineup's order, script ready. The same rows `today.build` counts.

    Read through `current_lineup`, like Today (28-Sep): on the Monday a week
    turns over it brings last week's unrecorded topics in, so the studio does
    not open empty while he has scripts waiting. `get_db` commits that copy.
    A topic he has filmed stays in the week but not here: the studio is for
    what he has still to film.

    A topic he names (`?candidate=`: "Record it again" in the Library, "Start
    recording" in the topic room) is in the list as well when its script is
    ready, filmed or not, in this week or not. The studio can only open what its
    list holds, so without it those buttons answered "That script is not ready
    to record yet" for every topic he had filmed (28-Sep review). A named topic
    whose script is not ready is left out, and then that answer is true.
    """
    from tce.editorial import lineup as lineup_service

    lineup = await lineup_service.current_lineup(db, ws)
    week = await lineup_service.lineup_to_json(db, ws, lineup)
    named = str(candidate) if candidate is not None else None
    wanted = [
        (uuid.UUID(r["candidate_id"]), uuid.UUID(r["packet_id"]))
        for r in week.get("primary") or []
        if r.get("script_state") == "ready"
        and r.get("packet_id")
        and (not r.get("filmed") or r["candidate_id"] == named)
    ]
    if candidate is not None and candidate not in {cid for cid, _ in wanted}:
        packet = await lineup_service.ready_script(db, ws, candidate)
        if packet is not None:
            wanted.append((candidate, packet.id))
    rows = []
    for candidate_id, packet_id in wanted:
        candidate = await db.get(TopicCandidate, candidate_id)
        packet = await db.get(RecordingPacket, packet_id)
        if candidate is not None and packet is not None and candidate.workspace_id == ws:
            rows.append((candidate, packet))
    ideas: list[dict[str, Any]] = []
    for candidate, packet in rows:
        active = (
            await db.execute(
                select(RecordingSession)
                .where(
                    RecordingSession.workspace_id == ws,
                    RecordingSession.candidate_id == candidate.id,
                    RecordingSession.packet_id == packet.id,
                    RecordingSession.status.notin_(("uploaded", "failed")),
                )
                .order_by(RecordingSession.retake_index.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        ideas.append(
            {
                "candidate_id": str(candidate.id),
                "packet_id": str(packet.id),
                "packet_version": packet.version,
                "title": candidate.title,
                "big_idea": candidate.lesson,
                "bullets": packet.bullets or [],
                "script_phrases": packet.script_phrases or [],
                "hook_options": packet.hook_options or [],
                "selected_hook_id": packet.selected_hook_id,
                "beats": packet.beats or [],
                "interviewer_prompt": packet.interviewer_prompt,
                "packet_format": "v2" if packet.hook_options and packet.beats else "legacy",
                "active_session_id": str(active.id) if active else None,
                "active_session_status": active.status if active else None,
            }
        )
    return {"ideas": ideas, "count": len(ideas)}


@router.get("/recorded")
async def recorded(
    limit: int = 20,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """What he has already recorded, and what came of it.

    The recorder could take a video and then showed nothing back: the file, the
    captions and the Google Doc each lived behind a different route and none of
    them was on screen. This is one call with all three.
    """
    limit = max(1, min(limit, 100))
    await reconcile_interrupted_uploads(db, ws)
    rows = (
        await db.execute(
            select(RecordingUpload, TopicCandidate, RecordingPacket)
            .join(TopicCandidate, TopicCandidate.id == RecordingUpload.candidate_id)
            .outerjoin(RecordingPacket, RecordingPacket.id == RecordingUpload.packet_id)
            .where(
                RecordingUpload.workspace_id == ws,
                # A synthetic take proving the pipeline works is not something he
                # recorded, and it should not sit in his list looking like one.
                TopicCandidate.origin != ORIGIN_TECHNICAL_VALIDATION,
            )
            # id breaks the tie so two takes in the same second do not swap
            # places between one refresh and the next.
            .order_by(RecordingUpload.created_at.desc(), RecordingUpload.id.desc())
            .limit(limit)
        )
    ).all()
    items = []
    for upload, candidate, packet in rows:
        data = upload_json(upload)
        items.append(
            {
                "upload_id": data["id"],
                "candidate_id": str(candidate.id),
                "title": candidate.title,
                "recorded_at": data["created_at"],
                "duration_s": upload.duration_s,
                "status": upload.status,
                "status_detail": upload.status_detail,
                "video_url": data["video_url"],
                "edited_url": data["edited_url"],
                "captions_srt_url": data["captions_srt_url"]
                if data["captions_available"]
                else None,
                "has_transcript": data["has_transcript"],
                "google_doc_url": packet.google_doc_url if packet else None,
            }
        )
    return {"recordings": items, "count": len(items)}


@router.post("/recording-sessions", status_code=201)
async def create_recording_session_route(
    body: RecordingSessionCreate,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = await recording_sessions.create_session(
            db, ws, body.candidate_id, body.packet_id, device_meta=body.device_meta
        )
    except recording_sessions.RecordingSessionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"session": await _recording_session_json(db, row)}


@router.get("/recording-sessions/{session_id}")
async def get_recording_session_route(
    session_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(RecordingSession).where(
                RecordingSession.id == session_id, RecordingSession.workspace_id == ws
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Recording session not found")
    return {"session": await _recording_session_json(db, row)}


@router.post("/recording-sessions/{session_id}/clips", status_code=201)
async def create_recording_clip_route(
    session_id: uuid.UUID,
    body: RecordingClipCreate,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = await recording_sessions.create_clip(
            db, ws, session_id, body.local_clip_id, body.mime_type, body.extension
        )
    except recording_sessions.RecordingSessionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"clip": _clip_json(row)}


@router.put("/recording-clips/{clip_id}/chunks/{sequence}", status_code=201)
async def upload_recording_chunk_route(
    clip_id: uuid.UUID,
    sequence: int,
    request: Request,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    digest = request.headers.get("x-chunk-sha256", "")
    data = await request.body()
    try:
        row = await recording_sessions.store_chunk(
            db, ws, clip_id, sequence, data, digest, _recording_root()
        )
    except recording_sessions.RecordingSessionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "chunk": {
            "id": str(row.id),
            "clip_id": str(row.clip_id),
            "sequence": row.sequence,
            "sha256": row.sha256,
            "size_bytes": row.size_bytes,
        }
    }


@router.post("/recording-clips/{clip_id}/finish")
async def finish_recording_clip_route(
    clip_id: uuid.UUID,
    body: RecordingClipFinish,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = await recording_sessions.finalize_clip(
            db,
            ws,
            clip_id,
            _recording_root(),
            active_duration_s=body.active_duration_s,
            take_markers=body.take_markers,
        )
    except recording_sessions.RecordingSessionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"clip": _clip_json(row)}


@router.post("/recording-sessions/{session_id}/finish")
async def finish_recording_session_route(
    session_id: uuid.UUID,
    body: RecordingSessionFinish,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row, upload = await recording_sessions.finalize_session(
            db, ws, session_id, body.selected_clip_ids, _recording_root()
        )
    except recording_sessions.RecordingSessionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = {"session": await _recording_session_json(db, row), "upload": upload_json(upload)}
    await db.commit()  # the edit runs in the background and must see the new video
    if upload.status == "uploaded" and not upload.transcript:
        start_auto_edit(upload.id, ws)
    return payload



# ---------------------------------------------------------------------------
# TCE edits by itself, on the subscription (25-Sep): "allow tce to do editing by
# itself on subscription". A finished session is transcribed, proofread, cut and
# rendered with no clicks; an editing request is carried out by the subscription
# worker. Every step writes what it is doing into status_detail (3-second rule),
# and every failure lands on the row, never only in a log.

AUTO_MARK = "auto-edit"


async def _step(upload_id: uuid.UUID, ws: uuid.UUID, status: str, detail: str, work) -> RecordingUpload:
    """Run one leased media step to completion and return the row as it ended."""
    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        attempt = _claim(row, status, detail)
        await s.commit()
    await _run_leased(upload_id, ws, status, attempt, lambda: work(attempt))
    async with session_factory()() as s:
        return await _load(s, upload_id, ws)


async def _note(upload_id: uuid.UUID, ws: uuid.UUID, status: str | None, detail: str) -> None:
    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        if status:
            row.status = status
        row.status_detail = detail[:500]
        await s.commit()


async def _script_context(s: AsyncSession, ws: uuid.UUID, row: RecordingUpload) -> str:
    packet = None
    if row.packet_id:
        packet = (
            await s.execute(
                select(RecordingPacket).where(
                    RecordingPacket.id == row.packet_id, RecordingPacket.workspace_id == ws
                )
            )
        ).scalar_one_or_none()
    title = None
    if row.candidate_id:
        cand = (
            await s.execute(
                select(TopicCandidate).where(
                    TopicCandidate.id == row.candidate_id, TopicCandidate.workspace_id == ws
                )
            )
        ).scalar_one_or_none()
        title = cand.title if cand else None
    return autoedit.script_context(packet, title)


async def _ask(
    kind: str,
    prompt: str,
    system: str,
    schema: dict[str, Any],
    ws: uuid.UUID,
    key: str,
    *,
    wait_timeout_s: float | None = None,
    prompt_version: str = autoedit.PROMPT_VERSION,
    max_tokens: int = 2000,
    requeue_failed: bool = False,
):
    from tce.llm import LLMRequest
    from tce.llm import provider as llm

    request = LLMRequest(
        job_type=kind,
        agent_name=autoedit.AGENT_NAME,
        messages=[{"role": "user", "content": prompt}],
        system=system,
        output_schema=schema,
        max_tokens=max_tokens,
        prompt_version=prompt_version,
        workspace_id=ws,
        idempotency_key=key,
    )
    return await llm.complete(
        request, sessionmaker=session_factory(), wait_timeout_s=wait_timeout_s, requeue_failed=requeue_failed
    )


# 28-Sep: the proofread was queued at 07:31 and the worker answered at 11:08; the edit
# had rendered unproofread at 07:52 and the late answer was never used. The review now
# waits REVIEW_FIRST_WAIT_S, the edit goes out on the rules if it must, and a waiter
# re-edits with the review when it lands.
REVIEW_FIRST_WAIT_S = 600.0
# A late review waiting for him to finish a sitting looks again this often.
SITTING_RECHECK_S = 30.0


_render_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _render_lock(upload_id: uuid.UUID) -> asyncio.Lock:
    """One plan-and-render of a video at a time in this process (review, 28-Sep: a late
    review landing during another render started a second ffmpeg on the same files)."""
    lock = _render_locks.get(upload_id)
    if lock is None:
        lock = _render_locks[upload_id] = asyncio.Lock()
    return lock


def _review_request(
    words: list[dict[str, Any]], context: str, voices: agent_talks.Voices | None = None
) -> tuple[str, str]:
    """The review's prompt and instructions. An agent talk (3-Oct) says who speaks each
    line and adds the conversation rules: the agent's lines are content."""
    system = autoedit.review_system(aside_names())
    if voices is None:
        return autoedit.review_prompt(words, context), system
    speakers = voices.speaker_names() if voices.known else None
    system += "\n\n" + autoedit.conversation_rules(voices.agent, known=voices.known)
    return autoedit.review_prompt(words, context, speakers), system


def _review_key(upload_id: uuid.UUID, prompt: str, system: str) -> str:
    """Everything the job reads is in its key: a changed topic title, script or dog name
    asks afresh instead of colliding with the old job (the queue refuses a reused key
    with a different input, and "Edit it again" failed on every click)."""
    body = "\x1f".join([autoedit.REVIEW_PROMPT_VERSION, system, prompt])
    return f"edit-review:{upload_id}:{hashlib.sha256(body.encode()).hexdigest()[:24]}"


async def _save_review(upload_id: uuid.UUID, ws: uuid.UUID, review: dict[str, Any], detail: str | None) -> None:
    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        plan = dict(row.edit_plan or {})
        plan["review"] = review
        row.edit_plan = plan
        if detail:
            row.status_detail = detail[:500]
        await s.commit()


async def _apply_review(
    upload_id: uuid.UUID,
    ws: uuid.UUID,
    words: list[dict[str, Any]],
    answer: Any,
    *,
    fix_words: bool = True,
    voices: agent_talks.Voices | None = None,
) -> dict[str, Any]:
    """Store what the editor decided. Removals are kept as time ranges, so the word
    fixes applied beside them cannot shift what they point at. `fix_words` False keeps
    the transcript as it is (a posted video: its word indices must not move). In an
    agent talk (`voices`) no removal takes the agent's words."""
    out = answer.structured or {}
    removals, notes = autoedit.validate_removals(
        words,
        out.get("removals") or [],
        protected=voices.agent_words if voices is not None else None,
        protected_name=voices.agent if voices is not None else "the agent",
    )
    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        current = list(row.transcript or [])
        applied: list[dict[str, Any]] = []
        if fix_words and [w.get("text") for w in current] == [w.get("text") for w in words]:
            fixed, applied = autoedit.apply_corrections(current, out.get("corrections") or [])
            row.transcript = fixed
        plan = dict(row.edit_plan or {})
        if fix_words:
            plan["proofread"] = [
                {"heard": c["heard"], "replacement": c["replacement"], "why": str(c.get("why") or "")[:200]}
                for c in applied
            ]
        review = {
            "state": "done" if removals is not None else "rules",
            "removals": removals or [],
            "notes": notes,
            "model": answer.model,
            "at": _utcnow().isoformat(),
        }
        plan["review"] = review
        row.edit_plan = plan
        took = len(removals or [])
        row.status_detail = (
            f"Jennifer marked {took} thing{'s' if took != 1 else ''} to take out and fixed "
            f"{len(applied)} misheard word{'s' if len(applied) != 1 else ''}"
            if removals is not None
            else f"Jennifer's review was not usable ({'; '.join(notes)[:200]}); cutting with the rules"
        )
        await s.commit()
    return review


async def _review(upload_id: uuid.UUID, ws: uuid.UUID, *, wait_timeout_s: float | None) -> str:
    """The editor's review on the subscription: misheard words, retakes (the complete
    take stays), talk to the dogs, recogniser junk. Returns its state."""
    from tce.llm import LLMUnavailable
    from tce.llm.queue import QueueError

    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        words = list(row.transcript or [])
        context = await _script_context(s, ws, row)
        voices = await talk_voices(row, words)
        if words and is_word_level(words):
            row.status = "proofreading"
            row.status_detail = (
                f"Jennifer is reading {len(words)} words on the subscription: misheard words, "
                "lines said twice, talk to the dogs"
                + (f"; {voices.agent}'s lines stay as they are" if voices is not None else "")
            )
            await s.commit()
    if not words or not is_word_level(words):
        return "skipped"
    prompt, system = _review_request(words, context, voices)
    key = _review_key(upload_id, prompt, system)
    try:
        answer = await _ask(
            autoedit.REVIEW_JOB, prompt, system, autoedit.REVIEW_SCHEMA, ws, key,
            wait_timeout_s=wait_timeout_s, prompt_version=autoedit.REVIEW_PROMPT_VERSION,
            max_tokens=4000,
        )
    except (LLMUnavailable, QueueError) as exc:
        waiting = isinstance(exc, LLMUnavailable) and exc.status in ("timeout", "waiting_capacity")
        why = getattr(exc, "status", exc.__class__.__name__)
        await _save_review(
            upload_id,
            ws,
            {"state": "waiting" if waiting else "unavailable", "key": key,
             "since": _utcnow().isoformat(), "detail": str(exc)[:300]},
            (
                "Jennifer has not answered yet, so this edit uses the rules; it re-edits "
                "by itself when her review lands"
                if waiting
                else f"Jennifer could not review this one ({why}); cutting with the rules"
            ),
        )
        return "waiting" if waiting else "unavailable"
    await _apply_review(upload_id, ws, words, answer, voices=voices)
    return "done"


async def _await_review(upload_id: uuid.UUID, ws: uuid.UUID) -> None:
    """Keep waiting for a review the edit went out without, then re-edit with it.

    Restart-safe: the review's state, job key and start time live on the plan, and
    startup resumes every waiter until production_review_wait_h after the review was
    first asked for. It stops when he changed the words or the brief meanwhile (the
    review read something else), when another edit of the video is running (that one
    asks for its own review), and once a post of this video went out (the edit he
    posted stays the edit he sees). While it applies and renders, the video carries
    the auto-edit mark: posting waits, "Edit it again" waits, a restart resumes it.
    While he is giving notes on the video (a sitting in front of him) it keeps waiting,
    so the file never changes under his player.
    """
    from tce.llm import LLMUnavailable
    from tce.llm.queue import QueueError

    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        since = ((row.edit_plan or {}).get("review") or {}).get("since")
    try:
        started = datetime.fromisoformat(since) if since else _utcnow()
    except ValueError:
        started = _utcnow()
    deadline = started + timedelta(hours=settings.production_review_wait_h)
    while _utcnow() < deadline:
        async with session_factory()() as s:
            row = await _load(s, upload_id, ws)
            review = dict((row.edit_plan or {}).get("review") or {})
            if review.get("state") != "waiting" or AUTO_MARK in (row.job_ids or []):
                return
            words = list(row.transcript or [])
            context = await _script_context(s, ws, row)
            voices = await talk_voices(row, words)
        prompt, system = _review_request(words, context, voices)
        key = _review_key(upload_id, prompt, system)
        if key != str(review.get("key") or ""):
            await _save_review(upload_id, ws, {**review, "state": "stale"}, None)
            return
        try:
            answer = await _ask(
                autoedit.REVIEW_JOB, prompt, system, autoedit.REVIEW_SCHEMA, ws, key,
                prompt_version=autoedit.REVIEW_PROMPT_VERSION, max_tokens=4000,
            )
        except LLMUnavailable as exc:
            if exc.status in ("timeout", "waiting_capacity"):
                await asyncio.sleep(30)
                continue
            await _save_review(upload_id, ws, {**review, "state": "unavailable", "detail": str(exc)[:300]}, None)
            return
        except QueueError as exc:
            await _save_review(upload_id, ws, {**review, "state": "unavailable", "detail": str(exc)[:300]}, None)
            return
        async with _render_lock(upload_id):
            async with session_factory()() as s:
                row = await _load(s, upload_id, ws)
                if ((row.edit_plan or {}).get("review") or {}).get("state") != "waiting":
                    return
                if AUTO_MARK in (row.job_ids or []) or row.status in BUSY_STATUSES:
                    return
                if [w.get("text") for w in row.transcript or []] != [w.get("text") for w in words]:
                    return
                # 30-Sep: he is giving notes on this edit right now. Swapping the file
                # under his player would move every second he pins: keep waiting.
                in_front = await library_service.active_sitting(s, ws, upload_id) is not None
                if not in_front:
                    posted = any(
                        p.status in ("posting", "scheduled", "posted")
                        for p in (await _publications(s, ws, upload_id)).values()
                    )
                    snapshot = (list(row.transcript or []), dict(row.edit_plan or {}), row.status, row.status_detail)
                    if not posted:
                        row.job_ids = [j for j in row.job_ids or [] if j != AUTO_MARK] + [AUTO_MARK]
                    await s.commit()
            if not in_front:
                if posted:
                    await _apply_review(upload_id, ws, words, answer, fix_words=False, voices=voices)
                    await _note(
                        upload_id, ws, None,
                        "Jennifer's review arrived after this video was posted; the posted edit stays",
                    )
                    return
                try:
                    await _apply_review(upload_id, ws, words, answer, voices=voices)
                    await _plan_and_render_locked(upload_id, ws, restore_if_blocked=snapshot)
                finally:
                    async with session_factory()() as s:
                        row = await _load(s, upload_id, ws)
                        row.job_ids = [j for j in row.job_ids or [] if j != AUTO_MARK]
                        await s.commit()
                return
        await asyncio.sleep(SITTING_RECHECK_S)
    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        review = dict((row.edit_plan or {}).get("review") or {})
    if review.get("state") == "waiting":
        await _save_review(upload_id, ws, {**review, "state": "unavailable",
                                           "detail": "no answer in time"}, None)


async def _plan_and_render(upload_id: uuid.UUID, ws: uuid.UUID) -> RecordingUpload:
    async with _render_lock(upload_id):
        return await _plan_and_render_locked(upload_id, ws)


_BLOCKED_SAYS = {
    "review": "Jennifer's review wants a cut that needs your eyes, so the edit you have stays: {reason}",
    "notes": "Your notes would make a cut that needs your eyes, so the edit you have stays: {reason}",
    "undo": "Going back to the version before your notes needs your eyes, so the edit you have "
    "stays: {reason}",
}


async def _plan_and_render_locked(
    upload_id: uuid.UUID,
    ws: uuid.UUID,
    *,
    restore_if_blocked: tuple[list[dict[str, Any]], dict[str, Any], str, str | None] | None = None,
    blocked_by: Literal["review", "notes", "undo"] = "review",
) -> RecordingUpload:
    """Plan, then render unless the meaning check wants his eyes. With
    `restore_if_blocked` (a late review, a sitting's notes, an undo), a plan that needs
    his eyes does not replace the edit he already has: transcript, plan and status go
    back, so the card, the subtitles and the posts keep describing the video that
    exists. Only a blocked review is kept as "blocked" on the plan: marking the review
    blocked for someone else's change would stop its cuts from being used (30-Sep)."""
    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        await _compute_plan(s, ws, row)
        if restore_if_blocked is not None and row.status != "planned" and row.edited_path:
            reason = row.status_detail or "the cut would change what you said"
            transcript, plan, status, detail = restore_if_blocked
            row.transcript = transcript
            if blocked_by == "review":
                review = (row.edit_plan or {}).get("review") or {}
                review = {**review, "state": "blocked", "detail": reason[:300]}
                row.edit_plan = {**plan, "review": review}
            else:
                row.edit_plan = dict(plan)
            row.status = status
            row.status_detail = _BLOCKED_SAYS[blocked_by].format(reason=reason)[:500]
        await s.commit()
        status = row.status
    if status != "planned":  # the meaning check wants his eyes: never render past it
        async with session_factory()() as s:
            return await _load(s, upload_id, ws)
    return await _step(
        upload_id,
        ws,
        "rendering",
        "Cutting and burning in your captions",
        lambda attempt: _run_render(upload_id, ws, attempt, "cut"),
    )


async def _second_listen(upload_id: uuid.UUID, ws: uuid.UUID) -> None:
    """Hear again the stretches the first transcription may have got wrong (29-Sep).

    "and then that question, and then that question" came out once, Hebrew to the dogs
    came out as an English "A", and a false start vanished inside "Bring": the editor
    cannot remove what the transcript does not hold. Once per transcript; the words it
    changes are listed on the plan. A worker that does not answer leaves the transcript
    as it was (the edit goes on)."""
    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        words = list(row.transcript or [])
        done = ((row.edit_plan or {}).get("second_listen") or {}).get("state") == "done"
        src = row.storage_path
    url = settings.production_transcribe_ws_url
    if done or not url or not words or not is_word_level(words) or not src or not Path(src).exists():
        return
    latin = sum(1 for w in words if wordbox.usable([{"text": w.get("text")}]))
    main_language = "en" if latin >= 0.8 * len(words) else "other"
    wins = relisten.windows(words)
    heard: list[dict[str, Any] | None] = []
    failures = 0

    def said(res: dict[str, Any]) -> str:
        return " ".join(str(w.get("word") or "") for w in res.get("words") or []).strip()

    for n, win in enumerate(wins, 1):
        await _note(
            upload_id, ws, "proofreading",
            f"Listening again to stretch {n} of {len(wins)} the first pass may have misheard "
            f"({win.why[0]})",
        )
        if failures >= 3:
            heard.append(None)  # the worker is not answering: leave the rest as heard
            continue
        try:
            res = await media.transcribe_clip(src, win.start, win.end, ws_url=url)
            if main_language == "en" and not relisten.english(res):
                he = await media.transcribe_clip(src, win.start, win.end, ws_url=url, language="he")
                res["hebrew"] = said(he)
                if len(win.utts) > 1:
                    # One verdict for the stretch would take English lines with the aside.
                    parts: list[dict[str, Any] | None] = []
                    for k, (a, b) in enumerate(relisten.utterance_clips(words, win), 1):
                        await _note(
                            upload_id, ws, "proofreading",
                            f"Stretch {n} is not all English: hearing its line {k} of {len(win.utts)} "
                            "on its own for which language it is",
                        )
                        try:
                            part = await media.transcribe_clip(src, a, b, ws_url=url)
                            if not relisten.english(part):
                                part["hebrew"] = said(
                                    await media.transcribe_clip(src, a, b, ws_url=url, language="he")
                                )
                            parts.append(part)
                        except Exception:  # noqa: BLE001 - that line stays as first heard
                            failures += 1
                            parts.append(None)
                    res["parts"] = parts
            heard.append(res)
        except Exception:  # noqa: BLE001 - a second listen is a bonus, never a stop
            failures += 1
            heard.append(None)
    activity = await _speech_activity(src)
    new_words, report = relisten.merge(
        words, wins, heard, main_language=main_language,
        regions=activity.regions if activity is not None else None,
    )
    sounds: list[dict[str, Any]] = []
    if activity is not None and main_language == "en":
        leads = relisten.lead_candidates(
            new_words, activity.levels, activity.low_db, activity.high_db, activity.regions
        )

        async def hear(a: float, b: float, why: str) -> dict[str, Any] | None:
            nonlocal failures
            await _note(upload_id, ws, "proofreading", why)
            if failures >= 3:
                return None
            try:
                return await media.transcribe_clip(src, a, b, ws_url=url, language="en")
            except Exception:  # noqa: BLE001 - a second listen is a bonus, never a stop
                failures += 1
                return None

        cuts = await relisten.find_cuts(new_words, leads, hear)
        new_words, sounds = relisten.split_leading_sounds(new_words, cuts)
    changes = [r for r in report if r.get("result") != "same"]
    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        if [w.get("text") for w in row.transcript or []] != [w.get("text") for w in words]:
            return  # he changed the words meanwhile; his version stands
        row.transcript = new_words
        plan = dict(row.edit_plan or {})
        # A worker that heard nothing leaves it to be tried again on the next edit.
        plan["second_listen"] = {
            "state": "done" if not wins or any(heard) else "unheard",
            "windows": len(wins), "heard": sum(1 for h in heard if h),
            "changes": changes, "sounds": sounds, "at": _utcnow().isoformat(),
        }
        row.edit_plan = plan
        row.status_detail = (
            f"Listened again to {sum(1 for h in heard if h)} of {len(wins)} stretches: "
            f"{sum(1 for c in changes if c['result'] == 'more words')} came back with words the "
            f"first pass dropped, {sum(1 for c in changes if c['result'] == 'not English')} were not "
            f"English, {len(sounds)} sound{'s' if len(sounds) != 1 else ''} split off"
        )[:500]
        await s.commit()


async def auto_edit(upload_id: uuid.UUID, ws: uuid.UUID) -> None:
    """Transcribe -> the editor's review -> plan -> render, for a session he just finished."""
    review_state = "skipped"
    try:
        async with session_factory()() as s:
            row = await _load(s, upload_id, ws)
            row.job_ids = [j for j in row.job_ids or [] if j != AUTO_MARK] + [AUTO_MARK]
            has_words = bool(row.transcript)
            await s.commit()
        if not has_words:
            row = await _step(
                upload_id,
                ws,
                "transcribing",
                "Editing it for you: transcribing on this server",
                lambda attempt: _run_transcription(upload_id, ws, attempt),
            )
            if row.status != "transcribed":
                return  # failed / unavailable: the row already says why
        await _second_listen(upload_id, ws)
        review_state = await _review(upload_id, ws, wait_timeout_s=REVIEW_FIRST_WAIT_S)
        row = await _plan_and_render(upload_id, ws)
        if row.status == "edited":
            start_draft_posts(upload_id, ws)
    except Exception as exc:  # noqa: BLE001 - lands on the row
        await _note(upload_id, ws, "failed", f"Automatic edit stopped: {str(exc)[:300]}. The recording is safe.")
    finally:
        async with session_factory()() as s:
            row = await _load(s, upload_id, ws)
            row.job_ids = [j for j in row.job_ids or [] if j != AUTO_MARK]
            await s.commit()
    if review_state == "waiting":
        _spawn(_await_review(upload_id, ws))


def start_auto_edit(upload_id: uuid.UUID, ws: uuid.UUID) -> None:
    if settings.production_auto_edit:
        _spawn(auto_edit(upload_id, ws))


EDIT_REQUEST_ROUNDS = 2  # the words changed while it read: read once more, then ask him
REQUEST_JOINED = (
    "Added to your notes on this video: it is made with them, in one re-render, when you say make it."
)
REQUEST_WAITS_FOR_NOTES = (
    "Waiting: your notes on this video are being made into a new version first. "
    "This request is read after that, on the new version."
)
REQUEST_WORDS_MOVED = (
    "The words of this video changed twice while Jennifer was reading this request, "
    "so nothing was changed. Send it again."
)
REQUEST_NOTES_TOOK_TOO_LONG = (
    "Your notes on this video were still being made, so this request was not carried out. "
    "Send it again once the new version is ready."
)


def edit_request_key(request_id: uuid.UUID, prompt: str, system: str) -> str:
    """Everything the request's job reads is in its key, like _review_key: words that
    changed while it read are read again as a new job (1-Oct review), and a changed
    skill file or history is no longer refused by the queue as a reused key."""
    body = "\x1f".join([autoedit.PROMPT_VERSION, system, prompt])
    return f"edit-request:{request_id}:{hashlib.sha256(body.encode()).hexdigest()[:24]}"


async def _load_request(s: AsyncSession, request_id: uuid.UUID, ws: uuid.UUID):
    from tce.models.editorial_workspace import EditingRequest

    query = select(EditingRequest).where(EditingRequest.id == request_id, EditingRequest.workspace_id == ws)
    return (await s.execute(query)).scalar_one_or_none()


async def _join_his_notes(s: AsyncSession, ws: uuid.UUID, req: Any) -> bool:
    """He is giving notes on this video: the request becomes one more of them (made with
    the others in one re-render) instead of re-rendering under his player."""
    sitting = await library_service.joinable_sitting(s, ws, req.upload_id)
    if sitting is None:
        return False
    await library_service.join_sitting(s, req, sitting)
    req.result = {"status": REQUEST_JOINED}
    await s.commit()
    return True


async def _request_gate(request_id: uuid.UUID, ws: uuid.UUID, upload_id: uuid.UUID, settle) -> str:
    """Before the request is read: "go"; "joined" when it became a note of the sitting he
    is giving notes in; "gone" when it is no longer to be carried out. While a sitting's
    notes are being made it waits for them (its words would be read before the batch
    changes them), then reads the video as it is after."""
    deadline = _utcnow() + timedelta(hours=settings.production_review_wait_h)
    said_waiting = False
    while True:
        async with session_factory()() as s:
            req = await _load_request(s, request_id, ws)
            if req is None or req.state not in ("open", "in_progress"):
                return "gone"
            if await library_service.working_sitting(s, ws, upload_id) is None:
                return "joined" if await _join_his_notes(s, ws, req) else "go"
        if _utcnow() >= deadline:
            await settle("needs_you", {"question": REQUEST_NOTES_TOOK_TOO_LONG})
            return "gone"
        if not said_waiting:
            await settle("in_progress", {"status": REQUEST_WAITS_FOR_NOTES})
            said_waiting = True
        await _sitting_recheck()


async def _sitting_recheck() -> None:
    """The pause between two looks at a sitting whose notes are being made."""
    await asyncio.sleep(SITTING_RECHECK_S)


async def _request_inputs(request_id: uuid.UUID, ws: uuid.UUID) -> dict[str, Any] | None:
    """What the request's job reads, in one snapshot."""
    from tce.models.editorial_workspace import EditingRequest

    async with session_factory()() as s:
        req = await _load_request(s, request_id, ws)
        if req is None or req.state not in ("open", "in_progress"):
            return None
        row = await _load(s, req.upload_id, ws)
        # One conversation per video (30-Sep: six notes about one "cou", each read as
        # new, got the same question back six times).
        earlier = (
            await s.execute(
                select(EditingRequest)
                .where(
                    EditingRequest.upload_id == row.id,
                    EditingRequest.workspace_id == ws,
                    EditingRequest.id != request_id,
                    EditingRequest.created_at <= req.created_at,
                    # 1-Oct review: a note given in a sitting that was never made (taken
                    # back, or still waiting for "make it") is not something he asked
                    # for; the voice test call drops one on a video every run.
                    EditingRequest.session_id.is_(None)
                    | EditingRequest.state.not_in(SITTING_NOTES_NEVER_MADE),
                )
                .order_by(EditingRequest.created_at)
            )
        ).scalars().all()
        return {
            "words": list(row.transcript or []),
            "keep": [list(r) for r in (row.edit_plan or {}).get("keep") or []],
            "kept": list((row.edit_plan or {}).get("words") or []),
            "context": await _script_context(s, ws, row),
            "text": req.request,
            "scope": req.scope,
            "start_s": req.start_s,
            "end_s": req.end_s,
            "src": row.storage_path,
            "history": [
                {
                    "request": str(e.request),
                    "reply": str((e.result or {}).get("reply") or ""),
                    "question": str((e.result or {}).get("question") or ""),
                }
                for e in earlier[-12:]
            ],
        }


async def _apply_request(
    request_id: uuid.UUID,
    ws: uuid.UUID,
    upload_id: uuid.UUID,
    words: list[dict[str, Any]],
    change: tuple[list[dict[str, Any]], list[Any], list[Any], list[Any]],
    settle,
) -> RecordingUpload | str:
    """Write what the request changes and render once, under the render lock. Returns
    the video as it ended, or "joined" (he is giving notes: it joined them), "gate" (a
    sitting's notes started being made: wait for them), "changed" (the words moved
    while it read: read them again)."""
    fixed, cut, restore, hold = change
    fp = library_service.transcript_fingerprint
    async with _render_lock(upload_id):
        async with session_factory()() as s:
            if await library_service.working_sitting(s, ws, upload_id) is not None:
                return "gate"
            req = await _load_request(s, request_id, ws)
            if req is not None and await _join_his_notes(s, ws, req):
                return "joined"
            row = await _load(s, upload_id, ws)
            if fp(row.transcript) != fp(words):
                return "changed"
            row.transcript = fixed
            plan = dict(row.edit_plan or {})
            plan["overrides"] = autoedit.merge_overrides(plan.get("overrides"), cut, restore, hold)
            row.edit_plan = plan
            await s.commit()
        await settle("in_progress", {"status": "Applying your changes and re-rendering"})
        return await _plan_and_render_locked(upload_id, ws)


async def run_edit_request(request_id: uuid.UUID, ws: uuid.UUID) -> None:
    """Carry out one editing request on the subscription, or ask one question.

    1-Oct review: a request read the words, waited on the worker, then wrote back words
    fixed from that old copy (undoing a batch's fixes made meanwhile) and rendered under
    a sitting. Now: while he is giving notes on the video it joins them as one more note;
    while a sitting's notes are being made it waits, then reads the new words; and it
    writes only under the render lock, only over the words it read (changed: it reads
    them again as a new job). While it runs, notes cannot be opened (upload_busy).
    """
    from tce.llm import LLMUnavailable

    upload_id: uuid.UUID | None = None

    async def settle(state: str, result: dict[str, Any]) -> None:
        async with session_factory()() as s:
            req = await _load_request(s, request_id, ws)
            if req is None:
                return
            req.state = state
            req.result = result
            req.updated_at = _utcnow()
            if state in ("done", "needs_you", "rejected"):
                req.resolved_at = _utcnow()
            await s.commit()
        if upload_id is not None and state == "in_progress" and result.get("status"):
            _request_running(upload_id, request_id, str(result["status"]))

    try:
        async with session_factory()() as s:
            req = await _load_request(s, request_id, ws)
            if req is None or req.state not in ("open", "in_progress"):
                return
            upload_id = req.upload_id
        _request_running(upload_id, request_id, "Reading your request on the subscription")
        moved = 0
        while True:
            if await _request_gate(request_id, ws, upload_id, settle) != "go":
                return
            got = await _request_inputs(request_id, ws)
            if got is None:
                return
            words, keep = got["words"], got["keep"]
            if not words or not keep:
                await settle("open", {"status": "Waiting: this recording is not edited yet."})
                return
            await settle("in_progress", {"status": "Reading your request on the subscription"})
            marks = await word_marks_for(got["src"], words, keep)
            prompt = autoedit.edit_request_prompt(
                words, keep, got["context"], got["text"], scope=got["scope"], start_s=got["start_s"],
                end_s=got["end_s"], kept=got["kept"], marks=marks, history=got["history"],
            )
            system = autoedit.edit_request_system()
            try:
                answer = await _ask(
                    autoedit.EDIT_REQUEST_JOB, prompt, system, autoedit.EDIT_REQUEST_SCHEMA, ws,
                    edit_request_key(request_id, prompt, system),
                )
            except LLMUnavailable as exc:
                await settle("in_progress", {"status": f"Waiting for the subscription worker ({exc.status})"})
                return
            out = answer.structured or {}
            if out.get("needs_you"):
                await settle(
                    "needs_you",
                    {"reply": str(out.get("reply") or ""), "question": str(out.get("question") or "")},
                )
                return
            fixed, applied = autoedit.apply_corrections(words, out.get("corrections") or [])
            cut = autoedit.word_ranges(words, out.get("cut") or [])
            restore = autoedit.word_ranges(words, out.get("restore") or [])
            hold = autoedit.word_holds(words, out.get("hold") or [])
            if not (applied or cut or restore or hold) and str(out.get("reply") or "").strip():
                # An answer, not a change (30-Sep: "the phone cut the 's' off 'course'; no
                # cut can bring it back" is the whole answer, not a question back to him).
                await settle("done", {"reply": str(out["reply"]), "changed": False, "model": answer.model})
                return
            if not (applied or cut or restore or hold):
                await settle(
                    "needs_you",
                    {
                        "reply": str(out.get("reply") or ""),
                        "question": "I could not turn that into a change to the video. "
                        "What exactly should change, and roughly where?",
                    },
                )
                return
            row = await _apply_request(request_id, ws, upload_id, words, (fixed, cut, restore, hold), settle)
            if row == "joined":
                return
            if row == "gate":
                continue  # a sitting's notes are being made: wait for them, then read again
            if row == "changed":
                moved += 1
                if moved >= EDIT_REQUEST_ROUNDS:
                    await settle("needs_you", {"reply": str(out.get("reply") or ""), "question": REQUEST_WORDS_MOVED})
                    return
                continue
            break
        result = {
            "reply": str(out.get("reply") or "Done."),
            "corrections": [{"heard": c["heard"], "replacement": c["replacement"]} for c in applied],
            "cut": cut,
            "restore": restore,
            "hold": hold,
            "file": f"/api/v1/production/uploads/{upload_id}/edited",
            "model": answer.model,
        }
        if row.status == "edited":
            await settle("done", result)
        else:
            await settle("needs_you", {**result, "question": f"The re-render stopped: {row.status_detail}"})
    except Exception as exc:  # noqa: BLE001 - lands on the request
        await settle("in_progress", {"status": f"Stopped with an error; it retries on restart: {str(exc)[:300]}"})
    finally:
        _request_stopped(request_id)


def start_edit_request(request_id: uuid.UUID, ws: uuid.UUID, upload_id: uuid.UUID | None = None) -> None:
    """Carry the request out now. With `upload_id` the video counts as busy from this
    moment, before the task first runs, so notes cannot open in between."""
    if settings.production_auto_edit:
        if upload_id is not None:
            _request_running(upload_id, request_id, "Reading your request on the subscription")
        _spawn(run_edit_request(request_id, ws))


# ---------------------------------------------------------------------------
# Talk to the editor (30-Sep): a sitting's notes in one job, then one render.
# "Collect all notes, one re-render at the end." The sitting's state is its lock on
# the video: thinking and rendering hold the gates that stop other renders, so every
# path out of them ends in done, needs_you, failed, or back to open with the notes kept.

TALK_ASK_WAIT_S = 60.0  # one wait on the worker before the sitting says where it stands
TALK_WORKER_RETRY_S = 30.0  # the worker is away: ask again this often
TALK_MAX_ASKS = 2  # the words changed while it read: read once more, then hand the notes back


def talk_key(session_id: uuid.UUID, prompt: str, system: str, attempt: int = 0) -> str:
    """Everything the batch reads is in its key, like _review_key: a changed skill file,
    note or transcript is a new job instead of the queue refusing a reused key.

    `attempt` counts his "make it" taps on the sitting (1-Oct review): after a failed job
    (an expired worker login is never re-queued) the same notes tapped again are a new
    job, not the failed one for ever. The worker-away wait and a restart keep the key."""
    parts = [autoedit.EDIT_BATCH_PROMPT_VERSION, system, prompt]
    if attempt > 1:
        parts.append(f"attempt {attempt}")
    body = "\x1f".join(parts)
    return f"edit-batch:{session_id}:{hashlib.sha256(body.encode()).hexdigest()[:24]}"


def talk_tokens(count: int) -> int:
    """Room for every note's answer: the request job's 2000 is sized for one."""
    return min(8000, 1500 + 600 * count)


async def _load_sitting(s: AsyncSession, session_id: uuid.UUID, ws: uuid.UUID):
    from tce.models.editorial_workspace import EditSession

    query = select(EditSession).where(EditSession.id == session_id, EditSession.workspace_id == ws)
    return (await s.execute(query)).scalar_one_or_none()


async def _talk_status(session_id: uuid.UUID, ws: uuid.UUID, status: str, **fields: Any) -> None:
    """What the batch is doing right now, on the sitting the sheet polls (3-second rule)."""
    async with session_factory()() as s:
        sitting = await _load_sitting(s, session_id, ws)
        if sitting is None:
            return
        sitting.result = {**(sitting.result or {}), "status": status[:500]}
        for name, value in fields.items():
            setattr(sitting, name, value)
        await s.commit()


async def _hand_back(session_id: uuid.UUID, ws: uuid.UUID, status: str) -> None:
    """Nothing was changed: the sitting takes notes again with every note as it was."""
    async with session_factory()() as s:
        sitting = await _load_sitting(s, session_id, ws)
        if sitting is None or sitting.state != "thinking":
            return
        sitting.state = "open"
        sitting.submitted_at = None
        sitting.result = {**(sitting.result or {}), "status": status[:500]}
        await s.commit()


def _talk_note(note: Any) -> dict[str, Any]:
    """One note as the batch prompt reads it."""
    where = None
    if note.scope == "timestamp" and note.start_s is not None and note.end_s is not None:
        where = f"{library_service.clock(note.start_s)} to {library_service.clock(note.end_s)} in the edit"
    elif note.scope == "section" and note.section_ref:
        where = str(note.section_ref)
    return {
        "said": note.request or "",
        "understood": note.understood or "",
        "edit_s": note.start_s if note.scope == "moment" else None,
        "where": where,
        "source_s": note.source_s,
    }


def _history_row(req: Any) -> dict[str, Any]:
    result = req.result or {}
    where = None
    if req.scope == "moment" and req.start_s is not None:
        where = f"At {library_service.clock(req.start_s)}"
    return {
        "request": (req.request or "").strip() or (req.understood or ""),
        "where": where,
        "reply": str(result.get("reply") or ""),
        "question": str(result.get("question") or ""),
        "undone": bool(result.get("undone_at")),
    }


async def _talk_inputs(session_id: uuid.UUID, ws: uuid.UUID) -> dict[str, Any] | None:
    """What the batch reads, in one snapshot: the notes he heard read back, in his order,
    the transcript and plan, the script, and what came of earlier notes on the video."""
    from tce.models.editorial_workspace import EditingRequest

    async with session_factory()() as s:
        sitting = await _load_sitting(s, session_id, ws)
        if sitting is None or sitting.state != "thinking":
            return None
        row = await _load(s, sitting.upload_id, ws)
        heard_ids = [str(i) for i in (sitting.result or {}).get("notes") or []]
        by_id = {
            str(r.id): r
            for r in (
                await s.execute(
                    select(EditingRequest).where(
                        EditingRequest.workspace_id == ws, EditingRequest.session_id == sitting.id
                    )
                )
            ).scalars()
        }
        waiting = library_service.WAITING_NOTE_STATES
        notes = [by_id[i] for i in heard_ids if i in by_id and by_id[i].state in waiting]
        earlier = (
            await s.execute(
                select(EditingRequest)
                .where(
                    EditingRequest.workspace_id == ws,
                    EditingRequest.upload_id == row.id,
                    EditingRequest.state.in_(("done", "needs_you")),
                )
                .order_by(EditingRequest.created_at)
            )
        ).scalars().all()
        plan = row.edit_plan or {}
        # 1-Oct review: the notes were given on the file he watched, so the editor reads
        # them against that file's keep, never a plan that moved on since (an uncut
        # render, a blocked re-plan, a failed render). The plan's word times only while
        # the plan is still that edit, the same rule as the moment.
        watched = [list(r) for r in sitting.keep_snapshot or []]
        plan_keep = [list(r) for r in plan.get("keep") or []]
        keep = watched or plan_keep
        kept = library_service.watched_plan_words(plan, keep)
        return {
            "upload_id": row.id,
            "words": list(row.transcript or []),
            "keep": keep,
            "kept": kept or [],
            "plan_moved": bool(watched) and bool(plan_keep) and kept is None,
            "context": await _script_context(s, ws, row),
            "src": row.storage_path,
            "note_ids": [n.id for n in notes],
            "notes": [_talk_note(n) for n in notes],
            "history": [_history_row(e) for e in earlier if e.session_id != sitting.id][-12:],
            "submitted_at": sitting.submitted_at,
            "attempt": int((sitting.result or {}).get("attempt") or 0),
            # An earlier re-edit's cut waits for his eyes: a re-plan would stop on it again.
            "waits": library_service.edit_waits_for_him(row),
        }


async def _ask_for_notes(
    session_id: uuid.UUID, ws: uuid.UUID, got: dict[str, Any], prompt: str, system: str, key: str
):
    """The one Opus job. While the worker is away the sitting says so and asks again
    (the queued job is reused, never asked twice) until production_review_wait_h after
    he said make it. Any other refusal hands the notes back unchanged. None when the
    notes were handed back."""
    from tce.llm import LLMUnavailable
    from tce.llm.queue import QueueError

    count = len(got["notes"])
    reading = f"Reading your {count} note{'s' if count != 1 else ''} on the subscription"
    deadline = (got["submitted_at"] or _utcnow()) + timedelta(hours=settings.production_review_wait_h)
    while True:
        try:
            return await _ask(
                autoedit.EDIT_BATCH_JOB, prompt, system, autoedit.EDIT_BATCH_SCHEMA, ws, key,
                wait_timeout_s=TALK_ASK_WAIT_S, prompt_version=autoedit.EDIT_BATCH_PROMPT_VERSION,
                max_tokens=talk_tokens(count), requeue_failed=True,
            )
        except LLMUnavailable as exc:
            if exc.status in ("timeout", "waiting_capacity") and _utcnow() < deadline:
                # A worker holding the job is reading it; otherwise nobody has picked it up.
                leased = "still leased" in str(exc.detail or "")
                away = f"Waiting for the subscription worker ({exc.status})"
                await _talk_status(session_id, ws, reading if leased else away)
                await asyncio.sleep(TALK_WORKER_RETRY_S)
                continue
            waited = exc.status in ("timeout", "waiting_capacity")
            await _hand_back(
                session_id,
                ws,
                (
                    f"Jennifer did not answer within {settings.production_review_wait_h:.0f} hours"
                    if waited
                    else f"Jennifer could not read the notes ({exc.status})"
                )
                + ". Your notes are kept and nothing was changed; make the new version again.",
            )
            return None
        except QueueError as exc:
            await _hand_back(
                session_id,
                ws,
                f"Jennifer could not read the notes ({exc.__class__.__name__}). Your notes are kept "
                "and nothing was changed; make the new version again.",
            )
            return None


async def _apply_notes(
    session_id: uuid.UUID, ws: uuid.UUID, got: dict[str, Any], answer: Any
) -> tuple[list[dict[str, Any]], dict[str, Any], str, str | None] | bool | None:
    """Write what the answer changes, under the render lock. Returns the edit as it was
    (for restore_if_blocked) when there is something to render, False when there is
    nothing to render, None when the words changed while the editor read (ask again)."""
    async with session_factory()() as s:
        sitting = await _load_sitting(s, session_id, ws)
        if sitting is None or sitting.state != "thinking":
            return False
        row = await _load(s, got["upload_id"], ws)
        if library_service.transcript_fingerprint(row.transcript) != library_service.transcript_fingerprint(
            got["words"]
        ):
            return None
        plan = dict(row.edit_plan or {})
        batch = autoedit.apply_batch(
            got["words"], plan.get("overrides"), answer.structured or {}, len(got["notes"])
        )
        outcomes = [{**o, "id": str(nid)} for o, nid in zip(batch["notes"], got["note_ids"], strict=True)]
        result = {
            **(sitting.result or {}),
            "outcomes": outcomes,
            "model": answer.model,
            "batch_summary": batch["summary"],
        }
        snapshot = None
        if batch["changed"]:
            snapshot = (list(row.transcript or []), dict(row.edit_plan or {}), row.status, row.status_detail)
            # For undo: the edit as it was, and a fingerprint of what this batch wrote, so
            # going back never undoes a later change.
            sitting.before = {
                "transcript": snapshot[0],
                "overrides": plan.get("overrides"),
                "plan": snapshot[1],
                "render_ref": row.render_ref,
                "status": row.status,
                "status_detail": row.status_detail,
                "after": library_service.transcript_fingerprint(batch["words"]),
                "after_overrides": batch["overrides"],
                "at": _utcnow().isoformat(),
            }
            row.transcript = batch["words"]
            plan["overrides"] = batch["overrides"]
            row.edit_plan = plan
            sitting.state = "rendering"
            result["status"] = "Applying your notes, then cutting and burning in your captions"
        sitting.result = result
        await s.commit()
    return snapshot if snapshot is not None else False


def _note_outcome(
    o: dict[str, Any], stop: str | None, file_url: str | None, model: str | None
) -> tuple[str, dict[str, Any]]:
    """A note's final state and result, from what the batch did with it."""
    base: dict[str, Any] = {"note": o.get("note"), "reply": str(o.get("reply") or ""), "model": model}
    if o.get("skipped"):
        base["skipped"] = list(o["skipped"])
    kind = o.get("outcome")
    if kind == "change":
        res = {
            **base,
            "reply": base["reply"] or "Done.",
            "corrections": o.get("corrections") or [],
            "cut": o.get("cut") or [],
            "restore": o.get("restore") or [],
            "hold": o.get("hold") or [],
            "file": file_url,
        }
        if stop:
            return "needs_you", {**res, "question": f"The re-render stopped: {stop}"}
        return "done", res
    if kind == "answer":
        return "done", {**base, "changed": False}
    return "needs_you", {**base, "question": str(o.get("question") or autoedit.UNCLEAR_QUESTION)}


async def _settle_talk(session_id: uuid.UUID, ws: uuid.UUID, *, stopped: str | None = None) -> None:
    """Every note of the batch ends done or needs_you, and the sitting ends with the
    render he now has. `stopped` says why the render never ran (an error)."""
    from tce.models.editorial_workspace import EditingRequest

    async with session_factory()() as s:
        sitting = await _load_sitting(s, session_id, ws)
        if sitting is None or sitting.state not in library_service.SITTING_WORKING_STATES:
            return
        row = await _load(s, sitting.upload_id, ws)
        result = dict(sitting.result or {})
        outcomes = list(result.get("outcomes") or [])
        before = dict(sitting.before or {})
        fp = library_service.transcript_fingerprint
        new_render = row.status == "edited" and row.render_ref != before.get("render_ref")
        rendered = bool(before) and stopped is None and new_render
        stop = None
        if before and not rendered:
            stop = stopped or row.status_detail or "the render did not finish"
            put_back = fp(row.transcript) == fp(before.get("transcript"))
            if put_back and (row.edit_plan or {}).get("overrides") == before.get("overrides"):
                sitting.before = None  # the edit he had was put back: nothing to undo
        file_url = library_service.edit_file_url(row, row.render_ref)
        notes = {
            str(n.id): n
            for n in (
                await s.execute(
                    select(EditingRequest).where(
                        EditingRequest.workspace_id == ws, EditingRequest.session_id == sitting.id
                    )
                )
            ).scalars()
        }
        now = _utcnow()
        needs = 0
        for o in outcomes:
            note = notes.get(str(o.get("id")))
            if note is None:
                continue
            state, res = _note_outcome(o, stop, file_url, result.get("model"))
            note.state, note.result = state, res
            note.updated_at = note.resolved_at = now
            needs += state == "needs_you"
        notes_said = f"{len(outcomes)} note{'s' if len(outcomes) != 1 else ''}"
        waiting = f" {needs} of them need{'s' if needs == 1 else ''} you." if needs else ""
        if stop:
            status = f"The re-render stopped: {stop}"
        elif rendered:
            status = f"New version made from your {notes_said}.{waiting}"
        else:
            status = f"Nothing in the video needed changing for your {notes_said}.{waiting}"
        if rendered:
            sitting.render_ref = row.render_ref
            sitting.keep_snapshot = [list(r) for r in row.rendered_keep or []]
        result["read_back"] = result.get("read_back") or sitting.summary
        result["status"] = status[:500]
        result["render_ref"] = row.render_ref
        sitting.summary = result.get("batch_summary") or status
        sitting.result = result
        sitting.state = "needs_you" if needs else "done"
        sitting.finished_at = now
        await s.commit()


async def _render_notes_locked(session_id: uuid.UUID, ws: uuid.UUID, upload_id: uuid.UUID) -> None:
    """The one render of a batch whose notes are written (the render lock held). After a
    restart the render may have finished already: then only the notes are settled."""
    async with session_factory()() as s:
        sitting = await _load_sitting(s, session_id, ws)
        if sitting is None or sitting.state != "rendering":
            return
        before = dict(sitting.before or {})
        row = await _load(s, upload_id, ws)
        finished = row.status == "edited" and row.render_ref != before.get("render_ref")
    if before and not finished:
        await _talk_status(session_id, ws, "Cutting and burning in your captions")
        await _plan_and_render_locked(
            upload_id,
            ws,
            restore_if_blocked=(
                list(before.get("transcript") or []),
                dict(before.get("plan") or {}),
                str(before.get("status") or "edited"),
                before.get("status_detail"),
            ),
            blocked_by="notes",
        )
    await _settle_talk(session_id, ws)


async def run_talk_session(session_id: uuid.UUID, ws: uuid.UUID) -> None:
    """Every note of a sitting in one job, then one render (talk to the editor, step 4).

    One Opus job on the subscription reads every note against one transcript snapshot;
    under the render lock the words are compared with that snapshot (changed: ask once
    more with a new key), then everything the notes change is written and the video is
    planned and rendered ONCE. A plan the meaning check blocks leaves the edit he has.
    Every note then ends done or needs_you, and the sitting ends with the new render.
    Restart-safe: a thinking sitting asks again (the same key reuses the job), a
    rendering one only renders and settles.
    """
    async with session_factory()() as s:
        sitting = await _load_sitting(s, session_id, ws)
        state = sitting.state if sitting is not None else None
        upload_id = sitting.upload_id if sitting is not None else None
    if state not in library_service.SITTING_WORKING_STATES or upload_id is None:
        return
    try:
        if state == "rendering":
            async with _render_lock(upload_id):
                await _render_notes_locked(session_id, ws, upload_id)
            return
        for _ask_round in range(TALK_MAX_ASKS):
            got = await _talk_inputs(session_id, ws)
            if got is None:
                return
            if not got["notes"]:
                await _hand_back(session_id, ws, "None of these notes has words yet. Nothing was changed.")
                return
            if got["waits"]:
                # 1-Oct final review: re-planned with an earlier re-edit's blocked cut still
                # in, the batch stopped on that cut, threw the notes' changes away and
                # blamed his notes. Handed back before any job is spent, saying whose cut.
                await _hand_back(session_id, ws, got["waits"])
                return
            if not got["words"] or not got["keep"]:
                await _hand_back(
                    session_id,
                    ws,
                    "This video has no edit to change right now. Your notes are kept and nothing was changed.",
                )
                return
            marks = await word_marks_for(got["src"], got["words"], got["keep"])
            prompt = autoedit.edit_batch_prompt(
                got["words"], got["keep"], got["context"], got["notes"],
                kept=got["kept"], marks=marks, history=got["history"], plan_moved=got["plan_moved"],
            )
            system = autoedit.edit_batch_system()
            key = talk_key(session_id, prompt, system, got["attempt"])
            count = len(got["notes"])
            reading = f"Reading your {count} note{'s' if count != 1 else ''} on the subscription"
            await _talk_status(session_id, ws, reading, llm_key=key)
            answer = await _ask_for_notes(session_id, ws, got, prompt, system, key)
            if answer is None:
                return
            async with _render_lock(upload_id):
                applied = await _apply_notes(session_id, ws, got, answer)
                if applied is None:
                    continue  # he or another step changed the words while it read
                if applied:
                    await _render_notes_locked(session_id, ws, upload_id)
                else:
                    await _settle_talk(session_id, ws)
            return
        await _hand_back(
            session_id,
            ws,
            "The words of this video changed twice while Jennifer was reading your notes. "
            "Your notes are kept and nothing was changed; make the new version again.",
        )
    except Exception as exc:  # noqa: BLE001 - lands on the sitting, never only in a log
        async with session_factory()() as s:
            sitting = await _load_sitting(s, session_id, ws)
            state = sitting.state if sitting is not None else None
        if state == "thinking":
            await _hand_back(
                session_id,
                ws,
                f"Stopped with an error before anything changed: {str(exc)[:300]}. Your notes are kept; "
                "make the new version again.",
            )
        elif state == "rendering":
            await _settle_talk(session_id, ws, stopped=f"Stopped with an error: {str(exc)[:300]}")


def start_talk_session(session_id: uuid.UUID, ws: uuid.UUID) -> None:
    """He said yes to the read-back: the one batch job for the sitting."""
    _spawn(run_talk_session(session_id, ws))


async def run_talk_undo(session_id: uuid.UUID, ws: uuid.UUID) -> None:
    """Put back the version from before a sitting's notes, then one re-render.

    Only while the transcript and the cuts are still what the batch wrote: going back
    over a later change would undo that too. Restart-safe: an undo whose words were put
    back before a restart only renders again.
    """
    from tce.models.editorial_workspace import EditingRequest

    fp = library_service.transcript_fingerprint

    async def say(undo: dict[str, Any]) -> None:
        async with session_factory()() as s:
            sitting = await _load_sitting(s, session_id, ws)
            if sitting is not None:
                sitting.result = {**(sitting.result or {}), "undo": {**undo, "at": _utcnow().isoformat()}}
                await s.commit()

    async with session_factory()() as s:
        sitting = await _load_sitting(s, session_id, ws)
        if sitting is None or not sitting.before:
            return
        if ((sitting.result or {}).get("undo") or {}).get("state") not in ("queued", "rendering"):
            return
        upload_id = sitting.upload_id
    try:
        async with _render_lock(upload_id):
            async with session_factory()() as s:
                sitting = await _load_sitting(s, session_id, ws)
                # 1-Oct review: two taps at once start two of these. The one that waited
                # for the lock finds the undo done (or stopped) by the other: nothing to
                # do, and nothing to overwrite with "the video was changed".
                undo_state = ((sitting.result or {}).get("undo") or {}).get("state")
                if not sitting.before or undo_state not in ("queued", "rendering"):
                    return
                before = dict(sitting.before or {})
                row = await _load(s, upload_id, ws)
                overrides = (row.edit_plan or {}).get("overrides")
                snapshot = None
                ref = row.render_ref
                now_words = fp(row.transcript)
                if now_words == before.get("after") and overrides == before.get("after_overrides"):
                    snapshot = (
                        list(row.transcript or []), dict(row.edit_plan or {}), row.status, row.status_detail
                    )
                    plan = dict(row.edit_plan or {})
                    if before.get("overrides") is None:
                        plan.pop("overrides", None)
                    else:
                        plan["overrides"] = before["overrides"]
                    row.transcript = list(before.get("transcript") or [])
                    row.edit_plan = plan
                elif not (now_words == fp(before.get("transcript")) and overrides == before.get("overrides")):
                    # Neither what the batch wrote nor the version from before: changed since.
                    await s.rollback()
                    await say({"state": "refused", "status": library_service.UNDO_CHANGED})
                    return
                sitting.result = {
                    **(sitting.result or {}),
                    "undo": {
                        "state": "rendering",
                        "status": "Putting back the version from before your notes: cutting and "
                        "burning in your captions",
                        "at": _utcnow().isoformat(),
                    },
                }
                await s.commit()
            row = await _plan_and_render_locked(upload_id, ws, restore_if_blocked=snapshot, blocked_by="undo")
            async with session_factory()() as s:
                sitting = await _load_sitting(s, session_id, ws)
                now = _utcnow()
                if row.status == "edited" and row.render_ref != ref:
                    sitting.before = None
                    sitting.result = {
                        **(sitting.result or {}),
                        "undo": {
                            "state": "done",
                            "status": "The version from before your notes is back.",
                            "render_ref": row.render_ref,
                            "at": now.isoformat(),
                        },
                    }
                    # Later notes on this video read these as undone, not as the edit he has.
                    for note in (
                        await s.execute(
                            select(EditingRequest).where(
                                EditingRequest.workspace_id == ws,
                                EditingRequest.session_id == sitting.id,
                                EditingRequest.state == "done",
                            )
                        )
                    ).scalars():
                        note.result = {**(note.result or {}), "undone_at": now.isoformat()}
                else:
                    sitting.result = {
                        **(sitting.result or {}),
                        "undo": {
                            "state": "stopped",
                            "status": f"Going back stopped: {row.status_detail}"[:500],
                            "at": now.isoformat(),
                        },
                    }
                await s.commit()
    except Exception as exc:  # noqa: BLE001 - lands on the sitting
        await say({"state": "stopped", "status": f"Going back stopped with an error: {str(exc)[:300]}"})


def start_talk_undo(session_id: uuid.UUID, ws: uuid.UUID) -> None:
    _spawn(run_talk_undo(session_id, ws))


async def resume_auto_work() -> None:
    """After a restart: finish automatic edits and requests that were mid-way."""
    import structlog

    from tce.models.editorial_workspace import EditingRequest, EditSession

    log = structlog.get_logger()
    # 30-Sep: a sitting he said "make it" to is his tap, like a post: it resumes whether
    # or not automatic editing is on, and a thinking or rendering sitting left alone
    # would hold the video's gates shut until the next restart.
    try:
        async with session_factory()() as s:
            working = (
                await s.execute(
                    select(EditSession).where(EditSession.state.in_(library_service.SITTING_WORKING_STATES))
                )
            ).scalars().all()
            sittings = [(r.id, r.workspace_id) for r in working]
            finished = (
                await s.execute(select(EditSession).where(EditSession.state.in_(("done", "needs_you", "failed"))))
            ).scalars().all()
            undos = [
                (r.id, r.workspace_id)
                for r in finished
                if ((r.result or {}).get("undo") or {}).get("state") in ("queued", "rendering")
            ]
        for session_id, ws in sittings:
            _spawn(run_talk_session(session_id, ws))
        for session_id, ws in undos:
            _spawn(run_talk_undo(session_id, ws))
        if sittings or undos:
            log.info("production.talk_resumed", sittings=len(sittings), undos=len(undos))
    except Exception:
        log.warning("production.talk_resume_failed", exc_info=True)
    if not settings.production_auto_edit:
        return
    try:
        async with session_factory()() as s:
            rows = (await s.execute(select(RecordingUpload))).scalars().all()
            marked = [(r.id, r.workspace_id) for r in rows if AUTO_MARK in (r.job_ids or [])]
            late = [
                (r.id, r.workspace_id)
                for r in rows
                if AUTO_MARK not in (r.job_ids or [])
                and ((r.edit_plan or {}).get("review") or {}).get("state") == "waiting"
            ]
            reqs = (
                await s.execute(select(EditingRequest).where(EditingRequest.state == "in_progress"))
            ).scalars().all()
            pending = [(r.id, r.workspace_id) for r in reqs]
        for upload_id, ws in marked:
            _spawn(auto_edit(upload_id, ws))
        for upload_id, ws in late:
            _spawn(_await_review(upload_id, ws))
        for request_id, ws in pending:
            _spawn(run_edit_request(request_id, ws))
        # 27-Sep: a deploy restarted TCE a minute after he tapped Post, and all four posts
        # sat on "posting" forever. A post that never reached its platform (still making
        # the upload copy, or queued) is finished now - his tap stands. One that was
        # mid-upload might be live already, so it waits for him instead of posting twice.
        async with session_factory()() as s:
            stuck = (
                await s.execute(select(VideoPublication).where(VideoPublication.status == "posting"))
            ).scalars().all()
            resume: dict[tuple[uuid.UUID, uuid.UUID], list[str]] = {}
            for pub in stuck:
                if (pub.detail or "").endswith(" now"):
                    pub.status = "failed"
                    pub.detail = (
                        "A restart stopped this while it was uploading. Check the platform before "
                        "posting again; it may already be live."
                    )
                else:
                    resume.setdefault((pub.upload_id, pub.workspace_id), []).append(pub.platform)
            await s.commit()
        for (upload_id, ws), platforms in resume.items():
            _spawn(publish_video(upload_id, ws, platforms, None))
            log.info("production.publish_resumed", upload=str(upload_id), platforms=platforms)
        if marked or pending or late:
            log.info("production.auto_resumed", uploads=len(marked), requests=len(pending), reviews=len(late))
    except Exception:
        log.warning("production.auto_resume_failed", exc_info=True)



# ---------------------------------------------------------------------------
# Publishing (26-Sep): "I want tce to be able to do the full publishing and to show
# me the post in the library". Copy is written on the subscription; his tap posts it
# through the schedule-* skills on this server; the Library shows the live links.


def _publication_json(row: VideoPublication) -> dict[str, Any]:
    return {
        "platform": row.platform,
        "label": publishing.LABELS.get(row.platform, row.platform),
        "status": row.status,
        "copy": row.copy or {},
        "scheduled_for": _iso(row.scheduled_for),
        "url": row.url,
        "detail": row.detail,
        "posted_at": _iso(row.posted_at),
    }


async def _publications(s: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID) -> dict[str, VideoPublication]:
    rows = (
        await s.execute(
            select(VideoPublication).where(
                VideoPublication.workspace_id == ws, VideoPublication.upload_id == upload_id
            )
        )
    ).scalars().all()
    return {r.platform: r for r in rows}


def _media_token(upload_id: uuid.UUID) -> str:
    key = settings.private_access_key.get_secret_value() if settings.private_access_key else ""
    return hashlib.sha256(f"social-media|{upload_id}|{key}".encode()).hexdigest()[:40]


async def draft_posts(upload_id: uuid.UUID, ws: uuid.UUID, *, rewrite: bool = False) -> None:
    """Write the four posts from what he says in the edit. Never touches a post that
    is already out, going out, or scheduled."""
    from tce.llm import LLMUnavailable

    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        existing = await _publications(s, ws, upload_id)
        if not rewrite and len(existing) == len(publishing.PLATFORMS):
            return
        words = list(row.transcript or [])
        keep = [list(r) for r in (row.edit_plan or {}).get("keep") or []]
        if not words or not keep:
            return
        title, script_posts = "", {}
        if row.candidate_id:
            cand = await s.get(TopicCandidate, row.candidate_id)
            title = cand.title if cand else ""
        if row.packet_id:
            packet = await s.get(RecordingPacket, row.packet_id)
            if packet is not None:
                script_posts = {"facebook": packet.facebook_post or "", "linkedin": packet.linkedin_post or ""}
        candidate_id = row.candidate_id
        spoken = publishing.spoken_text(words, keep, (row.edit_plan or {}).get("words"))
        from tce.editorial import lineup as lineup_service

        rules = await lineup_service.post_rules(s, ws)
    try:
        answer = await _ask(
            publishing.COPY_JOB,
            publishing.copy_prompt(title, spoken, rules, script_posts),
            publishing.COPY_SYSTEM,
            publishing.COPY_SCHEMA,
            ws,
            f"post-copy:{upload_id}:{hashlib.sha256((spoken + rules).encode()).hexdigest()[:12]}",
        )
    except LLMUnavailable:
        return  # the card offers "Write the posts" again
    copies = publishing.clean_copy(answer.structured or {})
    async with session_factory()() as s:
        existing = await _publications(s, ws, upload_id)
        for platform in publishing.PLATFORMS:
            pub = existing.get(platform)
            if pub is None:
                s.add(
                    VideoPublication(
                        workspace_id=ws, upload_id=upload_id, candidate_id=candidate_id,
                        platform=platform, status="draft", copy=copies[platform],
                    )
                )
            elif pub.status in ("draft", "failed"):
                pub.copy = copies[platform]
                pub.status, pub.detail = "draft", None
        await s.commit()


def start_draft_posts(upload_id: uuid.UUID, ws: uuid.UUID, *, rewrite: bool = False) -> None:
    _spawn(draft_posts(upload_id, ws, rewrite=rewrite))


async def revise_posts(upload_id: uuid.UUID, ws: uuid.UUID, request: str) -> None:
    """26-Sep: "I need a way to request a change to the posts". His words go to the
    subscription with the posts as they are; posts already out are never touched."""
    from tce.editorial import lineup as lineup_service
    from tce.llm import LLMUnavailable

    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        pubs = await _publications(s, ws, upload_id)
        words = list(row.transcript or [])
        keep = [list(r) for r in (row.edit_plan or {}).get("keep") or []]
        kept_words = (row.edit_plan or {}).get("words")
        title = ""
        if row.candidate_id:
            cand = await s.get(TopicCandidate, row.candidate_id)
            title = cand.title if cand else ""
        rules = await lineup_service.post_rules(s, ws)
        current = {p: dict(pub.copy or {}) for p, pub in pubs.items()}
        locked = [p for p, pub in pubs.items() if pub.status in ("posted", "scheduled", "posting")]
    spoken = publishing.spoken_text(words, keep, kept_words)

    async def finish(detail: str | None, copies: dict[str, dict[str, Any]] | None) -> None:
        async with session_factory()() as s:
            for p, pub in (await _publications(s, ws, upload_id)).items():
                if pub.status != "revising":
                    continue
                if copies is not None:
                    pub.copy = copies[p]
                pub.status, pub.detail = "draft", detail
            await s.commit()

    try:
        answer = await _ask(
            publishing.REVISE_JOB,
            publishing.revise_prompt(title, spoken, rules, current, locked, request),
            publishing.REVISE_SYSTEM,
            publishing.COPY_SCHEMA,
            ws,
            f"post-revise:{upload_id}:{hashlib.sha256((request + repr(current)).encode()).hexdigest()[:16]}",
        )
    except LLMUnavailable as exc:
        await finish(f"The change did not run ({exc.status}); ask again", None)
        return
    except Exception as exc:  # noqa: BLE001 - lands on the card
        await finish(f"The change stopped: {str(exc)[:200]}", None)
        return
    await finish(f"Changed as you asked: {request.strip()[:200]}", publishing.clean_copy(answer.structured or {}))


async def _social_copy(upload_id: uuid.UUID, ws: uuid.UUID) -> Path:
    """The upload-sized encode every platform gets (made once)."""
    async with session_factory()() as s:
        row = await _load(s, upload_id, ws)
        edited = Path(row.edited_path or "")
    if not edited.exists():
        raise RuntimeError("the edited video is not on the server")
    out = edited.with_name(f"{edited.stem}-social.mp4")
    if out.exists() and out.stat().st_mtime >= edited.stat().st_mtime:
        return out
    ff = media.ffmpeg_path()
    if not ff:
        raise RuntimeError("ffmpeg is not installed")
    tmp = out.with_name(f".{out.name}.part.mp4")
    proc = await asyncio.create_subprocess_exec(
        ff, *publishing.social_encode_args(edited, tmp),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _o, err = await proc.communicate()
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"could not make the upload copy: {err.decode(errors='replace')[-200:]}")
    os.replace(tmp, out)
    return out


def _linkedin_env() -> dict[str, str]:
    env = dict(os.environ)
    path = Path(settings.production_linkedin_env_file)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return env


async def run_platform(platform: str, argv: list[str]) -> tuple[int, str]:
    """Run one schedule-* skill from its own folder (its .env is read from there)."""
    cwd = Path(settings.production_skills_dir) / publishing.SKILLS[platform]
    env = _linkedin_env() if platform == "linkedin" else dict(os.environ)
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(cwd), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=1500)
    except TimeoutError:
        proc.kill()
        return 124, "timed out after 25 minutes"
    return proc.returncode or 0, out.decode(errors="replace")


async def _instagram_permalink(media_id: str) -> str | None:
    """The public link of an Instagram post (read-only Graph lookup, skill's own token)."""
    env_file = Path(settings.production_skills_dir) / publishing.SKILLS["instagram"] / ".env"
    token = None
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("META_PAGE_ACCESS_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"')
    if not token:
        return None
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"https://graph.facebook.com/v19.0/{media_id}",
                params={"fields": "permalink", "access_token": token},
            )
            return r.json().get("permalink")
    except Exception:  # noqa: BLE001 - a missing link is shown as "posted" without it
        return None


async def publish_video(
    upload_id: uuid.UUID, ws: uuid.UUID, platforms: list[str], at: datetime | None
) -> None:
    """Post (or schedule) the edited video on each chosen platform, one at a time."""
    async def mark(platform: str, **fields: Any) -> None:
        async with session_factory()() as s:
            pub = (await _publications(s, ws, upload_id))[platform]
            for k, v in fields.items():
                setattr(pub, k, v)
            await s.commit()

    try:
        for platform in platforms:
            await mark(platform, status="posting", detail="Making the upload copy of the video")
        social = await _social_copy(upload_id, ws)
    except Exception as exc:  # noqa: BLE001
        for platform in platforms:
            await mark(platform, status="failed", detail=str(exc)[:500])
        return
    media_url = (
        f"{settings.production_self_url}/api/v1/production/social-media/{upload_id}/"
        f"{_media_token(upload_id)}.mp4"
    )
    at_iso = at.replace(microsecond=0).isoformat() + "Z" if at else None
    for platform in platforms:
        async with session_factory()() as s:
            pub = (await _publications(s, ws, upload_id))[platform]
            copy, candidate_id = dict(pub.copy or {}), pub.candidate_id
        argv = publishing.command(platform, copy, media_path=str(social), media_url=media_url, at_iso=at_iso)
        await mark(platform, detail=f"{'Scheduling' if at else 'Posting'} on {publishing.LABELS[platform]} now")
        code, out = await run_platform(platform, argv)
        result = publishing.read_result(platform, out)
        if code == 0 and platform == "linkedin" and not at:
            await mark(platform, status="scheduled", scheduled_for=_utcnow(), external_id=result["row_id"],
                       detail="Queued on LinkedIn: kmboards posts it within about 5 minutes")
            continue
        if code != 0 or (not at and not result["post_id"] and platform != "linkedin"):
            tail = " ".join(out.strip().splitlines()[-3:])[-400:]
            await mark(platform, status="failed", detail=f"Did not go out: {tail}")
            continue
        if at:
            await mark(platform, status="scheduled", scheduled_for=at, external_id=result["row_id"],
                       detail=f"Scheduled for {at_iso}")
            continue
        url = result["url"]
        if platform == "instagram" and result["post_id"]:
            url = await _instagram_permalink(result["post_id"])
        await mark(platform, status="posted", external_id=result["post_id"] or result["row_id"],
                   url=url, posted_at=_utcnow(), detail=None)
        if candidate_id and result["post_id"]:
            async with session_factory()() as s:
                s.add(
                    PublicationReceipt(
                        workspace_id=ws, candidate_id=candidate_id, platform=platform,
                        external_post_id=str(result["post_id"])[:300], url=url,
                        published_at=_utcnow(),
                        final_text=copy.get("caption") or copy.get("message") or copy.get("description"),
                        recorded_by="tce-publish",
                    )
                )
                try:
                    await s.commit()
                except Exception:  # noqa: BLE001 - a duplicate receipt is not a failed post
                    await s.rollback()


class PublishBody(BaseModel):
    platforms: list[str] = Field(min_length=1)
    at: datetime | None = None


class CopyBody(BaseModel):
    fields: dict[str, Any]


class ReviseBody(BaseModel):
    request: str = Field(min_length=2, max_length=2000)


@router.get("/uploads/{upload_id}/publishing")
async def get_publishing(
    upload_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _upload(db, ws, upload_id)
    pubs = await _publications(db, ws, upload_id)
    return {
        "upload_id": str(upload_id),
        "platforms": [
            _publication_json(pubs[p]) if p in pubs
            else {"platform": p, "label": publishing.LABELS[p], "status": "none", "copy": {}}
            for p in publishing.PLATFORMS
        ],
    }


@router.post("/uploads/{upload_id}/publishing/draft", status_code=202)
async def write_posts(
    upload_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    row = await _upload(db, ws, upload_id)
    if not row.edited_path:
        raise HTTPException(status_code=409, detail="Edit the video first; the posts are written from the edit")
    start_draft_posts(upload_id, ws, rewrite=True)
    return {"status": "writing"}


@router.post("/uploads/{upload_id}/publishing/revise", status_code=202)
async def revise_posts_route(
    upload_id: uuid.UUID,
    body: ReviseBody,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    pubs = await _publications(db, ws, upload_id)
    open_ones = [pub for pub in pubs.values() if pub.status in ("draft", "failed")]
    if not open_ones:
        raise HTTPException(status_code=409, detail="There is no post left to change: they are all out")
    for pub in open_ones:
        pub.status, pub.detail = "revising", f"Changing: {body.request.strip()[:200]}"
    await db.commit()
    _spawn(revise_posts(upload_id, ws, body.request))
    return {"status": "revising"}


@router.put("/uploads/{upload_id}/publishing/{platform}")
async def save_post_copy(
    upload_id: uuid.UUID,
    platform: str,
    body: CopyBody,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    if platform not in publishing.PLATFORMS:
        raise HTTPException(status_code=404, detail="Unknown platform")
    pub = (await _publications(db, ws, upload_id)).get(platform)
    if pub is None:
        raise HTTPException(status_code=404, detail="No post written for this platform yet")
    if pub.status in ("posting", "posted", "scheduled", "revising"):
        raise HTTPException(status_code=409, detail="This post is already out or being changed; it cannot be edited now")
    pub.copy = publishing.clean_copy({platform: body.fields})[platform]
    await db.commit()
    return _publication_json(pub)


@router.post("/uploads/{upload_id}/publishing/publish", status_code=202)
async def publish_route(
    upload_id: uuid.UUID,
    body: PublishBody,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    row = await _upload(db, ws, upload_id)
    if not row.edited_path:
        raise HTTPException(status_code=409, detail="There is no edited video to post")
    # 28-Sep review: a post tapped while the video is being edited again would upload
    # the edit that is about to be replaced.
    if AUTO_MARK in (row.job_ids or []) or row.status in ("proofreading", "planned", "rendering"):
        raise HTTPException(
            status_code=409,
            detail="This video is being edited again. Post it when the new edit is ready.",
        )
    unknown = [p for p in body.platforms if p not in publishing.PLATFORMS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {', '.join(unknown)}")
    if body.at is not None:
        at = body.at.astimezone(UTC).replace(tzinfo=None) if body.at.tzinfo else body.at
        if at < _utcnow() + timedelta(minutes=15):
            raise HTTPException(status_code=400, detail="Schedule at least 15 minutes ahead")
    else:
        at = None
    pubs = await _publications(db, ws, upload_id)
    for platform in body.platforms:
        pub = pubs.get(platform)
        if pub is None:
            raise HTTPException(status_code=409, detail=f"No {publishing.LABELS[platform]} post written yet")
        if pub.status in ("posting", "posted", "scheduled", "revising"):
            raise HTTPException(status_code=409, detail=f"{publishing.LABELS[platform]} is {pub.status} right now")
        reason = publishing.missing(platform, pub.copy or {})
        if reason:
            raise HTTPException(status_code=409, detail=reason)
        pub.status, pub.detail = "posting", "Queued"
    await db.commit()
    _spawn(publish_video(upload_id, ws, list(body.platforms), at))
    return {"status": "posting", "platforms": body.platforms}


@router.get("/social-media/{upload_id}/{token}.mp4", include_in_schema=False)
async def social_media_file(upload_id: uuid.UUID, token: str):
    """The upload copy, for LinkedIn's fetcher on this box. No workspace key: the token
    is a secret derived from the private key, and the file is only what he chose to post."""
    if token != _media_token(upload_id):
        raise HTTPException(status_code=404, detail="Not found")
    async with session_factory()() as s:
        row = await s.get(RecordingUpload, upload_id)
        edited = Path(row.edited_path) if row and row.edited_path else None
    social = edited.with_name(f"{edited.stem}-social.mp4") if edited else None
    if social is None or not social.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(social, media_type="video/mp4")


# ---------------------------------------------------------------------------
# Activity

_RECEIPT_KEYS = (
    "auth_method",
    "api_provider",
    "api_key_source",
    "cli_version",
    "duration_ms",
    "worker_host",
)


def _receipt_summary(receipt: dict[str, Any] | None) -> dict[str, Any] | None:
    if not receipt:
        return None
    out = {
        k: receipt[k] for k in _RECEIPT_KEYS if k in receipt and not isinstance(receipt[k], dict)
    }
    models = receipt.get("models")
    if models is None and isinstance(receipt.get("modelUsage"), dict):
        models = sorted(receipt["modelUsage"].keys())
    if models is not None:
        out["models"] = models if isinstance(models, list) else [str(models)]
    return out


def job_activity(job: LLMJob, now: datetime) -> str:
    label = job.job_type.replace("_", " ")
    attempt = f"attempt {job.attempt_count} of {job.max_attempts}"
    if job.status == "waiting_capacity":
        when = f"retry at {job.retry_at:%H:%M} UTC" if job.retry_at else "retry time not set"
        return f"Waiting for subscription capacity: {label}, {when} ({attempt})"
    if job.status == "leased":
        owner = job.lease_owner or "a worker"
        return f"Running on {owner}: {label} ({attempt})"
    if job.status == "queued":
        return f"Queued for the subscription worker: {label}"
    if job.status == "failed":
        return f"Failed: {label} ({job.error_code or 'error'})"
    return f"{job.status.capitalize()}: {label}"


@router.get("/activity")
async def activity(
    limit: int = 20,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(limit, 100))
    await reconcile_interrupted_uploads(db, ws)
    now = _utcnow()
    jobs = (
        (
            await db.execute(
                select(LLMJob)
                .where(LLMJob.workspace_id == ws)
                .order_by(LLMJob.updated_at.desc(), LLMJob.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    runs = (
        (
            await db.execute(
                select(EvidenceCollectionRun)
                .where(EvidenceCollectionRun.workspace_id == ws)
                .order_by(EvidenceCollectionRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    uploads = (
        (
            await db.execute(
                select(RecordingUpload)
                .where(RecordingUpload.workspace_id == ws)
                .order_by(RecordingUpload.updated_at.desc(), RecordingUpload.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "now": now.isoformat() + "Z",
        "llm_jobs": [
            {
                "id": str(j.id),
                "status": j.status,
                "job_type": j.job_type,
                "agent_name": j.agent_name,
                "attempt": j.attempt_count,
                "max_attempts": j.max_attempts,
                "retry_at": _iso(j.retry_at),
                "leased_until": _iso(j.leased_until),
                "error_code": j.error_code,
                "receipt": _receipt_summary(j.receipt_json),
                "current_activity": job_activity(j, now),
                "updated_at": _iso(j.updated_at),
            }
            for j in jobs
        ],
        "collection_runs": [
            {
                "id": str(r.id),
                "source_kind": r.source_kind,
                "status": r.status,
                "counts": r.counts or {},
                "complete": r.complete,
                "current_activity": r.current_activity,
                "window_start": _iso(r.window_start),
                "window_end": _iso(r.window_end),
                "started_at": _iso(r.started_at),
                "finished_at": _iso(r.finished_at),
            }
            for r in runs
        ],
        "uploads": [
            {
                "id": str(u.id),
                "candidate_id": str(u.candidate_id),
                "original_filename": u.original_filename,
                "status": u.status,
                "status_detail": u.status_detail,
                "current_activity": u.status_detail,
                "updated_at": _iso(u.updated_at),
            }
            for u in uploads
        ],
    }
