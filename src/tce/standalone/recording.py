"""Private phone recording, playback and reversible local edits."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.standalone.auth import Principal, current_principal, require_scope
from tce.standalone.materials import storage_root
from tce.standalone.models import (
    StandaloneIdea,
    StandaloneRecording,
    StandaloneRender,
    StandaloneScriptVersion,
    StandaloneSourceItem,
)

router = APIRouter(prefix="/api", dependencies=[Depends(current_principal)])
MAX_VIDEO_BYTES = 500 * 1024 * 1024
MIME_EXTENSION = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}


class TrimBody(BaseModel):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    note: str = Field(default="", max_length=4000)


class NotesBody(BaseModel):
    notes: str = Field(max_length=4000)


def _safe_path(storage_key: str) -> Path:
    root = storage_root()
    path = (root / storage_key).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=404, detail="Video not found")
    return path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _probe(path: Path) -> dict:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Video could not be read") from exc
    video = next(
        (stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None
    )
    if video is None:
        raise HTTPException(status_code=422, detail="File has no video track")
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if not 0 < duration <= 3600:
        raise HTTPException(status_code=422, detail="Video must be between 1 second and 1 hour")
    return {
        "duration_s": round(duration, 2),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
    }


async def _recording(db: AsyncSession, ws: uuid.UUID, recording_id: uuid.UUID):
    row = (
        await db.execute(
            select(StandaloneRecording).where(
                StandaloneRecording.id == recording_id,
                StandaloneRecording.workspace_id == ws,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    return row


def _json(row: StandaloneRecording) -> dict:
    return {
        "id": str(row.id),
        "idea_id": str(row.idea_id),
        "script_version": row.script_version,
        "status": row.status,
        "qc": row.qc,
        "notes": row.notes,
        "size_bytes": row.size_bytes,
        "original_url": f"/api/recordings/{row.id}/video?version=original",
        "selected_url": f"/api/recordings/{row.id}/video?version=selected",
    }


@router.post("/ideas/{idea_id}/recordings", status_code=201)
async def upload_recording(
    idea_id: uuid.UUID,
    file: UploadFile = File(),
    script_version: int | None = Form(default=None),
    principal: Principal = Depends(require_scope("record")),
    db: AsyncSession = Depends(get_db),
):
    idea = (
        await db.execute(
            select(StandaloneIdea).where(
                StandaloneIdea.id == idea_id,
                StandaloneIdea.workspace_id == principal.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    if script_version is not None:
        script = (
            await db.execute(
                select(StandaloneScriptVersion).where(
                    StandaloneScriptVersion.workspace_id == principal.workspace_id,
                    StandaloneScriptVersion.idea_id == idea_id,
                    StandaloneScriptVersion.version == script_version,
                )
            )
        ).scalar_one_or_none()
        if script is None:
            raise HTTPException(status_code=404, detail="Script version not found")
    mime = (file.content_type or "").lower()
    if mime not in MIME_EXTENSION:
        raise HTTPException(status_code=415, detail="Record MP4, WebM or MOV video")
    root = storage_root()
    folder = root / str(principal.workspace_id) / "recordings"
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{uuid.uuid4().hex}.part"
    size = 0
    final: Path | None = None
    try:
        with tmp.open("xb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise HTTPException(status_code=413, detail="Video exceeds 500 MB")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="Video is empty")
        qc = await asyncio.to_thread(_probe, tmp)
        final = folder / f"{uuid.uuid4().hex}{MIME_EXTENSION[mime]}"
        tmp.replace(final)
        row = StandaloneRecording(
            workspace_id=principal.workspace_id,
            idea_id=idea_id,
            script_version=script_version,
            original_key=str(final.relative_to(root)),
            mime_type=mime,
            size_bytes=size,
            qc=qc,
        )
        db.add(row)
        idea.status = "recorded"
        await db.flush()
        return _json(row)
    except Exception:
        if final is not None:
            final.unlink(missing_ok=True)
        raise
    finally:
        tmp.unlink(missing_ok=True)
        await file.close()


@router.get("/recordings")
async def list_recordings(
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(StandaloneRecording)
            .where(StandaloneRecording.workspace_id == principal.workspace_id)
            .order_by(StandaloneRecording.created_at.desc())
        )
    ).scalars()
    return [_json(row) for row in rows]


@router.get("/recordings/{recording_id}")
async def get_recording(
    recording_id: uuid.UUID,
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    return _json(await _recording(db, principal.workspace_id, recording_id))


@router.get("/recordings/{recording_id}/export-manifest")
async def export_manifest(
    recording_id: uuid.UUID,
    principal: Principal = Depends(require_scope("export")),
    db: AsyncSession = Depends(get_db),
):
    recording = await _recording(db, principal.workspace_id, recording_id)
    key = recording.edited_key or recording.original_key
    path = _safe_path(key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Selected video is missing")
    idea = (
        await db.execute(
            select(StandaloneIdea).where(
                StandaloneIdea.id == recording.idea_id,
                StandaloneIdea.workspace_id == principal.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if idea is None:
        raise HTTPException(status_code=409, detail="The recording's idea is missing")
    source = None
    if idea.source_item_id:
        source = (
            await db.execute(
                select(StandaloneSourceItem).where(
                    StandaloneSourceItem.id == idea.source_item_id,
                    StandaloneSourceItem.workspace_id == principal.workspace_id,
                )
            )
        ).scalar_one_or_none()
    script = None
    if recording.script_version is not None:
        script = (
            await db.execute(
                select(StandaloneScriptVersion).where(
                    StandaloneScriptVersion.idea_id == idea.id,
                    StandaloneScriptVersion.workspace_id == principal.workspace_id,
                    StandaloneScriptVersion.version == recording.script_version,
                )
            )
        ).scalar_one_or_none()
    render = None
    if recording.edited_key:
        render = (
            await db.execute(
                select(StandaloneRender).where(
                    StandaloneRender.recording_id == recording_id,
                    StandaloneRender.workspace_id == principal.workspace_id,
                    StandaloneRender.storage_key == recording.edited_key,
                )
            )
        ).scalar_one_or_none()
    checksum = await asyncio.to_thread(_file_sha256, path)
    return {
        "manifest_version": 1,
        "workspace_id": str(principal.workspace_id),
        "recording_id": str(recording_id),
        "render_version": render.version if render else 0,
        "video": {
            "url": f"/api/recordings/{recording_id}/video?version=selected",
            "filename": path.name,
            "mime_type": "video/mp4" if path.suffix == ".mp4" else recording.mime_type,
            "size_bytes": path.stat().st_size,
            "sha256": checksum,
        },
        "idea": {"id": str(idea.id), "title": idea.title, "evidence": idea.evidence},
        "source": (
            {"id": str(source.id), "title": source.title, "url": source.url} if source else None
        ),
        "script": {"version": script.version, "text": script.script} if script else None,
        "captions": None,
        "transcript": None,
        "suggested_post_copy": None,
        "recording_notes": recording.notes,
    }


@router.get("/recordings/{recording_id}/video")
async def video(
    recording_id: uuid.UUID,
    version: str = "selected",
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    row = await _recording(db, principal.workspace_id, recording_id)
    if version not in {"selected", "original"}:
        raise HTTPException(status_code=422, detail="Choose original or selected")
    key = row.original_key if version == "original" else row.edited_key or row.original_key
    path = _safe_path(key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")
    mime = "video/mp4" if path.suffix == ".mp4" else row.mime_type
    return FileResponse(
        path, media_type=mime, filename=path.name, content_disposition_type="inline"
    )


@router.put("/recordings/{recording_id}/notes")
async def notes(
    recording_id: uuid.UUID,
    body: NotesBody,
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    row = await _recording(db, principal.workspace_id, recording_id)
    row.notes = body.notes
    return _json(row)


def _trim(original: Path, target: Path, start: float, end: float) -> None:
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-v",
                "error",
                "-ss",
                str(start),
                "-i",
                str(original),
                "-t",
                str(end - start),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(target),
            ],
            capture_output=True,
            timeout=180,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail="Video edit failed. Original is safe.") from exc


@router.post("/recordings/{recording_id}/trim")
async def trim(
    recording_id: uuid.UUID,
    body: TrimBody,
    principal: Principal = Depends(require_scope("record")),
    db: AsyncSession = Depends(get_db),
):
    row = await _recording(db, principal.workspace_id, recording_id)
    duration = float((row.qc or {}).get("duration_s") or 0)
    if body.end_s <= body.start_s or body.end_s > duration + 0.1:
        raise HTTPException(status_code=422, detail="Trim range is outside this video")
    original = _safe_path(row.original_key)
    if not original.is_file():
        raise HTTPException(status_code=404, detail="Original video is missing")
    root = storage_root()
    target = original.parent / f"{uuid.uuid4().hex}.mp4"
    await asyncio.to_thread(_trim, original, target, body.start_s, body.end_s)
    latest = (
        await db.execute(
            select(StandaloneRender)
            .where(
                StandaloneRender.workspace_id == principal.workspace_id,
                StandaloneRender.recording_id == recording_id,
            )
            .order_by(StandaloneRender.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    render = StandaloneRender(
        workspace_id=principal.workspace_id,
        recording_id=recording_id,
        version=(latest.version if latest else 0) + 1,
        storage_key=str(target.relative_to(root)),
        duration_s=round(body.end_s - body.start_s),
        start_s=round(body.start_s),
        end_s=round(body.end_s),
        note=body.note,
    )
    db.add(render)
    row.edited_key = render.storage_key
    row.status = "edited"
    await db.flush()
    return {"recording": _json(row), "render_id": str(render.id), "version": render.version}


@router.get("/recordings/{recording_id}/renders")
async def renders(
    recording_id: uuid.UUID,
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    await _recording(db, principal.workspace_id, recording_id)
    rows = (
        await db.execute(
            select(StandaloneRender)
            .where(
                StandaloneRender.workspace_id == principal.workspace_id,
                StandaloneRender.recording_id == recording_id,
            )
            .order_by(StandaloneRender.version.desc())
        )
    ).scalars()
    return [
        {
            "id": str(r.id),
            "version": r.version,
            "start_s": r.start_s,
            "end_s": r.end_s,
            "note": r.note,
        }
        for r in rows
    ]


@router.post("/recordings/{recording_id}/renders/{render_id}/select")
async def select_render(
    recording_id: uuid.UUID,
    render_id: uuid.UUID,
    principal: Principal = Depends(require_scope("record")),
    db: AsyncSession = Depends(get_db),
):
    row = await _recording(db, principal.workspace_id, recording_id)
    render = (
        await db.execute(
            select(StandaloneRender).where(
                StandaloneRender.id == render_id,
                StandaloneRender.recording_id == recording_id,
                StandaloneRender.workspace_id == principal.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if render is None:
        raise HTTPException(status_code=404, detail="Edit version not found")
    row.edited_key = render.storage_key
    row.status = "edited"
    return _json(row)


@router.post("/recordings/{recording_id}/original/select")
async def select_original(
    recording_id: uuid.UUID,
    principal: Principal = Depends(require_scope("record")),
    db: AsyncSession = Depends(get_db),
):
    row = await _recording(db, principal.workspace_id, recording_id)
    row.edited_key = None
    row.status = "uploaded"
    return _json(row)
