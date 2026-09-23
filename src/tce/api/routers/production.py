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
import os
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
from tce.editorial.common import ORIGIN_TECHNICAL_VALIDATION
from tce.models.editorial import (
    EvidenceCollectionRun,
    PublicationReceipt,
    RecordingPacket,
    RecordingUpload,
    TopicCandidate,
)
from tce.models.llm_job import LLMJob
from tce.models.recording_session import RecordingClip, RecordingSession
from tce.production import media
from tce.production import sessions as recording_sessions
from tce.production.export import GoogleDocsClient, GwsDocsClient, export_packet_durable
from tce.production.retakes import (
    build_cues,
    fmt_ts,
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
            row.transcript = timings
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
        row.transcript = body.transcript
    if not row.transcript:
        raise HTTPException(
            status_code=409, detail="No transcript yet. Transcribe the recording first."
        )
    phrases: list[str] = []
    packet = None
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
    plan = plan_edit(
        row.transcript,
        phrases,
        pause_threshold_s=body.pause_threshold_s or settings.production_pause_threshold_s,
        duration_s=row.duration_s,
    )
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
    await db.commit()
    await db.refresh(row)
    return upload_json(row)


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


async def _run_render(upload_id: uuid.UUID, ws: uuid.UUID, attempt: str, mode: str) -> None:
    async def report(text: str) -> None:
        await _set_status(upload_id, ws, "rendering", text, attempt)

    try:
        async with session_factory()() as s:
            row = await _load(s, upload_id, ws)
            src, plan, duration = Path(row.storage_path), dict(row.edit_plan or {}), row.duration_s
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
        await media.render_edit(
            src,
            keep,
            out,
            on_status=report,
            ass_text=to_ass(cues, *size),
            srt_text=srt_text,
        )
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
            kept_s = sum(e - b for b, e in keep)
            what = (
                "Uncut captioned MP4 ready (nothing removed)"
                if mode == "uncut"
                else f"Captioned MP4 ready: {len(keep)} ranges"
            )
            row.status_detail = (
                f"{what}, {fmt_ts(kept_s)} long, {len(cues)} captions burned in and "
                "as a subtitle track, plus SRT and VTT sidecars"
            )
            row.job_ids = _with_lease(row.job_ids, None)
            await s.commit()
    except media.StepUnavailableError as exc:
        await _set_status(upload_id, ws, "unavailable", str(exc), attempt)
    except Exception as exc:
        await _set_status(upload_id, ws, "failed", f"Render failed: {str(exc)[:400]}", attempt)


class RenderRequest(BaseModel):
    # The editor must explicitly accept a plan the meaning check blocked
    override_meaning_check: bool = False
    # "uncut" keeps the whole recording and only adds captions; it never needs an override
    mode: Literal["cut", "uncut"] = "cut"


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


def serve_video(
    request: Request, path: Path, media_type: str, filename: str, *, download: bool
) -> Response:
    """A video to PLAY by default, or to save with ?download=1.

    Every Watch button used to download the file, because FileResponse with a
    filename says "attachment" ("when I click watch it - it downloads the
    video", 23-Sep). And the server's Starlette (0.38) answers no Range
    requests, so an in-page player could not seek. This answers both: inline or
    attachment by choice, and byte ranges for scrubbing.
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
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    row = await _upload(db, ws, upload_id)
    if not row.edited_path or not Path(row.edited_path).exists():
        raise HTTPException(status_code=404, detail="No edited file yet")
    edited = Path(row.edited_path)
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
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The ideas Today counts as ready, and only those.

    This used to list every selected or recorded idea that ever got a script,
    from any week: Today said "1 script ready" and the studio showed 3 (an old
    week's idea, a technical test and one already recorded) while missing the
    one Today meant. One source now: this week's lineup, primary slots, in the
    lineup's order, script ready. The same rows `today.build` counts.
    """
    from tce.editorial import lineup as lineup_service

    lineup = await lineup_service.get_lineup(db, ws, lineup_service.week_start_for(None))
    week = await lineup_service.lineup_to_json(db, ws, lineup) if lineup is not None else {}
    wanted = [
        (uuid.UUID(r["candidate_id"]), uuid.UUID(r["packet_id"]))
        for r in week.get("primary") or []
        if r.get("script_state") == "ready" and r.get("packet_id")
    ]
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
    return {"session": await _recording_session_json(db, row), "upload": upload_json(upload)}


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
