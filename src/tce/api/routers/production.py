"""/production routes: recording docs, uploads, edit plans, render, publications, activity.

Every route depends on `require_private_workspace` and filters
`Model.workspace_id == ws` explicitly.

Nothing here publishes, posts or calls a metered API:
- export: Google Doc via the server's `gws` CLI when enabled, else a private .docx
- transcription: local faster-whisper worker, else `unavailable` with the reason
- render: local ffmpeg, else `unavailable`
- steps never auto-run after upload; the editor starts each one

Publication receipts dedupe on (workspace, platform, external_post_id): a repeat POST
returns HTTP 200 with `{"duplicate": true, "publication": <existing row>}`; a new
receipt returns 201 with `"duplicate": false`.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.api.private_access import require_private_workspace
from tce.db.session import get_db
from tce.models.editorial import (
    EvidenceCollectionRun,
    PublicationReceipt,
    RecordingPacket,
    RecordingUpload,
    TopicCandidate,
)
from tce.models.llm_job import LLMJob
from tce.production import media
from tce.production.export import GoogleDocsClient, GwsDocsClient, export_packet
from tce.production.retakes import build_cues, fmt_ts, plan_edit, to_srt, to_vtt
from tce.settings import settings

router = APIRouter(prefix="/production", tags=["production"])

PLATFORMS = ("facebook", "linkedin", "instagram", "youtube", "tiktok", "newsletter", "other")
_CHUNK = 1024 * 1024
_background: set[asyncio.Task] = set()


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
        result = await export_packet(
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
    return upload_json(await _upload(db, ws, upload_id))


# ---------------------------------------------------------------------------
# Transcribe, plan, render


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _set_status(upload_id: uuid.UUID, ws: uuid.UUID, status: str | None, detail: str) -> None:
    async with session_factory()() as s:
        row = (
            await s.execute(
                select(RecordingUpload).where(
                    RecordingUpload.id == upload_id, RecordingUpload.workspace_id == ws
                )
            )
        ).scalar_one()
        if status:
            row.status = status
        row.status_detail = detail[:500]
        await s.commit()


async def _run_transcription(upload_id: uuid.UUID, ws: uuid.UUID) -> None:
    async def report(text: str) -> None:
        await _set_status(upload_id, ws, "transcribing", text)

    try:
        async with session_factory()() as s:
            row = (
                await s.execute(
                    select(RecordingUpload).where(
                        RecordingUpload.id == upload_id, RecordingUpload.workspace_id == ws
                    )
                )
            ).scalar_one()
            path, duration = row.storage_path, row.duration_s
        timings = await media.transcribe_local(
            path,
            ws_url=settings.production_transcribe_ws_url,
            language=settings.production_transcribe_language or None,
            duration_s=duration,
            on_status=report,
        )
        async with session_factory()() as s:
            row = (
                await s.execute(
                    select(RecordingUpload).where(
                        RecordingUpload.id == upload_id, RecordingUpload.workspace_id == ws
                    )
                )
            ).scalar_one()
            row.transcript = timings
            row.status = "transcribed"
            row.status_detail = (
                f"Transcribed {len(timings)} segments locally. "
                "Click Plan edit to find retakes and pauses."
            )
            await s.commit()
    except media.StepUnavailableError as exc:
        await _set_status(upload_id, ws, "unavailable", str(exc))
    except Exception as exc:
        await _set_status(upload_id, ws, "failed", f"Transcription failed: {str(exc)[:400]}")


@router.post("/uploads/{upload_id}/transcribe", status_code=202)
async def transcribe_upload(
    upload_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    row = await _upload(db, ws, upload_id)
    if row.status in ("transcribing", "rendering"):
        return upload_json(row)
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
    row.status = "transcribing"
    row.status_detail = (
        f"Queued for local transcription ({media.fmt_duration(row.duration_s)} file)"
    )
    await db.commit()
    await db.refresh(row)
    _spawn(_run_transcription(row.id, ws))
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
            f"drop {len(drops)} retakes and {len(pauses)} pauses. Meaning check passed."
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


async def _run_render(upload_id: uuid.UUID, ws: uuid.UUID) -> None:
    async def report(text: str) -> None:
        await _set_status(upload_id, ws, "rendering", text)

    try:
        async with session_factory()() as s:
            row = (
                await s.execute(
                    select(RecordingUpload).where(
                        RecordingUpload.id == upload_id, RecordingUpload.workspace_id == ws
                    )
                )
            ).scalar_one()
            src, plan = Path(row.storage_path), dict(row.edit_plan or {})
        out = src.with_name(f"{src.stem}-edited{src.suffix}")
        await media.render_edit(src, plan.get("keep") or [], out, on_status=report)
        cues = build_cues(plan)
        srt = src.with_name(f"{src.stem}-edited.srt")
        srt.write_text(to_srt(cues), encoding="utf-8")
        src.with_name(f"{src.stem}-edited.vtt").write_text(to_vtt(cues), encoding="utf-8")
        async with session_factory()() as s:
            row = (
                await s.execute(
                    select(RecordingUpload).where(
                        RecordingUpload.id == upload_id, RecordingUpload.workspace_id == ws
                    )
                )
            ).scalar_one()
            row.edited_path = str(out)
            row.captions_path = str(srt)
            row.status = "edited"
            row.status_detail = (
                f"Edited file ready: {len(plan.get('keep') or [])} ranges, "
                f"{fmt_ts(plan.get('stats', {}).get('kept_seconds', 0))} long, "
                "captions as SRT and VTT sidecars"
            )
            await s.commit()
    except media.StepUnavailableError as exc:
        await _set_status(upload_id, ws, "unavailable", str(exc))
    except Exception as exc:
        await _set_status(upload_id, ws, "failed", f"Render failed: {str(exc)[:400]}")


class RenderRequest(BaseModel):
    # The editor must explicitly accept a plan the meaning check blocked
    override_meaning_check: bool = False


@router.post("/uploads/{upload_id}/render", status_code=202)
async def render_upload(
    upload_id: uuid.UUID,
    body: RenderRequest | None = None,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    row = await _upload(db, ws, upload_id)
    body = body or RenderRequest()
    if not row.edit_plan:
        raise HTTPException(status_code=409, detail="Plan the edit before rendering")
    if (
        row.edit_plan.get("meaning_check", {}).get("status") == "blocked"
        and not body.override_meaning_check
    ):
        raise HTTPException(
            status_code=409,
            detail="The meaning check blocked this plan. Review the issues before rendering.",
        )
    if row.status == "rendering":
        return upload_json(row)
    if not media.ffmpeg_path():
        row.status = "unavailable"
        row.status_detail = "Render unavailable: ffmpeg is not installed on this server"
        await db.commit()
        await db.refresh(row)
        return upload_json(row)
    row.status = "rendering"
    row.status_detail = f"Queued: cutting {len(row.edit_plan.get('keep') or [])} ranges with ffmpeg"
    await db.commit()
    await db.refresh(row)
    _spawn(_run_render(row.id, ws))
    return upload_json(row)


@router.get("/uploads/{upload_id}/edited")
async def edited_file(
    upload_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    row = await _upload(db, ws, upload_id)
    if not row.edited_path or not Path(row.edited_path).exists():
        raise HTTPException(status_code=404, detail="No edited file yet")
    return FileResponse(row.edited_path, filename=Path(row.edited_path).name)


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
