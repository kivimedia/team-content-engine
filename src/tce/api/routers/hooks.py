"""The hook library API (26-Nov-2026, T-25210).

GET    /hooks                      every proved hook (favorites first), this week's picks,
                                   and the videos of the week a pick can move to
GET    /hooks/{id}/preview         the hook's proof clip, rendered from his own take
POST   /hooks/{id}/favorite        {"on": true|false}
POST   /hooks/{id}/pick            {"candidate_id": optional} pick it for this week; with
                                   no video named, TCE puts it on the one it fits. The
                                   script is then rewritten to open on it (T-25711)
DELETE /hooks/{id}/pick            take it out of this week
GET    /hooks/for/{candidate_id}   the hooks picked onto that video this week, with what
                                   to do on camera (the recording screen, T-25711)

The owner's only, like the Book: the proof clips are his own footage.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from tce.api.private_access import require_private_workspace, scoped_editor_workspace
from tce.api.routers.editorial import get_editorial_sessionmaker
from tce.editorial import lineup as lineup_service
from tce.editorial.common import open_session
from tce.hooks import library, script_fit
from tce.hooks.catalog import BY_ID

router = APIRouter(prefix="/hooks", tags=["hooks"])


async def require_owner(
    ws: uuid.UUID = Depends(require_private_workspace),
    x_tce_editor_key: str | None = Header(None),
) -> uuid.UUID:
    if scoped_editor_workspace(x_tce_editor_key) is not None:
        raise HTTPException(status_code=403, detail="The hook library is the owner's only")
    return ws


class FavoriteRequest(BaseModel):
    on: bool = True


class PickRequest(BaseModel):
    candidate_id: str | None = None


def _week_key() -> str:
    return lineup_service.week_start_for(None).date().isoformat()


async def _lineup(sm: Any, ws: uuid.UUID) -> dict[str, Any]:
    async with open_session(sm) as db:
        row = await lineup_service.current_lineup(db, ws)
        payload = await lineup_service.lineup_to_json(db, ws, row)
        await db.commit()
        return payload


def _http(error: library.HookError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message})


def _preview_url(hook_id: str) -> str:
    return f"hooks/{hook_id}/preview"


@router.get("")
async def get_library(
    ws: uuid.UUID = Depends(require_owner), sm: Any = Depends(get_editorial_sessionmaker)
) -> dict[str, Any]:
    lineup = await _lineup(sm, ws)
    return await library.library(ws, _week_key(), lineup, _preview_url)


@router.get("/for/{candidate_id}")
async def hooks_for_video(candidate_id: str, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    hooks = library.for_video(ws, _week_key(), candidate_id)
    for hook in hooks:
        hook["preview_url"] = _preview_url(hook["id"])
    return {"candidate_id": candidate_id, "week_start": _week_key(), "hooks": hooks}


@router.get("/{hook_id}/preview")
async def get_preview(hook_id: str, ws: uuid.UUID = Depends(require_owner)) -> FileResponse:
    hook = BY_ID.get(hook_id)
    if hook is None or not hook.preview.is_file():
        raise HTTPException(status_code=404, detail="No preview for that hook")
    return FileResponse(hook.preview, media_type="video/mp4", headers={"Cache-Control": "private, max-age=86400"})


@router.post("/{hook_id}/favorite")
async def set_favorite(hook_id: str, body: FavoriteRequest, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    try:
        favorites = await library.toggle_favorite(ws, hook_id, body.on)
    except library.HookError as error:
        raise _http(error) from None
    return {"hook_id": hook_id, "favorite": hook_id in favorites, "favorites": favorites}


@router.post("/{hook_id}/pick")
async def pick_hook(
    hook_id: str,
    body: PickRequest,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_owner),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    lineup = await _lineup(sm, ws)
    week = _week_key()
    try:
        entry = await library.pick(ws, week, hook_id, lineup, body.candidate_id)
    except library.HookError as error:
        raise _http(error) from None
    if entry.get("candidate_id"):
        # T-25711: the script is rewritten to open on this hook, in the background
        # (the writer queue can take minutes); the pick shows how it went.
        await library.set_script(
            ws, week, hook_id, entry["candidate_id"], "writing", "Writing an opening for this hook."
        )
        background.add_task(script_fit.fit_script, sm, ws, week, entry["candidate_id"], hook_id)
    return await library.library(ws, week, lineup, _preview_url)


@router.delete("/{hook_id}/pick")
async def unpick_hook(
    hook_id: str, ws: uuid.UUID = Depends(require_owner), sm: Any = Depends(get_editorial_sessionmaker)
) -> dict[str, Any]:
    if hook_id not in BY_ID:
        raise HTTPException(status_code=404, detail="That hook is not in the library")
    await library.unpick(ws, _week_key(), hook_id)
    lineup = await _lineup(sm, ws)
    return await library.library(ws, _week_key(), lineup, _preview_url)
