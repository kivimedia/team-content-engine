"""Base agent class with LLM calling, cost tracking, and prompt resolution."""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import structlog
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from tce.llm import LLMPolicyError, LLMRequest, LLMUnavailable, complete
from tce.llm.provider import (
    ShimMessage,
    ShimUsage,
    TextBlock,
    flatten_system,
    normalize_messages,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from tce.services.cost_tracker import CostTracker
    from tce.services.prompt_manager import PromptManager
    from tce.settings import Settings

logger = structlog.get_logger()


# Every LLM call goes through tce.llm.complete(): a durable job run by a Claude Code
# subscription worker on POLICY_MODEL. There is no metered client, no per-model
# temperature handling (the worker CLI has no sampling knob), no 400-driven kwarg
# stripping and no lower-model fallback.


class AgentBase(ABC):
    """Abstract base for all content engine agents.

    Subclasses implement _execute() with agent-specific logic.
    The base class provides LLM calling with automatic usage tracking
    and prompt version resolution.
    """

    name: str = "base"
    default_model: str = "claude-sonnet-5"

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        cost_tracker: CostTracker,
        prompt_manager: PromptManager,
        run_id: uuid.UUID | None = None,
        progress_log: list[str] | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.cost_tracker = cost_tracker
        self.prompt_manager = prompt_manager
        self.run_id = run_id or uuid.uuid4()
        self._progress_log = progress_log if progress_log is not None else []

    def _report(self, message: str) -> None:
        """Report progress to the orchestrator's live log."""
        import datetime

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {message}"
        self._progress_log.append(entry)
        logger.info("agent.progress", agent=self.name, message=message)

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Public entry point. Wraps _execute with logging and error handling."""
        logger.info("agent.start", agent=self.name, run_id=str(self.run_id))
        self._report("Starting...")
        start = time.monotonic()
        try:
            result = await self._execute(context)
            elapsed = time.monotonic() - start
            self._report(f"Done ({elapsed:.1f}s)")
            logger.info("agent.complete", agent=self.name, elapsed=f"{elapsed:.2f}s")
            return result
        except Exception as exc:
            elapsed = time.monotonic() - start
            self._report(f"Failed: {str(exc)[:100]}")
            logger.exception("agent.error", agent=self.name, elapsed=f"{elapsed:.2f}s")
            raise

    @abstractmethod
    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Agent-specific logic. Must be implemented by subclasses."""
        ...

    @retry(
        # Transient infrastructure errors (e.g. a DB hiccup while enqueueing) are retried.
        # Waiting for capacity, a failed job or a policy error is final for this call.
        retry=retry_if_not_exception_type((LLMUnavailable, LLMPolicyError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        reraise=True,
    )
    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        output_schema: dict[str, Any] | None = None,
    ) -> ShimMessage:
        """Run one subscription LLM job and record its usage.

        ``model`` is recorded as the requested model only; the job always runs on
        the policy model. ``temperature`` is accepted for compatibility and ignored.
        Returns an Anthropic-shaped message (``content[0].text``, ``usage.*``).
        """
        requested_model = model or self.default_model
        start = time.monotonic()

        prompt_version: str | None = None
        if system is None:
            active = await self.prompt_manager.get_active(self.name)
            if active:
                system = active.prompt_text
                prompt_version = f"{self.name}:v{active.version}"

        system_text: str | None = None
        if system:
            # House voice, templates, QA rubric and founder voice ride along as
            # extra system segments, flattened to plain text for the worker.
            try:
                from tce.services.cache_prefix import CachePrefixBuilder

                builder = CachePrefixBuilder(self.db)
                system_text = flatten_system(await builder.build_system_message(system))
            except Exception:
                system_text = system

        if temperature != 0.7:
            logger.debug(
                "agent.temperature_ignored", agent=self.name, requested_temperature=temperature
            )

        req = LLMRequest(
            job_type=f"agent.{self.name}",
            agent_name=self.name,
            messages=normalize_messages(messages),
            system=system_text,
            output_schema=output_schema,
            max_tokens=max_tokens,
            requested_model=requested_model,
            prompt_version=prompt_version,
            run_id=self.run_id,
            # One agent call = one job. Re-running an agent must not replay an old answer.
            idempotency_key=f"agent:{self.name}:{uuid.uuid4().hex}",
        )

        self._report(f"Queued LLM job for the subscription worker (requested {requested_model})")
        result = await complete(req)
        elapsed = time.monotonic() - start
        self._report(
            f"LLM responded via {result.model} "
            f"({result.input_tokens}in/{result.output_tokens}out, {elapsed:.1f}s)"
        )

        # Usage is recorded with the model that actually ran. Billing is the
        # subscription, so no per-token dollars are attributed.
        await self.cost_tracker.record(
            run_id=self.run_id,
            agent_name=self.name,
            model_used=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            wall_time_seconds=elapsed,
            billing="subscription",
        )

        return ShimMessage(
            content=[TextBlock(text=result.text)],
            usage=ShimUsage(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
            model=result.model,
            id=f"llmjob_{result.job_id.hex}",
            job_id=result.job_id,
        )

    def _extract_text(self, response: Any) -> str:
        """Extract text content from an LLM response."""
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """Extract JSON from a response that may contain
        markdown code fences or surrounding text."""
        import json
        import re

        cleaned = text.strip()

        # Try direct parse first
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Strip markdown code fences if present
        if "```" in cleaned:
            # Find content between code fences
            match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    pass

        # Find the first [ ... ] block (array) or { ... } block (object)
        bracket_start = cleaned.find("[")
        brace_start = cleaned.find("{")

        # Try array first if it appears before the first object
        if bracket_start != -1 and (brace_start == -1 or bracket_start < brace_start):
            depth = 0
            for i in range(bracket_start, len(cleaned)):
                if cleaned[i] == "[":
                    depth += 1
                elif cleaned[i] == "]":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cleaned[bracket_start : i + 1])
                        except json.JSONDecodeError:
                            break

        # Try object
        if brace_start != -1:
            depth = 0
            for i in range(brace_start, len(cleaned)):
                if cleaned[i] == "{":
                    depth += 1
                elif cleaned[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cleaned[brace_start : i + 1])
                        except json.JSONDecodeError:
                            break

        # Nothing worked
        raise json.JSONDecodeError("No valid JSON found in response", text, 0)
