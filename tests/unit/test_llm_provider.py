"""Subscription-only provider: policy, leakage scan, dedup, waiting states, shim shape."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from tce.llm import (
    POLICY_MODEL,
    LLMPolicyError,
    LLMRequest,
    LLMResult,
    LLMUnavailable,
    complete,
    get_llm_client,
    queue,
)
from tce.llm import provider as provider_mod
from tce.models.llm_job import LLMJob
from tce.settings import settings

REPO = Path(__file__).resolve().parents[2]

RECEIPT = {
    "models": {
        POLICY_MODEL: {"input_tokens": 11, "output_tokens": 7, "auxiliary": False},
        "claude-haiku-4-5-20251001": {"input_tokens": 3, "output_tokens": 1, "auxiliary": True},
    },
    "policy_model_output_tokens": 7,
    "api_key_source": "none",
    "api_provider": "firstParty",
    "auth_method": "claude.ai",
}


# ---------------------------------------------------------------------------
# Leakage / policy
# ---------------------------------------------------------------------------


def test_no_metered_client_construction_in_source():
    patterns = [
        re.compile(r"AsyncAnthropic\s*\("),
        re.compile(r"anthropic\.Anthropic\s*\("),
        re.compile(r"^\s*import anthropic\b", re.MULTILINE),
        re.compile(r"^\s*from anthropic\b", re.MULTILINE),
        re.compile(r"messages\.batches\.(create|retrieve|results)"),
    ]
    offenders = []
    for root in (REPO / "src", REPO / "scripts"):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for pat in patterns:
                if pat.search(text):
                    offenders.append(f"{path.relative_to(REPO)}: {pat.pattern}")
    assert offenders == []


def test_non_subscription_provider_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "metered")
    with pytest.raises(LLMPolicyError):
        get_llm_client("x")
    req = LLMRequest(job_type="t", agent_name="a", messages=[{"role": "user", "content": "hi"}])
    with pytest.raises(LLMPolicyError):
        asyncio.run(complete(req, wait_timeout_s=0))


def test_batches_are_refused():
    client = get_llm_client("x")
    with pytest.raises(LLMPolicyError):
        _ = client.messages.batches
    with pytest.raises(LLMPolicyError):
        _ = client.batches
    from tce.services.batch_api import BatchAPIService

    with pytest.raises(LLMPolicyError):
        BatchAPIService()


def test_resilience_never_falls_back_to_another_model():
    from tce.services.resilience import FALLBACK_CHAIN, ResilienceManager

    mgr = ResilienceManager()
    for _ in range(10):
        mgr.get_circuit_breaker(POLICY_MODEL).record_failure()
    assert mgr.should_use_fallback(POLICY_MODEL) == (False, None)
    assert FALLBACK_CHAIN == {}


def test_is_policy_model():
    # Background writing moved to Opus 5.5 on 24-Sep (Ziv: "upgrade to 5.5").
    assert provider_mod.is_policy_model("claude-opus-5-5")
    assert provider_mod.is_policy_model("claude-opus-5-5[1m]")
    assert provider_mod.is_policy_model("claude-opus-5-5-20260901")
    assert not provider_mod.is_policy_model("claude-opus-5")
    assert not provider_mod.is_policy_model("claude-opus-5-5-mini")
    assert not provider_mod.is_policy_model("claude-sonnet-5")
    assert not provider_mod.is_policy_model(None)


def test_validate_output_helper():
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}
    assert provider_mod.validate_output({"a": 1}, schema) == []
    assert provider_mod.validate_output({"a": "x"}, schema)
    assert provider_mod.validate_output({}, schema)
    assert provider_mod.validate_output("anything", None) == []


def test_idempotency_key_scoped_to_workspace():
    base = LLMRequest(job_type="t", agent_name="a", messages=[{"role": "user", "content": "x"}])
    ws1 = LLMRequest(**{**base.__dict__, "workspace_id": uuid.uuid4()})
    ws2 = LLMRequest(**{**base.__dict__, "workspace_id": uuid.uuid4()})
    keys = {provider_mod.compute_idempotency_key(r) for r in (base, ws1, ws2)}
    assert len(keys) == 3
    assert provider_mod.compute_input_hash(ws1) == provider_mod.compute_input_hash(ws2)


# ---------------------------------------------------------------------------
# complete() against the real queue
# ---------------------------------------------------------------------------


@pytest.fixture
async def file_sessionmaker(tmp_path):
    """File-backed SQLite: the poller and the fake worker run concurrently, which a
    single shared in-memory connection cannot serve safely."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from tests.editorial_db import create_tables

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'llm.sqlite'}", poolclass=NullPool
    )
    await create_tables(engine)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _fake_worker(sessionmaker, *, result_text="synthetic answer", fail=None):
    """Lease the next job and finish it, like a subscription worker would."""
    for _ in range(200):
        async with sessionmaker() as s:
            job = await queue.lease_job(s, "fake-worker", 600)
            await s.commit()
        if job is not None:
            async with sessionmaker() as s:
                if fail:
                    await queue.fail_job(s, job.id, job.attempt_id, **fail)
                else:
                    await queue.complete_job(
                        s,
                        job.id,
                        job.attempt_id,
                        result_text=result_text,
                        result_json=None,
                        receipt=RECEIPT,
                    )
                await s.commit()
            return job.id
        await asyncio.sleep(0.01)
    raise AssertionError("no job was enqueued")


def _req(text="synthetic prompt"):
    return LLMRequest(
        job_type="test.provider",
        agent_name="tester",
        messages=[{"role": "user", "content": text}],
        system="sys",
        requested_model="claude-sonnet-5",
    )


async def test_complete_waits_for_worker_and_dedups(file_sessionmaker):
    task = asyncio.create_task(
        complete(_req(), wait_timeout_s=5, sessionmaker=file_sessionmaker, poll_interval_s=0.01)
    )
    job_id = await _fake_worker(file_sessionmaker)
    result = await task
    assert isinstance(result, LLMResult)
    assert result.job_id == job_id
    assert result.text == "synthetic answer"
    assert result.model == POLICY_MODEL
    assert (result.input_tokens, result.output_tokens) == (11, 7)

    again = await complete(_req(), wait_timeout_s=0, sessionmaker=file_sessionmaker)
    assert again.job_id == job_id and again.text == "synthetic answer"
    async with file_sessionmaker() as s:
        rows = (await s.execute(select(func.count()).select_from(LLMJob))).scalar()
        job = (await s.execute(select(LLMJob))).scalar_one()
    assert rows == 1
    assert job.requested_model == "claude-sonnet-5" and job.policy_model == POLICY_MODEL


async def test_complete_times_out_but_job_stays_queued(file_sessionmaker):
    with pytest.raises(LLMUnavailable) as exc:
        await complete(
            _req(), wait_timeout_s=0.05, sessionmaker=file_sessionmaker, poll_interval_s=0.01
        )
    assert exc.value.status == "timeout" and exc.value.job_id is not None
    async with file_sessionmaker() as s:
        job = (await s.execute(select(LLMJob))).scalar_one()
    assert job.status == "queued"


async def test_complete_surfaces_waiting_capacity_with_retry_at(file_sessionmaker):
    retry_at = queue.utcnow() + timedelta(hours=3)
    task = asyncio.create_task(
        complete(_req(), wait_timeout_s=5, sessionmaker=file_sessionmaker, poll_interval_s=0.01)
    )
    await _fake_worker(
        file_sessionmaker,
        fail={"error_code": "capacity", "error_detail": "usage limit", "retry_at": retry_at},
    )
    with pytest.raises(LLMUnavailable) as exc:
        await task
    assert exc.value.status == "waiting_capacity"
    assert exc.value.retry_at == retry_at


async def test_complete_surfaces_failed(file_sessionmaker):
    task = asyncio.create_task(
        complete(_req(), wait_timeout_s=5, sessionmaker=file_sessionmaker, poll_interval_s=0.01)
    )
    await _fake_worker(file_sessionmaker, fail={"error_code": "policy_violation"})
    with pytest.raises(LLMUnavailable) as exc:
        await task
    assert exc.value.status == "failed"
    # A failed row is not silently re-run by an identical request.
    with pytest.raises(LLMUnavailable):
        await complete(_req(), wait_timeout_s=0, sessionmaker=file_sessionmaker)


async def test_complete_rejects_non_text_blocks(editorial_sessionmaker):
    bad = LLMRequest(
        job_type="t",
        agent_name="a",
        messages=[{"role": "user", "content": [{"type": "image", "source": {}}]}],
    )
    with pytest.raises(ValueError):
        await complete(bad, wait_timeout_s=0, sessionmaker=editorial_sessionmaker)


# ---------------------------------------------------------------------------
# Shim
# ---------------------------------------------------------------------------


async def test_shim_returns_anthropic_like_shape(monkeypatch):
    seen = {}

    async def fake_complete(req, *, wait_timeout_s=None, sessionmaker=None, **_):
        seen["req"] = req
        return LLMResult(
            job_id=uuid.uuid4(),
            text="shim text",
            structured=None,
            model=POLICY_MODEL,
            input_tokens=5,
            output_tokens=3,
        )

    monkeypatch.setattr(provider_mod, "complete", fake_complete)
    client = get_llm_client("legacy_site")
    resp = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        temperature=0.3,
        system=[
            {"type": "text", "text": "part one", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "part two"},
        ],
        messages=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
    )
    assert resp.content[0].type == "text" and resp.content[0].text == "shim text"
    assert resp.usage.input_tokens == 5 and resp.usage.output_tokens == 3
    assert resp.usage.cache_read_input_tokens == 0 and resp.usage.cache_creation_input_tokens == 0
    assert resp.model == POLICY_MODEL and resp.stop_reason == "end_turn"
    req = seen["req"]
    assert req.system == "part one\n\npart two"
    assert req.messages == [{"role": "user", "content": "hello"}]
    assert req.requested_model == "claude-haiku-4-5-20251001"
    assert req.job_type == "legacy.legacy_site"


async def test_shim_emulates_tool_use(monkeypatch):
    calls = []

    async def fake_complete(req, **_):
        calls.append(req)
        if len(calls) == 1:
            structured = {
                "text": "",
                "tool_calls": [{"name": "web_search", "input": {"query": "q"}}],
            }
        else:
            structured = {"text": "final answer", "tool_calls": []}
        return LLMResult(job_id=uuid.uuid4(), text="", structured=structured, model=POLICY_MODEL)

    monkeypatch.setattr(provider_mod, "complete", fake_complete)
    client = get_llm_client("brainstorm")
    tools = [{"name": "web_search", "description": "search", "input_schema": {"type": "object"}}]
    messages = [{"role": "user", "content": "find"}]
    r1 = await client.messages.create(model="m", max_tokens=10, messages=messages, tools=tools)
    assert r1.stop_reason == "tool_use"
    block = r1.content[0]
    assert block.type == "tool_use" and block.name == "web_search" and block.input == {"query": "q"}
    assert calls[0].output_schema["required"] == ["text", "tool_calls"]

    messages.append({"role": "assistant", "content": r1.content})
    messages.append(
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": block.id, "content": "[results]"}],
        }
    )
    r2 = await client.messages.create(model="m", max_tokens=10, messages=messages, tools=tools)
    assert r2.stop_reason == "end_turn" and r2.content[0].text == "final answer"
    rendered = calls[1].messages
    assert "[tool call id=" in rendered[1]["content"]
    assert "[tool result for id=" in rendered[2]["content"]


async def test_shim_calls_are_not_deduplicated(editorial_sessionmaker):
    client = get_llm_client("legacy", sessionmaker=editorial_sessionmaker)
    for _ in range(2):
        with pytest.raises(LLMUnavailable):
            await client.messages.create(
                model="m",
                max_tokens=5,
                messages=[{"role": "user", "content": "same"}],
                wait_timeout_s=0,
            )
    async with editorial_sessionmaker() as s:
        assert (await s.execute(select(func.count()).select_from(LLMJob))).scalar() == 2
        await s.execute(update(LLMJob).values(status="cancelled"))
        await s.commit()
