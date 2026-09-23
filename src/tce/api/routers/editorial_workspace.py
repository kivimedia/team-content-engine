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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from tce.api.private_access import require_private_workspace
from tce.api.routers.editorial import get_editorial_sessionmaker
from tce.editorial import briefs as brief_service
from tce.editorial import changes as change_service
from tce.editorial import conversation, notify, voice_agent
from tce.editorial import inbox as inbox_service
from tce.editorial import library as library_service
from tce.editorial import lineup as lineup_service
from tce.editorial import today as today_service
from tce.editorial.common import open_session
from tce.editorial.packets import list_packets
from tce.models.editorial_workspace import ACTORS

logger = structlog.get_logger()

router = APIRouter(prefix="/editorial", tags=["editorial-workspace"])
production_router = APIRouter(prefix="/production", tags=["editorial-workspace"])


ServiceError = (
    change_service.ChangeError,
    notify.NotifyError,
    conversation.ConversationError,
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
    # "voice" when the voice agent decided it, so the workspace can say so.
    by: str = "ziv"


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


class EditBlockRequest(BaseModel):
    field: str
    value: str
    base_version: int | None = None


class ThreadRequest(BaseModel):
    context_type: str
    # Absent for the editorial room, which is one thread per workspace.
    context_id: str | None = None
    label: str | None = None


class MessageRequest(BaseModel):
    text: str
    mode: str = "discuss"


class SubscribeRequest(BaseModel):
    endpoint: str
    # The browser's own keys, from PushSubscription.toJSON().
    p256dh: str
    auth: str
    user_agent: str | None = None


class UnsubscribeRequest(BaseModel):
    endpoint: str


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
    it are the same act from his side, and every other decision takes it off the
    list again (remembering its place). Asking for the script stays separate.

    `undecided` takes a decision back, keeping the note. `previous_decision` is
    the decision THIS call replaced ("undecided" when there was none).

    A write that changed something (the decision, or the week with it) is written
    down under its own `change_id`, which the voice call undoes by; a write that
    changed nothing answers `change_id` null, so there is nothing to undo that
    does nothing. The topic is named by its id; a missing or unknown one is
    refused in words the voice agent can say.
    """
    if body.by not in ACTORS:
        raise HTTPException(status_code=400, detail=f"unknown actor {body.by}")
    async with open_session(sm) as db:
        try:
            candidate = await voice_agent.topic_by_id(db, ws, candidate_id)
            cid = candidate.id
            existing = await inbox_service.get_decision(db, ws, cid)
            before = existing.decision if existing is not None else None
            if body.decision == voice_agent.UNDECIDED:
                decision = await voice_agent.clear_decision(db, ws, cid, by=body.by)
            else:
                if body.by == "voice" and body.decision == "away" and before == "away":
                    # Undoing it would bring back an idea that was away before
                    # the call, so a put-away that changes nothing is not a write.
                    raise inbox_service.InboxError(
                        "already",
                        f'"{candidate.title}" is already put away. Nothing was changed.',
                        status=409,
                    )
                decision = await inbox_service.decide(
                    db, ws, cid, decision=body.decision, note=body.note, decided_by=body.by
                )
            week = await lineup_service.follow_decision(db, ws, candidate, decision, by=body.by)
            after = decision.decision if decision is not None else None
            change = await voice_agent.record_decision_change(
                db, ws, cid, before=before, after=after, by=body.by, week=week
            )
            await db.commit()
        except (*ServiceError, voice_agent.VoiceError) as error:
            raise _http(error) from error

    return {
        "candidate_id": str(cid),
        # This write's own id, what the voice call's undo takes back; None when
        # the write changed nothing.
        "change_id": str(change.id) if change is not None else None,
        "short_id": str(change.id)[:8] if change is not None else None,
        "decision": after,
        "previous_decision": before or voice_agent.UNDECIDED,
        "changed": before != after,
        "note": decision.note if decision is not None else None,
        "placed": week["placed"],
        "added_to_week": week["added"],
        "removed_from_week": week["removed"],
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
            listed = {i.candidate_id for i in await lineup_service.list_items(db, ws, row.id)}
            existing = await inbox_service.get_decision(db, ws, cid)
            item = await lineup_service.add_topic(
                db, ws, row, candidate, slot=body.slot, added_by="ziv"
            )
            # Adding to the week is itself a decision; keep the two in step, and
            # in the decision history, so a voice undo of an earlier decision
            # knows he chose it himself since.
            await inbox_service.decide(
                db, ws, cid, decision="this_week", decided_by="ziv"
            )
            await voice_agent.record_decision_change(
                db,
                ws,
                cid,
                before=existing.decision if existing is not None else None,
                after="this_week",
                by="ziv",
                week={
                    "added": cid not in listed,
                    "placed": {"slot": item.slot, "rank": item.rank},
                    "week_start": row.week_start.date().isoformat(),
                    "lineup_id": str(row.id),
                },
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


@router.post("/topics/{candidate_id}/brief")
async def edit_brief_block(
    candidate_id: str,
    body: EditBlockRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Save one block he typed himself, in one call.

    A diff sheet exists so an ASSISTANT cannot change his words without showing
    him. Making him review a sentence he just typed is ceremony, not safety - he
    is looking at it. So this proposes and applies in one step, which still
    writes a new immutable version and still leaves the old one restorable from
    History. Nothing about the audit trail is weaker; only the extra tap is gone.
    """
    cid = _uuid(candidate_id, "topic")
    async with open_session(sm) as db:
        try:
            change_set = await change_service.propose(
                db,
                ws,
                target_type="candidate_brief",
                target_id=cid,
                base_version=body.base_version,
                operations=[
                    change_service.OperationInput(
                        op="set_field", field=body.field, after=body.value
                    )
                ],
                summary=f"Edit {body.field.replace('_', ' ')}",
                origin="quick_action",
            )
            if change_set.state == "invalid":
                issues = (change_set.validation or {}).get("issues") or []
                message = issues[0]["message"] if issues else "that cannot be saved"
                await db.commit()
                raise HTTPException(
                    status_code=400, detail={"code": "invalid", "message": message}
                )
            result = await change_service.apply(db, ws, change_set.id, decided_by="ziv")
            payload = await inbox_service.topic_room(db, ws, cid)
            await db.commit()
        except ServiceError as error:
            await db.commit()
            raise _http(error) from error
    return {"saved": True, "version": result["version"], "room": payload}


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
# Conversation
# ---------------------------------------------------------------------------


@router.post("/threads")
async def open_thread(
    body: ThreadRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Get or create the one thread for an object. The room uses the workspace id."""
    if body.context_type not in ("topic", "packet", "week", "recording", "room"):
        raise HTTPException(status_code=400, detail="unknown context type")
    # Only the room and the week are workspace-wide. Letting the others fall back
    # to the workspace id builds a thread pointing at an object that does not
    # exist, and the failure only shows up a minute later when the turn runs.
    if body.context_type in ("topic", "packet", "recording") and not body.context_id:
        raise HTTPException(
            status_code=400,
            detail=f"a {body.context_type} conversation needs a {body.context_type} id",
        )
    context_id = _uuid(body.context_id, "context") if body.context_id else ws
    async with open_session(sm) as db:
        try:
            thread = await conversation.ensure_thread(
                db, ws, context_type=body.context_type, context_id=context_id,
                label=body.label,
            )
            messages = await conversation.list_messages(db, ws, thread.id)
            payload = conversation.thread_to_json(thread, messages)
            await db.commit()
            return payload
        except ServiceError as error:
            raise _http(error) from error


@router.get("/threads/{thread_id}")
async def read_thread(
    thread_id: str,
    after: int = Query(0, ge=0),
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    tid = _uuid(thread_id, "conversation")
    async with open_session(sm) as db:
        try:
            thread = await conversation.get_thread(db, ws, tid)
            messages = await conversation.list_messages(db, ws, tid, after=after)
            return conversation.thread_to_json(thread, messages)
        except ServiceError as error:
            raise _http(error) from error


@router.post("/threads/{thread_id}/messages")
async def post_message(
    thread_id: str,
    body: MessageRequest,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Store his turn and queue the reply.

    Returns immediately with a `queued` assistant message. A turn runs on the
    desktop subscription worker at about one job a minute, so awaiting it inside
    the request would be a minute-long POST that a phone on mobile data drops.
    """
    tid = _uuid(thread_id, "conversation")
    async with open_session(sm) as db:
        try:
            thread = await conversation.get_thread(db, ws, tid)
            editor, assistant = await conversation.post_message(
                db, ws, thread, text=body.text, mode=body.mode
            )
            payload = {
                "thread_id": str(thread.id),
                "messages": [
                    conversation.message_to_json(editor),
                    conversation.message_to_json(assistant),
                ],
                "pending": True,
            }
            message_id = assistant.id
            await db.commit()
        except ServiceError as error:
            raise _http(error) from error

    background.add_task(conversation.run_turn, sm, ws, tid, message_id)
    return payload


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@router.get("/notifications/config")
async def notifications_config(
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """What the page needs to decide whether to offer notifications at all.

    Never returns an endpoint or its keys: those are a capability to push to his
    phone, and a read endpoint is not where they belong.
    """
    async with open_session(sm) as db:
        subscriptions = await notify.active_subscriptions(db, ws)
    return {
        "available": notify.push_available(),
        "public_key": notify.vapid_public_key(),
        "subscribed": len(subscriptions),
        "reason": (
            "" if notify.push_available()
            else "Push is not configured on this server yet."
        ),
    }


@router.post("/notifications/subscribe")
async def notifications_subscribe(
    body: SubscribeRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        try:
            await notify.subscribe(
                db, ws, endpoint=body.endpoint, p256dh=body.p256dh, auth=body.auth,
                user_agent=body.user_agent,
            )
            await db.commit()
        except ServiceError as error:
            raise _http(error) from error
    return {"subscribed": True}


@router.post("/notifications/unsubscribe")
async def notifications_unsubscribe(
    body: UnsubscribeRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        removed = await notify.unsubscribe(db, ws, endpoint=body.endpoint)
        await db.commit()
    return {"removed": removed}


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
