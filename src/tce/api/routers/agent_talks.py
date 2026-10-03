"""/production/agent-talks: a filmed voice call with an agent, sent in pieces (contract C4).

The KM BOT voice service relays what the call's page records: it creates the talk when
he taps record, sends each MediaRecorder slice as it is spooled, and finishes the talk
when the call ends (or its sweeper finds the recording idle). The private key stays on
that server; a browser never holds it. Auth and the workspace come from
`require_private_workspace`, like every /production route, and every query filters on
the workspace explicitly.

1. POST /production/agent-talks {"agent","call_id","started_at","mime"}
   -> 201 {"talk_id","status":"recording"} (200 with the same talk when it was sent before)
2. PUT /production/agent-talks/{talk_id}/chunks/{seq} raw bytes, seq from 0
   -> {"ok":true,"bytes_total":N}; the same piece again changes nothing
3. POST /production/agent-talks/{talk_id}/finish {"ended_at","duration_ms","transcript"}
   -> {"upload_id","status"}: the pieces joined (remuxed, never re-encoded), a library
   video with source "agent_talk" titled "Talk with <Agent>, <date>", and its edit
   started unless TCE_PRODUCTION_AUTO_EDIT is off. Finishing again returns the same video.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tce.api.private_access import require_private_workspace
from tce.db.session import get_db
from tce.editorial.agent_talk_topics import talk_topic
from tce.models.editorial import RecordingUpload
from tce.models.recording_session import AgentTalk
from tce.production import agent_talks
from tce.production.agent_talks import TalkError
from tce.settings import settings

router = APIRouter(prefix="/production/agent-talks", tags=["production"])

_finish_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _finish_lock(talk_id: uuid.UUID) -> asyncio.Lock:
    """One finish of a talk at a time in this process: the call ending and the sweeper
    finding it idle can both ask, and must make one video."""
    lock = _finish_locks.get(talk_id)
    if lock is None:
        lock = _finish_locks[talk_id] = asyncio.Lock()
    return lock


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _root() -> Path:
    return Path(settings.evidence_upload_dir)


class AgentTalkCreate(BaseModel):
    agent: str = Field(min_length=1, max_length=80)
    call_id: str = Field(min_length=1, max_length=200)
    started_at: str = Field(min_length=1, max_length=64)
    mime: str = Field(min_length=1, max_length=120)


class TranscriptLine(BaseModel):
    who: str = Field(default="", max_length=40)
    text: str = Field(default="", max_length=20000)
    t_ms: float | None = None


class AgentTalkFinish(BaseModel):
    ended_at: str | None = Field(default=None, max_length=64)
    duration_ms: int | None = Field(default=None, ge=0)
    transcript: list[TranscriptLine] | None = Field(default=None, max_length=50000)


def _http(exc: TalkError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


async def _talk(db: AsyncSession, ws: uuid.UUID, talk_id: uuid.UUID) -> AgentTalk:
    row = (
        await db.execute(
            select(AgentTalk).where(AgentTalk.id == talk_id, AgentTalk.workspace_id == ws)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Agent talk not found")
    return row


def _folder(row: AgentTalk) -> Path:
    return agent_talks.talk_folder(_root(), row.workspace_id, row.id)


def talk_json(row: AgentTalk, *, pieces: int | None = None, bytes_total: int | None = None) -> dict[str, Any]:
    if pieces is None or bytes_total is None:
        pieces, bytes_total = agent_talks.received(_folder(row))
        meta = row.join_meta or {}
        if row.upload_id and not pieces:
            pieces, bytes_total = int(meta.get("pieces") or 0), int(meta.get("bytes") or 0)
    return {
        "talk_id": str(row.id),
        "status": row.status,
        "agent": agent_talks.display_name(row.agent),
        "title": agent_talks.talk_title(row.agent, row.started_at),
        "call_id": row.call_id,
        "pieces": pieces,
        "bytes_total": bytes_total,
        "upload_id": str(row.upload_id) if row.upload_id else None,
        "detail": row.status_detail,
    }


@router.post("", status_code=201)
async def create_agent_talk(
    body: AgentTalkCreate,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    try:
        extension = agent_talks.container_for(body.mime)
        started = agent_talks.parse_instant(body.started_at)
    except TalkError as exc:
        raise _http(exc) from exc
    agent = body.agent.strip()
    call_id = body.call_id.strip()

    async def existing() -> AgentTalk | None:
        return (
            await db.execute(
                select(AgentTalk).where(
                    AgentTalk.workspace_id == ws,
                    AgentTalk.agent == agent,
                    AgentTalk.call_id == call_id,
                    AgentTalk.started_at == started,
                )
            )
        ).scalar_one_or_none()

    # A create sent twice (the relay retried) is the same talk, whatever it became since.
    found = await existing()
    if found is not None:
        return JSONResponse(status_code=200, content=talk_json(found))
    row = AgentTalk(
        workspace_id=ws,
        agent=agent,
        call_id=call_id,
        started_at=started,
        mime_type=body.mime.strip()[:120],
        file_extension=extension,
        status="recording",
        status_detail=(
            f"Recording the talk with {agent_talks.display_name(agent)}: the pieces arrive "
            "while the call runs"
        ),
        join_meta={},
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        found = await existing()
        if found is None:
            raise
        return JSONResponse(status_code=200, content=talk_json(found))
    return talk_json(row, pieces=0, bytes_total=0)


@router.get("/{talk_id}")
async def get_agent_talk(
    talk_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Where a talk stands: the pieces that arrived, and the video once there is one."""
    return talk_json(await _talk(db, ws, talk_id))


@router.put("/{talk_id}/chunks/{seq}")
async def put_agent_talk_chunk(
    talk_id: uuid.UUID,
    seq: int,
    request: Request,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    row = await _talk(db, ws, talk_id)
    if row.upload_id is not None or row.status == "finished":
        raise HTTPException(
            status_code=409,
            detail="This talk is finished and its video is made; a piece sent now would not be in it",
        )
    if _finish_lock(talk_id).locked():
        raise HTTPException(
            status_code=409,
            detail="This talk is being joined into its video right now; a piece sent now would not be in it",
        )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > agent_talks.MAX_CHUNK_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"The piece is larger than {agent_talks.MAX_CHUNK_BYTES // (1024 * 1024)} MB",
        )
    data = await request.body()
    try:
        stored = await asyncio.to_thread(agent_talks.store_piece, _folder(row), seq, data)
    except TalkError as exc:
        raise _http(exc) from exc
    row.last_chunk_at = _utcnow()
    if row.status == "failed":  # a join failed; pieces still arriving make it a recording again
        row.status = "recording"
    row.status_detail = (
        f"Recording the talk with {agent_talks.display_name(row.agent)}: "
        f"{stored.pieces} {'piece' if stored.pieces == 1 else 'pieces'} here, "
        f"{stored.bytes_total / 1_000_000:.1f} MB, the last at {agent_talks.local_time(row.last_chunk_at):%H:%M:%S}"
    )
    await db.commit()
    return {
        "ok": True,
        "bytes_total": stored.bytes_total,
        "seq": seq,
        "pieces": stored.pieces,
        "duplicate": not stored.created,
    }


def _finished(row: AgentTalk, upload: RecordingUpload | None) -> dict[str, Any]:
    return {
        "upload_id": str(row.upload_id) if row.upload_id else None,
        "status": upload.status if upload is not None else row.status,
        "talk_id": str(row.id),
        "title": agent_talks.talk_title(row.agent, row.started_at),
        "detail": upload.status_detail if upload is not None else row.status_detail,
        "missing_pieces": list((row.join_meta or {}).get("missing") or []),
    }


async def _upload_of(db: AsyncSession, ws: uuid.UUID, upload_id: uuid.UUID | None) -> RecordingUpload | None:
    if upload_id is None:
        return None
    return (
        await db.execute(
            select(RecordingUpload).where(
                RecordingUpload.id == upload_id, RecordingUpload.workspace_id == ws
            )
        )
    ).scalar_one_or_none()


def _missing_line(missing: list[int]) -> str:
    if not missing:
        return ""
    shown = ", ".join(str(n) for n in missing[:8]) + (" and more" if len(missing) > 8 else "")
    return (
        f" {len(missing)} {'piece' if len(missing) == 1 else 'pieces'} never arrived "
        f"(number {shown}), so the video skips there."
    )


@router.post("/{talk_id}/finish")
async def finish_agent_talk(
    talk_id: uuid.UUID,
    body: AgentTalkFinish | None = None,
    ws: uuid.UUID = Depends(require_private_workspace),
    db: AsyncSession = Depends(get_db),
):
    body = body or AgentTalkFinish()
    row = await _talk(db, ws, talk_id)
    if row.upload_id is not None:  # finished before: the same video, as it stands now
        return _finished(row, await _upload_of(db, ws, row.upload_id))
    async with _finish_lock(talk_id):
        await db.refresh(row)
        if row.upload_id is not None:  # another finish made it while this one waited
            return _finished(row, await _upload_of(db, ws, row.upload_id))
        try:
            ended = agent_talks.parse_instant(body.ended_at) or _utcnow()
        except TalkError as exc:
            raise _http(exc) from exc
        name = agent_talks.display_name(row.agent)
        try:
            joined = await agent_talks.join(_folder(row), row.file_extension)
        except TalkError as exc:
            if exc.status == 422:  # the pieces are here and do not make a video
                row.status = "failed"
                row.status_detail = f"The talk with {name} could not be joined: {exc}"[:500]
                await db.commit()
            raise _http(exc) from exc
        sha = await asyncio.to_thread(agent_talks.sha256_of, joined.path)
        lines = [line.model_dump() for line in body.transcript or []]
        duration = joined.proof.get("duration_s") or (
            body.duration_ms / 1000.0 if body.duration_ms else None
        )
        row.ended_at = ended
        row.duration_ms = body.duration_ms
        row.join_meta = {
            "pieces": joined.pieces,
            "bytes": joined.bytes,
            "missing": joined.missing,
            "container": joined.container,
            "streams": joined.proof.get("streams") or [],
            "joined_at": _utcnow().isoformat(),
        }
        # The same bytes are already a video here (uq_recording_upload_sha): that one it is.
        upload = (
            await db.execute(
                select(RecordingUpload).where(
                    RecordingUpload.workspace_id == ws, RecordingUpload.sha256 == sha
                )
            )
        ).scalar_one_or_none()
        created = upload is None
        if created:
            # The library names a video by its topic row: one of the agent-talk kind,
            # which no list of ideas shows (editorial/agent_talk_topics.py).
            candidate = talk_topic(ws, row.agent, row.started_at)
            db.add(candidate)
            await db.flush()
            auto = bool(settings.production_auto_edit)
            upload = RecordingUpload(
                workspace_id=ws,
                candidate_id=candidate.id,
                packet_id=None,
                original_filename=f"agent-talk-{row.id}.{joined.container}",
                storage_path=str(joined.path),
                sha256=sha,
                duration_s=duration,
                status="uploaded",
                status_detail=(
                    (
                        f"Agent talk with {name}, joined from {joined.pieces} "
                        f"{'piece' if joined.pieces == 1 else 'pieces'} without re-encoding."
                        if joined.pieces
                        else f"Agent talk with {name}, joined without re-encoding."
                    )
                    + _missing_line(joined.missing)
                    + (
                        " Jennifer starts the edit now: transcribing first."
                        if auto
                        else " Automatic editing is switched off on this server, so it waits as it is."
                    )
                )[:500],
                job_ids=[],
                source=agent_talks.SOURCE,
                agent_name=name,
                call_transcript=lines,
            )
            db.add(upload)
            await db.flush()
        row.upload_id = upload.id
        row.status = "finished"
        row.status_detail = (
            f"Finished: the talk with {name} is in the library as “"
            f"{agent_talks.talk_title(row.agent, row.started_at)}”."
            + _missing_line(joined.missing)
        )[:500]
        await db.commit()
        upload_id = upload.id
        result = _finished(row, upload)
    if created:
        # The edit runs in the background and sees the committed video. The kill switch
        # (TCE_PRODUCTION_AUTO_EDIT) is read inside start_auto_edit.
        from tce.api.routers import production as production_routes

        production_routes.start_auto_edit(upload_id, ws)
    result["edit_started"] = bool(created and settings.production_auto_edit)
    return result
