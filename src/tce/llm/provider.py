"""Provider contract. Implementation owned by work package 1."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

POLICY_MODEL = "claude-opus-5"


class LLMPolicyError(RuntimeError):
    """A call tried to leave the subscription-only policy (metered client, batch API,
    non-subscription provider, model mismatch). Always fatal, never retried."""


class LLMUnavailable(RuntimeError):
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


async def complete(req: LLMRequest, *, wait_timeout_s: float | None = None) -> LLMResult:
    raise NotImplementedError


def get_llm_client(agent_name: str = "legacy") -> Any:
    raise NotImplementedError
