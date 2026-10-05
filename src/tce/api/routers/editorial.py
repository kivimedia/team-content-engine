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
from sqlalchemy import func, select

from tce.api.private_access import owner_action_workspace, require_private_workspace
from tce.editorial import more_ideas as more_ideas_service
from tce.editorial import status as job_status
from tce.editorial.common import (
    CANDIDATE_STATUSES,
    ORIGIN_AGENT_TALK,
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
    voice_pass,
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


class StartPacketRequest(BaseModel):
    # A new script replaces the current one, and every edit made to it, when it
    # finishes. False (the voice agent) refuses when a script exists, so he hears
    # what would be replaced first; None (the workspace button, which says
    # "Regenerate") keeps the old behaviour.
    replace: bool | None = None
    by: str | None = None


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
    # A filmed talk with an agent names a library video; it is not one of the week's ideas.
    q = q.where(TopicCandidate.origin != ORIGIN_AGENT_TALK)
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
        # Whether a script has already been written for an idea is the
        # difference between "ask for one" and "put the one you have in the
        # queue", and the caller cannot see it from the candidate alone.
        packets_by: dict[uuid.UUID, int] = {}
        if ids:
            rows = await db.execute(
                select(RecordingPacket.candidate_id, func.count(RecordingPacket.id))
                .where(
                    RecordingPacket.workspace_id == ws,
                    RecordingPacket.candidate_id.in_(ids),
                )
                .group_by(RecordingPacket.candidate_id)
            )
            packets_by = {cid: int(count) for cid, count in rows}
    cands = sorted(
        cands,
        key=lambda c: (c.week_start, c.rank if c.rank is not None else 10_000, str(c.created_at)),
    )
    return {
        "candidates": [
            {**candidate_to_json(c, fb_by.get(c.id)), "packet_count": packets_by.get(c.id, 0)}
            for c in cands
        ]
    }


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
    sm: Any,
    ws: uuid.UUID,
    candidate_id: uuid.UUID,
    resume_job_id: uuid.UUID | None = None,
    *,
    rewrite_id: uuid.UUID | None = None,
    by: str | None = None,
) -> None:
    key = str(candidate_id)

    def on_activity(msg: str, **kw: Any) -> None:
        job_status.update(ws, "packet", key, current_activity=msg, job_id=kw.get("job_id"))

    on_saved = None
    if rewrite_id is not None:
        from tce.editorial import voice_agent

        async def on_saved(
            session: Any, cand: Any, replaced: Any, packet: Any, job_id: Any
        ) -> None:
            # Written down in the transaction that saves the new script, with the
            # script it really replaced (edits made while it was written included).
            await voice_agent.record_rewrite(
                session,
                ws,
                rewrite_id=rewrite_id,
                by=by or "voice",
                candidate=cand,
                replaced=replaced,
                packet=packet,
                job_id=job_id,
            )

    try:
        outcome = await build_packet(
            sm,
            ws,
            candidate_id,
            on_activity=on_activity,
            resume_job_id=resume_job_id,
            on_saved=on_saved,
        )
    except Exception as exc:
        logger.exception("editorial.packet_failed", workspace_id=str(ws), candidate_id=key)
        # A save that raises (a lock, a dropped connection) is no verdict on a
        # written script. It used to mark it unsaveable for good: the tick
        # stopped trying and his own ask paid for a new model call (review,
        # 28-Sep). It stays resumable and is counted, so the next tick tries
        # again and something that raises every time stops.
        faults: dict[str, Any] = {}
        if resume_job_id is not None:
            entry = job_status.get(ws, "packet", key) or {}
            faults = {
                "resume_faults": int(entry.get("resume_faults") or 0) + 1,
                "resume_fault": type(exc).__name__,
            }
        job_status.update(
            ws,
            "packet",
            key,
            state="failed",
            current_activity="Packet failed",
            detail=type(exc).__name__,
            **faults,
        )
        return
    # A request that stops waiting (the Claude limit, or its wait running out)
    # leaves a job that finishes later, and the scheduler tick saves it then. It
    # is waiting, not failed, and it says so in his words rather than
    # "waiting_capacity: retry at ...Z" (28-Sep-2026).
    state = {
        "ready": "done",
        "issues": "done",
        "waiting_capacity": "waiting",
        "timeout": "waiting",
    }.get(outcome.status, "failed")
    activity, detail = f"Packet {outcome.status}", outcome.detail
    if state == "waiting":
        activity, detail = job_status.packet_wait_words(outcome.status, outcome.retry_at)
    # A save the job's own answer refused (a stricter check at save time,
    # evidence from outside the idea, the idea put away) is refused the same
    # way every time, so it is marked for the tick and for what he is told.
    refused: dict[str, Any] = {}
    if state == "failed" and resume_job_id is not None:
        refused = {"resume_refused": outcome.detail or activity}
    job_status.update(
        ws,
        "packet",
        key,
        state=state,
        job_id=outcome.job_id,
        current_activity=activity,
        detail=detail,
        **refused,
        result={
            "status": outcome.status,
            "packet_id": outcome.packet["id"] if outcome.packet else None,
            "errors": outcome.errors,
            "retry_at": outcome.retry_at.isoformat() if outcome.retry_at else None,
            # The version it replaced when it was saved, which is not always the
            # one that was current when it was asked for.
            "replaced_version": outcome.replaced_version,
        },
    )


@router.post("/candidates/{candidate_id}/packet")
async def start_packet(
    candidate_id: str,
    background: BackgroundTasks,
    body: StartPacketRequest | None = None,
    ws: uuid.UUID = Depends(owner_action_workspace("Writing a script")),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    from tce.editorial.voice_agent import current_packet

    async with open_session(sm) as db:
        cand = await _get_candidate(db, ws, candidate_id)
        if cand.status in ("rejected", "withdrawn"):
            raise HTTPException(status_code=409, detail=f"candidate is {cand.status}")
        cid = cand.id
        if job_status.is_running(ws, "packet", str(cid)):
            raise HTTPException(status_code=409, detail="packet already being written")
        existing = await current_packet(db, ws, cid)
        if existing is not None and body is not None and body.replace is False:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "has_script",
                    "message": (
                        f'"{cand.title}" already has a script (version {existing.version}, '
                        f"{existing.status}). A new one replaces it when it is written, "
                        "together with any edits made to it meanwhile. Nothing was started."
                    ),
                    "version": existing.version,
                    "status": existing.status,
                    "packet_id": str(existing.id),
                    "title": cand.title,
                },
            )
        replaces_version = existing.version if existing is not None else None
        # A rewrite asked for by someone (the voice agent says who) is recorded
        # when it is saved, under this id, so it is listed and can be undone.
        rewrite_id = uuid.uuid4() if existing is not None and body is not None and body.by else None
        rewrite_by = body.by if rewrite_id is not None and body is not None else None
        previous = await job_status.latest_packet_job(db, ws, cid)
        # An interrupted packet job (restart, timeout, capacity wait, written but
        # unsaved) is resumed; a finished or failed one is regenerated with a fresh
        # job as before.
        resume_job_id = (
            uuid.UUID(previous["job_ids"][0]) if previous and previous["resumable"] else None
        )
        # The rewrite a resume finishes is still the one that was asked for. Its id
        # and who asked ride on the job, so a resume that says nothing (the
        # workspace's button) still records it under the id the voice call holds,
        # and the call's undo reaches it. That holds for a job resumed from where
        # it stopped and for one left waiting for the PC worker, which the button
        # starts again. A restart forgets the job; then the undo says the script
        # moved on and offers the version instead.
        carried = await _unrecorded_rewrite(
            db, ws, cid, existing, resuming=resume_job_id is not None
        )
        if carried is not None:
            rewrite_id = carried[0]
            rewrite_by = rewrite_by or carried[1] or "voice"
        park = await job_status.capacity_park(db)
    job_status.start(
        ws,
        "packet",
        str(cid),
        "Resuming interrupted packet" if resume_job_id else "Queued packet",
        candidate_id=str(cid),
        resumed_job_id=str(resume_job_id) if resume_job_id else None,
        rewrite_id=str(rewrite_id) if rewrite_id else None,
        rewrite_by=rewrite_by,
    )
    if rewrite_id is not None:
        background.add_task(
            _run_packet, sm, ws, cid, resume_job_id, rewrite_id=rewrite_id, by=rewrite_by
        )
    else:
        background.add_task(_run_packet, sm, ws, cid, resume_job_id)
    return {
        "status": "running",
        "resumed": resume_job_id is not None,
        # The version current now. The one it really replaces is the one current
        # when it is saved; it stays readable, and undo-rewrite puts it back.
        "replaces_version": replaces_version,
        "rewrite_id": str(rewrite_id) if rewrite_id else None,
        "candidate_id": str(cid),
        "status_url": f"/api/v1/editorial/candidates/{cid}/packet-status",
        # What the button tells him. "A few minutes" was the answer even while
        # the worker was parked for two days on his Claude limit (28-Sep).
        "said": (
            "Asked. " + job_status.capacity_words(park)
            if park is not None
            else "Asked. The script is written on your PC worker; it takes a few minutes."
        ),
    }


async def _unrecorded_rewrite(
    db: Any, ws: uuid.UUID, cid: uuid.UUID, existing: Any, *, resuming: bool
) -> tuple[uuid.UUID, str | None] | None:
    """The rewrite an earlier ask in this process started and nothing recorded yet.

    Its id and who asked ride on the in-process entry, so whoever finishes the
    job (his button, or the scheduler tick) records it under the id the voice
    call holds.
    """
    carried = job_status.get(ws, "packet", str(cid))
    if not (
        carried
        and carried.get("rewrite_id")
        and existing is not None
        and (resuming or carried.get("state") == "waiting")
    ):
        return None
    earlier = uuid.UUID(carried["rewrite_id"])
    from tce.editorial import voice_agent

    if await voice_agent.rewrite_record(db, ws, earlier) is not None:
        return None
    return earlier, carried.get("rewrite_by")


async def redrive_packet_requests(sm: Any, ws: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    """Finish script requests whose own request ended before their job did.

    Called by the scheduler tick every five minutes. 28-Sep-2026: a script asked
    for while the worker was parked on his Claude limit was written when the
    limit reset, and then sat unsaved until someone asked again. A job that
    succeeded is resumed here exactly as his "Prepare the script" would resume
    it: the stored request is replayed, finds the finished job, and the script
    is saved with no model call (and the ready-script notification follows as
    for any saved script). A job still waiting is left alone, and a failed one
    is left for him: nothing here creates, re-queues or cancels a job.

    The save runs here, not after the tick answers, so "redriven" in the
    answer (scripts_saved in the cron line) means saved: a save that fails is
    listed under "failed" with the reason. It also cannot sit behind a content
    run the same tick woke, whose background coordinator can take hours.

    Claiming happens in this process with no await between the check and the
    claim, so two ticks at once resume a job once; a person resuming it at the
    same moment is caught by the save itself, which saves a job once.

    A claim is never left behind (review, 28-Sep). A lookup that raises for one
    idea is reported for that idea and the others are still saved; anything
    else that stops the tick between a claim and its save lets the claim go.
    A claim left "running" was never saved, and refused his own ask as
    "already being written" for as long as the process ran.
    """
    from tce.editorial.voice_agent import current_packet

    report: dict[str, list[dict[str, Any]]] = {"redriven": [], "waiting": [], "failed": []}
    claimed: list[tuple[dict[str, str], uuid.UUID, uuid.UUID, Any]] = []
    unsaved: set[uuid.UUID] = set()  # claimed here and not yet through a save
    try:
        async with open_session(sm) as db:
            rows = await job_status.unsaved_packet_requests(db, ws)
            for row in rows:
                cid, job_id = row["candidate_id"], row["job_id"]
                base = {"candidate_id": str(cid), "job_id": str(job_id)}
                if row["action"] == "waiting":
                    report["waiting"].append(
                        base
                        | {
                            "job_status": row["job_status"],
                            "retry_at": row["retry_at"],
                            "reason": row["reason"],
                        }
                    )
                    continue
                if row["action"] == "failed":
                    report["failed"].append(
                        base
                        | {
                            "job_status": row["job_status"],
                            "error_code": row["error_code"],
                            "reason": row["reason"],
                        }
                    )
                    continue
                if _resuming_already(ws, cid, job_id):
                    continue
                previous = job_status.get(ws, "packet", str(cid)) or {}
                try:
                    rewrite = None
                    if previous.get("rewrite_id"):
                        existing = await current_packet(db, ws, cid)
                        rewrite = await _unrecorded_rewrite(db, ws, cid, existing, resuming=True)
                except Exception as exc:
                    logger.exception(
                        "editorial.packet_redrive_lookup_failed",
                        workspace_id=str(ws),
                        candidate_id=str(cid),
                    )
                    report["failed"].append(
                        base
                        | {
                            "job_status": row["job_status"],
                            "error_code": None,
                            "reason": type(exc).__name__,
                        }
                    )
                    # PostgreSQL refuses every later statement in a transaction
                    # that raised; the next idea starts clean.
                    await db.rollback()
                    continue
                # Re-checked after the awaits above: another tick may have claimed it.
                if _resuming_already(ws, cid, job_id):
                    continue
                same_job = previous.get("resumed_job_id") == str(job_id)
                job_status.start(
                    ws,
                    "packet",
                    str(cid),
                    "Saving the script that was written after the request ended",
                    candidate_id=str(cid),
                    resumed_job_id=str(job_id),
                    rewrite_id=str(rewrite[0]) if rewrite else None,
                    rewrite_by=(rewrite[1] or "voice") if rewrite else None,
                    redriven_by="schedule_tick",
                    # Saves of this job that raised before, so a fault that
                    # comes back every time stops after RESUME_FAULT_LIMIT.
                    resume_faults=int(previous.get("resume_faults") or 0) if same_job else 0,
                    resume_fault=previous.get("resume_fault") if same_job else None,
                )
                claimed.append((base, cid, job_id, rewrite))
                unsaved.add(cid)
        # Saved once the listing's session is closed, so each save has the
        # database to itself (SQLite allows one writer, and the listing held a
        # reader).
        for base, cid, job_id, rewrite in claimed:
            if rewrite is not None:
                await _run_packet(
                    sm, ws, cid, job_id, rewrite_id=rewrite[0], by=rewrite[1] or "voice"
                )
            else:
                await _run_packet(sm, ws, cid, job_id)
            unsaved.discard(cid)
            entry = job_status.get(ws, "packet", str(cid)) or {}
            result = entry.get("result") or {}
            if entry.get("state") == "done":
                report["redriven"].append(base | {"packet_id": result.get("packet_id")})
            else:
                report["failed"].append(
                    base
                    | {
                        "job_status": "succeeded",
                        "error_code": None,
                        "reason": str(entry.get("detail") or entry.get("current_activity") or ""),
                    }
                )
    finally:
        for cid in unsaved:
            job_status.update(
                ws,
                "packet",
                str(cid),
                state="failed",
                current_activity="Not saved yet: the scheduler tick stopped before saving it",
                detail="the scheduler tick stopped before saving it",
            )
    return report


def _resuming_already(ws: uuid.UUID, cid: uuid.UUID, job_id: uuid.UUID) -> bool:
    """A request in this process is saving this candidate's script right now, or
    a resume of this very job already finished here (the listing was read before
    it committed)."""
    entry = job_status.get(ws, "packet", str(cid))
    if entry is None:
        return False
    if entry.get("state") == "running":
        return True
    return entry.get("resumed_job_id") == str(job_id) and entry.get("state") == "done"


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


async def _run_more_hooks(sm: Any, ws: uuid.UUID, packet_id: uuid.UUID) -> None:
    key = str(packet_id)
    try:
        outcome = await more_hook_options(sm, ws, packet_id)
    except Exception as exc:
        logger.exception("editorial.more_hooks_failed", workspace_id=str(ws), packet_id=key)
        job_status.update(
            ws,
            "more_hooks",
            key,
            state="failed",
            current_activity="Could not write more openings",
            detail=type(exc).__name__,
        )
        return
    state = {"ok": "done", "waiting_capacity": "waiting", "waiting_worker": "waiting"}.get(
        outcome.status, "failed"
    )
    job_status.update(
        ws,
        "more_hooks",
        key,
        state=state,
        job_id=outcome.job_id,
        current_activity=outcome.detail or f"More openings {outcome.status}",
        detail=outcome.detail,
        result={
            "status": outcome.status,
            "packet": outcome.packet,
            "dropped": outcome.errors,
        },
    )


@router.post("/packets/{packet_id}/more-hooks", status_code=202)
async def more_packet_hooks(
    packet_id: str,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Ask for more openings for the same script. Returns at once.

    One subscription job writes them into a new immutable version; the script,
    the bullets and the opening in use do not change. The job waits its turn in
    the worker queue, which can be minutes deep, so the caller polls
    more-hooks-status rather than holding an HTTP connection open through nginx.
    """
    pid = _parse_uuid(packet_id, "packet")
    async with open_session(sm) as db:
        packet = (
            await db.execute(
                select(RecordingPacket).where(
                    RecordingPacket.id == pid, RecordingPacket.workspace_id == ws
                )
            )
        ).scalar_one_or_none()
        cand = await db.get(TopicCandidate, packet.candidate_id) if packet is not None else None
        running = packet is not None and job_status.is_running(
            ws, "packet", str(packet.candidate_id)
        )
        # What is on its way comes from the record, not from this process's
        # last word on it: a request that stopped waiting stays "waiting" here
        # after its job fails, and refused more openings with "It saves itself"
        # for as long as the process ran (review, 28-Sep).
        coming = (
            (await job_status.packet_requests(db, ws, [packet.candidate_id])).get(
                packet.candidate_id
            )
            if packet is not None and not running
            else None
        )
    if packet is not None:
        # A new script being written, or on its way, replaces this one when it
        # is saved. Openings asked for now would land on the new script
        # unasked, or be dropped with it, so none are asked for.
        if running or (coming is not None and coming["pending"]):
            title = cand.title if cand is not None else "this topic"
            if running:
                why = f'A new script for "{title}" is being written right now.'
                then = "Ask for more openings once it is ready (tce_jobs says when)."
            else:
                why = f'A new script for "{title}" is on its way. {coming["sentence"]}'
                then = "Ask for more openings once it is saved."
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "still_writing",
                    "message": (
                        f"{why} When it is saved it replaces the current script, so openings "
                        f"asked for now would not stay with it. Nothing was asked for. {then}"
                    ),
                },
            )
    if job_status.is_running(ws, "more_hooks", str(pid)):
        return {
            "status": "running",
            "packet_id": str(pid),
            "status_url": f"/api/v1/editorial/packets/{pid}/more-hooks-status",
        }
    job_status.start(ws, "more_hooks", str(pid), "Queued: writing more openings")
    background.add_task(_run_more_hooks, sm, ws, pid)
    return {
        "status": "running",
        "packet_id": str(pid),
        "status_url": f"/api/v1/editorial/packets/{pid}/more-hooks-status",
    }


@router.get("/packets/{packet_id}/more-hooks-status")
async def more_packet_hooks_status(
    packet_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
) -> dict[str, Any]:
    pid = _parse_uuid(packet_id, "packet")
    entry = job_status.get(ws, "more_hooks", str(pid))
    if entry is None:
        return {"packet_id": str(pid), "state": "idle", "current_activity": "Nothing asked for yet"}
    return {"packet_id": str(pid), **entry}


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


@router.post("/packets/{packet_id}/voice-pass")
async def packet_voice_pass(
    packet_id: str,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Score a script's openings against his voice and rewrite them if they fail.

    One subscription job. A pass changes nothing; a fail appends replacements as a
    new packet version with the originals still on it, so the two can be compared.
    """
    outcome = await voice_pass(sm, ws, _parse_uuid(packet_id, "packet"))
    if outcome.status == "invalid":
        raise HTTPException(status_code=409, detail=outcome.detail or "cannot run the voice pass")
    return outcome.to_dict()


@router.post("/more-ideas")
async def more_ideas(
    limit: int = Query(more_ideas_service.DEFAULT_LIMIT, ge=1, le=more_ideas_service.MAX_LIMIT),
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """Offer ideas the selection validated and then set aside.

    No model call and no worker: these already passed every gate in their own week
    and carry their own citations. Answers 200 with added=0 and says why when the
    reserve is empty, because "nothing left" is an answer, not an error.
    """
    async with open_session(sm) as db:
        return await more_ideas_service.offer_more(db, ws, limit)


@router.get("/more-ideas")
async def more_ideas_available(
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_editorial_sessionmaker),
) -> dict[str, Any]:
    """How many more ideas are waiting, so a button can say so before it is pressed."""
    async with open_session(sm) as db:
        ready = await more_ideas_service.available(db, ws)
    return {"available": len(ready)}


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
