"""Rate limiting and resilience layer (PRD Section 42).

Provides circuit breaker, rate limit tracking, fallback model logic,
and queue management for external API calls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()

# PRD Section 42.2: Retry policy defaults
DEFAULT_RETRY_CONFIG = {
    "initial_delay_seconds": 1,
    "multiplier": 2,
    "max_delay_seconds": 60,
    "jitter_max_ms": 500,
    "max_retries": {
        "llm": 3,
        "fal_ai": 3,
        "web_search": 2,
    },
    "timeout_seconds": {
        "llm": 120,  # Opus can be slow
        "fal_ai": 60,
        "web_search": 30,
    },
}

# PRD Section 42.3: Fallback model chain
FALLBACK_CHAIN: dict[str, str] = {
    "claude-opus-4-20250514": "claude-sonnet-4-20250514",
    "claude-sonnet-4-20250514": "claude-haiku-4-5-20251001",
}

# Circuit breaker thresholds
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_RESET_SECONDS = 300  # 5 minutes


@dataclass
class CircuitBreakerState:
    """Tracks failures for a specific service."""

    service_name: str
    failure_count: int = 0
    last_failure_time: float = 0
    is_open: bool = False
    successes_since_half_open: int = 0

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            self.is_open = True
            logger.warning(
                "circuit_breaker.open",
                service=self.service_name,
                failures=self.failure_count,
            )

    def record_success(self) -> None:
        if self.is_open:
            self.successes_since_half_open += 1
            if self.successes_since_half_open >= 2:
                self.reset()
        else:
            self.failure_count = max(0, self.failure_count - 1)

    def should_allow_request(self) -> bool:
        if not self.is_open:
            return True
        # Check if enough time has passed for half-open
        elapsed = time.monotonic() - self.last_failure_time
        if elapsed >= CIRCUIT_BREAKER_RESET_SECONDS:
            return True  # Half-open: allow one request
        return False

    def reset(self) -> None:
        self.failure_count = 0
        self.is_open = False
        self.successes_since_half_open = 0
        logger.info(
            "circuit_breaker.reset",
            service=self.service_name,
        )


@dataclass
class RateLimitBudget:
    """Tracks token-per-minute and request-per-minute budgets."""

    service_name: str
    tpm_limit: int = 100_000
    rpm_limit: int = 60
    tpm_used: int = 0
    rpm_used: int = 0
    window_start: float = field(default_factory=time.monotonic)

    def _maybe_reset_window(self) -> None:
        elapsed = time.monotonic() - self.window_start
        if elapsed >= 60:
            self.tpm_used = 0
            self.rpm_used = 0
            self.window_start = time.monotonic()

    def record_usage(self, tokens: int) -> None:
        self._maybe_reset_window()
        self.tpm_used += tokens
        self.rpm_used += 1

    def should_delay(self) -> bool:
        self._maybe_reset_window()
        return (
            self.tpm_used >= self.tpm_limit * 0.9
            or self.rpm_used >= self.rpm_limit * 0.9
        )

    def get_usage_pct(self) -> dict[str, float]:
        self._maybe_reset_window()
        return {
            "tpm_pct": (
                self.tpm_used / self.tpm_limit * 100
                if self.tpm_limit > 0
                else 0
            ),
            "rpm_pct": (
                self.rpm_used / self.rpm_limit * 100
                if self.rpm_limit > 0
                else 0
            ),
        }


class ResilienceManager:
    """Manages circuit breakers, rate limits, and fallback logic."""

    def __init__(self) -> None:
        self._circuit_breakers: dict[str, CircuitBreakerState] = {}
        self._rate_limits: dict[str, RateLimitBudget] = {}

    def get_circuit_breaker(
        self, service_name: str
    ) -> CircuitBreakerState:
        if service_name not in self._circuit_breakers:
            self._circuit_breakers[service_name] = (
                CircuitBreakerState(service_name=service_name)
            )
        return self._circuit_breakers[service_name]

    def get_rate_limit(
        self, service_name: str
    ) -> RateLimitBudget:
        if service_name not in self._rate_limits:
            self._rate_limits[service_name] = RateLimitBudget(
                service_name=service_name
            )
        return self._rate_limits[service_name]

    def get_fallback_model(self, model: str) -> str | None:
        """Get the fallback model for a given model (PRD Section 42.3)."""
        return FALLBACK_CHAIN.get(model)

    def should_use_fallback(
        self, model: str
    ) -> tuple[bool, str | None]:
        """Check if we should fall back to a cheaper model."""
        cb = self.get_circuit_breaker(model)
        rl = self.get_rate_limit(model)

        if cb.is_open or rl.should_delay():
            fallback = self.get_fallback_model(model)
            if fallback:
                logger.info(
                    "resilience.fallback",
                    from_model=model,
                    to_model=fallback,
                )
                return True, fallback
        return False, None

    def get_status(self) -> dict[str, Any]:
        """Get overall resilience status."""
        return {
            "circuit_breakers": {
                name: {
                    "is_open": cb.is_open,
                    "failure_count": cb.failure_count,
                }
                for name, cb in self._circuit_breakers.items()
            },
            "rate_limits": {
                name: rl.get_usage_pct()
                for name, rl in self._rate_limits.items()
            },
        }


# Singleton
resilience_manager = ResilienceManager()
