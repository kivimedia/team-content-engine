"""/editorial workspace routes: Today, topics, the week, changes and the library.

These are the read and decide surfaces the phone uses. They are deliberately thin:
every rule lives in `tce.editorial.*` so the same contract holds whether a change
arrives from a button, from typed conversation, or later from speech.

Two conventions the whole file keeps:

*Mutations take an expected version.* A conflict returns 409 with the newer state
attached, never a silent overwrite. The client shows a review path.

*Service errors carry their own status and sentence.* `ChangeError`, `LineupError`
and `InboxError` already know what went wrong and how to say it to a human, so the
handlers translate rather than re-diagnose.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from tce.api.private_access import require_private_workspace
from tce.api.routers.editorial import get_editorial_sessionmaker
from tce.editorial import briefs as brief_service
from tce.editorial import changes as change_service
from tce.editorial import inbox as inbox_service
from tce.editorial import library as library_service
from tce.editorial import lineup as lineup_service
from tce.editorial import today as today_service
from tce.editorial.common import open_session
from tce.editorial.packets import list_packets

logger = structlog.get_logger()

router = APIRouter(prefix="/editorial", tags=["editorial-workspace"])
production_router = APIRouter(prefix="/production", tags=["editorial-workspace"])


ServiceError = (
    change_service.ChangeError,
    lineup_service.LineupError,
    inbox_service.InboxError,
    library_service.LibraryError,
)


def _http(error: Exception) -> HTTPException:
    """Translate a service error into its HTTP shape, keeping the extra detail."""
    status = getattr(error, "status", 409)
    payload: dict[str, Any] = {
        "code": getattr(error, "code", "error"),
        "message": getattr(error, "message", str(error)),
    }
    payload.update(getattr(error, "extra", {}) or {})
    return HTTPException(status_code=status, detail=payload)


def _uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{what} is not a valid id") from None


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DecideRequest(BaseModel):
    decision: str
    note: str | None = None


class AddToWeekRequest(BaseModel):
    candidate_id: str
    slot: str = "primary"


class LineupPatchRequest(BaseModel):
    # One relative move ("first", "up", "down", "slot", "remove", "rank") or a
    # whole new order. Buttons send the first; drag on desktop sends the second.
    move: dict[str, Any] | None = None
    order: list[dict[str, Any]] | None = None
    expected_revision: int | None = None


class OperationRequest(BaseModel):
    op: str
    field: str | None = None
    after: Any = None
    rationale: str | None = None
    depends_on: list[int] = Field(default_factory=list)


class ProposeRequest(BaseModel):
    target_type: str
    target_id: str
    base_version: int | None = None
    operations: list[OperationRequest]
    summary: str
    rationale: str | None = None
    origin: str = "quick_action"
    thread_id: str | None = None
    idempotency_key: str | None = None


class ApplyRequest(BaseModel):
    # Absent means "all of it". A list means partial approval.
    accept: list[int] | None = None


class RestoreRequest(BaseModel):
    to_version: int


class EditRequestBody(BaseModel):
    request: str
    scope: str = "whole"
    start_s: float | None = None
    end_s: float | None = None
    section_ref: str | None = None


# ---------------------------------------------------------------------------
# Today
# ---------------------------------------------------------------------------


@router.get("/today")
async def get_today(
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        return await today_service.build(db, ws, sessionmaker=sm)


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


@router.get("/topics")
async def get_topics(
    filter: str = Query("best"),
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        try:
            return await inbox_service.list_topics(
                db, ws, filter_key=filter, limit=limit, offset=offset
            )
        except ServiceError as error:
            raise _http(error) from error


@router.get("/topics/{candidate_id}/room")
async def get_topic_room(
    candidate_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    cid = _uuid(candidate_id, "topic")
    async with open_session(sm) as db:
        try:
            payload = await inbox_service.topic_room(db, ws, cid)
            await db.commit()
            return payload
        except ServiceError as error:
            raise _http(error) from error


@router.post("/topics/{candidate_id}/decide")
async def decide_topic(
    candidate_id: str,
    body: DecideRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """The four first decisions. None of them asks the engine for anything.

    `this_week` also puts the topic in the week, because choosing it and listing
    it are the same act from his side. Asking for the script stays separate.
    """
    cid = _uuid(candidate_id, "topic")
    async with open_session(sm) as db:
        try:
            decision = await inbox_service.decide(
                db, ws, cid, decision=body.decision, note=body.note, decided_by="ziv"
            )
            placed: dict[str, Any] | None = None
            if body.decision == "this_week":
                candidate = await inbox_service.get_candidate(db, ws, cid)
                week = await lineup_service.ensure_lineup(
                    db, ws, lineup_service.week_start_for(None)
                )
                item = await lineup_service.add_topic(
                    db, ws, week, candidate, added_by="ziv"
                )
                placed = {"slot": item.slot, "rank": item.rank, "revision": week.revision}
            await db.commit()
        except ServiceError as error:
            raise _http(error) from error

    return {
        "candidate_id": candidate_id,
        "decision": decision.decision,
        "previous_decision": decision.previous_decision,
        "note": decision.note,
        "placed": placed,
    }


# ---------------------------------------------------------------------------
# The week
# ---------------------------------------------------------------------------


@router.get("/weeks/{week}/lineup")
async def get_lineup(
    week: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    start = lineup_service.week_start_for(None if week in ("current", "this") else week)
    async with open_session(sm) as db:
        row = await lineup_service.ensure_lineup(db, ws, start)
        payload = await lineup_service.lineup_to_json(db, ws, row)
        await db.commit()
        return payload


@router.post("/weeks/{week}/lineup")
async def add_to_lineup(
    week: str,
    body: AddToWeekRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    start = lineup_service.week_start_for(None if week in ("current", "this") else week)
    cid = _uuid(body.candidate_id, "topic")
    async with open_session(sm) as db:
        try:
            candidate = await inbox_service.get_candidate(db, ws, cid)
            row = await lineup_service.ensure_lineup(db, ws, start)
            item = await lineup_service.add_topic(
                db, ws, row, candidate, slot=body.slot, added_by="ziv"
            )
            # Adding to the week is itself a decision; keep the two in step.
            await inbox_service.decide(
                db, ws, cid, decision="this_week", decided_by="ziv"
            )
            payload = await lineup_service.lineup_to_json(db, ws, row)
            await db.commit()
        except ServiceError as error:
            raise _http(error) from error
    return {"placed": {"slot": item.slot, "rank": item.rank}, "lineup": payload}


@router.patch("/weeks/{week}/lineup")
async def patch_lineup(
    week: str,
    body: LineupPatchRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    if body.move is None and body.order is None:
        raise HTTPException(status_code=400, detail="a move or an order is required")
    start = lineup_service.week_start_for(None if week in ("current", "this") else week)
    async with open_session(sm) as db:
        try:
            row = await lineup_service.ensure_lineup(db, ws, start)
            if body.move is not None:
                await lineup_service.move(
                    db,
                    ws,
                    row,
                    body.move,
                    expected_revision=body.expected_revision,
                    moved_by="ziv",
                )
            else:
                if (
                    body.expected_revision is not None
                    and body.expected_revision != row.revision
                ):
                    raise lineup_service.LineupError(
                        "conflict",
                        (
                            f"This week changed somewhere else (you had revision "
                            f"{body.expected_revision}, it is now {row.revision}). "
                            "Nothing was moved."
                        ),
                        status=409,
                        current_revision=row.revision,
                    )
                await lineup_service.apply_order(db, ws, row, body.order or [])
                row.revision += 1
                row.updated_by = "ziv"
            payload = await lineup_service.lineup_to_json(db, ws, row)
            await db.commit()
            return payload
        except ServiceError as error:
            raise _http(error) from error


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------


@router.post("/change-sets")
async def propose_change(
    body: ProposeRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Build a proposal. It changes nothing until it is applied."""
    target = _uuid(body.target_id, "target")
    thread = _uuid(body.thread_id, "thread") if body.thread_id else None
    operations = [
        change_service.OperationInput(
            op=op.op,
            field=op.field,
            after=op.after,
            rationale=op.rationale,
            depends_on=op.depends_on,
        )
        for op in body.operations
    ]
    async with open_session(sm) as db:
        try:
            change_set = await change_service.propose(
                db,
                ws,
                target_type=body.target_type,
                target_id=target,
                base_version=body.base_version,
                operations=operations,
                summary=body.summary,
                rationale=body.rationale,
                origin=body.origin,
                thread_id=thread,
                idempotency_key=body.idempotency_key,
            )
            ops = await change_service.load_operations(db, ws, change_set.id)
            payload = change_service.change_set_to_json(change_set, ops)
            await db.commit()
            return payload
        except ServiceError as error:
            raise _http(error) from error


@router.get("/change-sets/{change_set_id}")
async def get_change(
    change_set_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    csid = _uuid(change_set_id, "proposal")
    async with open_session(sm) as db:
        try:
            change_set = await change_service.get_change_set(db, ws, csid)
            ops = await change_service.load_operations(db, ws, csid)
            return change_service.change_set_to_json(change_set, ops)
        except ServiceError as error:
            raise _http(error) from error


@router.post("/change-sets/{change_set_id}/apply")
async def apply_change(
    change_set_id: str,
    body: ApplyRequest | None = None,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    csid = _uuid(change_set_id, "proposal")
    accept = body.accept if body else None
    async with open_session(sm) as db:
        try:
            result = await change_service.apply(
                db, ws, csid, accept_seqs=accept, decided_by="ziv"
            )
            await db.commit()
            return result
        except ServiceError as error:
            # A conflict commits the `superseded` marking, so the proposal does
            # not sit there looking applicable when it no longer is.
            await db.commit()
            raise _http(error) from error


@router.post("/change-sets/{change_set_id}/reject")
async def reject_change(
    change_set_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    csid = _uuid(change_set_id, "proposal")
    async with open_session(sm) as db:
        try:
            change_set = await change_service.reject(db, ws, csid, decided_by="ziv")
            ops = await change_service.load_operations(db, ws, csid)
            payload = change_service.change_set_to_json(change_set, ops)
            await db.commit()
            return payload
        except ServiceError as error:
            raise _http(error) from error


@router.post("/versions/{target_type}/{target_id}/restore")
async def restore_version(
    target_type: str,
    target_id: str,
    body: RestoreRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    tid = _uuid(target_id, "target")
    async with open_session(sm) as db:
        try:
            result = await change_service.undo(
                db,
                ws,
                target_type=target_type,
                target_id=tid,
                to_version=body.to_version,
                decided_by="ziv",
            )
            await db.commit()
            return result
        except ServiceError as error:
            raise _http(error) from error


@router.get("/topics/{candidate_id}/history")
async def get_history(
    candidate_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    cid = _uuid(candidate_id, "topic")
    async with open_session(sm) as db:
        versions = await brief_service.list_versions(db, ws, cid)
        return {
            "candidate_id": candidate_id,
            "versions": [brief_service.brief_to_json(v) for v in versions],
        }


# ---------------------------------------------------------------------------
# Script workshop
# ---------------------------------------------------------------------------


@router.get("/packets/{packet_id}/workshop")
async def get_workshop(
    packet_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Outline, full script, openings and post versions for one packet version."""
    pid = _uuid(packet_id, "script")
    async with open_session(sm) as db:
        try:
            state = await change_service.load_target(db, ws, "packet", pid)
        except ServiceError as error:
            raise _http(error) from error

        from sqlalchemy import select

        from tce.models.editorial import RecordingPacket

        result = await db.execute(
            select(RecordingPacket).where(
                RecordingPacket.workspace_id == ws, RecordingPacket.id == pid
            )
        )
        packet = result.scalar_one()
        versions = await list_packets(db, ws, packet.candidate_id)

    hooks = list(packet.hook_options or [])
    # Three at a time. Nine appended options is not a choice, it is a list to
    # scroll, and they were only ever added, never re-ranked.
    return {
        "packet_id": str(packet.id),
        "candidate_id": str(packet.candidate_id),
        "version": packet.version,
        "status": packet.status,
        "frozen_reason": state.frozen_reason,
        "outline": list(packet.bullets or []),
        "script": list(packet.script_phrases or []),
        "beats": list(packet.beats or []) if packet.beats else [],
        "openings": {
            "shown": hooks[:3],
            "selected_hook_id": packet.selected_hook_id,
            "more_available": max(0, len(hooks) - 3),
        },
        "posts": {
            "facebook": packet.facebook_post,
            "linkedin": packet.linkedin_post,
        },
        "public_safety": packet.public_safety or {},
        "versions": [
            {"packet_id": str(v.id), "version": v.version, "status": v.status}
            for v in versions
        ],
    }


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------


@production_router.get("/library")
async def get_library(
    filter: str = Query("all"),
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        try:
            return await library_service.list_library(db, ws, filter_key=filter)
        except ServiceError as error:
            raise _http(error) from error


@production_router.post("/recordings/{upload_id}/edit-requests")
async def create_edit_request(
    upload_id: str,
    body: EditRequestBody,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    uid = _uuid(upload_id, "recording")
    async with open_session(sm) as db:
        try:
            row = await library_service.create_edit_request(
                db,
                ws,
                uid,
                request=body.request,
                scope=body.scope,
                start_s=body.start_s,
                end_s=body.end_s,
                section_ref=body.section_ref,
                created_by="ziv",
            )
            payload = library_service.edit_request_to_json(row)
            await db.commit()
            return payload
        except ServiceError as error:
            raise _http(error) from error


@production_router.get("/recordings/{upload_id}/edit-requests")
async def list_edit_requests(
    upload_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    uid = _uuid(upload_id, "recording")
    async with open_session(sm) as db:
        rows = await library_service.list_edit_requests(db, ws, uid)
        return {
            "upload_id": upload_id,
            "requests": [library_service.edit_request_to_json(r) for r in rows],
        }
