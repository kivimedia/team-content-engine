"""A voice critic that did not run must never be reported as a pass.

Regression: `_critique_voice` used to swallow every exception and return
{"score": 7, "verdict": "pass"}, so a crashed or capped critic earned a
passing grade that the package then carried downstream.
"""

from __future__ import annotations

from typing import Any

import pytest

from tce.agents import platform_writer


class _CrashingAgent:
    def __init__(self) -> None:
        self.reports: list[str] = []

    async def _call_llm(self, **_: Any) -> Any:
        raise RuntimeError("subscription worker capped")

    def _extract_text(self, resp: Any) -> str:  # pragma: no cover - never reached
        return ""

    def _parse_json_response(self, text: str) -> dict[str, Any]:  # pragma: no cover
        return {}

    def _report(self, message: str) -> None:
        self.reports.append(message)


class _GarbageAgent(_CrashingAgent):
    async def _call_llm(self, **_: Any) -> Any:
        return object()

    def _extract_text(self, resp: Any) -> str:
        return "not json at all"

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        import json

        return json.loads(text)


@pytest.fixture(autouse=True)
def _voice_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform_writer, "load_voice_patterns", lambda: "RULE: be specific")


@pytest.mark.parametrize("agent_cls", [_CrashingAgent, _GarbageAgent])
async def test_failed_critic_is_unevaluated_not_pass(agent_cls: type[_CrashingAgent]) -> None:
    agent = agent_cls()
    result = {"facebook_post": "A draft post."}

    out = await platform_writer._run_voice_critic_loop(
        agent, result, "facebook_post", "facebook", system_prompt="sys"
    )

    assert out.get("voice_verdict") != "pass"
    assert out.get("voice_score") is None
    assert out["voice_evaluation_status"] == "unevaluated"
    assert out["voice_evaluation_error"]
    # The draft itself is kept untouched.
    assert out["facebook_post"] == "A draft post."


async def test_successful_critic_is_marked_evaluated() -> None:
    class _PassAgent(_CrashingAgent):
        async def _call_llm(self, **_: Any) -> Any:
            return object()

        def _extract_text(self, resp: Any) -> str:
            return '{"score": 9, "verdict": "pass", "violations": [], "summary": "ok"}'

        def _parse_json_response(self, text: str) -> dict[str, Any]:
            import json

            return json.loads(text)

    out = await platform_writer._run_voice_critic_loop(
        _PassAgent(), {"facebook_post": "x"}, "facebook_post", "facebook", system_prompt="s"
    )
    assert out["voice_verdict"] == "pass"
    assert out["voice_score"] == 9
    assert out["voice_evaluation_status"] == "evaluated"
