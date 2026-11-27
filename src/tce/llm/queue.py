"""State transitions for the subscription LLM job queue.

Pure async functions over an ``AsyncSession`` so the HTTP router, ``complete()``
and tests share one implementation. Functions flush; the caller commits.

    queued -> leased -> succeeded
                     -> queued            (retryable failure, attempts left)
                     -> failed            (policy/model/auth failure, or attempts exhausted)
                     -> waiting_capacity  (usage limit; leasable again at retry_at)
    leased with leased_until < now        (worker crashed) is leasable again.

Two lanes decide only which leasable job goes next: a job a person is waiting on
(INTERACTIVE_JOB_TYPES) before batch work, each lane oldest first.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, case, event, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

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
# The desktop workers on the owner's PC share one Claude login, so they park and
# resume together. Their key is unchanged so a parked row from before survives.
WORKER_GROUP_KEY = "claude-subscription-opus-5"
# 23-Nov-2026 (T-24600): the server's own worker writes through the team's pool of
# subscriptions and moves to the next one with room, like the KM BOT agents. It is
# its own group: one login reaching its limit never stops the other.
POOL_GROUP_KEY = "claude-subscription-pool"
POOL_WORKER_PREFIX = "vps-pool"
# A group counts as present while its workers asked for work this recently.
GROUP_LIVE_SECONDS = 180

# Jobs a person is waiting on (23-Nov-2026: "his job must not sit behind a batch of
# research jobs"): a conversation, a script he asked for with its voice pass, slip
# check, openings and each opening's script, an edit he typed, a sitting of notes,
# the editor's review and checks of his video, its Creatorz moments, the rule a note
# teaches, the post copy. They are leased before batch work (evidence, selection,
# news appraisal, the old pipeline agents). The lane changes ORDER only: who may
# lease, the lease, retries and capacity parking are the same in both lanes, and
# each lane keeps its oldest-first order. Any type not named here, a new one
# included, is batch. No column: the lane is read from job_type at lease time.
INTERACTIVE_JOB_TYPES = frozenset(
    {
        "editorial_conversation",
        "recording_packet",
        "recording_packet_voice",
        "recording_packet_hooks",
        "recording_packet_hook_scripts",
        "hook_video_match",
        "format_script",
        "recording_script_slips",
        "video_edit_request",
        "video_edit_batch",
        "video_edit_review",
        "video_qc_asides",
        "video_creatorz_moments",
        "video_post_copy",
        "video_post_revise",
        "editor_rule_distill",
    }
)

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


def group_for_worker(worker_id: str | None) -> str:
    """Which subscription group a worker belongs to: the pool worker on the server,
    or the desktop group every other worker id has always been part of."""
    if (worker_id or "").startswith(POOL_WORKER_PREFIX):
        return POOL_GROUP_KEY
    return WORKER_GROUP_KEY


async def _group_row(session: AsyncSession, key: str, *, create: bool) -> WorkerGroupState | None:
    row = (
        await session.execute(select(WorkerGroupState).where(WorkerGroupState.group_key == key))
    ).scalar_one_or_none()
    if row is None and create:
        row = WorkerGroupState(group_key=key, state="available")
        session.add(row)
    return row


def group_has_room(row: WorkerGroupState, now: datetime) -> bool:
    """Not parked on a limit and not refused."""
    if row.state == "refused_policy":
        return False
    return not (row.state == "waiting_capacity" and row.retry_at and row.retry_at > now)


def group_is_live(row: WorkerGroupState, now: datetime) -> bool:
    return bool(row.heartbeat_at and row.heartbeat_at >= now - timedelta(seconds=GROUP_LIVE_SECONDS))


async def _another_group_has_room(session: AsyncSession, key: str, now: datetime) -> bool:
    rows = {
        r.group_key: r for r in (await session.execute(select(WorkerGroupState))).scalars().all()
    }
    for other, row in rows.items():
        if other == key:
            continue
        present = other == WORKER_GROUP_KEY or group_is_live(row, now)
        if present and group_has_room(row, now):
            return True
    # The desktop group has no row until it first parks: no row is a group with room.
    return key != WORKER_GROUP_KEY and WORKER_GROUP_KEY not in rows


async def capacity_park_until(session: AsyncSession, *, now: datetime | None = None) -> datetime | None:
    """Until when no subscription group can write, or None while one can.

    The desktop group always counts (it is the original writer and its row is what
    a park was always read from); any other group counts while its worker is live.
    Parked means every counted group is parked; the earliest of them resumes first.
    """
    now = now or utcnow()
    rows = list((await session.execute(select(WorkerGroupState))).scalars().all())
    if not any(r.group_key == WORKER_GROUP_KEY for r in rows):
        return None  # the desktop group has never parked: it has room
    counted = [
        r for r in rows if r.group_key == WORKER_GROUP_KEY or group_is_live(r, now)
    ]
    if any(group_has_room(r, now) for r in counted):
        return None
    parked = [
        r.retry_at
        for r in counted
        if r.state == "waiting_capacity" and r.retry_at and r.retry_at > now
    ]
    return min(parked) if parked else None


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
    from tce.llm.provider import localize_request

    req = localize_request(req)  # a Hebrew workspace's jobs carry its language line
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
            session.info[_QUEUED_FLAG] = True  # held lease requests wake on commit
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
        session.info[_QUEUED_FLAG] = True
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
# Lease wake
# ---------------------------------------------------------------------------

# A lease request held open by the router (a worker asked to wait) sleeps on one
# of these events. A commit that queued a job (enqueue sets the flag on its
# session) sets them all. Only this process can reach them: a job queued by a
# script or another process is found because a held request also looks again
# every couple of seconds.
_QUEUED_FLAG = "tce_llm_job_queued"
_waiters_lock = threading.Lock()
_waiters: dict[asyncio.Event, asyncio.AbstractEventLoop] = {}


def add_lease_waiter(limit: int) -> asyncio.Event | None:
    """A new wake event for a held lease request, or None when ``limit`` are held."""
    loop = asyncio.get_running_loop()
    with _waiters_lock:
        if len(_waiters) >= limit:
            return None
        waiter = asyncio.Event()
        _waiters[waiter] = loop
        return waiter


def remove_lease_waiter(waiter: asyncio.Event) -> None:
    with _waiters_lock:
        _waiters.pop(waiter, None)


def held_lease_count() -> int:
    with _waiters_lock:
        return len(_waiters)


def wake_lease_waiters() -> int:
    """Wake every held lease request. Safe from any thread; returns how many."""
    with _waiters_lock:
        items = list(_waiters.items())
    for waiter, loop in items:
        with contextlib.suppress(RuntimeError):  # that loop has closed
            loop.call_soon_threadsafe(waiter.set)
    return len(items)


@event.listens_for(Session, "after_commit")
def _wake_after_commit(session: Session) -> None:
    # A savepoint released inside a longer transaction does not make the row
    # visible to another session yet; the outer commit does.
    if session.in_nested_transaction():
        return
    if session.info.pop(_QUEUED_FLAG, False):
        wake_lease_waiters()


@event.listens_for(Session, "after_rollback")
def _forget_after_rollback(session: Session) -> None:
    session.info.pop(_QUEUED_FLAG, None)


# ---------------------------------------------------------------------------
# Lease
# ---------------------------------------------------------------------------


def job_lane(job_type: str | None) -> str:
    return "interactive" if job_type in INTERACTIVE_JOB_TYPES else "batch"


def _lane_order() -> Any:
    """First lease sort key: 0 for a job a person is waiting on, 1 for batch."""
    return case((LLMJob.job_type.in_(sorted(INTERACTIVE_JOB_TYPES)), 0), else_=1)


def _parked_by_other_group(group_key: str) -> Any:
    pool_owned = LLMJob.lease_owner.like(f"{POOL_WORKER_PREFIX}%")
    if group_key == POOL_GROUP_KEY:
        return or_(LLMJob.lease_owner.is_(None), ~pool_owned)
    return and_(LLMJob.lease_owner.is_not(None), pool_owned)


def _leasable_clause(now: datetime, group_key: str = WORKER_GROUP_KEY) -> Any:
    return or_(
        and_(LLMJob.status == "queued", or_(LLMJob.retry_at.is_(None), LLMJob.retry_at <= now)),
        and_(
            LLMJob.status == "waiting_capacity",
            or_(
                LLMJob.retry_at.is_(None),
                LLMJob.retry_at <= now,
                # A job parked on one group's limit waits for its time in THAT group
                # only; a group that did not hit the limit takes it at once (T-24600).
                _parked_by_other_group(group_key),
            ),
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

    A leasable interactive job goes before any leasable batch job; within a lane the
    oldest goes first, as before. A job that is already leased is never touched.

    PostgreSQL: ``SELECT ... FOR UPDATE SKIP LOCKED``. Other dialects: a
    compare-and-swap UPDATE guarded by the status/attempt the candidate was read with.
    """
    now = now or utcnow()
    key = group_for_worker(worker_id)
    group = await _group_row(session, key, create=key != WORKER_GROUP_KEY)
    if group is not None and key != WORKER_GROUP_KEY:
        # The pool group says it is present on every ask, parked or not, so a reader
        # can tell "parked" from "gone" without a separate status feed.
        group.heartbeat_at = now
        await session.flush()
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
        stmt = (
            select(LLMJob)
            .where(_leasable_clause(now, key))
            .order_by(_lane_order(), LLMJob.created_at, LLMJob.id)
        )
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
        key = group_for_worker(job.lease_owner)
        group = await _group_row(session, key, create=True)
        group.state = "waiting_capacity"
        group.retry_at = job.retry_at
        group.reason = detail
        group.receipt = sanitize_receipt(receipt)
        await session.flush()
        # Only this group is parked. When another live group has room the job is
        # plain queued work again, so whoever waits on it keeps waiting for an
        # answer instead of being told to come back after this limit resets.
        if await _another_group_has_room(session, key, now):
            job.status = "queued"
            job.retry_at = None
    elif error_code in NON_RETRYABLE_ERRORS:
        job.status = "failed"
        job.error_code = error_code
        job.error_detail = detail
        job.leased_until = None
        job.completed_at = now
        group = await _group_row(session, group_for_worker(job.lease_owner), create=True)
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
