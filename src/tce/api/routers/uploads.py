"""Resumable chunked uploads (tus-style protocol).

Solves two problems with the legacy single-shot endpoints:

1. **1 GB cap blocked walking videos > 1 GB.** A 13-minute 4K phone walk is
   commonly 1.2-1.5 GB. The single-shot endpoint had to reject these.
2. **No upload progress feedback.** A bare browser fetch() upload reports
   no bytes-sent events; users saw a seconds counter and assumed broken.

Flow:
    POST /uploads/init        -> session_id + chunk_size
    PATCH /uploads/{id}       -> append a chunk, returns next_offset
    HEAD /uploads/{id}        -> resume probe (returns Upload-Offset)
    POST /uploads/{id}/finalize -> moves the assembled file into the real
                                    target slot (walking_raw, walking_edited,
                                    walking_weekly) + DB row update
    DELETE /uploads/{id}      -> cancel + cleanup

Each session writes data to {video_output_dir}/uploads/tmp/{id}.bin and
metadata to {id}.json. Cleanup happens on finalize/cancel/error.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.walking_video_script import WalkingVideoScript
from tce.settings import settings

router = APIRouter(prefix="/uploads", tags=["uploads"])

_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
_MAX_TOTAL_BYTES = 5_000_000_000  # 5 GB hard cap per resumable upload
_DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB; matches typical wifi RTT well

_VALID_INTENTS = {"walking_raw", "walking_edited", "walking_weekly"}


def _tmp_dir() -> Path:
    p = Path(settings.video_output_dir) / "uploads" / "tmp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _meta_path(upload_id: str) -> Path:
    return _tmp_dir() / f"{upload_id}.json"


def _data_path(upload_id: str) -> Path:
    return _tmp_dir() / f"{upload_id}.bin"


def _read_meta(upload_id: str) -> dict[str, Any]:
    mp = _meta_path(upload_id)
    if not mp.exists():
        raise HTTPException(status_code=404, detail="Upload session not found")
    return json.loads(mp.read_text())


def _write_meta(upload_id: str, meta: dict[str, Any]) -> None:
    _meta_path(upload_id).write_text(json.dumps(meta))


def _cleanup(upload_id: str) -> None:
    _meta_path(upload_id).unlink(missing_ok=True)
    _data_path(upload_id).unlink(missing_ok=True)


class InitRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    total_size: int = Field(..., gt=0)
    intent: str


class InitResponse(BaseModel):
    upload_id: str
    chunk_size: int
    next_offset: int


class FinalizeRequest(BaseModel):
    target_id: str  # script_id or weekly_plan_id (UUID string)


@router.post("/init", response_model=InitResponse)
async def init_upload(req: InitRequest) -> InitResponse:
    if req.intent not in _VALID_INTENTS:
        raise HTTPException(
            status_code=400,
            detail=f"intent must be one of {sorted(_VALID_INTENTS)}",
        )
    if req.total_size > _MAX_TOTAL_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"total_size {req.total_size} exceeds {_MAX_TOTAL_BYTES} byte cap",
        )
    ext = Path(req.filename).suffix.lower()
    if ext not in _VIDEO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported extension {ext!r}; expected {sorted(_VIDEO_EXTS)}",
        )

    upload_id = uuid.uuid4().hex
    _data_path(upload_id).write_bytes(b"")  # touch
    meta = {
        "upload_id": upload_id,
        "filename": req.filename,
        "ext": ext,
        "total_size": req.total_size,
        "intent": req.intent,
        "offset": 0,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    _write_meta(upload_id, meta)
    return InitResponse(
        upload_id=upload_id,
        chunk_size=_DEFAULT_CHUNK_SIZE,
        next_offset=0,
    )


@router.head("/{upload_id}")
async def head_upload(upload_id: str) -> Response:
    meta = _read_meta(upload_id)
    return Response(
        status_code=200,
        headers={
            "Upload-Offset": str(meta["offset"]),
            "Upload-Length": str(meta["total_size"]),
            "Cache-Control": "no-store",
        },
    )


@router.patch("/{upload_id}")
async def patch_chunk(
    upload_id: str,
    request: Request,
    upload_offset: int = Header(..., alias="Upload-Offset"),
) -> dict[str, Any]:
    meta = _read_meta(upload_id)
    if upload_offset != meta["offset"]:
        raise HTTPException(
            status_code=409,
            detail=f"offset mismatch: server={meta['offset']}, client={upload_offset}",
        )

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty chunk body")

    new_offset = meta["offset"] + len(body)
    if new_offset > meta["total_size"]:
        raise HTTPException(
            status_code=413,
            detail=f"chunk would exceed total_size {meta['total_size']}",
        )

    with _data_path(upload_id).open("ab") as f:
        f.write(body)

    meta["offset"] = new_offset
    _write_meta(upload_id, meta)
    return {
        "bytes_written": len(body),
        "next_offset": new_offset,
        "complete": new_offset == meta["total_size"],
    }


@router.post("/{upload_id}/finalize")
async def finalize_upload(
    upload_id: str,
    req: FinalizeRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    meta = _read_meta(upload_id)
    if meta["offset"] != meta["total_size"]:
        raise HTTPException(
            status_code=400,
            detail=f"upload incomplete: {meta['offset']}/{meta['total_size']} bytes received",
        )

    intent = meta["intent"]
    ext = meta["ext"]
    src_path = _data_path(upload_id)
    if not src_path.exists():
        raise HTTPException(status_code=500, detail="data file missing on disk")

    try:
        target_uuid = uuid.UUID(req.target_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid target_id (must be UUID): {req.target_id}")

    if intent in ("walking_raw", "walking_edited"):
        row = await db.get(WalkingVideoScript, target_uuid)
        if not row:
            raise HTTPException(status_code=404, detail="Walking-video script not found")
        kind = "raw" if intent == "walking_raw" else "edited"
        out_path = (
            Path(settings.video_output_dir)
            / "walking_scripts"
            / str(target_uuid)
            / f"{kind}{ext}"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            out_path.unlink()
        src_path.rename(out_path)
        if intent == "walking_raw":
            row.video_file_path = f"/media/walking_scripts/{target_uuid}/raw{ext}"
            row.status = "recorded"
            row.recorded_at = datetime.utcnow()
        else:
            row.edited_video_file_path = f"/media/walking_scripts/{target_uuid}/edited{ext}"
            row.status = "edited"
        await db.commit()
        await db.refresh(row)
        _meta_path(upload_id).unlink(missing_ok=True)
        return {
            "ok": True,
            "intent": intent,
            "target_id": str(target_uuid),
            "video_file_path": row.video_file_path,
            "edited_video_file_path": row.edited_video_file_path,
            "bytes_written": meta["total_size"],
        }

    if intent == "walking_weekly":
        from tce.models.weekly_walking_recording import WeeklyWalkingRecording

        out_path = (
            Path(settings.video_output_dir)
            / "weekly_recordings"
            / str(target_uuid)
            / f"raw{ext}"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            out_path.unlink()
        src_path.rename(out_path)

        existing_result = await db.execute(
            select(WeeklyWalkingRecording).where(
                WeeklyWalkingRecording.weekly_plan_id == target_uuid
            )
        )
        recording = existing_result.scalar_one_or_none()
        if recording:
            recording.long_video_path = str(out_path)
            recording.status = "uploaded"
            recording.transcript_json = None
            recording.alignment_json = None
            recording.cutsense_jobs = None
            recording.error_message = None
            recording.updated_at = datetime.now(tz=timezone.utc)
        else:
            recording = WeeklyWalkingRecording(
                weekly_plan_id=target_uuid,
                long_video_path=str(out_path),
                status="uploaded",
            )
            db.add(recording)
        await db.commit()
        await db.refresh(recording)
        _meta_path(upload_id).unlink(missing_ok=True)
        return {
            "ok": True,
            "intent": intent,
            "recording_id": str(recording.id),
            "weekly_plan_id": str(target_uuid),
            "status": recording.status,
            "long_video_path": recording.long_video_path,
            "bytes_written": meta["total_size"],
        }

    raise HTTPException(status_code=501, detail=f"intent {intent!r} finalize not implemented")


@router.delete("/{upload_id}")
async def cancel_upload(upload_id: str) -> dict[str, Any]:
    if not _meta_path(upload_id).exists():
        raise HTTPException(status_code=404, detail="Upload session not found")
    _cleanup(upload_id)
    return {"ok": True, "cancelled": upload_id}
