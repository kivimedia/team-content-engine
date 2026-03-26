"""Base agent class with LLM calling, cost tracking, and prompt resolution."""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import anthropic
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from tce.services.cost_tracker import CostTracker
    from tce.services.prompt_manager import PromptManager
    from tce.settings import Settings

logger = structlog.get_logger()


class AgentBase(ABC):
    """Abstract base for all content engine agents.

    Subclasses implement _execute() with agent-specific logic.
    The base class provides LLM calling with automatic cost tracking
    and prompt version resolution.
    """

    name: str = "base"
    default_model: str = "claude-sonnet-4-20250514"

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        cost_tracker: CostTracker,
        prompt_manager: PromptManager,
        run_id: uuid.UUID | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.cost_tracker = cost_tracker
        self.prompt_manager = prompt_manager
        self.run_id = run_id or uuid.uuid4()
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Public entry point. Wraps _execute with logging and error handling."""
        logger.info("agent.start", agent=self.name, run_id=str(self.run_id))
        start = time.monotonic()
        try:
            result = await self._execute(context)
            elapsed = time.monotonic() - start
            logger.info("agent.complete", agent=self.name, elapsed=f"{elapsed:.2f}s")
            return result
        except Exception:
            elapsed = time.monotonic() - start
            logger.exception("agent.error", agent=self.name, elapsed=f"{elapsed:.2f}s")
            raise

    @abstractmethod
    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Agent-specific logic. Must be implemented by subclasses."""
        ...

    @retry(
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
    ) -> anthropic.types.Message:
        """Call the Anthropic API with automatic retry and cost recording."""
        from tce.services.resilience import resilience_manager

        model = model or self.default_model

        # Check if we should use a fallback model (PRD Section 42.3)
        use_fallback, fallback_model = (
            resilience_manager.should_use_fallback(model)
        )
        if use_fallback and fallback_model:
            logger.warning(
                "agent.model_fallback",
                agent=self.name,
                from_model=model,
                to_model=fallback_model,
            )
            model = fallback_model

        start = time.monotonic()

        # Resolve system prompt from prompt library if not provided
        if system is None:
            prompt_version = await self.prompt_manager.get_active(self.name)
            if prompt_version:
                system = prompt_version.prompt_text

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
        }
        if system:
            # PRD Section 36.8: Prompt caching implementation
            # Place cache_control breakpoint at end of system prompt
            # so the stable prefix (system prompt + voice config +
            # template library) is cached across calls
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        response = await self._client.messages.create(**kwargs)
        elapsed = time.monotonic() - start

        # Record cost
        await self.cost_tracker.record(
            run_id=self.run_id,
            agent_name=self.name,
            model_used=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            wall_time_seconds=elapsed,
        )

        return response

    def _extract_text(self, response: anthropic.types.Message) -> str:
        """Extract text content from an Anthropic response."""
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """Extract JSON from a response that may contain markdown code fences."""
        import json

        # Strip markdown code fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first and last lines (code fences)
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        return json.loads(cleaned)
