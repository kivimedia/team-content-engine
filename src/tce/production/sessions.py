"""Append-only mobile recording sessions and recoverable chunk assembly."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate
from tce.models.recording_session import RecordingChunk, RecordingClip, RecordingSession
from tce.production.media import ffmpeg_path, probe_media

MAX_CHUNK_BYTES = 32 * 1024 * 1024
ALLOWED_EXTENSIONS = {"webm", "mp4", "mov", "m4a"}


class RecordingSessionError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def create_session(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    candidate_id: uuid.UUID,
    packet_id: uuid.UUID,
    *,
    device_meta: dict[str, Any] | None = None,
) -> RecordingSession:
    packet = (
        await db.execute(
            select(RecordingPacket).where(
                RecordingPacket.id == packet_id,
                RecordingPacket.workspace_id == workspace_id,
                RecordingPacket.candidate_id == candidate_id,
            )
        )
    ).scalar_one_or_none()
    candidate = (
        await db.execute(
            select(TopicCandidate).where(
                TopicCandidate.id == candidate_id,
                TopicCandidate.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if packet is None or candidate is None:
        raise RecordingSessionError("packet and candidate must belong to this workspace")
    # An empty draft for this exact packet IS this take set. Opening the studio
    # twice (a second tap, a reload, the hook step handing over to the script) used
    # to read the same max retake index twice and collide on the unique key, which
    # reached him as a failure to start recording.
    empty_draft = (
        await db.execute(
            select(RecordingSession)
            .outerjoin(RecordingClip, RecordingClip.session_id == RecordingSession.id)
            .where(
                RecordingSession.workspace_id == workspace_id,
                RecordingSession.candidate_id == candidate_id,
                RecordingSession.packet_id == packet_id,
                RecordingSession.status == "draft",
                RecordingClip.id.is_(None),
            )
            .order_by(RecordingSession.retake_index.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if empty_draft is not None:
        return empty_draft
    current = (
        await db.execute(
            select(func.max(RecordingSession.retake_index)).where(
                RecordingSession.workspace_id == workspace_id,
                RecordingSession.candidate_id == candidate_id,
                RecordingSession.packet_id == packet_id,
            )
        )
    ).scalar_one_or_none() or 0
    row = RecordingSession(
        workspace_id=workspace_id,
        candidate_id=candidate_id,
        packet_id=packet_id,
        packet_version=packet.version,
        retake_index=int(current) + 1,
        status="draft",
        device_meta=device_meta or {},
    )
    db.add(row)
    await db.flush()
    return row


async def create_clip(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    session_id: uuid.UUID,
    local_clip_id: str,
    mime_type: str,
    extension: str,
) -> RecordingClip:
    recording = (
        await db.execute(
            select(RecordingSession).where(
                RecordingSession.id == session_id,
                RecordingSession.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if recording is None:
        raise RecordingSessionError("recording session not found")
    if recording.status in {"finalizing", "uploaded", "failed"}:
        raise RecordingSessionError(f"session is {recording.status}")
    existing = (
        await db.execute(
            select(RecordingClip).where(
                RecordingClip.session_id == session_id,
                RecordingClip.local_clip_id == local_clip_id[:120],
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    ext = extension.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise RecordingSessionError("unsupported recording container")
    position = (
        await db.execute(
            select(func.max(RecordingClip.position)).where(RecordingClip.session_id == session_id)
        )
    ).scalar_one_or_none()
    clip = RecordingClip(
        workspace_id=workspace_id,
        session_id=session_id,
        local_clip_id=local_clip_id[:120],
        position=int(position if position is not None else -1) + 1,
        status="recording",
        mime_type=mime_type[:120],
        file_extension=ext,
        started_at=utcnow(),
    )
    recording.status = "recording"
    recording.started_at = recording.started_at or utcnow()
    db.add(clip)
    await db.flush()
    return clip


async def store_chunk(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    clip_id: uuid.UUID,
    sequence: int,
    data: bytes,
    claimed_sha256: str,
    root: Path,
) -> RecordingChunk:
    if sequence < 0 or sequence > 100000:
        raise RecordingSessionError("invalid chunk sequence")
    if not data or len(data) > MAX_CHUNK_BYTES:
        raise RecordingSessionError("chunk size is outside the allowed range")
    digest = hashlib.sha256(data).hexdigest()
    if digest != claimed_sha256.lower():
        raise RecordingSessionError("chunk checksum does not match")
    clip = (
        await db.execute(
            select(RecordingClip).where(
                RecordingClip.id == clip_id, RecordingClip.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()
    if clip is None:
        raise RecordingSessionError("clip not found")
    existing = (
        await db.execute(
            select(RecordingChunk).where(
                RecordingChunk.clip_id == clip_id, RecordingChunk.sequence == sequence
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.sha256 == digest and existing.size_bytes == len(data):
            return existing
        raise RecordingSessionError("chunk sequence already has different bytes")
    directory = root / str(workspace_id) / str(clip.session_id) / str(clip.id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{sequence:06d}.part"
    temp = path.with_suffix(".part.tmp")
    temp.write_bytes(data)
    temp.replace(path)
    chunk = RecordingChunk(
        workspace_id=workspace_id,
        clip_id=clip.id,
        sequence=sequence,
        sha256=digest,
        size_bytes=len(data),
        storage_path=str(path),
        uploaded_at=utcnow(),
    )
    db.add(chunk)
    clip.chunk_count = max(int(clip.chunk_count or 0), sequence + 1)
    await db.flush()
    return chunk


async def finalize_clip(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    clip_id: uuid.UUID,
    root: Path,
    *,
    active_duration_s: float,
    take_markers: list[dict[str, Any]] | None = None,
    prober: Callable[[str | Path], Awaitable[dict[str, Any]]] = probe_media,
) -> RecordingClip:
    clip = (
        await db.execute(
            select(RecordingClip).where(
                RecordingClip.id == clip_id, RecordingClip.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()
    if clip is None:
        raise RecordingSessionError("clip not found")
    if clip.status == "ready":
        return clip
    chunks = list(
        (
            await db.execute(
                select(RecordingChunk)
                .where(RecordingChunk.clip_id == clip.id)
                .order_by(RecordingChunk.sequence)
            )
        )
        .scalars()
        .all()
    )
    if not chunks or [item.sequence for item in chunks] != list(range(len(chunks))):
        raise RecordingSessionError("clip has missing chunk sequences")
    directory = root / str(workspace_id) / str(clip.session_id) / str(clip.id)
    assembled = directory / f"clip.{clip.file_extension}"
    with assembled.open("wb") as target:
        for chunk in chunks:
            target.write(Path(chunk.storage_path).read_bytes())
    proof = await prober(assembled)
    if not proof.get("has_audio"):
        raise RecordingSessionError("assembled clip has no audible track")
    if clip.mime_type.startswith("video/") and not proof.get("has_video"):
        raise RecordingSessionError("assembled clip has no video track")
    clip.assembled_path = str(assembled)
    clip.sha256 = hashlib.sha256(assembled.read_bytes()).hexdigest()
    clip.duration_s = proof.get("duration_s")
    clip.active_duration_s = max(0.0, float(active_duration_s))
    clip.take_markers = take_markers or []
    clip.timing_meta = proof
    clip.status = "ready"
    clip.finished_at = utcnow()
    await db.flush()
    return clip


async def assemble_clips(paths: list[Path], output: Path) -> dict[str, Any]:
    exe = ffmpeg_path()
    if not exe:
        raise RecordingSessionError("ffmpeg is not installed")
    output.parent.mkdir(parents=True, exist_ok=True)
    listing = output.with_suffix(".concat.txt")
    listing.write_text(
        "".join(
            f"file '{str(path).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
            for path in paths
        ),
        encoding="utf-8",
    )
    try:
        for args in (
            ["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(output)],
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output),
            ],
        ):
            output.unlink(missing_ok=True)
            proc = await asyncio.create_subprocess_exec(
                exe, "-y", *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            _out, _err = await proc.communicate()
            if proc.returncode == 0:
                proof = await probe_media(output)
                if proof.get("has_audio") and proof.get("has_video"):
                    return proof
        raise RecordingSessionError("ffmpeg could not assemble a valid audio and video timeline")
    finally:
        listing.unlink(missing_ok=True)


async def finalize_session(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    session_id: uuid.UUID,
    selected_clip_ids: list[uuid.UUID],
    root: Path,
    *,
    assembler: Callable[[list[Path], Path], Awaitable[dict[str, Any]]] = assemble_clips,
) -> tuple[RecordingSession, RecordingUpload]:
    recording = (
        await db.execute(
            select(RecordingSession).where(
                RecordingSession.id == session_id,
                RecordingSession.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if recording is None:
        raise RecordingSessionError("recording session not found")
    if recording.canonical_upload_id:
        upload = (
            await db.execute(
                select(RecordingUpload).where(
                    RecordingUpload.id == recording.canonical_upload_id,
                    RecordingUpload.workspace_id == workspace_id,
                )
            )
        ).scalar_one()
        return recording, upload
    if not selected_clip_ids:
        raise RecordingSessionError("select at least one clip")
    clips = list(
        (
            await db.execute(
                select(RecordingClip).where(
                    RecordingClip.workspace_id == workspace_id,
                    RecordingClip.session_id == session_id,
                    RecordingClip.id.in_(selected_clip_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {clip.id: clip for clip in clips}
    if set(by_id) != set(selected_clip_ids) or any(clip.status != "ready" for clip in clips):
        raise RecordingSessionError("every selected clip must be ready in this session")
    ordered = [by_id[clip_id] for clip_id in selected_clip_ids]
    recording.status = "finalizing"
    output = root / str(workspace_id) / str(recording.id) / "canonical.mp4"
    proof = await assembler([Path(clip.assembled_path or "") for clip in ordered], output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    upload = RecordingUpload(
        workspace_id=workspace_id,
        candidate_id=recording.candidate_id,
        packet_id=recording.packet_id,
        recording_session_id=recording.id,
        original_filename=f"recording-session-{recording.id}.mp4",
        storage_path=str(output),
        sha256=digest,
        duration_s=proof.get("duration_s"),
        status="uploaded",
        status_detail="assembled from selected session clips; source clips retained",
    )
    db.add(upload)
    await db.flush()
    recording.selected_clip_ids = [str(value) for value in selected_clip_ids]
    offset = 0.0
    timeline: list[dict[str, Any]] = []
    for clip in ordered:
        duration = float(clip.duration_s or clip.active_duration_s or 0)
        timeline.append(
            {
                "clip_id": str(clip.id),
                "position": clip.position,
                "timeline_start_s": round(offset, 3),
                "timeline_end_s": round(offset + duration, 3),
                "source_duration_s": duration,
                "take_markers": list(clip.take_markers or []),
            }
        )
        offset += duration
    recording.timeline_map = timeline
    recording.canonical_upload_id = upload.id
    recording.active_duration_s = sum(float(clip.active_duration_s or 0) for clip in ordered)
    recording.status = "uploaded"
    recording.finished_at = utcnow()
    await db.flush()
    return recording, upload
