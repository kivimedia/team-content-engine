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

from tce.api.private_access import require_private_workspace
from tce.editorial import runs
from tce.editorial.common import open_session
from tce.models.content_run import (
    ContentRun,
    EditorialSchedule,
    EditorialScheduleOccurrence,
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


class ClaudeRequestBody(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
    idempotency_key: str = Field(min_length=1, max_length=160)


class ScheduleBody(BaseModel):
    enabled: bool = False
    weekday: int = Field(default=0, ge=0, le=6)
    local_time: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "Asia/Jerusalem"
    catchup_days: int = Field(default=7, ge=0, le=31)


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


async def _execute_stage(sm: Any, run: ContentRun, stage: str) -> dict[str, Any]:
    from tce.editorial.packets import build_packet
    from tce.editorial.selector import select_candidates
    from tce.evidence.collect import collect_fathom, collect_github
    from tce.evidence.moments import extract_moments
    from tce.production.export import export_packet_durable
    from tce.settings import settings

    source_ids = await _source_ids_for_run(sm, run)
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
            output = await _execute_stage(sm, run, stage.stage)
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
    zone = ZoneInfo(schedule.timezone)
    local_now = now_utc.astimezone(zone)
    days_back = (local_now.weekday() - schedule.weekday) % 7
    day = local_now.date() - timedelta(days=days_back)
    hour, minute = (int(value) for value in schedule.local_time.split(":"))
    local_due = datetime.combine(day, time(hour, minute), zone)
    due_utc = local_due.astimezone(UTC)
    if due_utc > now_utc:
        return None
    age = now_utc - due_utc
    if age > timedelta(days=schedule.catchup_days):
        return None
    return local_due.strftime("%Y-%m-%dT%H:%M%z"), due_utc, age > timedelta(minutes=15)


@router.put("/schedule/weekly")
async def configure_weekly_schedule(
    body: ScheduleBody,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    try:
        ZoneInfo(body.timezone)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="unknown timezone") from exc
    async with open_session(sm) as db:
        row = (
            await db.execute(
                select(EditorialSchedule).where(
                    EditorialSchedule.workspace_id == ws, EditorialSchedule.name == "weekly-content"
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = EditorialSchedule(workspace_id=ws, name="weekly-content")
            db.add(row)
        row.enabled = body.enabled
        row.weekday = body.weekday
        row.local_time = body.local_time
        row.timezone = body.timezone
        row.catchup_days = body.catchup_days
        await db.commit()
        return {
            "id": str(row.id),
            "enabled": row.enabled,
            "timezone": row.timezone,
            "weekday": row.weekday,
            "local_time": row.local_time,
        }


@router.post("/schedule/tick")
async def tick_weekly_schedule(
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sm: Any = Depends(get_content_sessionmaker),
) -> dict[str, Any]:
    results = await tick_due_schedules(sm, workspace_id=ws)
    if not results:
        return {"status": "disabled_or_not_due"}
    result = results[0]
    if result["status"] == "queued":
        background.add_task(coordinate_content_run, sm, ws, uuid.UUID(result["run_id"]))
    return result


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
            due = due_occurrence(schedule, now)
            if due is None:
                continue
            key, due_utc, late = due
            existing = (
                await db.execute(
                    select(EditorialScheduleOccurrence).where(
                        EditorialScheduleOccurrence.schedule_id == schedule.id,
                        EditorialScheduleOccurrence.occurrence_key == key,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                results.append(
                    {
                        "status": "already_created",
                        "workspace_id": str(schedule.workspace_id),
                        "run_id": str(existing.content_run_id) if existing.content_run_id else None,
                    }
                )
                continue
            local_due = due_utc.astimezone(ZoneInfo(schedule.timezone))
            window_end = datetime.combine(
                local_due.date(), time.min, ZoneInfo(schedule.timezone)
            ).astimezone(UTC)
            window_start = window_end - timedelta(days=7)
            occurrence = EditorialScheduleOccurrence(
                workspace_id=schedule.workspace_id,
                schedule_id=schedule.id,
                occurrence_key=key,
                scheduled_for_utc=due_utc.replace(tzinfo=None),
                window_start=window_start.replace(tzinfo=None),
                window_end=window_end.replace(tzinfo=None),
                late=late,
            )
            db.add(occurrence)
            await db.flush()
            request = runs.ContentRunRequest(
                idempotency_key=f"schedule:{schedule.id}:{key}",
                scope_kind="week",
                window_start=window_start,
                window_end=window_end,
                trigger_origin="weekly_schedule",
                late=late,
                week_label=window_start.date().isoformat(),
            )
            row = await runs.create_or_get_run(db, schedule.workspace_id, request)
            occurrence.content_run_id = row.id
            occurrence.state = "queued"
            results.append(
                {
                    "status": "queued",
                    "workspace_id": str(schedule.workspace_id),
                    "run_id": str(row.id),
                    "late": late,
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
