"""Subscription worker: env fail-closed, auth preflight, stream-json receipts, capacity.

No real claude binary and no network: subprocess and HTTP are faked.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from tce.llm import POLICY_MODEL
from tce.llm import worker as w

AUX = "claude-haiku-4-5-20251001"
AUTH_OK = {
    "loggedIn": True,
    "authMethod": "claude.ai",
    "apiProvider": "firstParty",
    "subscriptionType": "max",
    "email": "someone@example.com",
    "orgId": "org-1",
}


def stream(result_text="synthetic answer", *, model=POLICY_MODEL, key_source="none", **result):
    events = [
        {
            "type": "system",
            "subtype": "init",
            "model": model,
            "apiKeySource": key_source,
            "session_id": "sess-1",
        },
        {"type": "assistant", "message": {"content": [{"type": "text", "text": result_text}]}},
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": result_text,
            "session_id": "sess-1",
            "num_turns": 1,
            "modelUsage": {
                model: {"inputTokens": 20, "outputTokens": 9, "cacheReadInputTokens": 0},
                AUX: {"inputTokens": 5, "outputTokens": 1},
            },
            **result,
        },
    ]
    return "\n".join(json.dumps(e) for e in events) + "\n"


def runner_for(auth: dict, version="2.1.270 (Claude Code)"):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        out = json.dumps(auth) if "auth" in cmd else version
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    run.calls = calls  # type: ignore[attr-defined]
    return run


class FakeProc:
    def __init__(self, stdout="", stderr="", hang=False):
        self._stdout, self._stderr, self._hang = stdout, stderr, hang
        self.killed = False
        self.stdin_text = None

    def communicate(self, input=None, timeout=None):  # noqa: A002
        if input is not None:
            self.stdin_text = input
        if self._hang and not self.killed:
            raise subprocess.TimeoutExpired("claude", timeout)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


class FakePopen:
    def __init__(self, proc):
        self.proc = proc
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return self.proc


class FakeApi:
    def __init__(self, jobs=None):
        self.jobs = list(jobs or [])
        self.posts = []

    def post(self, path, body):
        self.posts.append((path, body))
        if path == "/lease":
            return 200, {"job": self.jobs.pop(0) if self.jobs else None}
        return 200, {"status": "ok"}


BASE_ENV = {"PATH": "/usr/bin", "HOME": "/home/tester", "TCE_CLAUDE_BIN": "/opt/fake/claude"}


def job(schema=None, messages=None, system="be brief"):
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "attempt_id": "22222222-2222-2222-2222-222222222222",
        "attempt_count": 1,
        "job_type": "test.synthetic",
        "policy_model": POLICY_MODEL,
        "request_json": {
            "system": system,
            "messages": messages or [{"role": "user", "content": "synthetic prompt"}],
            "output_schema": schema,
            "max_tokens": 100,
        },
    }


def ok_preflight():
    return w.Preflight(
        True,
        "ok",
        logged_in=True,
        auth_method="claude.ai",
        api_provider="firstParty",
        subscription_type="max",
        cli_version="2.1.270",
    )


# --- environment -------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "TCE_ANTHROPIC_API_KEY",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "AWS_BEARER_TOKEN_BEDROCK",
    ],
)
def test_worker_refuses_to_start_with_metered_env(name):
    env = {**BASE_ENV, name: "synthetic-value"}
    api = FakeApi([job()])
    popen = FakePopen(FakeProc(stream()))
    runner = runner_for(AUTH_OK)
    worker = w.Worker(api, "w1", env=env, popen=popen, runner=runner, log=lambda _: None)
    assert worker.run(once=True) == w.EXIT_ENV_VIOLATION
    assert popen.calls == [] and runner.calls == []
    assert all(path != "/lease" for path, _ in api.posts)
    status = [b for p, b in api.posts if p == "/worker-status"][0]
    assert status["state"] == "refused" and name in status["env_violations"]
    assert "synthetic-value" not in json.dumps(api.posts)


def test_child_env_strips_provider_and_nested_session_vars():
    env = {
        **BASE_ENV,
        "ANTHROPIC_MODEL": "x",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "CLAUDE_CODE_SESSION_ID": "abc",
        "CLAUDE_CODE_CHILD_SESSION": "1",
        "CLAUDE_CODE_MESSAGING_SOCKET": "x",
        "TCE_PRIVATE_ACCESS_KEY": "k",
        "KEEP_ME": "yes",
    }
    child = w.child_env(env)
    assert child["KEEP_ME"] == "yes" and child["PATH"] == "/usr/bin"
    for gone in (
        "ANTHROPIC_MODEL",
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_CODE_MESSAGING_SOCKET",
        "TCE_PRIVATE_ACCESS_KEY",
    ):
        assert gone not in child


def test_empty_provider_var_is_not_a_violation_but_is_stripped():
    env = {**BASE_ENV, "ANTHROPIC_API_KEY": ""}
    assert w.env_violations(env) == []
    assert "ANTHROPIC_API_KEY" not in w.child_env(env)


# --- preflight -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("auth", "reason"),
    [
        ({**AUTH_OK, "loggedIn": False}, "not logged in"),
        ({**AUTH_OK, "authMethod": "api_key"}, "allow-list"),
        ({**AUTH_OK, "authMethod": "oauth_token"}, "allow-list"),
        ({**AUTH_OK, "apiProvider": "bedrock"}, "firstParty"),
    ],
)
def test_preflight_rejects_non_subscription_auth(auth, reason):
    pf = w.run_preflight("/opt/fake/claude", BASE_ENV, runner=runner_for(auth))
    assert not pf.ok and reason in pf.reason


def test_preflight_accepts_subscription_and_keeps_no_identity():
    pf = w.run_preflight("/opt/fake/claude", BASE_ENV, runner=runner_for(AUTH_OK))
    assert pf.ok and pf.auth_method == "claude.ai" and pf.cli_version == "2.1.270"
    blob = json.dumps(pf.public())
    assert "someone@example.com" not in blob and "org-1" not in blob


def test_preflight_oauth_token_needs_explicit_opt_in():
    auth = {**AUTH_OK, "authMethod": "oauth_token"}
    env = {**BASE_ENV, "TCE_WORKER_ALLOWED_AUTH": "oauth_token,api_key"}
    assert w.run_preflight("/opt/fake/claude", env, runner=runner_for(auth)).ok
    assert w.allowed_auth_methods(env) == frozenset({"claude.ai", "oauth_token"})


def test_worker_exits_nonzero_when_preflight_fails():
    api = FakeApi([job()])
    popen = FakePopen(FakeProc(stream()))
    worker = w.Worker(
        api,
        "w1",
        env=BASE_ENV,
        popen=popen,
        runner=runner_for({**AUTH_OK, "authMethod": "api_key"}),
        log=lambda _: None,
    )
    assert worker.run(once=True) == w.EXIT_PREFLIGHT_FAILED
    assert popen.calls == []
    assert all(path != "/lease" for path, _ in api.posts)


# --- command, parsing, receipts ------------------------------------------------------


def test_build_command_flags():
    cmd = w.build_command("/opt/fake/claude", system="sys", output_schema={"type": "object"})
    assert cmd[:4] == ["/opt/fake/claude", "-p", "--model", POLICY_MODEL]
    joined = " ".join(cmd)
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--verbose"):
        assert flag in cmd
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[cmd.index("--system-prompt") + 1] == "sys"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == {"type": "object"}
    assert "--fallback-model" not in joined


def test_parse_stream_json_builds_receipt_with_auxiliary_model():
    parsed = w.parse_stream_json(stream().splitlines() + ["not json"])
    assert parsed.init_model == POLICY_MODEL and parsed.api_key_source == "none"
    assert parsed.unparsed_lines == 1
    receipt = w.build_receipt(
        parsed, ok_preflight(), worker_id="w1", attempt_id="a1", duration_ms=5
    )
    assert receipt["models"][POLICY_MODEL]["output_tokens"] == 9
    assert receipt["models"][POLICY_MODEL]["auxiliary"] is False
    assert receipt["models"][AUX]["auxiliary"] is True
    assert receipt["auxiliary_models"] == [AUX]
    assert receipt["policy_model_output_tokens"] == 9
    assert receipt["api_key_source"] == "none" and receipt["session_id"] == "sess-1"
    assert receipt["auth_method"] == "claude.ai" and receipt["attempt_id"] == "a1"


def test_render_prompt_multi_turn_transcript():
    text = w.render_prompt(
        [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
    )
    assert "<USER>\nq1\n</USER>" in text and "<ASSISTANT>\na1\n</ASSISTANT>" in text
    assert w.render_prompt([{"role": "user", "content": "only"}]) == "only"


# --- execute --------------------------------------------------------------------


def test_execute_success_with_structured_output():
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    out = stream('{"title": "x"}', structured_output={"title": "x"})
    popen = FakePopen(FakeProc(out))
    worker = w.Worker(
        FakeApi(),
        "w1",
        env={**BASE_ENV, "CLAUDECODE": "1"},
        popen=popen,
        runner=runner_for(AUTH_OK),
        log=lambda _: None,
        heartbeat_s=3600,
    )
    outcome = worker.execute(job(schema=schema), ok_preflight())
    assert outcome.kind == "complete"
    assert outcome.body["result_json"] == {"title": "x"}
    assert outcome.body["receipt"]["auxiliary_models"] == [AUX]
    cmd, kwargs = popen.calls[0]
    assert "--json-schema" in cmd
    assert "CLAUDECODE" not in kwargs["env"]
    assert popen.proc.stdin_text == "synthetic prompt"


def test_execute_long_system_prompt_uses_file():
    popen = FakePopen(FakeProc(stream()))
    worker = w.Worker(
        FakeApi(),
        "w1",
        env=BASE_ENV,
        popen=popen,
        runner=runner_for(AUTH_OK),
        log=lambda _: None,
        heartbeat_s=3600,
    )
    outcome = worker.execute(job(system="x" * (w.SYSTEM_PROMPT_INLINE_LIMIT + 1)), ok_preflight())
    cmd, _ = popen.calls[0]
    assert "--system-prompt-file" in cmd and "--system-prompt" not in cmd
    assert outcome.kind == "complete"


def test_execute_reports_capacity_with_parsed_retry_at():
    limited = stream(
        "Claude usage limit reached. Your limit will reset at 2099-01-01T05:00:00Z",
        is_error=True,
        api_error_status=429,
    )
    worker = w.Worker(
        FakeApi(),
        "w1",
        env=BASE_ENV,
        popen=FakePopen(FakeProc(limited)),
        runner=runner_for(AUTH_OK),
        log=lambda _: None,
        heartbeat_s=3600,
    )
    outcome = worker.execute(job(), ok_preflight())
    assert outcome.kind == "fail" and outcome.body["error_code"] == "capacity"
    assert outcome.body["retry_at"].startswith("2099-01-01T05:00:00")


def test_capacity_without_parseable_time_defaults_to_30_minutes():
    limited = stream("You've hit your usage limit", is_error=True)
    worker = w.Worker(
        FakeApi(),
        "w1",
        env=BASE_ENV,
        popen=FakePopen(FakeProc(limited)),
        runner=runner_for(AUTH_OK),
        log=lambda _: None,
        heartbeat_s=3600,
    )
    outcome = worker.execute(job(), ok_preflight())
    retry_at = datetime.fromisoformat(outcome.body["retry_at"])
    now = datetime.now(UTC).replace(tzinfo=None)
    assert outcome.body["error_code"] == "capacity"
    assert now + timedelta(minutes=29) < retry_at < now + timedelta(minutes=31)


def test_parse_retry_at_formats():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    assert w.parse_retry_at("limit reached|4102444800", now) == datetime(2100, 1, 1)
    assert w.parse_retry_at("try again in 2 hours", now) == datetime(2026, 9, 16, 12, 0)
    assert w.parse_retry_at("resets 3pm (UTC)", now) == datetime(2026, 9, 16, 15, 0)
    assert w.parse_retry_at("resets 9am", now) == datetime(2026, 9, 17, 9, 0)
    assert w.parse_retry_at("no time here", now) is None


def test_execute_policy_violation_when_cli_used_api_key():
    out = stream(key_source="ANTHROPIC_API_KEY")
    worker = w.Worker(
        FakeApi(),
        "w1",
        env=BASE_ENV,
        popen=FakePopen(FakeProc(out)),
        runner=runner_for(AUTH_OK),
        log=lambda _: None,
        heartbeat_s=3600,
    )
    outcome = worker.execute(job(), ok_preflight())
    assert outcome.body["error_code"] == "policy_violation"


def test_execute_model_mismatch_when_session_model_differs():
    out = stream(model="claude-sonnet-5")
    worker = w.Worker(
        FakeApi(),
        "w1",
        env=BASE_ENV,
        popen=FakePopen(FakeProc(out)),
        runner=runner_for(AUTH_OK),
        log=lambda _: None,
        heartbeat_s=3600,
    )
    outcome = worker.execute(job(), ok_preflight())
    assert outcome.body["error_code"] == "model_mismatch"


def test_execute_timeout_kills_process():
    proc = FakeProc(stream(), hang=True)
    worker = w.Worker(
        FakeApi(),
        "w1",
        env=BASE_ENV,
        popen=FakePopen(proc),
        runner=runner_for(AUTH_OK),
        log=lambda _: None,
        job_timeout_s=0.01,
        heartbeat_s=3600,
    )
    outcome = worker.execute(job(), ok_preflight())
    assert proc.killed and outcome.body["error_code"] == "timeout"


def test_run_once_leases_executes_and_completes():
    api = FakeApi([job()])
    popen = FakePopen(FakeProc(stream()))
    worker = w.Worker(
        api,
        "w1",
        env=BASE_ENV,
        popen=popen,
        runner=runner_for(AUTH_OK),
        log=lambda _: None,
        heartbeat_s=3600,
    )
    assert worker.run(once=True) == w.EXIT_OK
    paths = [p for p, _ in api.posts]
    assert "/lease" in paths
    complete = [b for p, b in api.posts if p.endswith("/complete")]
    assert len(complete) == 1
    assert complete[0]["attempt_id"] == job()["attempt_id"]
    assert complete[0]["receipt"]["models"][POLICY_MODEL]["output_tokens"] == 9
    assert "someone@example.com" not in json.dumps(api.posts)
