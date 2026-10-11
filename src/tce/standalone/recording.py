"""Private phone recording, playback and reversible local edits."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.standalone.auth import Principal, current_principal, require_scope
from tce.standalone.brain import ask_brain
from tce.standalone.materials import storage_root
from tce.standalone.models import (
    StandaloneIdea,
    StandaloneRecording,
    StandaloneRender,
    StandaloneScriptVersion,
    StandaloneSecret,
    StandaloneSourceItem,
)
from tce.standalone.secrets import decrypt

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


def _sample_frame(path: Path, second: float) -> bytes:
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-ss", str(second),
                "-i", str(path), "-frames:v", "1", "-vf", "scale=640:-2",
                "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=503, detail="Could not inspect video frames") from exc
    if not 100 < len(result.stdout) <= 1_000_000:
        raise HTTPException(status_code=422, detail="Video frame is unavailable")
    return result.stdout


def _extract_audio(path: Path, target: Path) -> None:
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(path),
                "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(target),
            ],
            capture_output=True,
            timeout=180,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail="Could not prepare audio for captions") from exc
    if not target.is_file() or not 0 < target.stat().st_size <= 24 * 1024 * 1024:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Audio is missing or too long for captions")


def _srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    whole, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{whole:02},{millis:03}"


def _captions(segments: list[dict]) -> str:
    cues = []
    for segment in segments[:2000]:
        try:
            start, end = float(segment["start"]), float(segment["end"])
            words = str(segment["text"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if words and 0 <= start < end:
            cues.append(f"{len(cues) + 1}\n{_srt_time(start)} --> {_srt_time(end)}\n{words}")
    return "\n\n".join(cues) + ("\n" if cues else "")


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
    qc = dict(row.qc or {})
    export = qc.pop("export", None)
    if export:
        qc["export"] = {
            "prepared": True,
            "transcript_excerpt": (export.get("transcript") or "")[:350],
        }
    return {
        "id": str(row.id),
        "idea_id": str(row.idea_id),
        "script_version": row.script_version,
        "status": row.status,
        "qc": qc,
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
    prepared = (recording.qc or {}).get("export") or {}
    if prepared.get("video_sha256") != checksum:
        prepared = {}
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
        "captions": prepared.get("captions"),
        "transcript": prepared.get("transcript"),
        "suggested_post_copy": prepared.get("suggested_post_copy"),
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


@router.post("/recordings/{recording_id}/visual-review")
async def visual_review(
    recording_id: uuid.UUID,
    principal: Principal = Depends(require_scope("record")),
    db: AsyncSession = Depends(get_db),
):
    """Review a bounded set of still frames using this client's own brain."""
    row = await _recording(db, principal.workspace_id, recording_id)
    path = _safe_path(row.edited_key or row.original_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Selected video is missing")
    idea = (
        await db.execute(
            select(StandaloneIdea).where(
                StandaloneIdea.id == row.idea_id,
                StandaloneIdea.workspace_id == principal.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if idea is None:
        raise HTTPException(status_code=409, detail="Recording idea is missing")
    qc = await asyncio.to_thread(_probe, path)
    duration = qc["duration_s"]
    seconds = [round(min(duration - 0.1, duration * fraction), 2) for fraction in (0.1, 0.45, 0.8)]
    frames = [await asyncio.to_thread(_sample_frame, path, second) for second in seconds]
    summary = await ask_brain(
        db,
        principal.workspace_id,
        "You are Jennifer, a video editor. Inspect only the supplied still frames. "
        "Comment on composition, framing, lighting and visible continuity. "
        "Do not infer speech, audio quality, exact timing or unseen parts of the video. "
        "Be specific, kind and concise.",
        f"Idea: {idea.title}\nAngle: {idea.angle}\n"
        f"Three still frames were sampled at {seconds} seconds in order. "
        f"Technical checks: {qc}. Editor notes: {row.notes}.",
        images=frames,
        max_tokens=850,
    )
    review = {"summary": summary[:5000], "sampled_seconds": seconds, "audio_reviewed": False}
    row.qc = {**(row.qc or {}), "visual_review": review}
    return review


@router.post("/recordings/{recording_id}/prepare-export")
async def prepare_export(
    recording_id: uuid.UUID,
    principal: Principal = Depends(require_scope("export")),
    db: AsyncSession = Depends(get_db),
):
    """Create timed captions from the selected render with the client's OpenAI key."""
    row = await _recording(db, principal.workspace_id, recording_id)
    path = _safe_path(row.edited_key or row.original_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Selected video is missing")
    checksum = await asyncio.to_thread(_file_sha256, path)
    existing = (row.qc or {}).get("export") or {}
    if existing.get("video_sha256") == checksum:
        return {key: existing.get(key) for key in ("transcript", "captions", "suggested_post_copy")}
    if not (row.qc or {}).get("has_audio"):
        raise HTTPException(status_code=409, detail="This video has no audio track")
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
    audio_path = path.parent / f"{uuid.uuid4().hex}.mp3"
    try:
        await asyncio.to_thread(_extract_audio, path, audio_path)
        key = decrypt(secret.encrypted_value, principal.workspace_id, "openai_live")
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    data={
                        "model": "whisper-1",
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "segment",
                    },
                    files={"file": ("selected-audio.mp3", audio_path.read_bytes(), "audio/mpeg")},
                )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=503, detail="Caption transcription is unavailable"
            ) from exc
    finally:
        audio_path.unlink(missing_ok=True)
    if response.status_code != 200:
        raise HTTPException(
            status_code=503, detail=f"Caption transcription returned HTTP {response.status_code}"
        )
    data = response.json()
    transcript = str(data.get("text") or "").strip()[:30000]
    captions = _captions(data.get("segments") or [])[:120000]
    if not transcript or not captions:
        raise HTTPException(status_code=502, detail="Transcription returned no timed captions")
    idea = (
        await db.execute(
            select(StandaloneIdea).where(
                StandaloneIdea.id == row.idea_id,
                StandaloneIdea.workspace_id == principal.workspace_id,
            )
        )
    ).scalar_one_or_none()
    post_copy = None
    if idea is not None:
        try:
            post_copy = await ask_brain(
                db,
                principal.workspace_id,
                "Draft a short optional social post in this client's voice. Use only the provided "
                "transcript and verified idea evidence. Do not claim to publish or add "
                "invented facts.",
                f"Idea: {idea.title}\nEvidence: {idea.evidence}\nTranscript: {transcript[:12000]}",
                max_tokens=500,
            )
        except HTTPException:
            pass
    prepared = {
        "video_sha256": checksum,
        "transcript": transcript,
        "captions": captions,
        "suggested_post_copy": post_copy[:4000] if post_copy else None,
    }
    row.qc = {**(row.qc or {}), "export": prepared}
    return {key: prepared.get(key) for key in ("transcript", "captions", "suggested_post_copy")}


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
