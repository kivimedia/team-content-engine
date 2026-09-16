"""Batch API integration: disabled.

The Anthropic Message Batches API is a metered API. TCE runs every LLM call on a
Claude Code subscription worker (see ``tce.llm``), so this service fails closed.
Bulk work should enqueue ordinary jobs with ``tce.llm.complete`` instead; the
worker drains them on the subscription.
"""

from __future__ import annotations

from typing import Any

from tce.llm import LLMPolicyError

_REFUSAL = (
    "The Anthropic Batch API is metered and disabled by the subscription-only LLM policy. "
    "Enqueue jobs with tce.llm.complete() instead."
)


class BatchAPIService:
    """Kept for import compatibility. Every method raises LLMPolicyError."""

    def __init__(self) -> None:
        raise LLMPolicyError(_REFUSAL)

    async def create_batch(self, requests: list[dict[str, Any]]) -> str | None:
        raise LLMPolicyError(_REFUSAL)

    async def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        raise LLMPolicyError(_REFUSAL)

    async def get_results(self, batch_id: str) -> list[dict[str, Any]]:
        raise LLMPolicyError(_REFUSAL)
