"""Regression tests for base agent's reasoning-model temperature handling.

Anthropic's reasoning-class models (Opus 4.7 onward) reject the `temperature`
parameter. AgentBase._call_llm must silently drop it for those models and
keep passing it for all others.
"""

from __future__ import annotations

from tce.agents.base import (
    _MODELS_WITHOUT_TEMPERATURE,
    _STRIPPABLE_KWARGS,
    _kwarg_from_anthropic_400,
    _model_accepts_temperature,
)


def test_reasoning_models_reject_temperature() -> None:
    assert not _model_accepts_temperature("claude-opus-4-7")
    assert not _model_accepts_temperature("claude-opus-4-7[1m]")
    assert not _model_accepts_temperature("claude-opus-4-7-20260301")


def test_sampling_models_accept_temperature() -> None:
    assert _model_accepts_temperature("claude-sonnet-4-20250514")
    assert _model_accepts_temperature("claude-sonnet-4-6")
    assert _model_accepts_temperature("claude-haiku-4-5-20251001")
    assert _model_accepts_temperature("claude-opus-3-20240229")


def test_deny_list_is_prefix_based() -> None:
    for prefix in _MODELS_WITHOUT_TEMPERATURE:
        assert not _model_accepts_temperature(prefix)
        assert not _model_accepts_temperature(prefix + "-anything")


def test_empty_and_unknown_models_accept_by_default() -> None:
    assert _model_accepts_temperature("")
    assert _model_accepts_temperature("some-future-sampling-model")


# ---------- runtime kwarg-stripping safety net ----------


def test_kwarg_sniffer_catches_temperature_deprecation() -> None:
    msg = "`temperature` is deprecated for this model."
    assert _kwarg_from_anthropic_400(msg) == "temperature"


def test_kwarg_sniffer_catches_unexpected_top_p() -> None:
    msg = "Unexpected parameter: top_p is not allowed for this model"
    assert _kwarg_from_anthropic_400(msg) == "top_p"


def test_kwarg_sniffer_catches_unsupported_top_k() -> None:
    msg = "The parameter top_k is unsupported on reasoning models"
    assert _kwarg_from_anthropic_400(msg) == "top_k"


def test_kwarg_sniffer_ignores_unrelated_400s() -> None:
    # Prompt length / tool use / other 400s must NOT be interpreted as
    # a kwarg problem - those need to bubble up.
    assert _kwarg_from_anthropic_400("prompt is too long") is None
    assert _kwarg_from_anthropic_400("invalid tool definition") is None
    assert _kwarg_from_anthropic_400("") is None


def test_kwarg_sniffer_never_strips_load_bearing_args() -> None:
    # Make sure the sniffer doesn't pick up model/messages/max_tokens
    # even if an error happens to mention them.
    for load_bearing in ("model", "messages", "max_tokens", "system"):
        assert load_bearing not in _STRIPPABLE_KWARGS


def test_strippable_kwargs_are_only_sampling_knobs() -> None:
    # If we ever expand this set we want a test to fail so we reconsider.
    assert _STRIPPABLE_KWARGS == frozenset({"temperature", "top_p", "top_k"})
