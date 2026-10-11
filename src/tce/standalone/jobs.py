"""Workspace-scoped jobs for a client's native Claude Code worker."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.standalone.auth import Principal, current_principal, require_scope
from tce.standalone.models import (
    StandaloneChatMessage,
    StandaloneIdea,
    StandaloneJob,
    StandaloneScriptVersion,
    StandaloneSourceItem,
)

router = APIRouter(prefix="/api/jobs", dependencies=[Depends(current_principal)])
LEASE_MINUTES = 30


class JobCompletion(BaseModel):
    lease_token: str = Field(min_length=20, max_length=200)
    output: str = Field(min_length=1, max_length=40000)


class JobFailure(BaseModel):
    lease_token: str = Field(min_length=20, max_length=200)
    error_code: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9_]+$")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _public(row: StandaloneJob) -> dict:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "status": row.status,
        "phase": row.phase,
        "attempts": row.attempts,
        "result": row.result,
        "error_code": row.error_code,
        "created_at": row.created_at,
    }


async def queue_job(db: AsyncSession, ws: uuid.UUID, kind: str, input_data: dict) -> StandaloneJob:
    row = StandaloneJob(
        workspace_id=ws,
        kind=kind,
        status="queued",
        phase="Waiting for your Claude Code worker",
        input=input_data,
        attempts=0,
    )
    db.add(row)
    await db.flush()
    return row


@router.get("")
async def list_jobs(
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(StandaloneJob)
            .where(StandaloneJob.workspace_id == principal.workspace_id)
            .order_by(StandaloneJob.created_at.desc())
            .limit(30)
        )
    ).scalars()
    return [_public(row) for row in rows]


@router.post("/lease")
async def lease_job(
    principal: Principal = Depends(require_scope("worker")),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(UTC)
    exhausted = (
        await db.execute(
            select(StandaloneJob)
            .where(
                StandaloneJob.workspace_id == principal.workspace_id,
                StandaloneJob.status == "leased",
                StandaloneJob.attempts >= 3,
                StandaloneJob.lease_expires_at < now,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    for old in exhausted:
        old.status = "failed"
        old.phase = "Worker lease expired three times. Check the connection, then retry."
        old.error_code = "lease_expired"
        old.lease_hash = None
        old.lease_expires_at = None
    row = (
        await db.execute(
            select(StandaloneJob)
            .where(
                StandaloneJob.workspace_id == principal.workspace_id,
                StandaloneJob.attempts < 3,
                or_(
                    StandaloneJob.status == "queued",
                    (StandaloneJob.status == "leased")
                    & (StandaloneJob.lease_expires_at < now),
                ),
            )
            .order_by(StandaloneJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return {"job": None}
    token = secrets.token_urlsafe(32)
    row.status = "leased"
    row.phase = "Claude Code is working on this job"
    row.attempts += 1
    row.lease_hash = _hash(token)
    row.lease_expires_at = now + timedelta(minutes=LEASE_MINUTES)
    return {
        "job": {
            "id": str(row.id),
            "kind": row.kind,
            "prompt": row.input["prompt"],
            "lease_token": token,
            "expires_at": row.lease_expires_at,
        }
    }


async def _leased(
    db: AsyncSession, ws: uuid.UUID, job_id: uuid.UUID, lease_token: str
) -> StandaloneJob:
    row = (
        await db.execute(
            select(StandaloneJob)
            .where(StandaloneJob.id == job_id, StandaloneJob.workspace_id == ws)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if (
        row.status != "leased"
        or row.lease_hash != _hash(lease_token)
        or row.lease_expires_at is None
        or row.lease_expires_at.replace(tzinfo=UTC) < datetime.now(UTC)
    ):
        raise HTTPException(status_code=409, detail="Job lease is invalid or expired")
    return row


@router.post("/{job_id}/complete")
async def complete_job(
    job_id: uuid.UUID,
    body: JobCompletion,
    principal: Principal = Depends(require_scope("worker")),
    db: AsyncSession = Depends(get_db),
):
    row = await _leased(db, principal.workspace_id, job_id, body.lease_token)
    if row.kind == "scout":
        from tce.standalone.workflow import (
            IdeaDraft,
            _idea_json,
            _parse_json,
            generated_source,
        )

        parsed = _parse_json(body.output)
        if not isinstance(parsed, list) or not 1 <= len(parsed) <= 8:
            raise HTTPException(status_code=422, detail="Return 1 to 8 JSON ideas")
        refs = row.input.get("source_refs") or {}
        source_ids = {int(number): uuid.UUID(value) for number, value in refs.items()}
        web_lanes = set(row.input.get("web_lanes") or [])
        sources = {}
        for number, source_id in source_ids.items():
            source = (
                await db.execute(
                    select(StandaloneSourceItem).where(
                        StandaloneSourceItem.id == source_id,
                        StandaloneSourceItem.workspace_id == principal.workspace_id,
                        StandaloneSourceItem.active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if source is not None:
                sources[number] = source
        made = []
        for item in parsed:
            try:
                draft = IdeaDraft.model_validate(item)
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail="Idea fields are invalid") from exc
            source = await generated_source(
                db, principal.workspace_id, draft, sources, web_lanes
            )
            idea = StandaloneIdea(
                workspace_id=principal.workspace_id,
                source_item_id=source.id,
                lane_index=source.lane_index,
                title=draft.title,
                angle=draft.angle,
                why_now=draft.why_now,
                evidence=draft.evidence,
            )
            db.add(idea)
            await db.flush()
            made.append(_idea_json(idea, source.url, source.title))
        row.result = {"ideas": made, "sources_considered": len(refs)}
    elif row.kind == "script":
        script = body.output.strip()
        if not 20 <= len(script) <= 30000:
            raise HTTPException(status_code=422, detail="Script must be 20 to 30000 characters")
        idea_id = uuid.UUID(row.input["idea_id"])
        idea = (
            await db.execute(
                select(StandaloneIdea).where(
                    StandaloneIdea.id == idea_id,
                    StandaloneIdea.workspace_id == principal.workspace_id,
                )
            )
        ).scalar_one_or_none()
        if idea is None:
            raise HTTPException(status_code=409, detail="Script idea was removed")
        latest = (
            await db.execute(
                select(StandaloneScriptVersion.version)
                .where(
                    StandaloneScriptVersion.workspace_id == principal.workspace_id,
                    StandaloneScriptVersion.idea_id == idea_id,
                )
                .order_by(StandaloneScriptVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        version = (latest or 0) + 1
        db.add(
            StandaloneScriptVersion(
                workspace_id=principal.workspace_id,
                idea_id=idea_id,
                version=version,
                script=script,
                origin="claude_code",
            )
        )
        row.result = {"idea_id": str(idea_id), "version": version, "script": script}
    elif row.kind == "live_reply":
        from tce.standalone.live import parse_live_reply

        row.result = await parse_live_reply(
            db,
            principal.workspace_id,
            row.input["mode"],
            uuid.UUID(row.input["context_id"]) if row.input.get("context_id") else None,
            body.output,
        )
    elif row.kind == "talk_reply":
        from tce.standalone.live import parse_live_reply

        context_id = uuid.UUID(row.input["context_id"]) if row.input.get("context_id") else None
        row.result = await parse_live_reply(
            db, principal.workspace_id, row.input["mode"], context_id, body.output
        )
        db.add_all([
            StandaloneChatMessage(
                workspace_id=principal.workspace_id,
                context=row.input["mode"],
                context_id=context_id,
                role=role,
                content=content,
            )
            for role, content in (
                ("client", row.input["message"]),
                ("assistant", row.result["answer"]),
            )
        ])
    else:
        raise HTTPException(status_code=409, detail="Job kind is not supported")
    row.status = "done"
    row.phase = "Ready to review"
    row.lease_hash = None
    row.lease_expires_at = None
    await db.flush()
    return _public(row)


@router.post("/{job_id}/fail")
async def fail_job(
    job_id: uuid.UUID,
    body: JobFailure,
    principal: Principal = Depends(require_scope("worker")),
    db: AsyncSession = Depends(get_db),
):
    row = await _leased(db, principal.workspace_id, job_id, body.lease_token)
    row.status = "failed"
    row.phase = "Claude Code needs attention. Retry this card after fixing the connection."
    row.error_code = body.error_code
    row.lease_hash = None
    row.lease_expires_at = None
    return _public(row)


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: uuid.UUID,
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(StandaloneJob).where(
                StandaloneJob.id == job_id,
                StandaloneJob.workspace_id == principal.workspace_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if row.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried")
    row.status = "queued"
    row.phase = "Waiting for your Claude Code worker"
    row.attempts = 0
    row.error_code = None
    return _public(row)


@router.get("/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(StandaloneJob).where(
                StandaloneJob.id == job_id,
                StandaloneJob.workspace_id == principal.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _public(row)
