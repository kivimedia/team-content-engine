"""/evidence routes. Owned by its work package; every route depends on private access.

Every query filters `workspace_id == ws` explicitly. Collection and extraction run in
background tasks with their own DB sessions and return immediately. List endpoints
never return `payload_private`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tce.api.private_access import require_private_workspace
from tce.evidence import collect as collect_mod
from tce.evidence import moments as moments_mod
from tce.evidence.common import as_utc, to_db
from tce.models.editorial import EvidenceCollectionRun, EvidenceMoment, EvidenceSource

logger = structlog.get_logger()

router = APIRouter(prefix="/evidence", tags=["evidence"])

MAX_WINDOW = timedelta(days=93)


def get_evidence_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Sessionmaker used by these routes and their background tasks (overridable in tests)."""
    from tce.db.session import async_session

    return async_session


class CollectRequest(BaseModel):
    kinds: list[str] = Field(default_factory=lambda: ["fathom", "github"])
    window_start: datetime
    window_end: datetime


class ExtractRequest(BaseModel):
    window_start: datetime
    window_end: datetime


def _check_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start, end = as_utc(start), as_utc(end)
    if end <= start:
        raise HTTPException(status_code=422, detail="window_end must be after window_start")
    if end - start > MAX_WINDOW:
        raise HTTPException(status_code=422, detail="window is longer than 93 days")
    return start, end


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def run_json(run: EvidenceCollectionRun, *, include_items: bool = True) -> dict[str, Any]:
    data = {
        "id": str(run.id),
        "source_kind": run.source_kind,
        "window_start": _iso(run.window_start),
        "window_end": _iso(run.window_end),
        "status": run.status,
        "counts": run.counts or {},
        "errors": run.errors or [],
        "complete": run.complete,
        "current_activity": run.current_activity,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }
    if include_items:
        data["items"] = run.items or []
    return data


def source_json(src: EvidenceSource, *, include_payload: bool = False) -> dict[str, Any]:
    data = {
        "id": str(src.id),
        "source_kind": src.source_kind,
        "external_id": src.external_id,
        "title": src.title,
        "occurred_at": _iso(src.occurred_at),
        "fetched_at": _iso(src.fetched_at),
        "source_updated_at": _iso(src.source_updated_at),
        "version_hash": src.version_hash,
        "revision": src.revision,
        "fetch_status": src.fetch_status,
        "fetch_error": src.fetch_error,
        "language": src.language,
        "url_private": src.url_private,
        "meta": src.meta or {},
        "last_collection_run_id": str(src.last_collection_run_id)
        if src.last_collection_run_id else None,
    }
    if include_payload:
        data["payload_private"] = src.payload_private
    return data


def moment_json(m: EvidenceMoment) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "source_id": str(m.source_id),
        "source_version_hash": m.source_version_hash,
        "span_start_s": m.span_start_s,
        "span_end_s": m.span_end_s,
        "code_refs": m.code_refs,
        "speaker": m.speaker,
        "speaker_confidence": m.speaker_confidence,
        "language": m.language,
        "translation_label": m.translation_label,
        "language_uncertain": m.language_uncertain,
        "excerpt_private": m.excerpt_private,
        "context_private": m.context_private,
        "lesson_summary": m.lesson_summary,
        "claim_type": m.claim_type,
        "sensitivity_flags": m.sensitivity_flags or [],
        "status": m.status,
        "extraction_job_id": str(m.extraction_job_id) if m.extraction_job_id else None,
        "created_at": _iso(m.created_at),
    }


async def _run_collector(
    kind: str,
    sessionmaker: async_sessionmaker[AsyncSession],
    ws: uuid.UUID,
    start: datetime,
    end: datetime,
    run_id: uuid.UUID,
) -> None:
    fn = collect_mod.collect_fathom if kind == "fathom" else collect_mod.collect_github
    try:
        await fn(sessionmaker, ws, start, end, run_id=run_id)
    except Exception as exc:  # the collector records its own failures; this is a last guard
        logger.error("evidence.collect.crashed", kind=kind, error_type=type(exc).__name__)


async def _run_extraction(
    sessionmaker: async_sessionmaker[AsyncSession],
    ws: uuid.UUID,
    start: datetime,
    end: datetime,
    run_id: uuid.UUID,
) -> None:
    try:
        await moments_mod.extract_moments(sessionmaker, ws, start, end, run_id=run_id)
    except Exception as exc:
        logger.error("evidence.extract.crashed", error_type=type(exc).__name__)


@router.post("/collect")
async def start_collection(
    body: CollectRequest,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_evidence_sessionmaker),
) -> dict[str, Any]:
    start, end = _check_window(body.window_start, body.window_end)
    kinds = list(dict.fromkeys(body.kinds))
    unknown = [k for k in kinds if k not in collect_mod.RUN_KIND_BY_NAME]
    if unknown or not kinds:
        raise HTTPException(status_code=422, detail="kinds must be fathom and/or github")
    run_ids = []
    for kind in kinds:
        run_id = await collect_mod.RunLedger.create_run(
            sessionmaker, ws, collect_mod.RUN_KIND_BY_NAME[kind], start, end
        )
        run_ids.append(str(run_id))
        background.add_task(_run_collector, kind, sessionmaker, ws, start, end, run_id)
    return {"run_ids": run_ids}


@router.get("/runs")
async def list_runs(
    limit: int = Query(20, ge=1, le=200),
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_evidence_sessionmaker),
) -> dict[str, Any]:
    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(EvidenceCollectionRun)
                .where(EvidenceCollectionRun.workspace_id == ws)
                .order_by(EvidenceCollectionRun.started_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    return {"runs": [run_json(r, include_items=False) for r in rows]}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_evidence_sessionmaker),
) -> dict[str, Any]:
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(EvidenceCollectionRun).where(
                    EvidenceCollectionRun.id == run_id,
                    EvidenceCollectionRun.workspace_id == ws,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_json(row)


@router.get("/coverage")
async def coverage(
    window_start: datetime,
    window_end: datetime,
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_evidence_sessionmaker),
) -> dict[str, Any]:
    start, end = _check_window(window_start, window_end)
    out: dict[str, Any] = {}
    async with sessionmaker() as session:
        for kind in (*collect_mod.RUN_KIND_BY_NAME.values(), moments_mod.EXTRACTION_RUN_KIND):
            row = (
                await session.execute(
                    select(EvidenceCollectionRun)
                    .where(
                        EvidenceCollectionRun.workspace_id == ws,
                        EvidenceCollectionRun.source_kind == kind,
                        EvidenceCollectionRun.window_start == to_db(start),
                        EvidenceCollectionRun.window_end == to_db(end),
                    )
                    .order_by(EvidenceCollectionRun.started_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            out[kind] = run_json(row) if row else None
    return {"window_start": start.isoformat(), "window_end": end.isoformat(), "coverage": out}


@router.get("/sources")
async def list_sources(
    kind: str | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    limit: int = Query(500, ge=1, le=2000),
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_evidence_sessionmaker),
) -> dict[str, Any]:
    stmt = select(EvidenceSource).where(EvidenceSource.workspace_id == ws)
    if kind:
        stmt = stmt.where(EvidenceSource.source_kind == kind)
    if window_start:
        stmt = stmt.where(EvidenceSource.occurred_at >= to_db(window_start))
    if window_end:
        stmt = stmt.where(EvidenceSource.occurred_at < to_db(window_end))
    async with sessionmaker() as session:
        rows = (
            await session.execute(stmt.order_by(EvidenceSource.occurred_at.desc()).limit(limit))
        ).scalars().all()
    return {"sources": [source_json(r) for r in rows]}


@router.get("/sources/{source_id}")
async def get_source(
    source_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_evidence_sessionmaker),
) -> dict[str, Any]:
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(EvidenceSource).where(
                    EvidenceSource.id == source_id, EvidenceSource.workspace_id == ws
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source_json(row, include_payload=True)


@router.post("/extract")
async def start_extraction(
    body: ExtractRequest,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_evidence_sessionmaker),
) -> dict[str, Any]:
    start, end = _check_window(body.window_start, body.window_end)
    async with sessionmaker() as session:
        pending = await moments_mod.sources_needing_extraction(session, ws, start, end)
    pending = [s for s in pending if moments_mod.skip_reason(s) is None]
    if not pending:
        return {"started": False, "run_id": None, "job_ids": [], "sources": 0}
    run_id = await collect_mod.RunLedger.create_run(
        sessionmaker, ws, moments_mod.EXTRACTION_RUN_KIND, start, end
    )
    background.add_task(_run_extraction, sessionmaker, ws, start, end, run_id)
    # LLM job ids are created as the background run reaches each source; they appear in
    # GET /evidence/runs/{run_id} items[].job_ids and /api/v1/llm-jobs.
    return {"started": True, "run_id": str(run_id), "job_ids": [], "sources": len(pending)}


@router.get("/moments")
async def list_moments(
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    status: str | None = None,
    source_id: uuid.UUID | None = None,
    limit: int = Query(500, ge=1, le=2000),
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_evidence_sessionmaker),
) -> dict[str, Any]:
    stmt = (
        select(EvidenceMoment, EvidenceSource)
        .join(EvidenceSource, EvidenceSource.id == EvidenceMoment.source_id)
        .where(EvidenceMoment.workspace_id == ws, EvidenceSource.workspace_id == ws)
    )
    if status:
        stmt = stmt.where(EvidenceMoment.status == status)
    if source_id:
        stmt = stmt.where(EvidenceMoment.source_id == source_id)
    if window_start:
        stmt = stmt.where(EvidenceSource.occurred_at >= to_db(window_start))
    if window_end:
        stmt = stmt.where(EvidenceSource.occurred_at < to_db(window_end))
    async with sessionmaker() as session:
        rows = (
            await session.execute(stmt.order_by(EvidenceSource.occurred_at.desc()).limit(limit))
        ).all()
    out = []
    for moment, source in rows:
        data = moment_json(moment)
        data.update({
            "source_kind": source.source_kind,
            "source_title": source.title,
            "occurred_at": _iso(source.occurred_at),
            "url_private": source.url_private,
        })
        out.append(data)
    return {"moments": out}
