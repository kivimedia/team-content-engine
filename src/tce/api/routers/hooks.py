"""The hook library API (26-Nov-2026, T-25210).

GET    /hooks                      every proved hook (favorites first), this week's picks,
                                   and the videos of the week a pick can move to
GET    /hooks/{id}/preview         the hook's proof clip, rendered from his own take
POST   /hooks/{id}/favorite        {"on": true|false}
POST   /hooks/{id}/pick            {"candidate_id": optional} pick it for this week; with
                                   no video named, TCE puts it on the one it fits. The
                                   script is then rewritten to open on it (T-25711)
DELETE /hooks/{id}/pick            take it out of this week
POST   /hooks/style                {"accent": "#2EA3F2" | null} his color for the edit
GET    /hooks/trending?again=1     the trending video studio: this week's most watched
                                   short videos in his field (YouTube, once a day)
POST   /hooks/trending/{id}/consider  put one on the list of new hooks to prove
GET    /hooks/for/{candidate_id}   the hooks picked onto that video this week, with what
                                   to do on camera (the recording screen, T-25711)

Trend formats (T-25834), a whole video shape beside the hooks:
POST   /hooks/formats/{id}/pick    {"candidate_id": optional} put it on a video this week;
                                   TCE then writes its script from the topic, for review
DELETE /hooks/formats/{id}/pick    take it out of this week
POST   /hooks/formats/{id}/script  {"action": "again"} write it again, or
                                   {"action": "accept", "lines": {step: line}} accept it
POST   /hooks/formats/{id}/decide  {"choice": "want" | "pass" | null} his yes (it goes on his
                                     big ideas list), his no, or taking it back (T-26074)
GET    /hooks/formats/{id}/examples?again=1  real short videos in the format (YouTube)
GET    /hooks/formats/{id}/drawing/{step}.svg  the recording card's drawing

The owner's only, like the Book: the proof clips are his own footage.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from tce.api.private_access import require_private_workspace, scoped_editor_workspace
from tce.api.routers.editorial import get_editorial_sessionmaker
from tce.editorial import lineup as lineup_service
from tce.editorial.common import open_session
from tce.hooks import ai_match, format_library, format_script, formats, library, script_fit, trending
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


class StyleRequest(BaseModel):
    accent: str | None = None


class DecideRequest(BaseModel):
    choice: str | None = None


class FormatScriptRequest(BaseModel):
    action: str = "again"
    lines: dict[str, str] | None = None


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


async def _page(ws: uuid.UUID, week: str, lineup: dict[str, Any]) -> dict[str, Any]:
    """The studio's whole read: the hook library and, beside it, the trend formats (T-25834)."""
    data = await library.library(ws, week, lineup, _preview_url)
    data["formats"] = await format_library.page(ws, week, library.week_videos(lineup))
    data["big_ideas"] = format_library.wanted(ws)  # T-26074: the trends he said yes to
    return data


@router.get("")
async def get_library(
    ws: uuid.UUID = Depends(require_owner), sm: Any = Depends(get_editorial_sessionmaker)
) -> dict[str, Any]:
    lineup = await _lineup(sm, ws)
    return await _page(ws, _week_key(), lineup)


@router.post("/style")
async def set_style(
    body: StyleRequest, ws: uuid.UUID = Depends(require_owner), sm: Any = Depends(get_editorial_sessionmaker)
) -> dict[str, Any]:
    """His color for every hook and headline in the Creatorz edit (T-25711)."""
    try:
        await library.set_accent(ws, body.accent or None)
    except library.HookError as error:
        raise _http(error) from None
    lineup = await _lineup(sm, ws)
    return await _page(ws, _week_key(), lineup)


@router.get("/trending")
async def get_trending(again: bool = False, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    """The trending video studio (T-25711): this week's most watched shorts in his field."""
    return await trending.look(ws, again=again)


@router.post("/trending/{video_id}/consider")
async def consider_trending(video_id: str, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    try:
        return await trending.consider(ws, video_id)
    except library.HookError as error:
        raise _http(error) from None


@router.post("/formats/{format_id}/pick")
async def pick_format(
    format_id: str,
    body: PickRequest,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_owner),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    lineup = await _lineup(sm, ws)
    week = _week_key()
    try:
        entry = await format_library.pick(ws, week, format_id, lineup, body.candidate_id)
    except library.HookError as error:
        raise _http(error) from None
    if entry.get("candidate_id"):
        await _write_format_script(background, sm, ws, week, format_id, entry["candidate_id"], lineup)
    return await _page(ws, week, lineup)


async def _write_format_script(
    background: BackgroundTasks, sm: Any, ws: uuid.UUID, week: str, format_id: str, candidate_id: str,
    lineup: dict[str, Any],
) -> None:
    """The script is written in the background (the writer queue can take minutes);
    the format's card shows it is being written, then the draft to review."""
    topic = next((v for v in library.week_videos(lineup) if v["candidate_id"] == candidate_id), {})
    fmt = formats.BY_ID[format_id]
    await format_library.set_script(
        ws, week, format_id, candidate_id,
        {"state": "writing", "detail": f"Writing the {fmt.name} script from this video's topic."},
    )
    background.add_task(format_script.fill, sm, ws, week, format_id, candidate_id, dict(topic))


@router.delete("/formats/{format_id}/pick")
async def unpick_format(
    format_id: str, ws: uuid.UUID = Depends(require_owner), sm: Any = Depends(get_editorial_sessionmaker)
) -> dict[str, Any]:
    try:
        await format_library.unpick(ws, _week_key(), format_id)
    except library.HookError as error:
        raise _http(error) from None
    lineup = await _lineup(sm, ws)
    return await _page(ws, _week_key(), lineup)


@router.post("/formats/{format_id}/script")
async def format_script_action(
    format_id: str,
    body: FormatScriptRequest,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_owner),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    week = _week_key()
    lineup = await _lineup(sm, ws)
    try:
        if body.action == "accept":
            await format_library.approve(ws, week, format_id, body.lines or {})
        elif body.action == "again":
            entry = format_library.current(ws, week, format_id)
            if entry is None or not entry.get("candidate_id"):
                raise library.HookError("not_picked", "That format is not on a video this week.", status=409)
            await _write_format_script(background, sm, ws, week, format_id, entry["candidate_id"], lineup)
        else:
            raise library.HookError("unknown_action", "That is not something the script can do.", status=400)
    except library.HookError as error:
        raise _http(error) from None
    return await _page(ws, week, lineup)


@router.post("/formats/{format_id}/decide")
async def decide_format(
    format_id: str,
    body: DecideRequest,
    ws: uuid.UUID = Depends(require_owner),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """T-26074: the trend page's only choice. A yes puts the trend on his big ideas
    list; nothing is put on a video and no script is written here."""
    try:
        await format_library.decide(ws, format_id, body.choice)
    except library.HookError as error:
        raise _http(error) from None
    lineup = await _lineup(sm, ws)
    return await _page(ws, _week_key(), lineup)


@router.get("/formats/{format_id}/examples")
async def format_examples(format_id: str, again: bool = False, ws: uuid.UUID = Depends(require_owner)) -> dict[str, Any]:
    try:
        return await trending.format_examples(ws, format_id, again=again)
    except library.HookError as error:
        raise _http(error) from None


@router.get("/formats/{format_id}/drawing/{step_id}.svg")
async def format_drawing(format_id: str, step_id: str, ws: uuid.UUID = Depends(require_owner)) -> Response:
    fmt = formats.BY_ID.get(format_id)
    svg = formats.drawing(fmt, step_id) if fmt is not None else None
    if svg is None:
        raise HTTPException(status_code=404, detail="No drawing for that step")
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=86400"})


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
            ws, week, hook_id, entry["candidate_id"], "writing",
            "Choosing the best video for it, then writing an opening for it."
            if entry.get("chosen_by") == "tce" else "Writing an opening for this hook."
        )
        if entry.get("chosen_by") == "tce":
            # The AI reads the week's videos and may move it first, with its reason.
            background.add_task(ai_match.match_and_fit, sm, ws, week, hook_id, lineup)
        else:
            background.add_task(script_fit.fit_script, sm, ws, week, entry["candidate_id"], hook_id)
    return await _page(ws, week, lineup)


@router.delete("/{hook_id}/pick")
async def unpick_hook(
    hook_id: str, ws: uuid.UUID = Depends(require_owner), sm: Any = Depends(get_editorial_sessionmaker)
) -> dict[str, Any]:
    if hook_id not in BY_ID:
        raise HTTPException(status_code=404, detail="That hook is not in the library")
    await library.unpick(ws, _week_key(), hook_id)
    lineup = await _lineup(sm, ws)
    return await _page(ws, _week_key(), lineup)
