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


# Anthropic's reasoning-class models reject the `temperature` parameter
# (thinking budget is the knob, not sampling entropy). Any model whose ID
# starts with one of these prefixes gets the kwarg silently dropped inside
# _call_llm below. Extend this tuple when Anthropic releases another one.
_MODELS_WITHOUT_TEMPERATURE: tuple[str, ...] = (
    "claude-opus-4-7",
)


def _model_accepts_temperature(model: str) -> bool:
    return not model.startswith(_MODELS_WITHOUT_TEMPERATURE)


# Kwargs we're willing to strip on-the-fly when Anthropic returns a 400
# complaining about an unsupported or deprecated parameter. This is the
# runtime safety net that catches the NEXT undocumented model change
# before it kills a production pipeline. We only strip top-level kwargs
# that are safe to drop (sampling knobs); we never strip `model`,
# `messages`, `max_tokens`, or `system`.
_STRIPPABLE_KWARGS: frozenset[str] = frozenset({"temperature", "top_p", "top_k"})


def _kwarg_from_anthropic_400(error_message: str) -> str | None:
    """Extract the name of the offending kwarg from a 400 error message.

    Anthropic's error strings like `temperature is deprecated for this model`
    or `Unexpected parameter: top_p` consistently name the parameter. We
    intersect that with our allowed-to-strip set so we never drop anything
    the caller actually needs.
    """
    lower = error_message.lower()
    for name in _STRIPPABLE_KWARGS:
        if name in lower and (
            "deprecat" in lower
            or "unsupported" in lower
            or "unexpected" in lower
            or "not allowed" in lower
            or "cannot be used" in lower
        ):
            return name
    return None


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
        progress_log: list[str] | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.cost_tracker = cost_tracker
        self.prompt_manager = prompt_manager
        self.run_id = run_id or uuid.uuid4()
        self._progress_log = progress_log if progress_log is not None else []
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )

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
        use_fallback, fallback_model = resilience_manager.should_use_fallback(model)
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
        }
        if _model_accepts_temperature(model):
            kwargs["temperature"] = temperature
        elif temperature != 0.7:
            logger.info(
                "agent.temperature_dropped",
                agent=self.name,
                model=model,
                requested_temperature=temperature,
            )
        if system:
            # GAP-07: Multi-segment prompt caching (PRD Section 36.8)
            # Try to build full cached prefix with house voice, templates, etc.
            try:
                from tce.services.cache_prefix import CachePrefixBuilder

                builder = CachePrefixBuilder(self.db)
                kwargs["system"] = await builder.build_system_message(system)
            except Exception:
                # Fallback to single-segment caching
                kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]

        self._report(f"Calling {model}...")
        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.BadRequestError as exc:
            # Runtime safety net: if Anthropic 400s because a parameter is
            # deprecated/unsupported for this model, strip it once and retry.
            # See _kwarg_from_anthropic_400 - we only strip sampling knobs,
            # never load-bearing args like model/messages/max_tokens.
            offender = _kwarg_from_anthropic_400(str(exc))
            if offender and offender in kwargs:
                logger.warning(
                    "agent.kwarg_stripped_on_400",
                    agent=self.name,
                    model=model,
                    stripped_kwarg=offender,
                    error=str(exc)[:200],
                )
                kwargs.pop(offender)
                response = await self._client.messages.create(**kwargs)
            else:
                raise
        elapsed = time.monotonic() - start
        in_tok = response.usage.input_tokens
        out_tok = response.usage.output_tokens
        self._report(f"LLM responded ({in_tok}in/{out_tok}out, {elapsed:.1f}s)")

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
