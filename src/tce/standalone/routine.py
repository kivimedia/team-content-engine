"""Weekly client-local scouting, with one receipt per workspace and date."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import async_session, get_db
from tce.standalone.auth import Principal, current_principal, require_scope
from tce.standalone.models import (
    StandaloneAccount,
    StandaloneConfigRevision,
    StandaloneJob,
    StandaloneMembership,
    StandaloneRoutineRun,
    StandaloneWorkspace,
)

router = APIRouter(prefix="/api/routine", dependencies=[Depends(current_principal)])


def due_local_date(now: datetime, timezone: str, routine: dict) -> date | None:
    if not routine.get("enabled"):
        return None
    local = now.astimezone(ZoneInfo(timezone))
    if local.weekday() != routine["weekday"]:
        return None
    hour, minute = map(int, routine["local_time"].split(":"))
    minute_of_day = local.hour * 60 + local.minute
    delay = minute_of_day - (hour * 60 + minute)
    return local.date() if delay >= 0 else None


@router.get("")
async def routine_status(
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(StandaloneRoutineRun)
            .where(StandaloneRoutineRun.workspace_id == principal.workspace_id)
            .order_by(StandaloneRoutineRun.routine_date.desc())
            .limit(10)
        )
    ).scalars()
    result = []
    for run in rows:
        job = await db.get(StandaloneJob, run.job_id) if run.job_id else None
        if job is not None and job.workspace_id != principal.workspace_id:
            job = None
        result.append(
            {
                "date": run.routine_date.isoformat(),
                "status": job.status if job else run.status,
                "phase": job.phase if job else None,
                "error_code": run.error_code or (job.error_code if job else None),
            }
        )
    return result


async def _run_workspace(workspace_id: uuid.UUID, now: datetime) -> None:
    async with async_session() as db:
        workspace = await db.get(StandaloneWorkspace, workspace_id)
        if workspace is None or not workspace.active:
            return
        config_row = (
            await db.execute(
                select(StandaloneConfigRevision)
                .where(StandaloneConfigRevision.workspace_id == workspace_id)
                .order_by(StandaloneConfigRevision.revision.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if config_row is None:
            return
        from tce.standalone.app import ClientConfig

        config = ClientConfig.model_validate(config_row.content)
        routine_date = due_local_date(now, config.timezone, config.routine.model_dump())
        if routine_date is None:
            return
        existing = (
            await db.execute(
                select(StandaloneRoutineRun).where(
                    StandaloneRoutineRun.workspace_id == workspace_id,
                    StandaloneRoutineRun.routine_date == routine_date,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        owner = (
            await db.execute(
                select(StandaloneAccount, StandaloneMembership)
                .join(StandaloneMembership, StandaloneMembership.account_id == StandaloneAccount.id)
                .where(
                    StandaloneMembership.workspace_id == workspace_id,
                    StandaloneMembership.active.is_(True),
                    StandaloneMembership.role == "owner",
                    StandaloneAccount.email_verified_at.is_not(None),
                    StandaloneAccount.disabled_at.is_(None),
                )
                .limit(1)
            )
        ).first()
        if owner is None:
            return
        receipt = StandaloneRoutineRun(
            workspace_id=workspace_id, routine_date=routine_date, status="running"
        )
        db.add(receipt)
        await db.flush()
        account, membership = owner
        principal = Principal(
            account_id=account.id,
            workspace_id=workspace_id,
            email=account.email,
            role=membership.role,
            scopes=frozenset({"read", "write"}),
        )
        from tce.standalone.workflow import scout

        try:
            outcome = await scout(principal, db)
            if isinstance(outcome, JSONResponse):
                job_id = json.loads(outcome.body)["job_id"]
                receipt.job_id = uuid.UUID(job_id)
                receipt.status = "queued"
            else:
                receipt.status = "done"
            await db.commit()
        except HTTPException as exc:
            await db.rollback()
            await _save_failure(workspace_id, routine_date, f"http_{exc.status_code}")
        except Exception:
            await db.rollback()
            await _save_failure(workspace_id, routine_date, "scout_error")


async def _save_failure(workspace_id: uuid.UUID, routine_date: date, code: str) -> None:
    async with async_session() as db:
        existing = (
            await db.execute(
                select(StandaloneRoutineRun).where(
                    StandaloneRoutineRun.workspace_id == workspace_id,
                    StandaloneRoutineRun.routine_date == routine_date,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                StandaloneRoutineRun(
                    workspace_id=workspace_id,
                    routine_date=routine_date,
                    status="failed",
                    error_code=code,
                )
            )
        await db.commit()


async def tick(now: datetime | None = None) -> None:
    moment = now or datetime.now(UTC)
    async with async_session() as db:
        workspace_ids = (
            await db.execute(
                select(StandaloneWorkspace.id).where(StandaloneWorkspace.active.is_(True))
            )
        ).scalars().all()
    for workspace_id in workspace_ids:
        try:
            await _run_workspace(workspace_id, moment)
        except Exception:
            # Keep the scheduler alive. Never print source content or provider credentials.
            print(f"Weekly scout needs attention for workspace {workspace_id}", flush=True)


async def main() -> None:
    while True:
        try:
            await tick()
        except Exception:
            print("Weekly scout scheduler will retry database connection", flush=True)
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
