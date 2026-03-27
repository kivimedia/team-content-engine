"""Anthropic Batch API integration for cost-efficient bulk processing (PRD Section 36.8).

Batch API provides ~50% cost savings for non-time-sensitive operations
like research_agent calls. Requests are queued and results retrieved asynchronously.
"""

from __future__ import annotations

import uuid
from typing import Any

import anthropic
import structlog

from tce.settings import settings

logger = structlog.get_logger()


class BatchAPIService:
    """Manages batch API requests for cost-efficient processing.

    Usage:
        service = BatchAPIService()
        batch_id = await service.create_batch([
            {"custom_id": "req-1", "model": "...", "messages": [...], "max_tokens": 4096}
        ])
        # Poll later...
        results = await service.get_results(batch_id)
    """

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )

    async def create_batch(
        self,
        requests: list[dict[str, Any]],
    ) -> str | None:
        """Submit a batch of message requests.

        Args:
            requests: List of dicts with keys:
                - custom_id: unique identifier for this request
                - model: model to use
                - max_tokens: max tokens
                - messages: list of message dicts
                - system: optional system prompt

        Returns:
            Batch ID string, or None if batch creation failed.
        """
        if not requests:
            return None

        try:
            batch_requests = []
            for req in requests:
                params: dict[str, Any] = {
                    "model": req["model"],
                    "max_tokens": req.get("max_tokens", 4096),
                    "messages": req["messages"],
                }
                if req.get("system"):
                    params["system"] = req["system"]

                batch_requests.append(
                    {
                        "custom_id": req.get("custom_id", f"req-{uuid.uuid4().hex[:8]}"),
                        "params": params,
                    }
                )

            batch = await self._client.messages.batches.create(requests=batch_requests)
            logger.info(
                "batch.created",
                batch_id=batch.id,
                request_count=len(batch_requests),
            )
            return batch.id

        except Exception:
            logger.exception("batch.create_failed", request_count=len(requests))
            return None

    async def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        """Check the status of a batch."""
        try:
            batch = await self._client.messages.batches.retrieve(batch_id)
            return {
                "batch_id": batch.id,
                "status": batch.processing_status,
                "created_at": str(batch.created_at),
                "request_counts": {
                    "total": batch.request_counts.processing
                    + batch.request_counts.succeeded
                    + batch.request_counts.errored
                    + batch.request_counts.canceled
                    + batch.request_counts.expired,
                    "succeeded": batch.request_counts.succeeded,
                    "errored": batch.request_counts.errored,
                    "processing": batch.request_counts.processing,
                },
            }
        except Exception:
            logger.exception("batch.status_failed", batch_id=batch_id)
            return {"batch_id": batch_id, "status": "error"}

    async def get_results(self, batch_id: str) -> list[dict[str, Any]]:
        """Retrieve completed batch results.

        Returns list of dicts with custom_id, result_type, and content.
        """
        try:
            results = []
            async for result in self._client.messages.batches.results(batch_id):
                entry: dict[str, Any] = {
                    "custom_id": result.custom_id,
                    "result_type": result.result.type,
                }
                if result.result.type == "succeeded":
                    msg = result.result.message
                    text = ""
                    for block in msg.content:
                        if block.type == "text":
                            text = block.text
                            break
                    entry["content"] = text
                    entry["usage"] = {
                        "input_tokens": msg.usage.input_tokens,
                        "output_tokens": msg.usage.output_tokens,
                    }
                else:
                    entry["error"] = str(getattr(result.result, "error", "Unknown error"))
                results.append(entry)

            logger.info("batch.results", batch_id=batch_id, count=len(results))
            return results

        except Exception:
            logger.exception("batch.results_failed", batch_id=batch_id)
            return []
