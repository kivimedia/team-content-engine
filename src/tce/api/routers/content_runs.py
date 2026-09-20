"""Private durable content runs shared by weekly, Produce now and Claude requests."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tce.api.private_access import require_private_workspace
from tce.editorial import runs
from tce.editorial.common import open_session
from tce.llm import queue as llm_queue
from tce.models.content_run import (
    ContentRun,
    EditorialSchedule,
    EditorialScheduleOccurrence,
    WorkerGroupState,
)
from tce.models.editorial import (
    EvidenceCollectionRun,
    EvidenceSource,
    RecordingPacket,
    TopicCandidate,
)

router = APIRouter(prefix="/content-runs", tags=["content-runs"])


def get_content_sessionmaker() -> Any:
    from tce.db.session import async_session

    return async_session


class ContentRunBody(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    scope_kind: str = Field(pattern="^(week|sources)$")
    source_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    window_start: datetime | None = None
    window_end: datetime | None = None
    maximum_candidate_count: int = Field(default=6, ge=1, le=6)
    target_packet_count: int = Field(default=3, ge=1, le=10)
    trigger_origin: str = Field(default="produce_now", max_length=40)
    actor: str | None = Field(default=None, max_length=120)
    week_label: str | None = Field(default=None, max_length=80)
    final_stage: str = Field(default="exporting", pattern="^(" + "|".join(runs.STAGES) + ")$")


class ClaudeRequestBody(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
    idempotency_key: str = Field(min_length=1, max_length=160)


class ScheduleBody(BaseModel):
    enabled: bool = False
    cadence: str = Field(default="weekly", pattern="^(weekly|daily)$")
    weekday: int = Field(default=0, ge=0, le=6)
    local_time: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "Asia/Jerusalem"
    catchup_days: int = Field(default=7, ge=0, le=31)
    final_stage: str = Field(default="exporting", pattern="^(" + "|".join(runs.STAGES) + ")$")
    window_days: int = Field(default=7, ge=1, le=31)


# The two schedules the VPS cron owns. Names are fixed so the tick, the report
# and the runbook all talk about the same rows.
SCHEDULE_NAMES = ("weekly-content", "daily-evidence")
# No worker has reported for this long: the run says so and waits for a tick.
NO_WORKER_RETRY = timedelta(minutes=5)
# Stages that need the desktop subscription worker to make progress.
WORKER_STAGES = frozenset({"extracting", "selecting", "drafting"})


async def _source_ids_for_run(sm: Any, run: ContentRun) -> list[uuid.UUID]:
    source_ids = [uuid.UUID(value) for value in (run.source_ids_private or [])]
    if not source_ids:
        return []
    async with open_session(sm) as db:
        found = set(
            (
                await db.execute(
                    select(EvidenceSource.id).where(
                        EvidenceSource.workspace_id == run.workspace_id,
                        EvidenceSource.id.in_(source_ids),
                    )
                )
            ).scalars()
        )
    missing = [str(value) for value in source_ids if value not in found]
    if missing:
        raise ValueError(f"source ids do not belong to this workspace: {', '.join(missing)}")
    return source_ids


async def worker_availability(sm: Any) -> dict[str, Any]:
    """What the desktop worker group can do right now, from durable facts only.

    Presence comes from the worker-status receipts the supervisor posts (stale
    after 180 s); capacity from the worker group row the queue maintains when a
    job fails on subscription limits. Neither is guessed from the absence of an
    error.
    """
    from tce.api.routers.llm_jobs import get_worker_status

    status = await get_worker_status()
    workers = status.get("workers") or []
    online = [w for w in workers if not w.get("stale")]
    async with open_session(sm) as db:
        group = (
            await db.execute(
                select(WorkerGroupState).where(
                    WorkerGroupState.group_key == llm_queue.WORKER_GROUP_KEY
                )
            )
        ).scalar_one_or_none()
        capacity = {
            "state": group.state if group else "available",
            "retry_at": group.retry_at.isoformat() + "Z" if group and group.retry_at else None,
            "reason": group.reason if group else None,
        }
    now = runs.utcnow()
    capped = bool(
        group and group.state == "waiting_capacity" and group.retry_at and group.retry_at > now
    )
    refused = bool(group and group.state == "refused_policy")
    if capped:
        detail = (
            f"Subscription capacity: {group.reason or 'limit reached'}; "
            f"resumes at {group.retry_at.isoformat()}Z"
        )
    elif refused:
        detail = f"Worker refused by policy: {group.reason or 'see worker log'}"
    elif not online:
        detail = (
            "No subscription worker has reported in the last 3 minutes. "
            "Jobs start when the desktop worker checks in."
        )
    else:
        detail = f"{len(online)} worker(s) online"
    return {
        "online": bool(online),
        "online_count": len(online),
        "workers": workers,
        "capacity": capacity,
        "capped": capped,
        "refused": refused,
        "detail": detail,
        "retry_at": group.retry_at if capped else None,
    }


def worker_summary(state: dict[str, Any]) -> dict[str, Any]:
    """The JSON-safe part of `worker_availability` the API and cron log show."""
    return {k: state[k] for k in ("online", "online_count", "capacity", "detail")}


async def _require_worker(sm: Any) -> None:
    """Say why a worker stage cannot progress instead of blocking on the queue."""
    state = await worker_availability(sm)
    if state["capped"]:
        raise runs.StageWaitingError("waiting_capacity", state["detail"], state["retry_at"])
    if state["refused"]:
        raise runs.StageWaitingError(
            "waiting_worker", state["detail"], datetime.now(UTC) + NO_WORKER_RETRY
        )
    if not state["online"]:
        raise runs.StageWaitingError(
            "waiting_worker", state["detail"], datetime.now(UTC) + NO_WORKER_RETRY
        )


async def _execute_stage(sm: Any, run: ContentRun, stage: str) -> dict[str, Any]:
    from tce.editorial.packets import build_packet
    from tce.editorial.selector import select_candidates
    from tce.evidence.collect import collect_fathom, collect_github
    from tce.evidence.moments import extract_moments
    from tce.production.export import export_packet_durable
    from tce.settings import settings

    source_ids = await _source_ids_for_run(sm, run)
    if stage in WORKER_STAGES:
        await _require_worker(sm)
    if stage == "collecting":
        if run.scope_kind == "sources":
            return {"source_ids": [str(value) for value in source_ids], "collection": "existing"}
        if not run.window_start or not run.window_end:
            raise ValueError("week runs require window_start and window_end")
        fathom = await collect_fathom(sm, run.workspace_id, run.window_start, run.window_end)
        github = await collect_github(sm, run.workspace_id, run.window_start, run.window_end)
        return {"collection_run_ids": [str(fathom), str(github)]}

    if stage == "extracting":
        extraction_id = await extract_moments(
            sm,
            run.workspace_id,
            None if source_ids else run.window_start,
            None if source_ids else run.window_end,
            source_ids=source_ids or None,
        )
        async with open_session(sm) as db:
            ledger = await db.get(EvidenceCollectionRun, extraction_id)
            if ledger is None or not ledger.complete:
                detail = ledger.current_activity if ledger else "extraction ledger missing"
                raise runs.StageWaitingError("waiting_capacity", detail or "extraction incomplete")
        return {"extraction_run_id": str(extraction_id)}

    week = (run.window_start or datetime.now(UTC)).date()
    if stage == "selecting":
        selection_id = uuid.uuid5(run.id, "selection")
        result = await select_candidates(
            sm,
            run.workspace_id,
            week,
            max_candidates=run.maximum_candidate_count,
            selection_run_id=selection_id,
            source_ids=source_ids or None,
        )
        if result.status not in {"complete", "no_evidence"}:
            wait_state = "waiting_capacity" if result.status == "waiting_capacity" else "failed"
            raise runs.StageWaitingError(
                wait_state, result.detail or result.status, result.retry_at
            )
        return {
            "selection_run_id": str(selection_id),
            "candidate_ids": [row["id"] for row in result.candidates],
            "job_ids": [str(value) for value in result.job_ids],
            "coverage": result.coverage,
        }

    async with open_session(sm) as db:
        stages = await runs.list_stages(db, run.id)
        outputs = {item.stage: item.output_refs or {} for item in stages}
    if stage == "ranking":
        ids = outputs.get("selecting", {}).get("candidate_ids", [])
        if not ids:
            return {"candidate_ids": [], "ranked": 0}
        async with open_session(sm) as db:
            ranked = list(
                (
                    await db.execute(
                        select(TopicCandidate.id).where(
                            TopicCandidate.workspace_id == run.workspace_id,
                            TopicCandidate.id.in_([uuid.UUID(value) for value in ids]),
                            TopicCandidate.rank.is_not(None),
                        )
                    )
                ).scalars()
            )
        if len(ranked) != len(ids):
            raise ValueError("selection finished without a rank for every finalist")
        return {"candidate_ids": [str(value) for value in ranked], "ranked": len(ranked)}

    if stage == "drafting":
        ids = outputs.get("ranking", {}).get("candidate_ids", [])[: run.target_packet_count]
        packet_ids: list[str] = []
        job_ids: list[str] = []
        for candidate_id in ids:
            outcome = await build_packet(sm, run.workspace_id, uuid.UUID(candidate_id))
            if outcome.status == "waiting_capacity":
                raise runs.StageWaitingError(
                    "waiting_capacity", outcome.detail or "packet waiting", outcome.retry_at
                )
            if outcome.packet is None:
                raise ValueError(outcome.detail or f"packet failed for {candidate_id}")
            packet_ids.append(outcome.packet["id"])
            if outcome.job_id:
                job_ids.append(str(outcome.job_id))
        return {"packet_ids": packet_ids, "job_ids": job_ids}

    if stage == "exporting":
        from tce.api.routers.production import google_client

        packet_ids = [
            uuid.UUID(value) for value in outputs.get("drafting", {}).get("packet_ids", [])
        ]
        exported: list[dict[str, Any]] = []
        async with open_session(sm) as db:
            packets = list(
                (
                    await db.execute(
                        select(RecordingPacket).where(
                            RecordingPacket.workspace_id == run.workspace_id,
                            RecordingPacket.id.in_(packet_ids),
                        )
                    )
                ).scalars()
            )
            candidates = {
                row.id: row
                for row in (
                    await db.execute(
                        select(TopicCandidate).where(
                            TopicCandidate.workspace_id == run.workspace_id,
                            TopicCandidate.id.in_([packet.candidate_id for packet in packets]),
                        )
                    )
                ).scalars()
            }
            for packet in packets:
                result = await export_packet_durable(
                    db,
                    packet,
                    candidates.get(packet.candidate_id),
                    client=google_client(),
                    docx_dir=Path(settings.evidence_upload_dir) / str(run.workspace_id) / "exports",
                    docx_url=f"/api/v1/production/packets/{packet.id}/docx",
                    team_emails=settings.production_doc_team_emails.split(","),
                )
                if result["status"] != "exported":
                    raise runs.StageWaitingError(
                        "waiting_worker", result.get("reason") or result["status"]
                    )
                exported.append(result)
        return {"exports": exported}
    raise ValueError(f"unknown stage {stage}")


# How often a coordinator renews the lease of the stage it is executing. Well
# inside runs.DEFAULT_LEASE (5 min): collecting alone took 5m12s on 20-Sep, and
# the cron tick re-drives any stage whose lease has lapsed.
LEASE_HEARTBEAT = timedelta(seconds=60)


async def _execute_stage_leased(sm: Any, run: ContentRun, stage: Any, owner: str) -> dict[str, Any]:
    """Run the stage while keeping its lease alive.

    A stage that outlives its lease without a heartbeat is re-leased by the next
    tick; the first coordinator's finish is then rejected and the work repeats.
    If the lease is lost anyway (another owner took it), the work is cancelled
    and LeaseLostError tells the coordinator to stand down without touching
    the run.
    """
    import asyncio

    work = asyncio.ensure_future(_execute_stage(sm, run, stage.stage))
    try:
        while True:
            done, _ = await asyncio.wait({work}, timeout=LEASE_HEARTBEAT.total_seconds())
            if done:
                return work.result()
            async with open_session(sm) as db:
                kept = await runs.extend_lease(db, stage.id, owner)
                await db.commit()
            if not kept:
                raise runs.LeaseLostError(f"stage {stage.stage} of run {run.id} was re-leased")
    finally:
        if not work.done():
            work.cancel()
            try:
                await work
            except (asyncio.CancelledError, Exception):
                pass


async def coordinate_content_run(sm: Any, workspace_id: uuid.UUID, run_id: uuid.UUID) -> None:
    owner = f"api:{uuid.uuid4()}"
    while True:
        async with open_session(sm) as db:
            run = await runs.get_run(db, workspace_id, run_id)
            if run is None or run.state in runs.TERMINAL_STATES:
                return
            stage = await runs.lease_next_stage(db, run.id, owner)
            await db.commit()
        if stage is None:
            return
        try:
            output = await _execute_stage_leased(sm, run, stage, owner)
        except runs.LeaseLostError:
            return
        except runs.StageWaitingError as exc:
            async with open_session(sm) as db:
                await runs.wait_stage(
                    db,
                    stage.id,
                    owner,
                    exc.state,
                    exc.detail,
                    next_eligible_at=exc.retry_at,
                )
                await db.commit()
            return
        except Exception as exc:
            async with open_session(sm) as db:
                await runs.wait_stage(db, stage.id, owner, "failed", f"{type(exc).__name__}: {exc}")
                await db.commit()
            return
        async with open_session(sm) as db:
            if not await runs.finish_stage(db, stage.id, owner, output):
                return
            await db.commit()


async def _create_run(ws: uuid.UUID, body: ContentRunBody, sm: Any) -> ContentRun:
    request = runs.ContentRunRequest(
        idempotency_key=body.idempotency_key,
        scope_kind=body.scope_kind,
        source_ids=[str(value) for value in body.source_ids],
        window_start=body.window_start,
        window_end=body.window_end,
        maximum_candidate_count=body.maximum_candidate_count,
        target_packet_count=body.target_packet_count,
        trigger_origin=body.trigger_origin,
        actor=body.actor,
        week_label=body.week_label,
        final_stage=body.final_stage,
    )
    async with open_session(sm) as db:
        row = await runs.create_or_get_run(db, ws, request)
        await db.commit()
        return row


@router.post("")
async def create_content_run(
    body: ContentRunBody,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    try:
        row = await _create_run(ws, body, sm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background.add_task(coordinate_content_run, sm, ws, row.id)
    async with open_session(sm) as db:
        stages = await runs.list_stages(db, row.id)
    return runs.run_json(row, stages)


@router.post("/produce-now")
async def produce_now(
    body: ContentRunBody,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    body.trigger_origin = "produce_now"
    return await create_content_run(body, background, ws, sm)


@router.get("")
async def list_content_runs(
    limit: int = Query(default=20, ge=1, le=100),
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        rows = list(
            (
                await db.execute(
                    select(ContentRun)
                    .where(ContentRun.workspace_id == ws)
                    .order_by(ContentRun.created_at.desc())
                    .limit(limit)
                )
            ).scalars()
        )
        return {"runs": [runs.run_json(row, await runs.list_stages(db, row.id)) for row in rows]}


# Registered before "/{run_id}": a static path declared after the UUID
# parameter route is never reached (FastAPI matches in declaration order and
# "schedule" fails UUID validation with a 422).
@router.get("/schedule")
async def list_schedules(
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with open_session(sm) as db:
        rows = list(
            (
                await db.execute(
                    select(EditorialSchedule)
                    .where(EditorialSchedule.workspace_id == ws)
                    .order_by(EditorialSchedule.name)
                )
            ).scalars()
        )
        out = []
        for row in rows:
            occurrences = list(
                (
                    await db.execute(
                        select(EditorialScheduleOccurrence)
                        .where(EditorialScheduleOccurrence.schedule_id == row.id)
                        .order_by(EditorialScheduleOccurrence.scheduled_for_utc.desc())
                        .limit(5)
                    )
                ).scalars()
            )
            item = schedule_json(row)
            due = due_occurrence(row, now) if row.enabled else None
            item["due_now"] = due[0] if due else None
            item["recent_occurrences"] = [
                {
                    "occurrence_key": o.occurrence_key,
                    "scheduled_for_utc": o.scheduled_for_utc.isoformat() + "Z",
                    "window_start": o.window_start.isoformat() + "Z",
                    "window_end": o.window_end.isoformat() + "Z",
                    "state": o.state,
                    "late": o.late,
                    "content_run_id": str(o.content_run_id) if o.content_run_id else None,
                }
                for o in occurrences
            ]
            out.append(item)
    return {"schedules": out, "worker": worker_summary(await worker_availability(sm))}


@router.get("/{run_id}")
async def get_content_run(
    run_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        row = await runs.get_run(db, ws, run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="content run not found")
        return runs.run_json(row, await runs.list_stages(db, row.id))


@router.post("/{run_id}/resume")
async def resume_content_run(
    run_id: uuid.UUID,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    async with open_session(sm) as db:
        row = await runs.get_run(db, ws, run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="content run not found")
        await runs.make_run_resumable(db, row)
        await db.commit()
    background.add_task(coordinate_content_run, sm, ws, run_id)
    return {"id": str(run_id), "status": "resuming", "status_url": f"/api/v1/content-runs/{run_id}"}


@router.post("/from-claude/request")
async def request_from_claude(
    body: ClaudeRequestBody,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    name_match = re.search(r"(?:with|from)\s+([A-Za-z][A-Za-z' -]{1,60})", body.text, re.I)
    if not name_match:
        raise HTTPException(
            status_code=422, detail="Name the Fathom meeting person or choose a source"
        )
    name = name_match.group(1).strip().split(" is ")[0].strip()
    now_local = datetime.now(ZoneInfo("Asia/Jerusalem"))
    target = (now_local - timedelta(days=1)).date() if "yesterday" in body.text.lower() else None
    async with open_session(sm) as db:
        stmt = select(EvidenceSource).where(
            EvidenceSource.workspace_id == ws,
            EvidenceSource.source_kind == "fathom_meeting",
            EvidenceSource.title.ilike(f"%{name}%"),
        )
        matches = list(
            (await db.execute(stmt.order_by(EvidenceSource.occurred_at.desc()))).scalars()
        )
    if target:
        matches = [row for row in matches if row.occurred_at and row.occurred_at.date() == target]
    if not matches:
        raise HTTPException(status_code=404, detail=f"No matching Fathom meeting found for {name}")
    if len(matches) > 1:
        return {
            "status": "needs_source_choice",
            "choices": [
                {
                    "source_id": str(row.id),
                    "title": row.title,
                    "occurred_at": row.occurred_at.isoformat(),
                }
                for row in matches[:10]
            ],
        }
    source = matches[0]
    request = ContentRunBody(
        idempotency_key=body.idempotency_key,
        scope_kind="sources",
        source_ids=[source.id],
        trigger_origin="claude_request",
        actor="claude",
        week_label=f"Targeted: {source.title}",
    )
    return await create_content_run(request, background, ws, sm)


def due_occurrence(
    schedule: EditorialSchedule, now_utc: datetime
) -> tuple[str, datetime, bool] | None:
    """The single most recent due occurrence within catch-up, evaluated in the
    schedule's own timezone. Israel DST is whatever ZoneInfo says for that day:
    the key carries the offset, so 07:15+0300 in summer and 07:15+0200 in
    winter are different occurrences with the same wall-clock intent."""
    zone = ZoneInfo(schedule.timezone)
    local_now = now_utc.astimezone(zone)
    hour, minute = (int(value) for value in schedule.local_time.split(":"))
    daily = getattr(schedule, "cadence", "weekly") == "daily"
    if daily:
        day = local_now.date()
        if local_now.time() < time(hour, minute):
            day -= timedelta(days=1)
    else:
        days_back = (local_now.weekday() - schedule.weekday) % 7
        day = local_now.date() - timedelta(days=days_back)
    local_due = datetime.combine(day, time(hour, minute), zone)
    due_utc = local_due.astimezone(UTC)
    if due_utc > now_utc:
        if daily:
            return None
        # The weekly moment is later today; last week's occurrence is the
        # candidate instead, still subject to catch-up.
        local_due = datetime.combine(day - timedelta(days=7), time(hour, minute), zone)
        due_utc = local_due.astimezone(UTC)
    age = now_utc - due_utc
    if age > timedelta(days=schedule.catchup_days):
        return None
    return local_due.strftime("%Y-%m-%dT%H:%M%z"), due_utc, age > timedelta(minutes=15)


def occurrence_window(schedule: EditorialSchedule, due_utc: datetime) -> tuple[datetime, datetime]:
    """Evidence window for an occurrence, both ends UTC-aware.

    Weekly: the completed local week ending at local midnight of the due day
    (Monday 07:30 -> the previous Monday 00:00 to this Monday 00:00). Daily: the
    last `window_days` days ending at the due moment itself, so a missed day
    never leaves a gap and collection stays an idempotent upsert.
    """
    zone = ZoneInfo(schedule.timezone)
    days = int(getattr(schedule, "window_days", 7) or 7)
    if getattr(schedule, "cadence", "weekly") == "daily":
        return due_utc - timedelta(days=days), due_utc
    local_due = due_utc.astimezone(zone)
    window_end = datetime.combine(local_due.date(), time.min, zone).astimezone(UTC)
    return window_end - timedelta(days=days), window_end


def schedule_json(row: EditorialSchedule) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "enabled": row.enabled,
        "cadence": row.cadence,
        "timezone": row.timezone,
        "weekday": row.weekday,
        "local_time": row.local_time,
        "catchup_days": row.catchup_days,
        "final_stage": row.final_stage,
        "window_days": row.window_days,
        "last_checked_at": row.last_checked_at.isoformat() + "Z" if row.last_checked_at else None,
    }


async def _configure_schedule(
    name: str, body: ScheduleBody, ws: uuid.UUID, sm: Any
) -> dict[str, Any]:
    if name not in SCHEDULE_NAMES:
        raise HTTPException(
            status_code=404, detail=f"unknown schedule; use one of {', '.join(SCHEDULE_NAMES)}"
        )
    try:
        ZoneInfo(body.timezone)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="unknown timezone") from exc
    async with open_session(sm) as db:
        row = (
            await db.execute(
                select(EditorialSchedule).where(
                    EditorialSchedule.workspace_id == ws, EditorialSchedule.name == name
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = EditorialSchedule(workspace_id=ws, name=name)
            db.add(row)
        row.enabled = body.enabled
        row.cadence = body.cadence
        row.weekday = body.weekday
        row.local_time = body.local_time
        row.timezone = body.timezone
        row.catchup_days = body.catchup_days
        row.final_stage = body.final_stage
        row.window_days = body.window_days
        await db.commit()
        return schedule_json(row)


@router.put("/schedule/weekly")
async def configure_weekly_schedule(
    body: ScheduleBody,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    return await _configure_schedule("weekly-content", body, ws, sm)


@router.put("/schedule/{name}")
async def configure_schedule(
    name: str,
    body: ScheduleBody,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    return await _configure_schedule(name, body, ws, sm)


@router.post("/schedule/tick")
async def tick_weekly_schedule(
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    """One scheduler heartbeat, owned by the VPS cron.

    Creates every due occurrence exactly once (durable keys), then re-drives
    active runs nobody is coordinating: a run parked on "waiting for worker"
    moves the moment a worker checks in, a run whose coordinator died with the
    process picks up at its expired lease. Repeated and concurrent ticks are
    safe; the response says what happened so the cron log is readable.
    """
    results = await tick_due_schedules(sm, workspace_id=ws)
    queued_ids = {r["run_id"] for r in results if r["status"] == "queued"}
    for run_id in queued_ids:
        background.add_task(coordinate_content_run, sm, ws, uuid.UUID(run_id))
    worker = await worker_availability(sm)
    redriven: list[dict[str, Any]] = []
    async with open_session(sm) as db:
        for run in await runs.list_redrivable_runs(db, ws):
            if str(run.id) in queued_ids:
                continue
            if run.state in {"waiting_worker", "waiting_capacity"} and not worker["online"]:
                # Waking it would only park it on the same wait again.
                continue
            redriven.append({"run_id": str(run.id), "state": run.state, "stage": run.current_stage})
            background.add_task(coordinate_content_run, sm, ws, run.id)
    if queued_ids:
        status = "queued"
    elif redriven:
        status = "redriven"
    else:
        status = "disabled_or_not_due"
    return {
        "status": status,
        "occurrences": results,
        "redriven": redriven,
        "worker": worker_summary(worker),
    }


async def tick_due_schedules(
    sm: Any,
    *,
    workspace_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Create each due occurrence once. Callers decide how to dispatch created runs."""
    now = now or datetime.now(UTC)
    results: list[dict[str, Any]] = []
    async with open_session(sm) as db:
        stmt = select(EditorialSchedule).where(EditorialSchedule.enabled.is_(True))
        if workspace_id is not None:
            stmt = stmt.where(EditorialSchedule.workspace_id == workspace_id)
        schedules = list((await db.execute(stmt.with_for_update())).scalars())
        for schedule in schedules:
            schedule.last_checked_at = now.replace(tzinfo=None)
            due = due_occurrence(schedule, now)
            if due is None:
                continue
            key, due_utc, late = due
            # Plain values, read before any savepoint: a rolled-back savepoint
            # expires the modified schedule row, and an expired attribute load
            # inside the async session is a MissingGreenlet, not a refresh.
            schedule_id = schedule.id
            schedule_name = schedule.name
            schedule_ws = schedule.workspace_id
            cadence = schedule.cadence
            final_stage = schedule.final_stage or runs.STAGES[-1]

            async def existing_result() -> dict[str, Any] | None:
                row = (
                    await db.execute(
                        select(EditorialScheduleOccurrence).where(
                            EditorialScheduleOccurrence.schedule_id == schedule_id,
                            EditorialScheduleOccurrence.occurrence_key == key,
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    return None
                return {
                    "status": "already_created",
                    "schedule": schedule_name,
                    "occurrence_key": key,
                    "workspace_id": str(schedule_ws),
                    "run_id": str(row.content_run_id) if row.content_run_id else None,
                }

            seen = await existing_result()
            if seen:
                results.append(seen)
                continue
            window_start, window_end = occurrence_window(schedule, due_utc)
            occurrence = EditorialScheduleOccurrence(
                workspace_id=schedule_ws,
                schedule_id=schedule_id,
                occurrence_key=key,
                scheduled_for_utc=due_utc.replace(tzinfo=None),
                window_start=window_start.replace(tzinfo=None),
                window_end=window_end.replace(tzinfo=None),
                late=late,
            )
            try:
                async with db.begin_nested():
                    db.add(occurrence)
                    await db.flush()
            except IntegrityError:
                # A concurrent tick won the unique key: report its run, create nothing.
                results.append(
                    await existing_result()
                    or {
                        "status": "already_created",
                        "schedule": schedule_name,
                        "occurrence_key": key,
                        "workspace_id": str(schedule_ws),
                        "run_id": None,
                    }
                )
                continue
            request = runs.ContentRunRequest(
                idempotency_key=f"schedule:{schedule_id}:{key}",
                scope_kind="week",
                window_start=window_start,
                window_end=window_end,
                trigger_origin="daily_schedule" if cadence == "daily" else "weekly_schedule",
                late=late,
                week_label=window_start.date().isoformat(),
                final_stage=final_stage,
            )
            row = await runs.create_or_get_run(db, schedule_ws, request)
            occurrence.content_run_id = row.id
            occurrence.state = "queued"
            results.append(
                {
                    "status": "queued",
                    "schedule": schedule_name,
                    "occurrence_key": key,
                    "workspace_id": str(schedule_ws),
                    "run_id": str(row.id),
                    "late": late,
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                    "final_stage": row.final_stage,
                }
            )
        await db.commit()
    return results


async def poll_weekly_schedules(sm: Any) -> None:
    import asyncio

    while True:
        try:
            for result in await tick_due_schedules(sm):
                if result["status"] == "queued":
                    asyncio.create_task(
                        coordinate_content_run(
                            sm,
                            uuid.UUID(result["workspace_id"]),
                            uuid.UUID(result["run_id"]),
                        )
                    )
        except Exception:
            # A polling failure is retried. Durable occurrence keys prevent duplicates.
            pass
        await asyncio.sleep(60)
