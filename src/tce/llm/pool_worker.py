"""The server's own subscription worker: same queue, the team's pool of accounts.

23-Nov-2026 (T-24600). Every TCE writer ran on the owner's PC under one Claude
login. When that login reached its weekly limit the whole queue parked until the
reset, and picking an opening on the record page said to wait for the window,
while the KM BOT agents on the same server simply moved to the next account with
room.

This worker runs inside the API process on the server. It is the ordinary
``Worker`` (same command, same receipt, same subscription-only checks), with
three differences:

- its claude is the server's subscription wrapper, which takes the account from
  the fleet's own picker and never falls through to a metered key;
- before each job it asks that picker which account has room and pins the job to
  it, so a limit reached is recorded against the account that actually hit it;
- on a limit it records that account in the pool's observed-caps file (the file
  the picker already reads), so the next job goes to the next account with room.
  When no account has room the worker stops asking for work and says so.

It never decides from guessed usage: an account is skipped only when the picker
skips it, or after it answered with a limit.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tce.llm.queue import POOL_WORKER_PREFIX
from tce.llm.worker import (
    EXIT_ENV_VIOLATION,
    ApiClient,
    JobOutcome,
    Preflight,
    Worker,
    _is_forbidden,
    parse_retry_at,
)

WRAPPER_BIN = "/usr/local/bin/claude"
PICKER_BIN = "/home/ziv/bin/claude-pool-token"
POOL_DIR = "/home/ziv/.claude-accounts"
NO_ROOM = "every team subscription is at its limit"
# How long the worker rests when no account has room before asking the picker again.
NO_ROOM_REST_S = 300.0
# When the account that hit its limit is not the last one, the group parks this long
# only, then the next account takes the job.
NEXT_ACCOUNT_DELAY = timedelta(seconds=10)
# A reply that names a limit benches the account; an overload (529) alone does not.
_LIMIT_RE = re.compile(r"(hit your|usage|weekly|session|5-hour|daily)\s+limit|limit reached", re.I)

Picker = Callable[[], str | None]


def default_picker() -> str | None:
    """The account the fleet's picker would hand a background claude right now."""
    try:
        res = subprocess.run(  # noqa: S603
            [PICKER_BIN], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    name = (res.stdout or "").strip()
    return name if res.returncode == 0 and re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name) else None


def _parse_iso(raw: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")) if raw else None
    except ValueError:
        return None


def record_observed_cap(
    account: str, until: datetime, *, pool_dir: str = POOL_DIR, now: datetime | None = None
) -> bool:
    """Bench ``account`` until ``until`` in the pool's observed-caps file (merge, atomic)."""
    now = now or datetime.now(UTC)
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    path = Path(pool_dir) / "observed-caps.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    previous = data.get(account) if isinstance(data.get(account), dict) else {}
    try:
        prev_until = datetime.fromisoformat(str(previous.get("until")).replace("Z", "+00:00"))
        if prev_until.tzinfo is None:
            prev_until = prev_until.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        prev_until = None
    if prev_until is not None and prev_until > until:
        until = prev_until  # never shorten a bench someone else recorded
    data[account] = {
        "until": until.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "seen": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "by": "tce",
    }
    tmp = path.with_name(f".observed-caps.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, mode)
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False
    return True


def pool_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """The worker's own environment: no metered switches, no pinned token, the wrapper."""
    env = {
        k: v
        for k, v in dict(os.environ if base is None else base).items()
        if not _is_forbidden(k) and k not in ("CLAUDE_CODE_OAUTH_TOKEN", "SUB_ACCOUNTS")
    }
    env["TCE_CLAUDE_BIN"] = WRAPPER_BIN
    env["TCE_WORKER_ALLOWED_AUTH"] = "oauth_token"
    env.pop("TCE_WORKER_OUTBOX_DIR", None)
    return env


class PoolWorker(Worker):
    def __init__(
        self,
        api: Any,
        worker_id: str = f"{POOL_WORKER_PREFIX}-1",
        *,
        picker: Picker = default_picker,
        pool_dir: str = POOL_DIR,
        **kwargs: Any,
    ) -> None:
        if not worker_id.startswith(POOL_WORKER_PREFIX):
            raise ValueError(f"a pool worker id starts with {POOL_WORKER_PREFIX!r}")
        kwargs.setdefault("env", pool_env())
        super().__init__(api, worker_id, **kwargs)
        self.picker = picker
        self.pool_dir = pool_dir
        self.account: str | None = None

    def check(self, max_age_s: float = 120.0) -> Preflight:
        account = self.picker()
        if account is None:
            self.account = None
            return Preflight(False, NO_ROOM)
        if account != self.account:
            self.preflight = None  # a different account is checked afresh
        self.account = account
        self.env["SUB_ACCOUNTS"] = account
        return super().check(max_age_s)

    def execute(self, job: dict[str, Any], preflight: Preflight) -> JobOutcome:
        account = self.account
        outcome = super().execute(job, preflight)
        if outcome.body.get("error_code") != "capacity" or account is None:
            return outcome
        message = str(outcome.body.get("error_detail") or "")
        if _LIMIT_RE.search(message):
            until = _parse_iso(outcome.body.get("retry_at")) or parse_retry_at(message)
            until = until or (datetime.now(UTC) + timedelta(minutes=30))
            if record_observed_cap(account, until, pool_dir=self.pool_dir):
                self.log(f"pool account {account} at its limit until {until.isoformat()}")
        nxt = self.picker()
        if nxt is not None and nxt != account:
            # Another account has room: park this group for seconds, not hours.
            retry = datetime.now(UTC).replace(tzinfo=None) + NEXT_ACCOUNT_DELAY
            outcome.body["retry_at"] = retry.isoformat()
            outcome.body["error_detail"] = (
                f"{message[:400]} (account {account} at its limit; next account {nxt})"
            )
        return outcome

    def serve(self, stop: threading.Event, *, poll_seconds: float = 10.0) -> None:
        """Run until ``stop`` is set; rest and ask again whenever no account has room."""
        while not stop.is_set():
            try:
                code = self.run(poll_seconds=poll_seconds)
            except Exception as exc:  # the API must outlive any worker fault
                self.log(f"pool worker fault: {type(exc).__name__}: {exc}")
                code = -1
            if code == EXIT_ENV_VIOLATION:
                return  # a metered switch in its own environment: never retried
            if self.account is None:
                self.report_status("waiting_capacity", Preflight(False, NO_ROOM))
            stop.wait(NO_ROOM_REST_S)


_started: threading.Event | None = None


def pool_worker_enabled(env: dict[str, str] | None = None) -> bool:
    """On only when TCE_POOL_WORKER=1 (the server's start.sh sets it) and the
    server's subscription wrapper and picker are both installed. A test, a PC or a
    container never starts one by accident."""
    env = dict(os.environ if env is None else env)
    if env.get("TCE_DISABLE_SCHEDULER") == "1" or env.get("TCE_POOL_WORKER") != "1":
        return False
    return os.access(WRAPPER_BIN, os.X_OK) and os.access(PICKER_BIN, os.X_OK)


def start_pool_worker(api_base: str, service_key: str) -> threading.Event | None:
    """Start the pool worker thread once per process. Returns its stop event."""
    global _started
    if _started is not None or not service_key or not pool_worker_enabled():
        return None
    stop = threading.Event()
    worker = PoolWorker(ApiClient(api_base, service_key))
    thread = threading.Thread(target=worker.serve, args=(stop,), name="tce-pool-worker", daemon=True)
    thread.start()
    _started = stop
    return stop


def stop_pool_worker() -> None:
    global _started
    if _started is not None:
        _started.set()
        _started = None


__all__ = [
    "NO_ROOM",
    "PoolWorker",
    "default_picker",
    "pool_env",
    "pool_worker_enabled",
    "record_observed_cap",
    "start_pool_worker",
    "stop_pool_worker",
]

