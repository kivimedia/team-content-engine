"""Durable coordinator primitives shared by every TCE content request surface."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.content_run import ContentRun, ContentRunStage

STAGES = ("collecting", "extracting", "selecting", "ranking", "drafting", "exporting")
ACTIVE_STATES = frozenset((*STAGES, "queued", "waiting_capacity", "waiting_worker"))
TERMINAL_STATES = frozenset({"ready", "failed", "cancelled"})
# Waits a scheduler tick may re-drive on its own. "failed" and
# "needs_source_choice" need a person and stay parked until /resume.
REDRIVABLE_STATES = frozenset({"queued", "waiting_capacity", "waiting_worker", *STAGES})
DEFAULT_LEASE = timedelta(minutes=5)


class StageWaitingError(RuntimeError):
    def __init__(
        self,
        state: str,
        detail: str,
        retry_at: datetime | None = None,
    ) -> None:
        super().__init__(detail)
        self.state = state
        self.detail = detail
        self.retry_at = _db_time(retry_at)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _db_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


@dataclass(frozen=True)
class ContentRunRequest:
    idempotency_key: str
    scope_kind: str
    source_ids: list[str] = field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None
    maximum_candidate_count: int = 6
    target_packet_count: int = 3
    trigger_origin: str = "produce_now"
    actor: str | None = None
    late: bool = False
    week_label: str | None = None
    # Last stage to execute. A daily evidence refresh stops after "extracting".
    final_stage: str = STAGES[-1]


def stages_through(final_stage: str) -> tuple[str, ...]:
    if final_stage not in STAGES:
        raise ValueError(f"final_stage must be one of {', '.join(STAGES)}")
    return STAGES[: STAGES.index(final_stage) + 1]


def normalized_scope(req: ContentRunRequest) -> tuple[dict[str, Any], str]:
    source_ids = sorted({str(uuid.UUID(value)) for value in req.source_ids})
    payload = {
        "scope_kind": req.scope_kind,
        "source_ids": source_ids,
        "window_start": _db_time(req.window_start).isoformat() if req.window_start else None,
        "window_end": _db_time(req.window_end).isoformat() if req.window_end else None,
        "maximum_candidate_count": max(1, min(req.maximum_candidate_count, 6)),
        "target_packet_count": max(1, min(req.target_packet_count, 10)),
        "final_stage": req.final_stage,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(raw.encode()).hexdigest()


async def create_or_get_run(
    session: AsyncSession, workspace_id: uuid.UUID, req: ContentRunRequest
) -> ContentRun:
    if req.scope_kind not in {"week", "sources"}:
        raise ValueError("scope_kind must be week or sources")
    if req.scope_kind == "sources" and not req.source_ids:
        raise ValueError("source scope needs at least one source id")
    stages = stages_through(req.final_stage)
    if (
        req.window_start
        and req.window_end
        and _db_time(req.window_end) <= _db_time(req.window_start)
    ):
        raise ValueError("window_end must be after window_start")
    payload, scope_hash = normalized_scope(req)
    existing = (
        await session.execute(
            select(ContentRun).where(
                ContentRun.workspace_id == workspace_id,
                ContentRun.request_key == req.idempotency_key[:160],
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    active = (
        await session.execute(
            select(ContentRun)
            .where(
                ContentRun.workspace_id == workspace_id,
                ContentRun.normalized_scope_hash == scope_hash,
                ContentRun.state.in_(ACTIVE_STATES),
            )
            .order_by(ContentRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if active is not None:
        return active

    run = ContentRun(
        workspace_id=workspace_id,
        request_key=req.idempotency_key[:160],
        normalized_scope_hash=scope_hash,
        scope_kind=req.scope_kind,
        source_ids_private=payload["source_ids"],
        window_start=_db_time(req.window_start),
        window_end=_db_time(req.window_end),
        week_label=req.week_label,
        trigger_origin=req.trigger_origin[:40],
        actor=(req.actor or "")[:120] or None,
        priority=80 if req.scope_kind == "sources" else 50,
        maximum_candidate_count=payload["maximum_candidate_count"],
        target_packet_count=payload["target_packet_count"],
        state="queued",
        current_stage=STAGES[0],
        late=req.late,
        final_stage=req.final_stage,
    )
    try:
        async with session.begin_nested():
            session.add(run)
            await session.flush()
            run.focused_path = f"/dashboard?content_run={run.id}"
            for position, stage in enumerate(stages):
                session.add(
                    ContentRunStage(
                        workspace_id=workspace_id,
                        run_id=run.id,
                        stage=stage,
                        position=position,
                        status="pending",
                    )
                )
            await session.flush()
        return run
    except IntegrityError:
        winner = (
            await session.execute(
                select(ContentRun).where(
                    ContentRun.workspace_id == workspace_id,
                    ContentRun.request_key == req.idempotency_key[:160],
                )
            )
        ).scalar_one()
        return winner


async def get_run(
    session: AsyncSession, workspace_id: uuid.UUID, run_id: uuid.UUID
) -> ContentRun | None:
    return (
        await session.execute(
            select(ContentRun).where(
                ContentRun.id == run_id, ContentRun.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()


async def list_stages(session: AsyncSession, run_id: uuid.UUID) -> list[ContentRunStage]:
    return list(
        (
            await session.execute(
                select(ContentRunStage)
                .where(ContentRunStage.run_id == run_id)
                .order_by(ContentRunStage.position)
            )
        )
        .scalars()
        .all()
    )


async def lease_next_stage(
    session: AsyncSession,
    run_id: uuid.UUID,
    owner: str,
    *,
    now: datetime | None = None,
    lease_for: timedelta = DEFAULT_LEASE,
) -> ContentRunStage | None:
    now = now or utcnow()
    run = (
        await session.execute(select(ContentRun).where(ContentRun.id == run_id).with_for_update())
    ).scalar_one_or_none()
    if run is None or run.state in TERMINAL_STATES:
        return None
    stages = await list_stages(session, run_id)
    for stage in stages:
        if stage.status == "succeeded":
            continue
        if stage.status == "running" and stage.leased_until and stage.leased_until >= now:
            return None
        if stage.next_eligible_at and stage.next_eligible_at > now:
            return None
        stage.status = "running"
        stage.lease_owner = owner[:120]
        stage.leased_until = now + lease_for
        stage.attempt_count = int(stage.attempt_count or 0) + 1
        stage.started_at = stage.started_at or now
        stage.error_code = None
        stage.error_detail = None
        run.state = stage.stage
        run.current_stage = stage.stage
        await session.flush()
        return stage
    return None


async def finish_stage(
    session: AsyncSession,
    stage_id: uuid.UUID,
    owner: str,
    outputs: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    now = now or utcnow()
    stage = (
        await session.execute(
            select(ContentRunStage).where(ContentRunStage.id == stage_id).with_for_update()
        )
    ).scalar_one_or_none()
    if stage is None or stage.status != "running" or stage.lease_owner != owner[:120]:
        return False
    stage.status = "succeeded"
    stage.output_refs = outputs
    stage.leased_until = None
    stage.lease_owner = None
    stage.finished_at = now
    run = (
        await session.execute(select(ContentRun).where(ContentRun.id == stage.run_id))
    ).scalar_one()
    remaining = [item for item in await list_stages(session, run.id) if item.status != "succeeded"]
    if not remaining:
        run.state = "ready"
        run.current_stage = "ready"
        run.ready_at = now
    else:
        run.state = remaining[0].stage
        run.current_stage = remaining[0].stage
    await session.flush()
    return True


async def wait_stage(
    session: AsyncSession,
    stage_id: uuid.UUID,
    owner: str,
    state: str,
    detail: str,
    *,
    next_eligible_at: datetime | None = None,
) -> bool:
    if state not in {"waiting_capacity", "waiting_worker", "needs_source_choice", "failed"}:
        raise ValueError("invalid wait state")
    stage = (
        await session.execute(select(ContentRunStage).where(ContentRunStage.id == stage_id))
    ).scalar_one_or_none()
    if stage is None or stage.status != "running" or stage.lease_owner != owner[:120]:
        return False
    stage.status = state
    stage.error_code = state
    stage.error_detail = detail[:4000]
    stage.next_eligible_at = next_eligible_at
    stage.lease_owner = None
    stage.leased_until = None
    run = (
        await session.execute(select(ContentRun).where(ContentRun.id == stage.run_id))
    ).scalar_one()
    run.state = state
    run.error_code = state
    run.error_detail = detail[:4000]
    await session.flush()
    return True


async def make_run_resumable(session: AsyncSession, run: ContentRun) -> None:
    if run.state == "cancelled" or run.state == "ready":
        raise ValueError(f"run is {run.state}")
    stages = await list_stages(session, run.id)
    current = next((item for item in stages if item.status != "succeeded"), None)
    if current is None:
        return
    if current.status in {"failed", "waiting_capacity", "waiting_worker", "needs_source_choice"}:
        current.status = "pending"
        current.next_eligible_at = None
        current.error_code = None
        current.error_detail = None
    run.state = current.stage
    run.current_stage = current.stage
    run.error_code = None
    run.error_detail = None
    await session.flush()


async def list_redrivable_runs(
    session: AsyncSession,
    workspace_id: uuid.UUID | None,
    *,
    now: datetime | None = None,
    limit: int = 20,
) -> list[ContentRun]:
    """Active runs nobody is driving right now, oldest first.

    A run is re-drivable when it is not terminal, not parked on a person, and
    its first unfinished stage holds no live lease and is past `next_eligible_at`.
    Leasing re-checks all of that under a row lock, so a race here is harmless.
    """
    now = now or utcnow()
    stmt = (
        select(ContentRun)
        .where(ContentRun.state.in_(REDRIVABLE_STATES))
        .order_by(ContentRun.priority.desc(), ContentRun.created_at.asc())
        .limit(limit * 4)
    )
    if workspace_id is not None:
        stmt = stmt.where(ContentRun.workspace_id == workspace_id)
    picked: list[ContentRun] = []
    for run in (await session.execute(stmt)).scalars():
        current = next(
            (s for s in await list_stages(session, run.id) if s.status != "succeeded"), None
        )
        if current is None:
            continue
        if current.status == "running" and current.leased_until and current.leased_until >= now:
            continue
        if current.next_eligible_at and current.next_eligible_at > now:
            continue
        if current.status in {"failed", "needs_source_choice"}:
            continue
        picked.append(run)
        if len(picked) >= limit:
            break
    return picked


def run_json(run: ContentRun, stages: list[ContentRunStage]) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "request_key": run.request_key,
        "scope_kind": run.scope_kind,
        "final_stage": run.final_stage,
        "window_start": run.window_start.isoformat() + "Z" if run.window_start else None,
        "window_end": run.window_end.isoformat() + "Z" if run.window_end else None,
        "week_label": run.week_label,
        "trigger_origin": run.trigger_origin,
        "priority": run.priority,
        "state": run.state,
        "current_stage": run.current_stage,
        "late": run.late,
        "focused_path": run.focused_path,
        "error_code": run.error_code,
        "error_detail": run.error_detail,
        "ready_at": run.ready_at.isoformat() + "Z" if run.ready_at else None,
        "stages": [
            {
                "stage": stage.stage,
                "position": stage.position,
                "status": stage.status,
                "job_ids": stage.job_ids or [],
                "output_refs": stage.output_refs or {},
                "attempt_count": stage.attempt_count,
                "next_eligible_at": stage.next_eligible_at.isoformat() + "Z"
                if stage.next_eligible_at
                else None,
                "error_code": stage.error_code,
                "error_detail": stage.error_detail,
            }
            for stage in stages
        ],
    }
