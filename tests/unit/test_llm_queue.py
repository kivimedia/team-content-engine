"""State-transition tests for the subscription LLM job queue (synthetic, SQLite)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from tce.llm import queue
from tce.llm.provider import POLICY_MODEL, LLMRequest
from tce.models.llm_job import LLMJob

SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}


def good_receipt(**over):
    receipt = {
        "models": {
            POLICY_MODEL: {"input_tokens": 120, "output_tokens": 40, "auxiliary": False},
            "claude-haiku-4-5-20251001": {"input_tokens": 9, "output_tokens": 2, "auxiliary": True},
        },
        "policy_model_output_tokens": 40,
        "auxiliary_models": ["claude-haiku-4-5-20251001"],
        "auth_method": "claude.ai",
        "api_provider": "firstParty",
        "api_key_source": "none",
        "cli_version": "2.1.270",
        "worker_id": "w1",
        # must be stripped
        "email": "someone@example.com",
        "orgId": "org-123",
    }
    receipt.update(over)
    return receipt


def req(n: int = 0, schema=None) -> LLMRequest:
    return LLMRequest(
        job_type="test.synthetic",
        agent_name="tester",
        messages=[{"role": "user", "content": f"synthetic prompt {n}"}],
        system="be brief",
        output_schema=schema,
    )


async def enqueue(session, n=0, schema=None) -> LLMJob:
    job = await queue.enqueue(session, req(n, schema))
    await session.commit()
    return job


async def test_enqueue_dedups_by_idempotency_key(editorial_session):
    a = await enqueue(editorial_session, 1)
    b = await enqueue(editorial_session, 1)
    c = await enqueue(editorial_session, 2)
    assert a.id == b.id != c.id
    count = (await editorial_session.execute(select(func.count()).select_from(LLMJob))).scalar()
    assert count == 2
    assert a.policy_model == POLICY_MODEL and a.status == "queued"


async def test_lease_is_exclusive_and_increments_attempt(editorial_session):
    job = await enqueue(editorial_session)
    first = await queue.lease_job(editorial_session, "w1", 600)
    await editorial_session.commit()
    second = await queue.lease_job(editorial_session, "w2", 600)
    assert first is not None and first.id == job.id
    assert first.attempt_count == 1 and first.attempt_id is not None
    assert first.lease_owner == "w1"
    assert second is None


async def test_lease_cas_loses_when_row_changed_underneath(editorial_sessionmaker, monkeypatch):
    """Simulate two workers reading the same candidate: the second write must not win."""
    async with editorial_sessionmaker() as s:
        await enqueue(s)

    original_execute = None
    raced = {"done": False}

    async with editorial_sessionmaker() as a, editorial_sessionmaker() as b:
        original_execute = a.execute

        async def execute_with_race(stmt, *args, **kwargs):
            # Right before worker A's conditional UPDATE, worker B leases the same job.
            if not raced["done"] and getattr(stmt, "is_update", False):
                raced["done"] = True
                won_b = await queue.lease_job(b, "w-b", 600)
                await b.commit()
                assert won_b is not None
            return await original_execute(stmt, *args, **kwargs)

        monkeypatch.setattr(a, "execute", execute_with_race)
        won_a = await queue.lease_job(a, "w-a", 600)
        await a.commit()

    assert raced["done"]
    assert won_a is None
    async with editorial_sessionmaker() as s:
        job = (await s.execute(select(LLMJob))).scalar_one()
        assert job.lease_owner == "w-b" and job.attempt_count == 1


async def test_expired_lease_is_reclaimed_after_worker_crash(editorial_session):
    await enqueue(editorial_session)
    crashed = await queue.lease_job(editorial_session, "crashed-worker", 600)
    old_attempt = crashed.attempt_id
    await editorial_session.commit()

    # Not reclaimable while the lease is live.
    assert await queue.lease_job(editorial_session, "w2", 600) is None

    later = queue.utcnow() + timedelta(seconds=601)
    reclaimed = await queue.lease_job(editorial_session, "w2", 600, now=later)
    await editorial_session.commit()
    assert reclaimed is not None
    assert reclaimed.attempt_count == 2 and reclaimed.attempt_id != old_attempt
    assert reclaimed.lease_owner == "w2"

    # The crashed worker's late completion is stale.
    with pytest.raises(queue.StaleAttemptError):
        await queue.complete_job(
            editorial_session,
            reclaimed.id,
            old_attempt,
            result_text="late",
            result_json=None,
            receipt=good_receipt(),
        )
    with pytest.raises(queue.StaleAttemptError):
        await queue.heartbeat(editorial_session, reclaimed.id, old_attempt, 600)


async def test_attempts_beyond_max_fail_with_max_attempts(editorial_session):
    await enqueue(editorial_session)
    now = queue.utcnow()
    for i in range(3):
        job = await queue.lease_job(editorial_session, "w", 60, now=now)
        assert job is not None and job.attempt_count == i + 1
        await editorial_session.commit()
        now = now + timedelta(seconds=61)  # lease expires: simulated crash
    assert await queue.lease_job(editorial_session, "w", 60, now=now) is None
    await editorial_session.commit()
    job = (await editorial_session.execute(select(LLMJob))).scalar_one()
    assert job.status == "failed" and job.error_code == "max_attempts"


async def test_complete_success_and_idempotent_repeat(editorial_session):
    await enqueue(editorial_session)
    job = await queue.lease_job(editorial_session, "w1", 600)
    attempt = job.attempt_id
    done = await queue.complete_job(
        editorial_session,
        job.id,
        attempt,
        result_text="hello",
        result_json=None,
        receipt=good_receipt(),
    )
    await editorial_session.commit()
    assert done.status == "succeeded" and done.result_text == "hello"
    assert "email" not in done.receipt_json and "orgId" not in done.receipt_json
    assert done.receipt_json["attempt_id"] == str(attempt)

    again = await queue.complete_job(
        editorial_session,
        job.id,
        attempt,
        result_text="hello",
        result_json=None,
        receipt=good_receipt(),
    )
    assert again.status == "succeeded"
    with pytest.raises(queue.StaleAttemptError):
        await queue.complete_job(
            editorial_session,
            job.id,
            attempt,
            result_text="different",
            result_json=None,
            receipt=good_receipt(),
        )
    with pytest.raises(queue.StaleAttemptError):
        await queue.complete_job(
            editorial_session,
            job.id,
            uuid.uuid4(),
            result_text="hello",
            result_json=None,
            receipt=good_receipt(),
        )


async def test_capacity_waits_until_retry_at(editorial_session):
    await enqueue(editorial_session)
    job = await queue.lease_job(editorial_session, "w1", 600)
    retry_at = queue.utcnow() + timedelta(hours=2)
    failed = await queue.fail_job(
        editorial_session,
        job.id,
        job.attempt_id,
        error_code="capacity",
        error_detail="usage limit reached",
        retry_at=retry_at,
    )
    await editorial_session.commit()
    assert failed.status == "waiting_capacity"
    assert failed.retry_at == retry_at
    assert failed.attempt_count == 0  # capacity does not spend an attempt

    assert await queue.lease_job(editorial_session, "w2", 600) is None
    after = retry_at + timedelta(seconds=1)
    again = await queue.lease_job(editorial_session, "w2", 600, now=after)
    assert again is not None and again.status == "leased"


async def test_capacity_without_retry_at_defaults_to_30_minutes(editorial_session):
    await enqueue(editorial_session)
    job = await queue.lease_job(editorial_session, "w1", 600)
    before = queue.utcnow()
    failed = await queue.fail_job(editorial_session, job.id, job.attempt_id, error_code="capacity")
    assert failed.retry_at >= before + timedelta(minutes=29)


async def test_invalid_json_requeues_then_fails_at_max_attempts(editorial_session):
    await enqueue(editorial_session, schema=SCHEMA)
    for attempt in range(1, 4):
        job = await queue.lease_job(editorial_session, "w1", 600)
        assert job is not None and job.attempt_count == attempt
        out = await queue.complete_job(
            editorial_session,
            job.id,
            job.attempt_id,
            result_text='{"wrong": 1}',
            result_json={"wrong": 1},
            receipt=good_receipt(),
        )
        await editorial_session.commit()
        assert out.error_code == "invalid_json"
        assert out.status == ("queued" if attempt < 3 else "failed")
    assert await queue.lease_job(editorial_session, "w1", 600) is None


async def test_valid_schema_result_parsed_from_text(editorial_session):
    await enqueue(editorial_session, schema=SCHEMA)
    job = await queue.lease_job(editorial_session, "w1", 600)
    out = await queue.complete_job(
        editorial_session,
        job.id,
        job.attempt_id,
        result_text='{"title": "ok"}',
        result_json=None,
        receipt=good_receipt(),
    )
    assert out.status == "succeeded" and out.result_json == {"title": "ok"}


@pytest.mark.parametrize(
    ("receipt", "code"),
    [
        (good_receipt(models={"claude-sonnet-5": {"output_tokens": 50}}), "model_mismatch"),
        (
            good_receipt(
                models={
                    POLICY_MODEL: {"output_tokens": 0},
                    "claude-haiku-4-5": {"output_tokens": 9},
                }
            ),
            "model_mismatch",
        ),
        (good_receipt(api_key_source="ANTHROPIC_API_KEY_SOURCE_ENV"), "policy_violation"),
        (good_receipt(api_provider="bedrock"), "policy_violation"),
    ],
)
async def test_receipt_violations_fail_without_retry(editorial_session, receipt, code):
    await enqueue(editorial_session)
    job = await queue.lease_job(editorial_session, "w1", 600)
    out = await queue.complete_job(
        editorial_session,
        job.id,
        job.attempt_id,
        result_text="answer",
        result_json=None,
        receipt=receipt,
    )
    await editorial_session.commit()
    assert out.status == "failed" and out.error_code == code
    assert out.attempt_count == 1
    assert await queue.lease_job(editorial_session, "w2", 600) is None


async def test_policy_fail_codes_are_final_and_other_codes_retry(editorial_session):
    a = await enqueue(editorial_session, 1)
    b = await enqueue(editorial_session, 2)
    # make lease order deterministic
    await editorial_session.execute(
        update(LLMJob)
        .where(LLMJob.id == b.id)
        .values(created_at=a.created_at + timedelta(seconds=5))
    )
    await editorial_session.commit()
    ja = await queue.lease_job(editorial_session, "w", 600)
    fa = await queue.fail_job(editorial_session, ja.id, ja.attempt_id, error_code="auth")
    assert fa.status == "failed"
    jb = await queue.lease_job(editorial_session, "w", 600)
    fb = await queue.fail_job(editorial_session, jb.id, jb.attempt_id, error_code="timeout")
    assert fb.status == "queued"
    # a repeated fail report for the same attempt is idempotent
    again = await queue.fail_job(editorial_session, jb.id, jb.attempt_id, error_code="timeout")
    assert again.status == "queued"


async def test_requeue_failed_once_only(editorial_session):
    job = await enqueue(editorial_session)
    await editorial_session.execute(
        update(LLMJob).where(LLMJob.id == job.id).values(status="failed", error_code="timeout")
    )
    await editorial_session.commit()
    from tce.llm import LLMUnavailable

    with pytest.raises(LLMUnavailable):
        await queue.enqueue(editorial_session, req())
    requeued = await queue.enqueue(editorial_session, req(), requeue_failed=True)
    assert requeued.status == "queued" and requeued.id == job.id
    await editorial_session.execute(
        update(LLMJob).where(LLMJob.id == job.id).values(status="failed", error_code="timeout")
    )
    await editorial_session.commit()
    with pytest.raises(LLMUnavailable):
        await queue.enqueue(editorial_session, req(), requeue_failed=True)


async def test_list_jobs_counts(editorial_session):
    await enqueue(editorial_session, 1)
    await enqueue(editorial_session, 2)
    await queue.lease_job(editorial_session, "w", 600)
    await editorial_session.commit()
    jobs, counts = await queue.list_jobs(editorial_session)
    assert len(jobs) == 2
    assert counts == {"queued": 1, "leased": 1}


async def test_explicit_key_with_changed_input_is_a_conflict(editorial_session):
    first = LLMRequest(
        job_type="packet",
        agent_name="a",
        idempotency_key="named",
        messages=[{"role": "user", "content": "one"}],
    )
    await queue.enqueue(editorial_session, first)
    await editorial_session.commit()
    same = await queue.enqueue(editorial_session, first)
    assert same.status == "queued"
    changed = LLMRequest(
        job_type="packet",
        agent_name="a",
        idempotency_key="named",
        messages=[{"role": "user", "content": "two"}],
    )
    with pytest.raises(queue.IdempotencyConflictError):
        await queue.enqueue(editorial_session, changed)


@pytest.mark.parametrize("missing", ["auth_method", "api_provider", "api_key_source", "models"])
def test_receipt_missing_proof_fails_closed(missing):
    receipt = queue.sanitize_receipt(good_receipt())
    receipt.pop(missing)
    assert queue.verify_receipt(receipt) is not None
    assert queue.verify_receipt(queue.sanitize_receipt(good_receipt())) is None
