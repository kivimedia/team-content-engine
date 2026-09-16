"""Claude Code subscription worker for the TCE LLM job queue.

Runs on a machine where ``claude`` is logged in to a subscription. It leases
jobs over HTTP, runs each one through ``claude -p`` on POLICY_MODEL with no
tools, no MCP, no settings and no session persistence, and posts the result
plus a receipt proving which models and which auth were used.

Fail-closed rules:
- the worker refuses to start when its own environment carries any metered or
  third-party-provider switch (Anthropic key/token/base URL, Bedrock/Vertex/Foundry);
- before every lease batch (and between jobs), ``claude auth status`` must report a
  logged-in first-party subscription auth method from the allow-list;
- a job is never retried under a different model or account. Usage limits are
  reported as ``capacity`` with a retry time; the job waits.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from tce.llm.provider import POLICY_MODEL, is_policy_model

# --- environment policy ------------------------------------------------------

# Any variable whose name contains ANTHROPIC (keys, auth tokens, base URL overrides,
# model overrides, custom headers - with or without a TCE_ prefix) or that switches
# the CLI to Bedrock/Vertex/Foundry is refused.
FORBIDDEN_ENV_SUBSTRINGS = ("ANTHROPIC",)
FORBIDDEN_ENV_PREFIXES = ("CLAUDE_CODE_USE_", "CLAUDE_CODE_SKIP_")
FORBIDDEN_ENV_NAMES = frozenset({"AWS_BEARER_TOKEN_BEDROCK", "CLAUDE_CODE_API_KEY_HELPER_TTL_MS"})
NESTED_SESSION_NAMES = frozenset(
    {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION"}
)
NESTED_SESSION_PREFIXES = ("CLAUDE_CODE_MESSAGING_",)
# The worker's own service key is never passed to the model subprocess.
WORKER_ONLY_NAMES = frozenset({"TCE_PRIVATE_ACCESS_KEY"})

DEFAULT_ALLOWED_AUTH = frozenset({"claude.ai"})
OPTIONAL_AUTH = frozenset({"oauth_token"})

EXIT_OK = 0
EXIT_ENV_VIOLATION = 2
EXIT_PREFLIGHT_FAILED = 3


def _is_forbidden(name: str) -> bool:
    upper = name.upper()
    return (
        upper in FORBIDDEN_ENV_NAMES
        or upper.startswith(FORBIDDEN_ENV_PREFIXES)
        or any(part in upper for part in FORBIDDEN_ENV_SUBSTRINGS)
    )


def env_violations(env: dict[str, str]) -> list[str]:
    """Names (never values) of metered/third-party variables that are set non-empty."""
    return sorted(name for name, value in env.items() if value and _is_forbidden(name))


def child_env(env: dict[str, str]) -> dict[str, str]:
    out = {}
    for name, value in env.items():
        upper = name.upper()
        if _is_forbidden(name) or upper in NESTED_SESSION_NAMES or upper in WORKER_ONLY_NAMES:
            continue
        if upper.startswith(NESTED_SESSION_PREFIXES):
            continue
        out[name] = value
    return out


def allowed_auth_methods(env: dict[str, str]) -> frozenset[str]:
    extra = {
        item.strip()
        for item in (env.get("TCE_WORKER_ALLOWED_AUTH") or "").split(",")
        if item.strip() in OPTIONAL_AUTH
    }
    return DEFAULT_ALLOWED_AUTH | extra


def resolve_claude_bin(env: dict[str, str]) -> str | None:
    explicit = env.get("TCE_CLAUDE_BIN")
    if explicit:
        return explicit
    return shutil.which("claude")


# --- subprocess plumbing -----------------------------------------------------


def _popen_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def _command(bin_path: str, args: list[str]) -> list[str]:
    # npm installs claude as a .cmd shim on Windows; it must run through cmd.exe.
    if os.name == "nt" and bin_path.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/d", "/c", bin_path, *args]
    return [bin_path, *args]


@dataclass
class Preflight:
    ok: bool
    reason: str
    logged_in: bool = False
    auth_method: str | None = None
    api_provider: str | None = None
    subscription_type: str | None = None
    cli_version: str | None = None
    env_violations: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "logged_in": self.logged_in,
            "auth_method": self.auth_method,
            "api_provider": self.api_provider,
            "subscription_type": self.subscription_type,
            "cli_version": self.cli_version,
            "env_violations": self.env_violations,
            "policy_model": POLICY_MODEL,
        }


Runner = Callable[..., subprocess.CompletedProcess]


def run_preflight(
    bin_path: str | None,
    env: dict[str, str],
    *,
    runner: Runner = subprocess.run,
) -> Preflight:
    violations = env_violations(env)
    if violations:
        return Preflight(
            False,
            "metered or third-party provider variables are set: " + ", ".join(violations),
            env_violations=violations,
        )
    if not bin_path:
        return Preflight(False, "claude CLI not found (set TCE_CLAUDE_BIN or add it to PATH)")
    cenv = child_env(env)
    common = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 60,
        "env": cenv,
        **_popen_kwargs(),
    }
    try:
        status = runner(_command(bin_path, ["auth", "status", "--json"]), **common)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Preflight(False, f"claude auth status could not run: {type(exc).__name__}")
    try:
        data = json.loads(status.stdout or "{}")
    except json.JSONDecodeError:
        return Preflight(False, "claude auth status did not return JSON")
    if not isinstance(data, dict):
        return Preflight(False, "claude auth status returned an unexpected shape")

    version = None
    try:
        ver = runner(_command(bin_path, ["--version"]), **common)
        version = (ver.stdout or "").strip().split(" ")[0] or None
    except (OSError, subprocess.TimeoutExpired):
        version = None

    # Only these fields are kept; email / org id in the status output are discarded.
    pf = Preflight(
        ok=False,
        reason="",
        logged_in=data.get("loggedIn") is True,
        auth_method=data.get("authMethod"),
        api_provider=data.get("apiProvider"),
        subscription_type=data.get("subscriptionType"),
        cli_version=version,
    )
    allowed = allowed_auth_methods(env)
    if not pf.logged_in:
        pf.reason = "claude CLI is not logged in"
    elif pf.api_provider != "firstParty":
        pf.reason = f"apiProvider={pf.api_provider!r}; only firstParty is allowed"
    elif pf.auth_method not in allowed:
        pf.reason = f"authMethod={pf.auth_method!r} is not in the allow-list {sorted(allowed)}"
    else:
        pf.ok = True
        pf.reason = "subscription auth verified"
    return pf


# --- prompt/command ------------------------------------------------------------

SYSTEM_PROMPT_INLINE_LIMIT = 8000


def render_prompt(messages: list[dict[str, Any]]) -> str:
    def text_of(msg: dict[str, Any]) -> str:
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        return "\n\n".join(b.get("text", "") for b in content if isinstance(b, dict))

    if len(messages) == 1 and messages[0].get("role") == "user":
        return text_of(messages[0])
    lines = [
        "The conversation so far is below. Reply as the assistant to the final user turn. "
        "Output only that reply.",
        "",
    ]
    for msg in messages:
        label = "USER" if msg.get("role") == "user" else "ASSISTANT"
        lines.append(f"<{label}>\n{text_of(msg)}\n</{label}>")
    return "\n".join(lines)


def build_command(
    bin_path: str,
    *,
    system: str | None,
    output_schema: dict[str, Any] | None,
    system_prompt_file: str | None = None,
) -> list[str]:
    args = [
        "-p",
        "--model",
        POLICY_MODEL,
        "--tools",
        "",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--no-session-persistence",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if system_prompt_file:
        args += ["--system-prompt-file", system_prompt_file]
    elif system:
        args += ["--system-prompt", system]
    if output_schema is not None:
        args += ["--json-schema", json.dumps(output_schema, separators=(",", ":"))]
    return _command(bin_path, args)


# --- stream-json parsing and receipts -------------------------------------------


@dataclass
class ParsedRun:
    init_model: str | None = None
    api_key_source: str | None = None
    result_event: dict[str, Any] | None = None
    assistant_text: list[str] = field(default_factory=list)
    unparsed_lines: int = 0


def parse_stream_json(lines: Iterable[str]) -> ParsedRun:
    parsed = ParsedRun()
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            parsed.unparsed_lines += 1
            continue
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype == "system" and event.get("subtype") == "init":
            parsed.init_model = event.get("model")
            parsed.api_key_source = event.get("apiKeySource")
        elif etype == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    parsed.assistant_text.append(block.get("text", ""))
        elif etype == "result":
            parsed.result_event = event
    return parsed


def _usage_entry(usage: dict[str, Any]) -> dict[str, int]:
    def num(*keys: str) -> int:
        for key in keys:
            if usage.get(key) is not None:
                try:
                    return int(usage[key])
                except (TypeError, ValueError):
                    return 0
        return 0

    return {
        "input_tokens": num("inputTokens", "input_tokens"),
        "output_tokens": num("outputTokens", "output_tokens"),
        "cache_read_input_tokens": num("cacheReadInputTokens", "cache_read_input_tokens"),
        "cache_creation_input_tokens": num(
            "cacheCreationInputTokens", "cache_creation_input_tokens"
        ),
    }


def build_receipt(
    parsed: ParsedRun,
    preflight: Preflight,
    *,
    worker_id: str,
    attempt_id: str,
    duration_ms: int,
) -> dict[str, Any]:
    result = parsed.result_event or {}
    models: dict[str, dict[str, Any]] = {}
    for name, usage in (result.get("modelUsage") or {}).items():
        entry: dict[str, Any] = _usage_entry(usage if isinstance(usage, dict) else {})
        entry["auxiliary"] = not is_policy_model(name)
        models[name] = entry
    policy_out = sum(m["output_tokens"] for n, m in models.items() if is_policy_model(n))
    return {
        "models": models,
        "policy_model": POLICY_MODEL,
        "policy_model_output_tokens": policy_out,
        "auxiliary_models": sorted(n for n, m in models.items() if m["auxiliary"]),
        "auth_method": preflight.auth_method,
        "api_provider": preflight.api_provider,
        "subscription_type": preflight.subscription_type,
        "api_key_source": parsed.api_key_source,
        "cli_version": preflight.cli_version,
        "session_id": result.get("session_id"),
        "duration_ms": duration_ms,
        "worker_host": socket.gethostname(),
        "worker_id": worker_id,
        "attempt_id": attempt_id,
        "is_error": bool(result.get("is_error")),
        "api_error_status": result.get("api_error_status"),
        "num_turns": result.get("num_turns"),
        "stop_reason": result.get("stop_reason"),
    }


_CAPACITY_RE = re.compile(
    r"usage limit|rate limit|rate_limit|limit reached|limit will reset|resets? (?:at|in|on)\b|"
    r"out of (?:extra )?usage|overloaded|too many requests",
    re.IGNORECASE,
)


def parse_retry_at(message: str, now: datetime | None = None) -> datetime | None:
    """Best-effort reset time from a CLI limit message, as naive UTC."""
    now = now or datetime.now(UTC)
    epoch = re.search(r"\|\s*(\d{10})\b", message)
    if epoch:
        return datetime.fromtimestamp(int(epoch.group(1)), UTC).replace(tzinfo=None)
    iso = re.search(
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)", message
    )
    if iso:
        try:
            dt = datetime.fromisoformat(iso.group(1).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC).replace(tzinfo=None)
        except ValueError:
            pass
    rel = re.search(r"\bin\s+(\d+)\s*(minutes?|mins?|hours?|hrs?|h|m)\b", message, re.IGNORECASE)
    if rel:
        n = int(rel.group(1))
        delta = timedelta(hours=n) if rel.group(2).lower().startswith("h") else timedelta(minutes=n)
        return (now + delta).astimezone(UTC).replace(tzinfo=None)
    clock = re.search(
        r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:\(([A-Za-z_/+-]+)\))?",
        message,
        re.IGNORECASE,
    )
    if clock:
        hour = int(clock.group(1))
        minute = int(clock.group(2) or 0)
        ampm = (clock.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None
        tz: Any = UTC
        if clock.group(4):
            try:
                from zoneinfo import ZoneInfo

                tz = ZoneInfo(clock.group(4))
            except Exception:
                tz = UTC
        local_now = now.astimezone(tz)
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC).replace(tzinfo=None)
    return None


def detect_capacity(parsed: ParsedRun, stderr: str = "") -> tuple[bool, str]:
    result = parsed.result_event or {}
    status = result.get("api_error_status")
    parts = [str(result.get("result") or ""), " ".join(parsed.assistant_text), stderr]
    message = " ".join(p for p in parts if p).strip()
    if status in (429, 529, "429", "529"):
        return True, message
    if (result.get("is_error") or not result) and _CAPACITY_RE.search(message):
        return True, message
    return False, message


# --- HTTP client ----------------------------------------------------------------


class ApiClient:
    def __init__(self, api_base: str, service_key: str, *, timeout: float = 30.0) -> None:
        self.api_base = api_base.rstrip("/")
        self._key = service_key
        self.timeout = timeout

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        data = json.dumps(body, default=str).encode("utf-8")
        req = urllib.request.Request(
            f"{self.api_base}/api/v1/llm-jobs{path}",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8")
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, {"detail": raw[:500]}


# --- job execution ----------------------------------------------------------------


@dataclass
class JobOutcome:
    kind: str  # complete | fail
    body: dict[str, Any]


class Worker:
    def __init__(
        self,
        api: Any,
        worker_id: str,
        *,
        env: dict[str, str] | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        runner: Runner = subprocess.run,
        lease_seconds: int = 600,
        job_timeout_s: float = 540.0,
        heartbeat_s: float = 60.0,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.api = api
        self.worker_id = worker_id
        self.env = dict(os.environ if env is None else env)
        self.popen = popen
        self.runner = runner
        self.lease_seconds = lease_seconds
        self.job_timeout_s = job_timeout_s
        self.heartbeat_s = heartbeat_s
        self.log = log or (lambda msg: print(msg, file=sys.stderr, flush=True))
        self.bin_path = resolve_claude_bin(self.env)
        self.preflight: Preflight | None = None

    def report_status(
        self, state: str, preflight: Preflight | None, job_id: str | None = None
    ) -> None:
        payload: dict[str, Any] = {
            "worker_id": self.worker_id,
            "worker_host": socket.gethostname(),
            "checked_at": datetime.now(UTC).isoformat(),
            "state": state,
            "current_job_id": job_id,
        }
        if preflight is not None:
            payload.update(preflight.public())
        try:
            self.api.post("/worker-status", payload)
        except Exception as exc:  # status is best-effort; leasing still requires auth
            self.log(f"worker-status post failed: {type(exc).__name__}")

    def check(self) -> Preflight:
        pf = run_preflight(self.bin_path, self.env, runner=self.runner)
        self.preflight = pf
        return pf

    def execute(self, job: dict[str, Any], preflight: Preflight) -> JobOutcome:
        attempt_id = str(job["attempt_id"])
        request = job.get("request_json") or {}
        system = request.get("system")
        schema = request.get("output_schema")
        prompt = render_prompt(request.get("messages") or [])

        tmp_system = None
        if system and len(system) > SYSTEM_PROMPT_INLINE_LIMIT:
            fd, tmp_system = tempfile.mkstemp(prefix="tce-llm-system-", suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(system)
        cmd = build_command(
            self.bin_path or "claude",
            system=system,
            output_schema=schema,
            system_prompt_file=tmp_system,
        )

        stop_heartbeat = threading.Event()

        def beat() -> None:
            while not stop_heartbeat.wait(self.heartbeat_s):
                try:
                    status, _ = self.api.post(
                        f"/{job['id']}/heartbeat",
                        {"attempt_id": attempt_id, "lease_seconds": self.lease_seconds},
                    )
                    if status == 409:
                        self.log(f"job {job['id']}: lease lost (409 on heartbeat)")
                        return
                except Exception as exc:
                    self.log(f"heartbeat failed: {type(exc).__name__}")

        start = time.monotonic()
        timed_out = False
        out = err = ""
        hb = threading.Thread(target=beat, daemon=True)
        hb.start()
        try:
            proc = self.popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=child_env(self.env),
                cwd=tempfile.gettempdir(),
                **_popen_kwargs(),
            )
            try:
                out, err = proc.communicate(input=prompt, timeout=self.job_timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                out, err = proc.communicate()
        except OSError as exc:
            err = f"could not start claude: {type(exc).__name__}"
        finally:
            stop_heartbeat.set()
            hb.join(timeout=5)
            if tmp_system:
                try:
                    os.unlink(tmp_system)
                except OSError:
                    pass

        duration_ms = int((time.monotonic() - start) * 1000)
        parsed = parse_stream_json((out or "").splitlines())
        receipt = build_receipt(
            parsed,
            preflight,
            worker_id=self.worker_id,
            attempt_id=attempt_id,
            duration_ms=duration_ms,
        )
        stderr = err or ""

        if timed_out:
            return self._fail(
                attempt_id, "timeout", f"no result after {self.job_timeout_s:.0f}s", receipt
            )
        if parsed.api_key_source is not None and parsed.api_key_source != "none":
            return self._fail(
                attempt_id,
                "policy_violation",
                f"CLI reported apiKeySource={parsed.api_key_source!r}",
                receipt,
            )
        capacity, message = detect_capacity(parsed, stderr)
        if capacity:
            retry_at = parse_retry_at(message) or (
                datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30)
            )
            return JobOutcome(
                "fail",
                {
                    "attempt_id": attempt_id,
                    "error_code": "capacity",
                    "error_detail": message[:500],
                    "retry_at": retry_at.isoformat(),
                    "receipt": receipt,
                },
            )
        result = parsed.result_event
        if result is None:
            return self._fail(
                attempt_id,
                "no_result",
                f"CLI exited without a result event; stderr tail: {stderr[-500:]}",
                receipt,
            )
        if result.get("is_error"):
            return self._fail(
                attempt_id, "cli_error", str(result.get("result") or "")[:1000], receipt
            )
        if parsed.init_model and not is_policy_model(parsed.init_model):
            return self._fail(
                attempt_id,
                "model_mismatch",
                f"CLI session model was {parsed.init_model!r}",
                receipt,
            )
        text = result.get("result")
        structured = result.get("structured_output")
        if schema is not None and structured is None and text:
            try:
                structured = json.loads(text)
            except json.JSONDecodeError:
                structured = None
        return JobOutcome(
            "complete",
            {
                "attempt_id": attempt_id,
                "result_text": text if isinstance(text, str) else None,
                "result_json": structured,
                "receipt": receipt,
            },
        )

    @staticmethod
    def _fail(attempt_id: str, code: str, detail: str, receipt: dict[str, Any]) -> JobOutcome:
        return JobOutcome(
            "fail",
            {
                "attempt_id": attempt_id,
                "error_code": code,
                "error_detail": detail,
                "receipt": receipt,
            },
        )

    def submit(self, job_id: str, outcome: JobOutcome) -> tuple[int, Any]:
        path = f"/{job_id}/complete" if outcome.kind == "complete" else f"/{job_id}/fail"
        for delay in (0, 2, 5, 15):
            if delay:
                time.sleep(delay)
            try:
                return self.api.post(path, outcome.body)
            except Exception as exc:
                self.log(f"submit {outcome.kind} failed ({type(exc).__name__}); retrying")
        return 0, None

    def run(
        self, *, once: bool = False, max_jobs: int | None = None, poll_seconds: float = 10.0
    ) -> int:
        violations = env_violations(self.env)
        if violations:
            pf = Preflight(
                False,
                "refusing to start: metered or third-party provider variables are set: "
                + ", ".join(violations),
                env_violations=violations,
            )
            self.log(pf.reason)
            self.report_status("refused", pf)
            return EXIT_ENV_VIOLATION

        done = 0
        while True:
            pf = self.check()
            if not pf.ok:
                self.log(f"preflight failed: {pf.reason}")
                self.report_status("preflight_failed", pf)
                return EXIT_PREFLIGHT_FAILED
            self.report_status("idle", pf)
            leased_any = False
            capacity_hit = False
            while max_jobs is None or done < max_jobs:
                status, body = self.api.post(
                    "/lease", {"worker_id": self.worker_id, "lease_seconds": self.lease_seconds}
                )
                if status != 200:
                    self.log(f"lease failed: HTTP {status}")
                    break
                job = (body or {}).get("job")
                if not job:
                    break
                leased_any = True
                self.log(
                    f"job {job['id']} ({job.get('job_type')}) attempt {job.get('attempt_count')}"
                )
                self.report_status("running", pf, job_id=job["id"])
                outcome = self.execute(job, pf)
                code, _ = self.submit(job["id"], outcome)
                done += 1
                self.log(
                    f"job {job['id']} -> {outcome.kind} "
                    f"{outcome.body.get('error_code', '')} (HTTP {code})"
                )
                if outcome.body.get("error_code") == "capacity":
                    capacity_hit = True  # stop leasing until the subscription resets
                    break
                pf = self.check()  # a logout mid-batch must not run the next job
                if not pf.ok:
                    self.log(f"preflight failed: {pf.reason}")
                    self.report_status("preflight_failed", pf)
                    return EXIT_PREFLIGHT_FAILED
            if once or (max_jobs is not None and done >= max_jobs):
                self.report_status("stopped", pf)
                return EXIT_OK
            self.report_status("waiting_capacity" if capacity_hit else "idle", pf)
            time.sleep(poll_seconds if (capacity_hit or not leased_any) else min(poll_seconds, 1.0))


def default_worker_id() -> str:
    return f"{platform.node() or 'worker'}-{os.getpid()}"
