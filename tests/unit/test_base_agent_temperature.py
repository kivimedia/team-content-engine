"""AgentBase._call_llm under the subscription-only LLM policy.

This file used to cover per-model temperature stripping and the runtime
400-driven kwarg-stripping safety net for the metered SDK client. Both are gone:
every agent call is now one llm_jobs row run by a Claude Code subscription worker
on POLICY_MODEL, which has no sampling knob. These tests pin the replacement
behaviour: temperature and model are accepted for compatibility, the model is
recorded only as the requested model, and nothing reaches a metered client.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

import tce.agents.base as base_mod
from tce.agents.base import AgentBase
from tce.llm import POLICY_MODEL, LLMRequest, LLMResult, LLMUnavailable


class _Agent(AgentBase):
    name = "synthetic_agent"
    default_model = "claude-sonnet-5"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        return {}


class _Prompts:
    def __init__(self, active=None):
        self.active = active

    async def get_active(self, agent_name: str):
        return self.active


class _Costs:
    def __init__(self):
        self.events: list[dict[str, Any]] = []

    async def record(self, **kwargs):
        self.events.append(kwargs)


def _agent(active=None) -> tuple[_Agent, _Costs]:
    costs = _Costs()
    agent = _Agent(
        db=None,
        settings=SimpleNamespace(),
        cost_tracker=costs,
        prompt_manager=_Prompts(active),
        run_id=uuid.uuid4(),
    )
    return agent, costs


@pytest.fixture
def captured(monkeypatch):
    calls: list[LLMRequest] = []

    async def fake_complete(req: LLMRequest, **_: Any) -> LLMResult:
        calls.append(req)
        return LLMResult(
            job_id=uuid.uuid4(),
            text="agent answer",
            structured=None,
            model=POLICY_MODEL,
            input_tokens=30,
            output_tokens=12,
        )

    monkeypatch.setattr(base_mod, "complete", fake_complete)
    return calls


def test_base_module_has_no_metered_client():
    assert not hasattr(base_mod, "anthropic")
    agent, _ = _agent()
    assert not hasattr(agent, "_client")


async def test_call_llm_goes_through_complete(captured):
    agent, costs = _agent()
    resp = await agent._call_llm(
        [{"role": "user", "content": "synthetic"}],
        system="system text",
        model="claude-opus-4-7",
        max_tokens=321,
        temperature=0.2,
    )
    assert len(captured) == 1
    req = captured[0]
    assert req.requested_model == "claude-opus-4-7"
    assert req.max_tokens == 321 and req.run_id == agent.run_id
    assert req.job_type == "agent.synthetic_agent"
    assert req.system == "system text"  # no DB: cache-prefix builder falls back to the prompt
    assert req.messages == [{"role": "user", "content": "synthetic"}]
    assert not hasattr(req, "temperature")

    assert agent._extract_text(resp) == "agent answer"
    assert resp.content[0].text == "agent answer"
    assert resp.usage.input_tokens == 30 and resp.usage.output_tokens == 12
    assert resp.model == POLICY_MODEL

    assert costs.events[0]["model_used"] == POLICY_MODEL
    assert costs.events[0]["billing"] == "subscription"
    assert costs.events[0]["input_tokens"] == 30


async def test_temperature_is_ignored_for_every_model(captured):
    agent, _ = _agent()
    for model in ("claude-opus-4-7", "claude-sonnet-5", "claude-haiku-4-5-20251001", None):
        await agent._call_llm(
            [{"role": "user", "content": "x"}], system="s", model=model, temperature=0.9
        )
    assert [r.requested_model for r in captured] == [
        "claude-opus-4-7",
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-5",
    ]


async def test_each_agent_call_is_its_own_job(captured):
    agent, _ = _agent()
    for _ in range(2):
        await agent._call_llm([{"role": "user", "content": "same"}], system="s")
    assert captured[0].idempotency_key != captured[1].idempotency_key


async def test_active_prompt_used_when_system_missing(captured):
    agent, _ = _agent(active=SimpleNamespace(prompt_text="library prompt", version=7))
    await agent._call_llm([{"role": "user", "content": "x"}])
    assert captured[0].system == "library prompt"
    assert captured[0].prompt_version == "synthetic_agent:v7"


async def test_unavailable_is_not_retried(monkeypatch):
    calls = []

    async def waiting(req, **_):
        calls.append(req)
        raise LLMUnavailable("waiting_capacity", "usage limit")

    monkeypatch.setattr(base_mod, "complete", waiting)
    agent, costs = _agent()
    with pytest.raises(LLMUnavailable):
        await agent._call_llm([{"role": "user", "content": "x"}], system="s")
    assert len(calls) == 1 and costs.events == []
