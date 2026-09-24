"""Subscription-only LLM provider.

Every text call becomes one durable ``llm_jobs`` row. A Claude Code worker that is
authenticated to a subscription leases the row, runs the prompt on
``POLICY_MODEL`` and writes the result back (see ``tce.llm.queue`` and
``tce.llm.worker``). This module never talks to a model API itself, never picks
another model and never rotates accounts. Capacity exhaustion surfaces as
``LLMUnavailable("waiting_capacity", retry_at=...)``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger()

POLICY_MODEL = "claude-opus-5-5"
ACCEPTED_PROVIDER = "subscription"


class LLMPolicyError(RuntimeError):
    """A call tried to leave the subscription-only policy (metered client, batch API,
    non-subscription provider, model mismatch). Always fatal, never retried."""


class LLMUnavailable(RuntimeError):  # noqa: N818 - contract name
    """The subscription worker could not produce a result right now."""

    def __init__(
        self,
        status: str,
        detail: str,
        *,
        job_id: uuid.UUID | None = None,
        retry_at: datetime | None = None,
    ) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status  # waiting_capacity | failed | timeout | cancelled
        self.detail = detail
        self.job_id = job_id
        self.retry_at = retry_at


@dataclass
class LLMRequest:
    job_type: str
    agent_name: str
    messages: list[dict[str, Any]]
    system: str | None = None
    output_schema: dict[str, Any] | None = None
    max_tokens: int = 4096
    requested_model: str | None = None
    prompt_version: str | None = None
    workspace_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    # Default: sha256 of (job_type, system, messages, output_schema, prompt_version)
    idempotency_key: str | None = None


@dataclass
class LLMResult:
    job_id: uuid.UUID
    text: str
    structured: Any | None
    model: str
    receipt: dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# Hashing, policy helpers, schema validation
# ---------------------------------------------------------------------------


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_input_hash(req: LLMRequest) -> str:
    return sha256_hex(
        canonical_json(
            {
                "job_type": req.job_type,
                "system": req.system,
                "messages": req.messages,
                "output_schema": req.output_schema,
                "prompt_version": req.prompt_version,
            }
        )
    )


def compute_idempotency_key(req: LLMRequest) -> str:
    """Stored job key. An explicit key names the job within its job_type and
    workspace; without one the input hash is the name. Either way the workspace is
    folded in so two tenants never share (or read) each other's job rows."""
    if req.idempotency_key:
        return sha256_hex(
            canonical_json(
                {
                    "job_type": req.job_type,
                    "workspace_id": str(req.workspace_id) if req.workspace_id else None,
                    "key": req.idempotency_key,
                }
            )
        )
    base = compute_input_hash(req)
    if req.workspace_id is None:
        return base
    return sha256_hex(f"{base}:ws:{req.workspace_id}")


def schema_hash(schema: dict[str, Any] | None) -> str | None:
    return sha256_hex(canonical_json(schema)) if schema is not None else None


def is_policy_model(model: str | None) -> bool:
    """Exact policy model, its long-context tag or a dated snapshot of it."""
    if not model:
        return False
    if model == POLICY_MODEL or model.startswith(POLICY_MODEL + "["):
        return True
    suffix = model[len(POLICY_MODEL) + 1 :] if model.startswith(POLICY_MODEL + "-") else ""
    return suffix.isdigit() and len(suffix) == 8


def validate_output(result: Any, schema: dict[str, Any] | None) -> list[str]:
    """Validate a structured result against a JSON schema. Returns error messages
    (empty list = valid). ``schema is None`` accepts anything."""
    if schema is None:
        return []
    import jsonschema

    try:
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
    except jsonschema.SchemaError as exc:
        return [f"invalid schema: {exc.message}"]
    validator = validator_cls(schema)
    return [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in validator.iter_errors(result)
    ]


def ensure_policy() -> None:
    from tce.settings import settings

    provider = (settings.llm_provider or "").strip().lower()
    if provider != ACCEPTED_PROVIDER:
        raise LLMPolicyError(
            f"TCE_LLM_PROVIDER={settings.llm_provider!r} is not allowed. Only "
            f"'{ACCEPTED_PROVIDER}' (Claude Code worker on {POLICY_MODEL}) is permitted."
        )


def _check_text_only(messages: list[dict[str, Any]]) -> None:
    if not messages:
        raise ValueError("LLMRequest.messages must not be empty")
    for msg in messages:
        if msg.get("role") not in ("user", "assistant"):
            raise ValueError(f"unsupported message role: {msg.get('role')!r}")
        content = msg.get("content")
        if isinstance(content, str):
            continue
        if not isinstance(content, list):
            raise ValueError("message content must be a string or a list of text blocks")
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                raise ValueError(
                    "subscription worker jobs accept text only; normalize blocks first "
                    "(tce.llm.provider.normalize_messages)"
                )


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


def _default_sessionmaker() -> Any:
    from tce.db.session import async_session

    return async_session


def _result_from_job(job: Any) -> LLMResult:
    receipt = dict(job.receipt_json or {})
    models = receipt.get("models") or {}
    model = next((m for m in models if is_policy_model(m)), None) or job.policy_model
    usage = models.get(model, {}) if isinstance(models, dict) else {}
    text = job.result_text
    if text is None:
        text = canonical_json(job.result_json) if job.result_json is not None else ""
    return LLMResult(
        job_id=job.id,
        text=text,
        structured=job.result_json,
        model=model,
        receipt=receipt,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(
            usage.get("output_tokens") or receipt.get("policy_model_output_tokens") or 0
        ),
    )


async def complete(
    req: LLMRequest,
    *,
    wait_timeout_s: float | None = None,
    sessionmaker: Any | None = None,
    poll_interval_s: float = 0.5,
    max_poll_interval_s: float = 5.0,
    requeue_failed: bool = False,
) -> LLMResult:
    """Enqueue (or reuse) one subscription job and wait for its result.

    - succeeded row with the same idempotency key: returned immediately (dedup)
    - failed row: raises LLMUnavailable("failed") unless ``requeue_failed`` is set,
      which re-queues it once (never for policy/model failures)
    - waiting_capacity: keeps waiting until the deadline; if retry_at is already
      past the deadline, raises LLMUnavailable("waiting_capacity") right away
    """
    from tce.llm import queue
    from tce.settings import settings

    ensure_policy()
    _check_text_only(req.messages)
    timeout = settings.llm_job_wait_timeout_s if wait_timeout_s is None else wait_timeout_s
    maker = sessionmaker or _default_sessionmaker()

    async with maker() as session:
        job = await queue.enqueue(session, req, requeue_failed=requeue_failed)
        job_id = job.id
        await session.commit()

    logger.info(
        "llm.job_enqueued",
        job_id=str(job_id),
        job_type=req.job_type,
        agent=req.agent_name,
        requested_model=req.requested_model,
    )

    deadline = time.monotonic() + max(0.0, timeout)
    interval = poll_interval_s
    while True:
        async with maker() as session:
            job = await queue.get_job(session, job_id)
        if job is None:
            raise LLMUnavailable("failed", "job row disappeared", job_id=job_id)
        status = job.status
        if status == "succeeded":
            return _result_from_job(job)
        if status in ("failed", "cancelled"):
            raise LLMUnavailable(
                status,
                f"{job.error_code or status}: {job.error_detail or ''}".strip(),
                job_id=job_id,
            )
        now_mono = time.monotonic()
        if status == "waiting_capacity" and job.retry_at is not None:
            seconds_until_retry = (job.retry_at - queue.utcnow()).total_seconds()
            if now_mono + seconds_until_retry > deadline:
                raise LLMUnavailable(
                    "waiting_capacity",
                    f"subscription capacity exhausted; retry at {job.retry_at.isoformat()}Z",
                    job_id=job_id,
                    retry_at=job.retry_at,
                )
        if now_mono >= deadline:
            if status == "waiting_capacity":
                raise LLMUnavailable(
                    "waiting_capacity",
                    "subscription capacity exhausted",
                    job_id=job_id,
                    retry_at=job.retry_at,
                )
            raise LLMUnavailable(
                "timeout",
                f"job still {status} after {timeout:.0f}s (it stays queued; a later "
                "identical request reuses it)",
                job_id=job_id,
                retry_at=job.retry_at,
            )
        await asyncio.sleep(min(interval, max(0.0, deadline - now_mono)))
        interval = min(interval * 1.5, max_poll_interval_s)


# ---------------------------------------------------------------------------
# Anthropic-SDK-shaped shim for legacy call sites
# ---------------------------------------------------------------------------


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class ShimUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class ShimMessage:
    content: list[Any]
    usage: ShimUsage
    model: str
    stop_reason: str = "end_turn"
    id: str = ""
    role: str = "assistant"
    type: str = "message"
    job_id: uuid.UUID | None = None


def _get(block: Any, key: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def flatten_system(system: Any) -> str | None:
    """System prompt as str, or a list of text blocks (cache_control is dropped)."""
    if system is None:
        return None
    if isinstance(system, str):
        return system or None
    parts = []
    for block in system:
        if isinstance(block, str):
            parts.append(block)
        elif _get(block, "type") == "text":
            parts.append(_get(block, "text", ""))
        else:
            raise ValueError(f"unsupported system block type: {_get(block, 'type')!r}")
    text = "\n\n".join(p for p in parts if p)
    return text or None


def _block_to_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    btype = _get(block, "type")
    if btype == "text":
        return _get(block, "text", "")
    if btype == "tool_use":
        return (
            f"[tool call id={_get(block, 'id')} name={_get(block, 'name')}] "
            f"{canonical_json(_get(block, 'input', {}))}"
        )
    if btype == "tool_result":
        inner = _get(block, "content", "")
        if isinstance(inner, list):
            inner = "\n".join(_block_to_text(b) for b in inner)
        return f"[tool result for id={_get(block, 'tool_use_id')}]\n{inner}"
    raise ValueError(
        f"content block type {btype!r} is not supported by the subscription text worker"
    )


def normalize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = _get(msg, "role")
        content = _get(msg, "content", "")
        if isinstance(content, str):
            text = content
        else:
            text = "\n\n".join(_block_to_text(b) for b in content)
        out.append({"role": role, "content": text})
    return out


def _tool_prompt_and_schema(tools: list[Any]) -> tuple[str, dict[str, Any]]:
    names = [_get(t, "name") for t in tools]
    described = [
        {
            "name": _get(t, "name"),
            "description": _get(t, "description", ""),
            "input_schema": _get(t, "input_schema", {}),
        }
        for t in tools
    ]
    prompt = (
        "TOOLS: you cannot run tools yourself. When a tool would help, request it in "
        "`tool_calls` and leave `text` empty or brief; the caller runs it and sends the "
        "result back as a '[tool result for id=...]' message. When you have the final "
        "answer, put it in `text` and return an empty `tool_calls` list.\n"
        f"Available tools: {canonical_json(described)}"
    )
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "tool_calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": names},
                        "input": {"type": "object"},
                    },
                    "required": ["name", "input"],
                },
            },
        },
        "required": ["text", "tool_calls"],
    }
    return prompt, schema


class _Messages:
    def __init__(self, agent_name: str, sessionmaker: Any | None) -> None:
        self._agent_name = agent_name
        self._sessionmaker = sessionmaker

    @property
    def batches(self) -> Any:
        raise LLMPolicyError(
            "The Anthropic Batch API is metered and disabled by the subscription-only policy."
        )

    async def create(
        self,
        *,
        messages: list[Any],
        model: str | None = None,
        system: Any = None,
        max_tokens: int = 4096,
        temperature: float | None = None,  # ignored: the worker CLI has no sampling knob
        tools: list[Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        job_type: str | None = None,
        prompt_version: str | None = None,
        idempotency_key: str | None = None,
        workspace_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        wait_timeout_s: float | None = None,
        **_ignored: Any,
    ) -> ShimMessage:
        system_text = flatten_system(system)
        schema = output_schema
        if tools:
            tool_prompt, schema = _tool_prompt_and_schema(tools)
            system_text = f"{system_text}\n\n{tool_prompt}" if system_text else tool_prompt
        req = LLMRequest(
            job_type=job_type or f"legacy.{self._agent_name}",
            agent_name=self._agent_name,
            messages=normalize_messages(messages),
            system=system_text,
            output_schema=schema,
            max_tokens=max_tokens,
            requested_model=model,
            prompt_version=prompt_version,
            workspace_id=workspace_id,
            run_id=run_id,
            # A legacy call is one call: a new job per call unless the caller opts in
            # to dedup, so "regenerate" buttons do not return a cached answer.
            idempotency_key=idempotency_key or f"call:{uuid.uuid4().hex}",
        )
        result = await complete(req, wait_timeout_s=wait_timeout_s, sessionmaker=self._sessionmaker)
        content: list[Any] = []
        stop_reason = "end_turn"
        if tools:
            data = result.structured if isinstance(result.structured, dict) else {}
            if data.get("text"):
                content.append(TextBlock(text=data["text"]))
            for i, call in enumerate(data.get("tool_calls") or []):
                content.append(
                    ToolUseBlock(
                        id=f"toolu_{result.job_id.hex[:16]}_{i}",
                        name=call.get("name", ""),
                        input=call.get("input") or {},
                    )
                )
                stop_reason = "tool_use"
            if not content:
                content.append(TextBlock(text=""))
        else:
            content.append(TextBlock(text=result.text))
        return ShimMessage(
            content=content,
            usage=ShimUsage(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
            model=result.model,
            stop_reason=stop_reason,
            id=f"llmjob_{result.job_id.hex}",
            job_id=result.job_id,
        )


class SubscriptionLLMClient:
    """Drop-in for the few ``client.messages.create`` shapes TCE used."""

    def __init__(self, agent_name: str = "legacy", sessionmaker: Any | None = None) -> None:
        self.agent_name = agent_name
        self.messages = _Messages(agent_name, sessionmaker)

    @property
    def batches(self) -> Any:
        raise LLMPolicyError("The Anthropic Batch API is disabled by the subscription-only policy.")


def get_llm_client(agent_name: str = "legacy", *, sessionmaker: Any | None = None) -> Any:
    ensure_policy()
    return SubscriptionLLMClient(agent_name, sessionmaker)
