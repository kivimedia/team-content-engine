"""/editorial voice-agent routes: find, change, undo, restore, research, activity.

The voice agent's tools (mcp-server/tools/voice.mjs) call these. They are also
what the workspace's "Changes by voice" panel reads and what its Undo and Restore
buttons press, so the phone and the call share one contract.

Every write here takes `by` ("voice" or "ziv") and records it, so nothing the
agent does is anonymous.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from tce.api.private_access import require_private_workspace
from tce.api.routers.editorial import get_editorial_sessionmaker
from tce.editorial import changes as change_service
from tce.editorial import inbox as inbox_service
from tce.editorial import lineup as lineup_service
from tce.editorial import voice_agent
from tce.editorial.common import open_session

router = APIRouter(prefix="/editorial", tags=["editorial-voice"])

ServiceError = (
    voice_agent.VoiceError,
    change_service.ChangeError,
    inbox_service.InboxError,
    lineup_service.LineupError,
)


def _http(error: Exception) -> HTTPException:
    payload: dict[str, Any] = {
        "code": getattr(error, "code", "error"),
        "message": getattr(error, "message", str(error)),
    }
    payload.update(getattr(error, "extra", {}) or {})
    return HTTPException(status_code=getattr(error, "status", 409), detail=payload)


def _uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{what} is not a valid id") from None


class ByRequest(BaseModel):
    by: str = "voice"


class VoiceOperation(BaseModel):
    op: str = "set_field"
    field: str | None = None
    after: Any = None
    # The text the agent read back as current. A mismatch means someone changed
    # it since, and nothing is written.
    expect: str | None = None


class VoiceChangeRequest(BaseModel):
    candidate_id: str
    target: str  # brief | script | week
    operations: list[VoiceOperation] = Field(min_length=1)
    summary: str = "Changed by voice"
    by: str = "voice"


# ---------------------------------------------------------------- reading


@router.get("/voice/topic")
async def find_topic(
    q: str = Query(..., min_length=1, max_length=300),
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """One topic in full (brief, script, openings), found by id, short id or title words.

    Ambiguous words return the candidates instead, so the agent can ask which.
    """
    async with open_session(sm) as db:
        try:
            found = await voice_agent.find_topics(db, ws, q)
            if found["status"] != "found":
                return {
                    "status": found["status"],
                    "topic": None,
                    "candidates": [
                        voice_agent.candidate_brief_json(c) for c in found["candidates"]
                    ],
                }
            detail = await voice_agent.topic_detail(db, ws, found["candidate"])
            # Reading seeds brief version 1 the first time; keep it.
            await db.commit()
            return {"status": "found", "topic": detail, "candidates": []}
        except ServiceError as error:
            raise _http(error) from error


@router.get("/voice/activity")
async def voice_activity(
    hours: int = Query(24, ge=1, le=24 * 14),
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        return await voice_agent.activity(db, ws, hours=hours)


# ---------------------------------------------------------------- writing


@router.post("/voice/change")
async def voice_change(
    body: VoiceChangeRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Propose and apply in one call. Undo it with /change-sets/{id}/undo."""
    cid = _uuid(body.candidate_id, "topic")
    async with open_session(sm) as db:
        try:
            result = await voice_agent.apply_change(
                db,
                ws,
                candidate_id=cid,
                target=body.target,
                operations=[op.model_dump() for op in body.operations],
                summary=body.summary,
                by=body.by,
            )
            await db.commit()
            return result
        except ServiceError as error:
            if getattr(error, "code", None) == "conflict":
                # A version conflict marks the proposal superseded; keep that record.
                await db.commit()
            else:
                # Anything else writes nothing: a move that failed halfway must not
                # leave the moves before it, or a proposal waiting for a yes or no.
                await db.rollback()
            raise _http(error) from error


@router.post("/change-sets/{change_set_id}/undo")
async def undo_change(
    change_set_id: str,
    body: ByRequest | None = None,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    csid = _uuid(change_set_id, "change")
    async with open_session(sm) as db:
        try:
            result = await voice_agent.undo_change_set(
                db, ws, csid, by=(body.by if body else "voice")
            )
            await db.commit()
            return result
        except ServiceError as error:
            await db.rollback()
            raise _http(error) from error


@router.post("/topics/{candidate_id}/restore")
async def restore_topic(
    candidate_id: str,
    body: ByRequest | None = None,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Bring a put-away idea back to where it was before."""
    cid = _uuid(candidate_id, "topic")
    async with open_session(sm) as db:
        try:
            result = await voice_agent.restore_topic(db, ws, cid, by=(body.by if body else "voice"))
            await db.commit()
            return result
        except ServiceError as error:
            raise _http(error) from error


# ---------------------------------------------------------------- research


@router.post("/candidates/{candidate_id}/research", status_code=202)
async def start_research(
    candidate_id: str,
    background: BackgroundTasks,
    body: ByRequest | None = None,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Start research on one idea. Returns at once; poll /editorial/research/{id}."""
    cid = _uuid(candidate_id, "topic")
    async with open_session(sm) as db:
        try:
            row, created = await voice_agent.start_research(
                db, ws, cid, by=(body.by if body else "voice")
            )
            payload = voice_agent.research_to_json(row)
            await db.commit()
        except ServiceError as error:
            raise _http(error) from error
    # One job per idea at a time: asking again while it runs reports the same job.
    if created:
        background.add_task(voice_agent.run_research, sm, ws, uuid.UUID(payload["research_id"]))
    return {
        **payload,
        "already_running": not created,
        "status_url": f"/api/v1/editorial/research/{payload['research_id']}",
    }


@router.get("/research/{research_id}")
async def get_research(
    research_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    rid = _uuid(research_id, "research")
    from sqlalchemy import select

    from tce.models.editorial_workspace import IdeaResearch

    async with open_session(sm) as db:
        row = (
            await db.execute(
                select(IdeaResearch).where(IdeaResearch.workspace_id == ws, IdeaResearch.id == rid)
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="research not found")
        return voice_agent.research_to_json(row)
