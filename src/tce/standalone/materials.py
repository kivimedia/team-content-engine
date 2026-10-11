"""Private source and voice material, versioned by content hash."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.standalone.auth import Principal, current_principal, require_scope
from tce.standalone.models import StandaloneMaterial, StandaloneSecret
from tce.standalone.secrets import decrypt

router = APIRouter(prefix="/api/materials", dependencies=[Depends(current_principal)])
ALLOWED = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}
MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_VOICE_BYTES = 20 * 1024 * 1024


def storage_root() -> Path:
    value = os.environ.get("TCE_STANDALONE_STORAGE_DIR", "")
    if not value:
        raise HTTPException(status_code=503, detail="Private storage is not configured")
    root = Path(value).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _public(row: StandaloneMaterial) -> dict:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "lane_index": row.lane_index,
        "name": row.name,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "active": row.active,
        "notes": row.notes,
        "transcribed": bool(row.transcript_text),
        "transcript_excerpt": (row.transcript_text or "")[:600],
        "created_at": row.created_at,
    }


@router.post("", status_code=201)
async def upload_material(
    file: UploadFile = File(),
    kind: str = Form(),
    lane_index: int | None = Form(default=None),
    notes: str = Form(default=""),
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    if kind not in {"source", "voice"}:
        raise HTTPException(status_code=422, detail="Choose source or voice")
    if kind == "source" and lane_index not in {0, 1, 2}:
        raise HTTPException(status_code=422, detail="Choose one of the three idea sources")
    if kind == "voice" and lane_index is not None:
        raise HTTPException(status_code=422, detail="Voice material has no idea source")
    if len(notes) > 4000:
        raise HTTPException(status_code=422, detail="Notes are too long")
    name = Path(file.filename or "material").name[:250]
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED or (
        kind == "voice" and ext not in {".txt", ".md", ".m4a", ".mp3", ".wav"}
    ):
        raise HTTPException(status_code=415, detail="This file type is not supported")
    root = storage_root()
    folder = root / str(principal.workspace_id) / "materials"
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    limit = MAX_SOURCE_BYTES if kind == "source" else MAX_VOICE_BYTES
    size = 0
    try:
        with tmp.open("xb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail="Material exceeds the size limit")
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="File is empty")
        with tmp.open("rb") as check:
            head = check.read(8)
        if ext == ".pdf" and not head.startswith(b"%PDF-"):
            raise HTTPException(status_code=415, detail="Invalid PDF file")
        if ext == ".docx" and not head.startswith(b"PK"):
            raise HTTPException(status_code=415, detail="Invalid Word file")
        if ext in {".txt", ".md"}:
            try:
                tmp.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(status_code=415, detail="Text must be UTF-8") from exc
        existing = (
            await db.execute(
                select(StandaloneMaterial).where(
                    StandaloneMaterial.workspace_id == principal.workspace_id,
                    StandaloneMaterial.kind == kind,
                    StandaloneMaterial.sha256 == digest.hexdigest(),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.active = True
            existing.lane_index = lane_index
            existing.notes = notes
            return _public(existing)
        final = folder / f"{uuid.uuid4().hex}{ext}"
        tmp.replace(final)
        row = StandaloneMaterial(
            workspace_id=principal.workspace_id,
            kind=kind,
            lane_index=lane_index,
            name=name,
            mime_type=ALLOWED[ext],
            sha256=digest.hexdigest(),
            storage_key=str(final.relative_to(root)),
            size_bytes=size,
            notes=notes,
            active=True,
        )
        db.add(row)
        await db.flush()
        return _public(row)
    finally:
        tmp.unlink(missing_ok=True)
        await file.close()


@router.get("")
async def list_materials(
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(StandaloneMaterial)
            .where(StandaloneMaterial.workspace_id == principal.workspace_id)
            .order_by(StandaloneMaterial.created_at.desc())
        )
    ).scalars()
    return [_public(row) for row in rows]


@router.post("/{material_id}/transcribe")
async def transcribe_voice_material(
    material_id: uuid.UUID,
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(StandaloneMaterial).where(
                StandaloneMaterial.id == material_id,
                StandaloneMaterial.workspace_id == principal.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Voice sample not found")
    if row.kind != "voice" or Path(row.name).suffix.lower() not in {".m4a", ".mp3", ".wav"}:
        raise HTTPException(status_code=422, detail="Choose an audio voice sample")
    if not row.active:
        raise HTTPException(
            status_code=409, detail="Use this voice sample again before transcribing"
        )
    secret = (
        await db.execute(
            select(StandaloneSecret).where(
                StandaloneSecret.workspace_id == principal.workspace_id,
                StandaloneSecret.kind == "openai_live",
            )
        )
    ).scalar_one_or_none()
    if secret is None or secret.verified_at is None:
        raise HTTPException(status_code=409, detail="Verify your OpenAI key in Settings first")
    path = (storage_root() / row.storage_key).resolve()
    if not path.is_relative_to(storage_root()) or not path.is_file():
        raise HTTPException(status_code=404, detail="Voice sample file is missing")
    key = decrypt(secret.encrypted_value, principal.workspace_id, "openai_live")
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                data={"model": "gpt-4o-mini-transcribe"},
                files={"file": (row.name, path.read_bytes(), row.mime_type)},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Voice transcription is unavailable") from exc
    if response.status_code != 200:
        raise HTTPException(
            status_code=503, detail=f"Voice transcription returned HTTP {response.status_code}"
        )
    transcript = response.json().get("text", "").strip()
    if not transcript:
        raise HTTPException(status_code=502, detail="Voice transcription returned no text")
    row.transcript_text = transcript[:30000]
    return _public(row)


@router.get("/{material_id}/download")
async def download_material(
    material_id: uuid.UUID,
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(StandaloneMaterial).where(
                StandaloneMaterial.id == material_id,
                StandaloneMaterial.workspace_id == principal.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Material not found")
    root = storage_root()
    path = (root / row.storage_key).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Material file not found")
    return FileResponse(path, media_type=row.mime_type, filename=row.name)


@router.post("/{material_id}/active")
async def set_active(
    material_id: uuid.UUID,
    active: bool,
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(StandaloneMaterial).where(
                StandaloneMaterial.id == material_id,
                StandaloneMaterial.workspace_id == principal.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Material not found")
    row.active = active
    return _public(row)
