"""/llm-jobs routes: subscription worker lease/heartbeat/complete/fail + dashboard reads.

Every route requires the private access key. State transitions live in
``tce.llm.queue``; this module only maps them to HTTP.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tce.api.private_access import require_private_access
from tce.db.session import get_db
from tce.llm import queue
from tce.settings import settings

router = APIRouter(
    prefix="/llm-jobs",
    tags=["llm-jobs"],
    dependencies=[Depends(require_private_access)],
)

MIN_LEASE_SECONDS = 30
MAX_LEASE_SECONDS = 3600
WORKER_STALE_SECONDS = 180

# A lease request that asks to wait (newer workers send wait_seconds) is held until
# a job can be leased, at most this long, then answered like any lease. Without
# wait_seconds the answer comes at once, exactly as before.
LEASE_WAIT_MAX_S = 25.0
# A held request wakes when this process queues a job, and also looks again this
# often, so a job queued by another process or freed by the clock is found too.
LEASE_LOOK_AGAIN_S = 1.5
# Each worker process holds at most one request (the PC runs three). Beyond this
# many held at once, a request is answered at once, as before.
MAX_HELD_LEASES = 8


class LeaseBody(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)
    lease_seconds: int | None = None
    wait_seconds: float | None = None


class HeartbeatBody(BaseModel):
    attempt_id: uuid.UUID
    lease_seconds: int | None = None


class CompleteBody(BaseModel):
    attempt_id: uuid.UUID
    result_text: str | None = None
    result_json: Any | None = None
    receipt: dict[str, Any] = Field(default_factory=dict)


class FailBody(BaseModel):
    attempt_id: uuid.UUID
    error_code: str = Field(min_length=1, max_length=60)
    error_detail: str | None = None
    retry_at: datetime | None = None
    receipt: dict[str, Any] | None = None


def _lease_seconds(value: int | None) -> int:
    seconds = value or settings.llm_job_lease_seconds
    return max(MIN_LEASE_SECONDS, min(int(seconds), MAX_LEASE_SECONDS))


def _wait_seconds(value: float | None) -> float:
    if not value or value != value or value <= 0:  # absent, zero, negative or NaN
        return 0.0
    return min(float(value), LEASE_WAIT_MAX_S)


def _map_errors(exc: queue.QueueError) -> HTTPException:
    if isinstance(exc, queue.JobNotFoundError):
        return HTTPException(status_code=404, detail="LLM job not found")
    return HTTPException(status_code=409, detail=str(exc))


# ---------------------------------------------------------------------------
# Worker preflight status (no secrets: allow-listed keys only)
# ---------------------------------------------------------------------------

WORKER_STATUS_KEYS = frozenset(
    {
        "worker_id",
        "worker_host",
        "ok",
        "reason",
        "checked_at",
        "logged_in",
        "auth_method",
        "api_provider",
        "subscription_type",
        "cli_version",
        "policy_model",
        "env_violations",
        "state",
        "current_job_id",
    }
)
_status_lock = threading.Lock()
_worker_status: dict[str, dict[str, Any]] = {}


def _status_path() -> Path:
    return Path(tempfile.gettempdir()) / "tce-llm-worker-status.json"


def _load_status_file() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_status_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_worker_status(payload: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in payload.items() if k in WORKER_STATUS_KEYS}
    worker_id = str(clean.get("worker_id") or "unknown")[:120]
    clean["worker_id"] = worker_id
    clean["received_at"] = queue.utcnow().isoformat() + "Z"
    with _status_lock:
        if not _worker_status:
            _worker_status.update(_load_status_file())
        _worker_status[worker_id] = clean
        try:
            _status_path().write_text(json.dumps(_worker_status, default=str), encoding="utf-8")
        except OSError:
            pass
    return clean


@router.post("/worker-status")
async def post_worker_status(payload: dict[str, Any]) -> dict[str, Any]:
    return record_worker_status(payload)


@router.get("/worker-status")
async def get_worker_status() -> dict[str, Any]:
    with _status_lock:
        if not _worker_status:
            _worker_status.update(_load_status_file())
        workers = [dict(worker) for worker in _worker_status.values()]
    now = queue.utcnow().replace(tzinfo=UTC)
    for worker in workers:
        raw = str(worker.get("received_at") or "")
        try:
            received = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            age_s = max(0, int((now - received.astimezone(UTC)).total_seconds()))
        except ValueError:
            age_s = WORKER_STALE_SECONDS + 1
        stale = age_s > WORKER_STALE_SECONDS
        worker["age_seconds"] = age_s
        worker["stale"] = stale
        worker["current_state"] = "offline" if stale else str(worker.get("state") or "unknown")
    workers.sort(key=lambda w: str(w.get("received_at") or ""), reverse=True)
    return {"workers": workers, "latest": workers[0] if workers else None}


# ---------------------------------------------------------------------------
# Worker routes
# ---------------------------------------------------------------------------


@router.post("/lease")
async def lease(
    body: LeaseBody, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    lease_seconds = _lease_seconds(body.lease_seconds)
    wait_s = _wait_seconds(body.wait_seconds)
    if wait_s > 0:
        job = await _lease_or_hold(request, db, body.worker_id, lease_seconds, wait_s)
    else:
        job = await queue.lease_job(db, body.worker_id, lease_seconds)
    if job is None:
        return {"job": None}
    await db.commit()
    return {"job": queue.job_to_dict(job, include_request=True, include_result=False)}


async def _lease_or_hold(
    request: Request, db: AsyncSession, worker_id: str, lease_seconds: int, wait_s: float
) -> Any:
    """Lease like any request; when nothing is leasable, hold the request until a job
    can be leased, ``wait_s`` runs out or the client goes away.

    Each look is ``queue.lease_job`` in its own short transaction, so every lease
    rule applies to every look, and no connection or transaction is held across
    the wait. A job leased in the moment its client went away is rolled back: it
    stays exactly as it was for the next worker.
    """
    waiter = queue.add_lease_waiter(MAX_HELD_LEASES)
    if waiter is None:
        # Enough requests are held already: answered at once, as before.
        return await queue.lease_job(db, worker_id, lease_seconds)
    gone = asyncio.Event()
    watcher = asyncio.create_task(_watch_disconnect(request, gone, waiter))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_s
    try:
        while True:
            waiter.clear()  # a job queued from here on wakes the wait below
            job = await queue.lease_job(db, worker_id, lease_seconds)
            if job is not None:
                if gone.is_set():
                    await db.rollback()
                    return None
                return job
            await db.commit()  # what the look changed is saved; the connection goes back
            db.expunge_all()  # the next look reads every row fresh
            remaining = deadline - loop.time()
            if gone.is_set() or remaining <= 0:
                return None
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(waiter.wait(), timeout=min(LEASE_LOOK_AGAIN_S, remaining))
            if gone.is_set():
                return None
    finally:
        watcher.cancel()
        queue.remove_lease_waiter(waiter)


async def _watch_disconnect(request: Request, gone: asyncio.Event, waiter: asyncio.Event) -> None:
    """Set ``gone`` (and wake the hold) the moment the client disconnects."""
    try:
        while True:
            message = await request.receive()
            if message.get("type") == "http.disconnect":
                break
    except Exception:  # noqa: BLE001 - a broken receive channel means nobody is there
        pass
    gone.set()
    waiter.set()


@router.post("/{job_id}/heartbeat")
async def heartbeat(
    job_id: uuid.UUID, body: HeartbeatBody, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        job = await queue.heartbeat(db, job_id, body.attempt_id, _lease_seconds(body.lease_seconds))
    except queue.QueueError as exc:
        raise _map_errors(exc) from exc
    return {"leased_until": job.leased_until.isoformat() + "Z" if job.leased_until else None}


@router.post("/{job_id}/complete")
async def complete(
    job_id: uuid.UUID, body: CompleteBody, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        job = await queue.complete_job(
            db,
            job_id,
            body.attempt_id,
            result_text=body.result_text,
            result_json=body.result_json,
            receipt=body.receipt,
        )
    except queue.QueueError as exc:
        raise _map_errors(exc) from exc
    return queue.job_to_dict(job)


@router.post("/{job_id}/fail")
async def fail(job_id: uuid.UUID, body: FailBody, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        job = await queue.fail_job(
            db,
            job_id,
            body.attempt_id,
            error_code=body.error_code,
            error_detail=body.error_detail,
            retry_at=body.retry_at,
            receipt=body.receipt,
        )
    except queue.QueueError as exc:
        raise _map_errors(exc) from exc
    return queue.job_to_dict(job)


# ---------------------------------------------------------------------------
# Dashboard reads
# ---------------------------------------------------------------------------


@router.get("/")
async def list_llm_jobs(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    jobs, counts = await queue.list_jobs(db, status=status, limit=limit)
    return {
        "jobs": [queue.job_to_dict(j, include_result=False) for j in jobs],
        "counts": counts,
    }


@router.get("/{job_id}")
async def get_llm_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    job = await queue.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="LLM job not found")
    return queue.job_to_dict(job, include_request=True)
