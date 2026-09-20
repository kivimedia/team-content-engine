"""State transitions for the subscription LLM job queue.

Pure async functions over an ``AsyncSession`` so the HTTP router, ``complete()``
and tests share one implementation. Functions flush; the caller commits.

    queued -> leased -> succeeded
                     -> queued            (retryable failure, attempts left)
                     -> failed            (policy/model/auth failure, or attempts exhausted)
                     -> waiting_capacity  (usage limit; leasable again at retry_at)
    leased with leased_until < now        (worker crashed) is leasable again.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tce.llm.provider import (
    POLICY_MODEL,
    LLMRequest,
    LLMUnavailable,
    canonical_json,
    compute_idempotency_key,
    compute_input_hash,
    is_policy_model,
    schema_hash,
    sha256_hex,
    validate_output,
)
from tce.models.content_run import WorkerGroupState
from tce.models.llm_job import LLMJob

logger = structlog.get_logger()

NON_RETRYABLE_ERRORS = frozenset({"policy_violation", "model_mismatch", "auth"})
# Subscription auth methods a receipt may prove. The worker enforces its own narrower
# allow-list (claude.ai by default; oauth_token only when explicitly enabled).
SUBSCRIPTION_AUTH_METHODS = frozenset({"claude.ai", "oauth_token"})
CAPACITY_ERROR = "capacity"
DEFAULT_CAPACITY_BACKOFF = timedelta(minutes=30)
MAX_REQUEUES_OF_FAILED = 1
WORKER_GROUP_KEY = "claude-subscription-opus-5"

# Receipt keys a worker may store. Anything else (emails, org ids, tokens) is dropped.
RECEIPT_ALLOWED_KEYS = frozenset(
    {
        "models",
        "policy_model",
        "policy_model_output_tokens",
        "auxiliary_models",
        "auth_method",
        "api_provider",
        "subscription_type",
        "api_key_source",
        "cli_version",
        "session_id",
        "duration_ms",
        "worker_host",
        "worker_id",
        "attempt_id",
        "is_error",
        "api_error_status",
        "num_turns",
        "stop_reason",
    }
)


class QueueError(Exception):
    pass


class JobNotFoundError(QueueError):
    pass


class IdempotencyConflictError(QueueError):
    """An existing job carries this idempotency key but was created from different
    input. Reusing its answer for the new input would be wrong, so it is refused."""


class StaleAttemptError(QueueError):
    """The attempt is not the job's current lease (another worker reclaimed it,
    or the job already finished under a different attempt/output)."""


def utcnow() -> datetime:
    """Naive UTC, matching the DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def get_job(session: AsyncSession, job_id: uuid.UUID | str) -> LLMJob | None:
    result = await session.execute(
        select(LLMJob)
        .where(LLMJob.id == _as_uuid(job_id))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def _get_by_key(session: AsyncSession, key: str) -> LLMJob | None:
    result = await session.execute(
        select(LLMJob)
        .where(LLMJob.idempotency_key == key)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


async def enqueue(
    session: AsyncSession, req: LLMRequest, *, requeue_failed: bool = False
) -> LLMJob:
    key = compute_idempotency_key(req)
    existing = await _get_by_key(session, key)
    if existing is None:
        job = LLMJob(
            job_type=req.job_type[:80],
            agent_name=req.agent_name[:80],
            status="queued",
            idempotency_key=key,
            request_json={
                "system": req.system,
                "messages": req.messages,
                "output_schema": req.output_schema,
                "max_tokens": req.max_tokens,
            },
            requested_model=req.requested_model,
            policy_model=POLICY_MODEL,
            prompt_version=req.prompt_version,
            input_hash=compute_input_hash(req),
            output_schema_hash=schema_hash(req.output_schema),
            run_id=req.run_id,
            workspace_id=req.workspace_id,
            attempt_count=0,
            max_attempts=3,
        )
        try:
            async with session.begin_nested():
                session.add(job)
                await session.flush()
            return job
        except IntegrityError:
            # Lost an insert race on the idempotency key: drop our pending row so
            # the lookup cannot autoflush it again, then use the winner's row.
            if job in session:
                session.expunge(job)
            existing = await _get_by_key(session, key)
            if existing is None:
                raise
    if existing.input_hash != compute_input_hash(req):
        raise IdempotencyConflictError(
            f"idempotency key already used by job {existing.id} with different input "
            "(job_type, system, messages, output_schema or prompt_version changed)"
        )
    if existing.status == "failed" and requeue_failed:
        _requeue_failed(existing)
        await session.flush()
    elif existing.status == "failed":
        raise LLMUnavailable(
            "failed",
            f"{existing.error_code}: {existing.error_detail or ''} (pass requeue_failed=True "
            "to re-queue once)",
            job_id=existing.id,
        )
    elif existing.status == "cancelled":
        raise LLMUnavailable("cancelled", "job was cancelled", job_id=existing.id)
    return existing


def _requeue_failed(job: LLMJob) -> None:
    if job.error_code in NON_RETRYABLE_ERRORS:
        raise LLMUnavailable(
            "failed",
            f"{job.error_code} failures are never re-queued: {job.error_detail or ''}",
            job_id=job.id,
        )
    request = dict(job.request_json or {})
    count = int(request.get("requeue_count") or 0)
    if count >= MAX_REQUEUES_OF_FAILED:
        raise LLMUnavailable(
            "failed", "job was already re-queued once and failed again", job_id=job.id
        )
    request["requeue_count"] = count + 1
    job.request_json = request
    job.status = "queued"
    job.attempt_count = 0
    job.attempt_id = None
    job.lease_owner = None
    job.leased_until = None
    job.retry_at = None
    job.error_code = None
    job.error_detail = None
    job.completed_at = None


# ---------------------------------------------------------------------------
# Lease
# ---------------------------------------------------------------------------


def _leasable_clause(now: datetime) -> Any:
    return or_(
        and_(LLMJob.status == "queued", or_(LLMJob.retry_at.is_(None), LLMJob.retry_at <= now)),
        and_(
            LLMJob.status == "waiting_capacity",
            or_(LLMJob.retry_at.is_(None), LLMJob.retry_at <= now),
        ),
        and_(LLMJob.status == "leased", LLMJob.leased_until < now),
    )


def _max_attempts_detail(job: LLMJob) -> str:
    prior = f" (last error {job.error_code}: {job.error_detail})" if job.error_code else ""
    return f"attempt {job.attempt_count + 1} exceeds max_attempts={job.max_attempts}{prior}"


async def lease_job(
    session: AsyncSession,
    worker_id: str,
    lease_seconds: int,
    *,
    now: datetime | None = None,
) -> LLMJob | None:
    """Atomically lease the oldest leasable job, or return None.

    PostgreSQL: ``SELECT ... FOR UPDATE SKIP LOCKED``. Other dialects: a
    compare-and-swap UPDATE guarded by the status/attempt the candidate was read with.
    """
    now = now or utcnow()
    group = (
        await session.execute(
            select(WorkerGroupState).where(WorkerGroupState.group_key == WORKER_GROUP_KEY)
        )
    ).scalar_one_or_none()
    if group is not None:
        if group.state == "refused_policy":
            return None
        if group.state == "waiting_capacity" and group.retry_at and group.retry_at > now:
            return None
        if group.state == "waiting_capacity":
            group.state = "available"
            group.retry_at = None
            group.reason = "capacity retry time reached; next lease must verify subscription"
            await session.flush()
    dialect = session.bind.dialect.name if session.bind is not None else ""
    for _ in range(25):
        stmt = select(LLMJob).where(_leasable_clause(now)).order_by(LLMJob.created_at, LLMJob.id)
        if dialect == "postgresql":
            stmt = stmt.limit(1).with_for_update(skip_locked=True)
        else:
            stmt = stmt.limit(1)
        result = await session.execute(stmt.execution_options(populate_existing=True))
        job = result.scalar_one_or_none()
        if job is None:
            return None

        new_count = (job.attempt_count or 0) + 1
        if new_count > (job.max_attempts or 0):
            values: dict[str, Any] = {
                "status": "failed",
                "error_code": "max_attempts",
                "error_detail": _max_attempts_detail(job),
                "leased_until": None,
                "completed_at": now,
            }
        else:
            values = {
                "status": "leased",
                "attempt_count": new_count,
                "attempt_id": uuid.uuid4(),
                "lease_owner": worker_id[:120],
                "leased_until": now + timedelta(seconds=lease_seconds),
                "heartbeat_at": now,
            }

        if dialect == "postgresql":
            for k, v in values.items():
                setattr(job, k, v)
            await session.flush()
            won = True
        else:
            guard = [LLMJob.id == job.id, LLMJob.status == job.status]
            guard.append(
                LLMJob.attempt_id.is_(None)
                if job.attempt_id is None
                else LLMJob.attempt_id == job.attempt_id
            )
            res = await session.execute(
                update(LLMJob)
                .where(*guard)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            won = res.rowcount == 1
            if won:
                await session.refresh(job)
        if not won:
            continue  # another worker took it between read and write
        if job.status == "failed":
            logger.warning("llm.job_max_attempts", job_id=str(job.id))
            continue
        logger.info(
            "llm.job_leased",
            job_id=str(job.id),
            worker_id=worker_id,
            attempt=job.attempt_count,
        )
        return job
    return None


def _require_current_attempt(job: LLMJob, attempt_id: uuid.UUID) -> None:
    if job.status != "leased" or job.attempt_id != attempt_id:
        raise StaleAttemptError(
            f"attempt {attempt_id} is not the current lease (status={job.status}, "
            f"current_attempt={job.attempt_id})"
        )


async def heartbeat(
    session: AsyncSession,
    job_id: uuid.UUID | str,
    attempt_id: uuid.UUID | str,
    lease_seconds: int,
    *,
    now: datetime | None = None,
) -> LLMJob:
    now = now or utcnow()
    job = await get_job(session, job_id)
    if job is None:
        raise JobNotFoundError(str(job_id))
    _require_current_attempt(job, _as_uuid(attempt_id))
    job.heartbeat_at = now
    job.leased_until = now + timedelta(seconds=lease_seconds)
    await session.flush()
    return job


# ---------------------------------------------------------------------------
# Complete / fail
# ---------------------------------------------------------------------------


def sanitize_receipt(receipt: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (receipt or {}).items() if k in RECEIPT_ALLOWED_KEYS}


def verify_receipt(receipt: dict[str, Any]) -> tuple[str, str] | None:
    """Return (error_code, detail) when the receipt breaks policy, else None."""
    source = receipt.get("api_key_source")
    if source != "none":
        return (
            "policy_violation",
            f"api_key_source={source!r}; only subscription auth (apiKeySource 'none') is allowed",
        )
    provider = receipt.get("api_provider")
    if provider != "firstParty":
        return ("policy_violation", f"api_provider={provider!r}; firstParty proof is required")
    auth_method = receipt.get("auth_method")
    if auth_method not in SUBSCRIPTION_AUTH_METHODS:
        return (
            "policy_violation",
            f"auth_method={auth_method!r}; subscription auth proof is required",
        )
    models = receipt.get("models")
    if not isinstance(models, dict) or not models:
        return ("model_mismatch", "receipt lists no models")
    policy_out = sum(
        int((usage or {}).get("output_tokens") or 0)
        for name, usage in models.items()
        if is_policy_model(name)
    )
    if policy_out <= 0:
        return (
            "model_mismatch",
            f"{POLICY_MODEL} produced no output tokens; models used: {sorted(models)}",
        )
    return None


def output_hash(result_text: str | None, result_json: Any) -> str:
    return sha256_hex(canonical_json({"text": result_text, "json": result_json}))


def _retryable_failure(job: LLMJob, code: str, detail: str, now: datetime) -> None:
    job.error_code = code[:60]
    job.error_detail = detail
    job.leased_until = None
    if (job.attempt_count or 0) >= (job.max_attempts or 0):
        job.status = "failed"
        job.error_detail = (
            f"max_attempts reached ({job.attempt_count}/{job.max_attempts}): {detail}"
        )
        job.completed_at = now
    else:
        job.status = "queued"


async def complete_job(
    session: AsyncSession,
    job_id: uuid.UUID | str,
    attempt_id: uuid.UUID | str,
    *,
    result_text: str | None,
    result_json: Any,
    receipt: dict[str, Any] | None,
    now: datetime | None = None,
) -> LLMJob:
    now = now or utcnow()
    attempt = _as_uuid(attempt_id)
    job = await get_job(session, job_id)
    if job is None:
        raise JobNotFoundError(str(job_id))

    digest = output_hash(result_text, result_json)
    if job.status == "succeeded" and job.attempt_id == attempt:
        if job.output_hash == digest:
            return job  # same attempt re-sent the same output: idempotent
        raise StaleAttemptError("job already completed by this attempt with a different output")
    _require_current_attempt(job, attempt)

    clean = sanitize_receipt(receipt)
    clean["attempt_id"] = str(attempt)
    violation = verify_receipt(clean)
    if violation is not None:
        code, detail = violation
        job.status = "failed"
        job.error_code = code
        job.error_detail = detail
        job.receipt_json = clean
        job.leased_until = None
        job.completed_at = now
        await session.flush()
        logger.error("llm.job_policy_failure", job_id=str(job.id), code=code, detail=detail)
        return job

    schema = (job.request_json or {}).get("output_schema")
    if schema is not None:
        structured = result_json
        if structured is None and result_text:
            try:
                structured = json.loads(result_text)
            except json.JSONDecodeError:
                structured = None
        errors = (
            ["no JSON output"] if structured is None else validate_output(structured, schema)
        )
        if errors:
            job.receipt_json = clean
            _retryable_failure(job, "invalid_json", "; ".join(errors)[:2000], now)
            await session.flush()
            return job
        result_json = structured

    job.status = "succeeded"
    job.result_text = result_text
    job.result_json = result_json
    job.output_hash = digest
    job.receipt_json = clean
    job.error_code = None
    job.error_detail = None
    job.leased_until = None
    job.retry_at = None
    job.completed_at = now
    await session.flush()
    return job


async def fail_job(
    session: AsyncSession,
    job_id: uuid.UUID | str,
    attempt_id: uuid.UUID | str,
    *,
    error_code: str,
    error_detail: str | None = None,
    retry_at: datetime | None = None,
    receipt: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> LLMJob:
    now = now or utcnow()
    attempt = _as_uuid(attempt_id)
    job = await get_job(session, job_id)
    if job is None:
        raise JobNotFoundError(str(job_id))
    if job.attempt_id == attempt and job.status != "leased" and job.error_code == error_code[:60]:
        return job  # retried fail report for the same attempt
    _require_current_attempt(job, attempt)
    if retry_at is not None and retry_at.tzinfo is not None:
        retry_at = retry_at.astimezone(UTC).replace(tzinfo=None)
    detail = (error_detail or "")[:4000]
    if receipt:
        clean = sanitize_receipt(receipt)
        clean["attempt_id"] = str(attempt)
        job.receipt_json = clean

    if error_code == CAPACITY_ERROR:
        job.status = "waiting_capacity"
        job.error_code = CAPACITY_ERROR
        job.error_detail = detail
        job.retry_at = retry_at if retry_at and retry_at > now else now + DEFAULT_CAPACITY_BACKOFF
        job.leased_until = None
        # Capacity is not the job's fault: do not spend one of its attempts.
        job.attempt_count = max(0, (job.attempt_count or 0) - 1)
        group = (
            await session.execute(
                select(WorkerGroupState).where(WorkerGroupState.group_key == WORKER_GROUP_KEY)
            )
        ).scalar_one_or_none()
        if group is None:
            group = WorkerGroupState(group_key=WORKER_GROUP_KEY)
            session.add(group)
        group.state = "waiting_capacity"
        group.retry_at = job.retry_at
        group.reason = detail
        group.receipt = sanitize_receipt(receipt)
    elif error_code in NON_RETRYABLE_ERRORS:
        job.status = "failed"
        job.error_code = error_code
        job.error_detail = detail
        job.leased_until = None
        job.completed_at = now
        group = (
            await session.execute(
                select(WorkerGroupState).where(WorkerGroupState.group_key == WORKER_GROUP_KEY)
            )
        ).scalar_one_or_none()
        if group is None:
            group = WorkerGroupState(group_key=WORKER_GROUP_KEY)
            session.add(group)
        group.state = "refused_policy"
        group.retry_at = None
        group.reason = f"{error_code}: {detail}"
        group.receipt = sanitize_receipt(receipt)
    else:
        _retryable_failure(job, error_code, detail, now)
    await session.flush()
    return job


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt is not None else None


def job_to_dict(job: LLMJob, *, include_request: bool = False, include_result: bool = True) -> dict:
    data: dict[str, Any] = {
        "id": str(job.id),
        "job_type": job.job_type,
        "agent_name": job.agent_name,
        "status": job.status,
        "policy_model": job.policy_model,
        "requested_model": job.requested_model,
        "prompt_version": job.prompt_version,
        "run_id": str(job.run_id) if job.run_id else None,
        "workspace_id": str(job.workspace_id) if job.workspace_id else None,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "attempt_id": str(job.attempt_id) if job.attempt_id else None,
        "lease_owner": job.lease_owner,
        "leased_until": _iso(job.leased_until),
        "heartbeat_at": _iso(job.heartbeat_at),
        "retry_at": _iso(job.retry_at),
        "error_code": job.error_code,
        "error_detail": job.error_detail,
        "created_at": _iso(job.created_at),
        "completed_at": _iso(job.completed_at),
        "receipt": job.receipt_json,
        "input_hash": job.input_hash,
        "output_hash": job.output_hash,
    }
    if include_request:
        data["request_json"] = job.request_json
    if include_result:
        data["result_text"] = job.result_text
        data["result_json"] = job.result_json
    return data


async def list_jobs(
    session: AsyncSession, *, status: str | None = None, limit: int = 50
) -> tuple[list[LLMJob], dict[str, int]]:
    stmt = select(LLMJob).order_by(LLMJob.created_at.desc()).limit(max(1, min(limit, 500)))
    if status:
        stmt = stmt.where(LLMJob.status == status)
    jobs = list((await session.execute(stmt)).scalars().all())
    counts_rows = await session.execute(select(LLMJob.status, func.count()).group_by(LLMJob.status))
    counts = {row[0]: int(row[1]) for row in counts_rows.all()}
    return jobs, counts
