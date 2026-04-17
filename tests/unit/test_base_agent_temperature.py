"""Regression tests for base agent's reasoning-model temperature handling.

Anthropic's reasoning-class models (Opus 4.7 onward) reject the `temperature`
parameter. AgentBase._call_llm must silently drop it for those models and
keep passing it for all others.
"""

from __future__ import annotations

from tce.agents.base import (
    _MODELS_WITHOUT_TEMPERATURE,
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
