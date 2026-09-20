"""/editorial routes: candidates, feedback, recording packets, effective strategy.

Every route depends on `require_private_workspace` and filters on the resolved
workspace explicitly. Selection and packet writing run as background tasks with
their own sessions; their live state is exposed via status routes (with llm job ids
for the dashboard activity panel). Nothing here publishes anything.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from tce.api.private_access import require_private_workspace
from tce.editorial import status as job_status
from tce.editorial.common import (
    CANDIDATE_STATUSES,
    ORIGIN_SELECTOR_REJECTED,
    candidate_to_json,
    feedback_to_json,
    open_session,
    packet_to_json,
    week_bounds,
)
from tce.editorial.feedback import (
    CandidateNotFoundError,
    FeedbackError,
    list_feedback,
    record_feedback,
    summarize_feedback,
)
from tce.editorial.packets import (
    PacketValidationError,
    build_packet,
    choose_hook,
    list_packets,
    more_hook_options,
)
from tce.editorial.selector import MAX_CANDIDATES_CAP, select_candidates
from tce.models.editorial import EditorialFeedback, RecordingPacket, TopicCandidate
from tce.services.strategy_loader import load_effective_strategy

logger = structlog.get_logger()

router = APIRouter(prefix="/editorial", tags=["editorial"])


def get_editorial_sessionmaker() -> Any:
    """Sessionmaker for editorial work (overridden in tests)."""
    from tce.db.session import async_session

    return async_session


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SelectRequest(BaseModel):
    week_start: date
    max_candidates: int = Field(default=6, ge=0, le=MAX_CANDIDATES_CAP)


class CandidatePatch(BaseModel):
    status: str | None = None
    editor_notes: str | None = None


class FeedbackRequest(BaseModel):
    kind: str
    rating: str | None = None
    gate: str | None = None
    note: str | None = None
    created_by: str | None = None


class HookChoiceRequest(BaseModel):
    hook_id: str = Field(min_length=1, max_length=80)


def _parse_uuid(value: str, what: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"{what} not found") from exc


async def _get_candidate(db, ws: uuid.UUID, candidate_id: str) -> TopicCandidate:
    cand = (
        await db.execute(
            select(TopicCandidate).where(
                TopicCandidate.id == _parse_uuid(candidate_id, "candidate"),
                TopicCandidate.workspace_id == ws,
            )
        )
    ).scalar_one_or_none()
    if cand is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return cand


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


async def _run_selection(
    sm: Any, ws: uuid.UUID, week_start: date, max_candidates: int, run_id: uuid.UUID
) -> None:
    """Run or resume one selection. A run_id whose jobs already exist is resumed."""
    key = week_start.isoformat()

    def on_activity(msg: str, **kw: Any) -> None:
        job_status.update(ws, "select", key, current_activity=msg, job_id=kw.get("job_id"))

    try:
        result = await select_candidates(
            sm,
            ws,
            week_start,
            max_candidates=max_candidates,
            selection_run_id=run_id,
            on_activity=on_activity,
        )
    except Exception as exc:  # surfaced in status; never silently "done"
        logger.exception("editorial.select_failed", workspace_id=str(ws), week_start=key)
        job_status.update(
            ws,
            "select",
            key,
            state="failed",
            current_activity="Selection failed",
            detail=type(exc).__name__,
        )
        return
    state = (
        "done"
        if result.status in ("complete", "no_evidence")
        else ("waiting" if result.status == "waiting_capacity" else "failed")
    )
    job_status.update(
        ws,
        "select",
        key,
        state=state,
        job_id=result.job_id,
        current_activity=(
            f"Selection {result.status}: {len(result.candidates)} candidates, "
            f"{len(result.rejected)} rejections"
        ),
        detail=result.detail,
        result=result.to_dict() | {"candidates": [c["id"] for c in result.candidates]},
    )


@router.post("/select")
async def start_selection(
    body: SelectRequest,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    key = body.week_start.isoformat()
    if job_status.is_running(ws, "select", key):
        raise HTTPException(status_code=409, detail="selection already running for this week")
    async with open_session(sm) as db:
        previous = await job_status.latest_selection_run(db, ws, key)
    # An interrupted run (restart, timeout, capacity wait, failed job that may be re-queued)
    # is resumed under its own run id, so its jobs are reused rather than duplicated.
    resume = bool(
        previous
        and previous["resumable"]
        and previous["max_candidates"] in (None, body.max_candidates)
    )
    run_id = uuid.UUID(previous["selection_run_id"]) if resume and previous else uuid.uuid4()
    job_status.start(
        ws,
        "select",
        key,
        "Resuming interrupted selection" if resume else "Queued selection",
        selection_run_id=str(run_id),
        week_start=key,
        resumed=resume,
    )
    background.add_task(_run_selection, sm, ws, body.week_start, body.max_candidates, run_id)
    return {
        "selection_run_id": str(run_id),
        "resumed": resume,
        "status": "running",
        "candidates": [],
        "rejected": [],
        "status_url": f"/api/v1/editorial/select-status?week_start={key}",
    }


@router.get("/select-status")
async def selection_status(
    week_start: date = Query(...),
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    key = week_start.isoformat()
    start, _ = week_bounds(week_start)
    async with open_session(sm) as db:
        rows = (
            await db.execute(
                select(TopicCandidate.status, TopicCandidate.origin).where(
                    TopicCandidate.workspace_id == ws, TopicCandidate.week_start == start
                )
            )
        ).all()
        durable = await job_status.latest_selection_run(db, ws, key)
    counts: dict[str, int] = {}
    for st, origin in rows:
        label = "selector_rejected" if origin == ORIGIN_SELECTOR_REJECTED else st
        counts[label] = counts.get(label, 0) + 1
    entry = job_status.get(ws, "select", key)
    return {
        "week_start": key,
        "job": _pick_status(entry, durable, "No selection on record"),
        "durable": durable,
        "persisted_counts": counts,
    }


def _pick_status(
    entry: dict[str, Any] | None, durable: dict[str, Any] | None, idle: str
) -> dict[str, Any]:
    """This process's live entry while it runs. Otherwise the database decides: a request
    that ended (timeout, restart) says nothing about whether its jobs later finished, so
    the durable view wins, carrying the ended request's entry as `last_request` when it
    was about the same job."""
    if entry and entry["state"] == "running":
        return entry
    if durable:
        same = bool(durable["job_ids"]) and durable["job_ids"][0] in (entry or {}).get(
            "job_ids", []
        )
        return durable | {"last_request": entry if same else None}
    if entry:
        return entry
    return {"state": "idle", "current_activity": idle, "job_ids": []}


@router.get("/jobs")
async def editorial_jobs(
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        in_flight = await job_status.unattended_jobs(db, ws)
    return {
        "jobs": job_status.list_for_workspace(ws),
        # queued/leased/waiting editorial jobs on record, whether or not this process
        # is awaiting them
        "in_flight": in_flight,
    }


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


@router.get("/candidates")
async def list_candidates(
    week_start: date | None = Query(None),
    status: str | None = Query(None),
    include_rejections: bool = Query(False),
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    q = select(TopicCandidate).where(TopicCandidate.workspace_id == ws)
    if week_start is not None:
        q = q.where(TopicCandidate.week_start == week_bounds(week_start)[0])
    if status:
        if status not in CANDIDATE_STATUSES:
            raise HTTPException(status_code=400, detail="unknown status")
        q = q.where(TopicCandidate.status == status)
    else:
        q = q.where(TopicCandidate.status != "withdrawn")
    if not include_rejections:
        q = q.where(TopicCandidate.origin != ORIGIN_SELECTOR_REJECTED)
    async with open_session(sm) as db:
        cands = (await db.execute(q)).scalars().all()
        ids = [c.id for c in cands]
        fb_by: dict[uuid.UUID, list[EditorialFeedback]] = {}
        if ids:
            for fb in (
                await db.execute(
                    select(EditorialFeedback)
                    .where(
                        EditorialFeedback.workspace_id == ws,
                        EditorialFeedback.candidate_id.in_(ids),
                    )
                    .order_by(EditorialFeedback.preference_version)
                )
            ).scalars():
                fb_by.setdefault(fb.candidate_id, []).append(fb)
    cands = sorted(
        cands,
        key=lambda c: (c.week_start, c.rank if c.rank is not None else 10_000, str(c.created_at)),
    )
    return {"candidates": [candidate_to_json(c, fb_by.get(c.id)) for c in cands]}


@router.get("/candidates/{candidate_id}")
async def get_candidate(
    candidate_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        cand = await _get_candidate(db, ws, candidate_id)
        fb = await list_feedback(db, ws, cand.id)
    return candidate_to_json(cand, fb)


@router.patch("/candidates/{candidate_id}")
async def patch_candidate(
    candidate_id: str,
    body: CandidatePatch,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    if body.status is not None and body.status not in CANDIDATE_STATUSES:
        raise HTTPException(status_code=400, detail="unknown status")
    async with open_session(sm) as db:
        cand = await _get_candidate(db, ws, candidate_id)
        if body.status is not None:
            cand.status = body.status
        if body.editor_notes is not None:
            cand.editor_notes = body.editor_notes
        await db.commit()
        fb = await list_feedback(db, ws, cand.id)
    return candidate_to_json(cand, fb)


@router.post("/candidates/{candidate_id}/feedback")
async def post_feedback(
    candidate_id: str,
    body: FeedbackRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    cid = _parse_uuid(candidate_id, "candidate")
    async with open_session(sm) as db:
        try:
            row = await record_feedback(
                db,
                ws,
                cid,
                kind=body.kind,
                rating=body.rating,
                gate=body.gate,
                note=body.note,
                created_by=body.created_by,
            )
        except CandidateNotFoundError as exc:
            raise HTTPException(status_code=404, detail="candidate not found") from exc
        except FeedbackError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return feedback_to_json(row)


@router.get("/candidates/{candidate_id}/feedback")
async def get_feedback(
    candidate_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        cand = await _get_candidate(db, ws, candidate_id)
        rows = await list_feedback(db, ws, cand.id)
    return {"feedback": [feedback_to_json(f) for f in rows]}


@router.get("/feedback-summary")
async def feedback_summary(
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        summary = await summarize_feedback(db, ws)
    return summary.to_dict() | {"prompt_text": summary.to_prompt_text()}


# ---------------------------------------------------------------------------
# Packets
# ---------------------------------------------------------------------------


async def _run_packet(
    sm: Any, ws: uuid.UUID, candidate_id: uuid.UUID, resume_job_id: uuid.UUID | None = None
) -> None:
    key = str(candidate_id)

    def on_activity(msg: str, **kw: Any) -> None:
        job_status.update(ws, "packet", key, current_activity=msg, job_id=kw.get("job_id"))

    try:
        outcome = await build_packet(
            sm, ws, candidate_id, on_activity=on_activity, resume_job_id=resume_job_id
        )
    except Exception as exc:
        logger.exception("editorial.packet_failed", workspace_id=str(ws), candidate_id=key)
        job_status.update(
            ws,
            "packet",
            key,
            state="failed",
            current_activity="Packet failed",
            detail=type(exc).__name__,
        )
        return
    state = {"ready": "done", "issues": "done", "waiting_capacity": "waiting"}.get(
        outcome.status, "failed"
    )
    job_status.update(
        ws,
        "packet",
        key,
        state=state,
        job_id=outcome.job_id,
        current_activity=f"Packet {outcome.status}",
        detail=outcome.detail,
        result={
            "status": outcome.status,
            "packet_id": outcome.packet["id"] if outcome.packet else None,
            "errors": outcome.errors,
            "retry_at": outcome.retry_at.isoformat() if outcome.retry_at else None,
        },
    )


@router.post("/candidates/{candidate_id}/packet")
async def start_packet(
    candidate_id: str,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        cand = await _get_candidate(db, ws, candidate_id)
        if cand.status in ("rejected", "withdrawn"):
            raise HTTPException(status_code=409, detail=f"candidate is {cand.status}")
        cid = cand.id
        if job_status.is_running(ws, "packet", str(cid)):
            raise HTTPException(status_code=409, detail="packet already being written")
        previous = await job_status.latest_packet_job(db, ws, cid)
    # An interrupted packet job (restart, timeout, capacity wait, written but unsaved) is
    # resumed; a finished or failed one is regenerated with a fresh job as before.
    resume_job_id = (
        uuid.UUID(previous["job_ids"][0]) if previous and previous["resumable"] else None
    )
    job_status.start(
        ws,
        "packet",
        str(cid),
        "Resuming interrupted packet" if resume_job_id else "Queued packet",
        candidate_id=str(cid),
        resumed_job_id=str(resume_job_id) if resume_job_id else None,
    )
    background.add_task(_run_packet, sm, ws, cid, resume_job_id)
    return {
        "status": "running",
        "resumed": resume_job_id is not None,
        "candidate_id": str(cid),
        "status_url": f"/api/v1/editorial/candidates/{cid}/packet-status",
    }


@router.get("/candidates/{candidate_id}/packet-status")
async def packet_status(
    candidate_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        cand = await _get_candidate(db, ws, candidate_id)
        durable = await job_status.latest_packet_job(db, ws, cand.id)
    entry = job_status.get(ws, "packet", str(cand.id))
    return {
        "candidate_id": str(cand.id),
        "job": _pick_status(entry, durable, "No packet job on record"),
        "durable": durable,
    }


@router.get("/candidates/{candidate_id}/packets")
async def get_candidate_packets(
    candidate_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        cand = await _get_candidate(db, ws, candidate_id)
        rows = await list_packets(db, ws, cand.id)
    return {"packets": [packet_to_json(p) for p in rows]}


@router.get("/packets/{packet_id}")
async def get_packet(
    packet_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        row = (
            await db.execute(
                select(RecordingPacket).where(
                    RecordingPacket.id == _parse_uuid(packet_id, "packet"),
                    RecordingPacket.workspace_id == ws,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="packet not found")
    return packet_to_json(row)


@router.post("/packets/{packet_id}/choose-hook")
async def choose_packet_hook(
    packet_id: str,
    body: HookChoiceRequest,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        try:
            packet = await choose_hook(db, ws, packet_id, body.hook_id)
        except PacketValidationError as exc:
            code = 404 if str(exc) in {"packet not found", "hook option not found"} else 409
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        await db.commit()
    return packet_to_json(packet)


@router.post("/packets/{packet_id}/more-hooks")
async def more_packet_hooks(
    packet_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """More openings for the same script, as a new immutable version.

    One subscription job. The script, the bullets and the evidence do not change
    and the opening in use stays in use, so this is safe to ask for while
    deciding - but not while a take set is recording against the version.
    """
    outcome = await more_hook_options(sm, ws, packet_id)
    if outcome.status == "invalid":
        code = 404 if outcome.detail == "packet not found" else 409
        raise HTTPException(status_code=code, detail=outcome.detail)
    if outcome.status in {"waiting_capacity", "waiting_worker"}:
        raise HTTPException(status_code=503, detail=outcome.detail)
    if outcome.packet is None:
        raise HTTPException(status_code=502, detail=outcome.detail or "no opening came back")
    return {"packet": outcome.packet, "detail": outcome.detail, "dropped": outcome.errors}


@router.post("/candidates/{candidate_id}/archive")
async def archive_candidate(
    candidate_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Put an idea away without judging it.

    Rejecting teaches the engine what Ziv does not want; archiving says only
    "not this one, not now". Both keep it out of the recording queue and out of
    future selection, and an archived idea can be brought back by approving it.
    """
    async with open_session(sm) as db:
        cand = await _get_candidate(db, ws, candidate_id)
        if cand.status == "recorded":
            raise HTTPException(status_code=409, detail="that idea has already been recorded")
        cand.status = "withdrawn"
        await db.commit()
        fb = await list_feedback(db, ws, cand.id)
    return candidate_to_json(cand, fb)


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


@router.get("/strategy")
async def effective_strategy(
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    from tce.editorial import packets, selector

    async with open_session(sm) as db:
        eff = await load_effective_strategy(db, ws)
    return {
        "workspace_id": str(ws),
        "text": eff.text,
        "sources": eff.sources
        + [
            {
                "kind": "prompt_version",
                "agent_name": selector.AGENT_NAME,
                "version": selector.PROMPT_VERSION,
                "ref": "code",
            },
            {
                "kind": "prompt_version",
                "agent_name": packets.AGENT_NAME,
                "version": packets.PROMPT_VERSION,
                "ref": "code",
            },
        ],
    }
