"""Tests for rate limiting and resilience (PRD Section 42)."""

from tce.services.resilience import (
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    DEFAULT_RETRY_CONFIG,
    FALLBACK_CHAIN,
    CircuitBreakerState,
    RateLimitBudget,
    ResilienceManager,
)


def test_retry_config():
    """PRD Section 42.2: retry policy defaults."""
    assert DEFAULT_RETRY_CONFIG["max_retries"]["llm"] == 3
    assert DEFAULT_RETRY_CONFIG["max_retries"]["fal_ai"] == 3
    assert DEFAULT_RETRY_CONFIG["max_retries"]["web_search"] == 2
    assert DEFAULT_RETRY_CONFIG["timeout_seconds"]["llm"] == 120
    assert DEFAULT_RETRY_CONFIG["timeout_seconds"]["fal_ai"] == 60


def test_fallback_chain():
    """PRD Section 42.3: Opus -> Sonnet -> Haiku."""
    assert "claude-opus-4-20250514" in FALLBACK_CHAIN
    assert FALLBACK_CHAIN["claude-opus-4-20250514"] == "claude-sonnet-4-20250514"
    assert FALLBACK_CHAIN["claude-sonnet-4-20250514"] == "claude-haiku-4-5-20251001"


def test_circuit_breaker_initial():
    cb = CircuitBreakerState(service_name="test")
    assert not cb.is_open
    assert cb.failure_count == 0
    assert cb.should_allow_request()


def test_circuit_breaker_opens():
    cb = CircuitBreakerState(service_name="test")
    for _ in range(CIRCUIT_BREAKER_FAILURE_THRESHOLD):
        cb.record_failure()
    assert cb.is_open
    assert not cb.should_allow_request()


def test_circuit_breaker_success_resets():
    cb = CircuitBreakerState(service_name="test")
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.failure_count == 1  # Decremented by 1


def test_rate_limit_tracking():
    rl = RateLimitBudget(service_name="test", tpm_limit=100, rpm_limit=10)
    assert not rl.should_delay()
    for _ in range(9):
        rl.record_usage(10)
    assert rl.should_delay()  # 90% of tpm used


def test_rate_limit_usage_pct():
    rl = RateLimitBudget(service_name="test", tpm_limit=1000, rpm_limit=100)
    rl.record_usage(500)
    pct = rl.get_usage_pct()
    assert pct["tpm_pct"] == 50.0
    assert pct["rpm_pct"] == 1.0


def test_resilience_manager():
    manager = ResilienceManager()
    cb = manager.get_circuit_breaker("anthropic")
    assert cb.service_name == "anthropic"
    rl = manager.get_rate_limit("anthropic")
    assert rl.service_name == "anthropic"


def test_resilience_manager_fallback():
    manager = ResilienceManager()
    fallback = manager.get_fallback_model("claude-opus-4-20250514")
    assert fallback == "claude-sonnet-4-20250514"
    assert manager.get_fallback_model("unknown") is None


def test_resilience_status():
    manager = ResilienceManager()
    manager.get_circuit_breaker("test")
    status = manager.get_status()
    assert "circuit_breakers" in status
    assert "rate_limits" in status
