"""Keep the TCE subscription worker(s) and their SSH tunnel alive on a desktop.

The LLM queue lives on the server; the Claude Code subscription lives on the
desktop. This supervisor is what joins them without anyone's terminal staying
open:

    pythonw scripts/tce_worker_supervisor.py --ssh-target user@host --workers 2

It owns exactly three things and nothing else on the machine:

- one SSH local forward (127.0.0.1:<local-port> -> server 127.0.0.1:<remote-port>),
  restarted with backoff when it drops;
- N ``scripts/tce_llm_worker.py`` processes, each with its own worker id;
- a status file (``status.json``) and a log in the state directory.

Fail-closed rules, inherited from the worker and kept here:

- exit 2 (a metered or third-party provider variable is set): that slot stays
  stopped until the supervisor is restarted. Nothing retries around a policy
  violation.
- exit 3 (``claude`` missing, logged out, or not a claude.ai subscription): the
  slot waits ``--preflight-retry-seconds`` and runs the worker again, which
  re-verifies before it leases anything. No job ever runs unverified.
- the private access key is read from a file and handed to the workers through
  their environment only. It never appears on a command line or in a log.

A ``STOP`` file in the state directory stops the workers and the tunnel and
exits (the kill switch). A lock file keeps a second copy from starting, so a
scheduler may relaunch it every few minutes to recover from a crash.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKER_SCRIPT = REPO_ROOT / "scripts" / "tce_llm_worker.py"

EXIT_ENV_VIOLATION = 2
EXIT_PREFLIGHT_FAILED = 3
LOG_MAX_BYTES = 5 * 1024 * 1024


def _default_state_dir() -> Path:
    # Not under AppData: Microsoft Store Python silently redirects AppData writes
    # into its package cache, where nobody would look for the status file.
    return Path.home() / ".tce-worker" / "state"


def _default_key_file() -> Path:
    return Path.home() / ".tce-worker" / "private_access_key"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _no_window() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def _worker_python() -> str:
    # pythonw has no console; its child python.exe gets CREATE_NO_WINDOW instead.
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        candidate = exe.with_name("python.exe")
        if candidate.exists():
            return str(candidate)
    return str(exe)


class Log:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __call__(self, msg: str) -> None:
        try:
            if self.path.exists() and self.path.stat().st_size > LOG_MAX_BYTES:
                self.path.replace(self.path.with_suffix(".log.1"))
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(f"{_now()} {msg}\n")
        except OSError:
            pass


class SingleInstance:
    """Holds an exclusive lock on a file for the life of the process."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fh: Any = None

    def acquire(self) -> bool:
        self.fh = self.path.open("a+")
        try:
            if os.name == "nt":
                import msvcrt

                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        return True


@dataclass
class Slot:
    worker_id: str
    proc: subprocess.Popen | None = None
    state: str = "starting"
    restarts: int = 0
    last_exit: int | None = None
    next_start: float = 0.0
    backoff: float = 5.0
    started_at: str | None = None
    started_mono: float = 0.0
    log_path: Path | None = None
    log_fh: Any = None
    notes: list[str] = field(default_factory=list)


class Supervisor:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.state_dir = Path(args.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log = Log(self.state_dir / "supervisor.log")
        self.tunnel: subprocess.Popen | None = None
        self.tunnel_backoff = 5.0
        self.tunnel_next = 0.0
        self.tunnel_restarts = 0
        self.api_ok = False
        self.api_checked_at: str | None = None
        self.api_error: str | None = None
        self.slots = [
            Slot(worker_id=f"{args.worker_prefix}-{i + 1}") for i in range(args.workers)
        ]
        self.started_at = _now()

    # --- configuration -------------------------------------------------------

    @property
    def api_base(self) -> str:
        return f"http://127.0.0.1:{self.args.local_port}"

    def read_key(self) -> str | None:
        try:
            key = Path(self.args.key_file).read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return key or None

    def worker_env(self, key: str) -> dict[str, str]:
        env = dict(os.environ)
        env["TCE_PRIVATE_ACCESS_KEY"] = key
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    # --- tunnel --------------------------------------------------------------

    def ensure_tunnel(self) -> None:
        if not self.args.ssh_target:
            return  # the API is reachable directly (running on the server itself)
        if self.tunnel is not None and self.tunnel.poll() is None:
            return
        if self.tunnel is not None:
            self.log(f"tunnel exited with {self.tunnel.returncode}")
            self.tunnel = None
            self.tunnel_restarts += 1
            self.tunnel_next = time.monotonic() + self.tunnel_backoff
            self.tunnel_backoff = min(self.tunnel_backoff * 2, 300.0)
        if time.monotonic() < self.tunnel_next:
            return
        ssh = self.args.ssh_bin or shutil.which("ssh") or "ssh"
        cmd = [
            ssh,
            "-N",
            "-o", "BatchMode=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "ConnectTimeout=15",
            "-L", f"127.0.0.1:{self.args.local_port}:127.0.0.1:{self.args.remote_port}",
            self.args.ssh_target,
        ]
        err = (self.state_dir / "tunnel.log").open("a", encoding="utf-8")
        try:
            self.tunnel = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=err, stderr=err, **_no_window()
            )
            self.log(f"tunnel started pid={self.tunnel.pid} local={self.args.local_port}")
        except OSError as exc:
            self.log(f"tunnel could not start: {type(exc).__name__}")
            self.tunnel_next = time.monotonic() + self.tunnel_backoff
        finally:
            err.close()

    def check_api(self) -> None:
        self.api_checked_at = _now()
        try:
            with urllib.request.urlopen(f"{self.api_base}/api/v1/health", timeout=10) as resp:
                self.api_ok = resp.status == 200
                self.api_error = None if self.api_ok else f"HTTP {resp.status}"
        except Exception as exc:  # noqa: BLE001 - recorded in status, never swallowed
            self.api_ok = False
            self.api_error = type(exc).__name__
        if self.api_ok:
            self.tunnel_backoff = 5.0

    # --- workers -------------------------------------------------------------

    def start_worker(self, slot: Slot, key: str) -> None:
        slot.log_path = self.state_dir / f"{slot.worker_id}.log"
        slot.log_fh = slot.log_path.open("a", encoding="utf-8")
        cmd = [
            _worker_python(),
            str(WORKER_SCRIPT),
            "--api-base", self.api_base,
            "--worker-id", slot.worker_id,
            "--poll-seconds", str(self.args.poll_seconds),
        ]
        try:
            slot.proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                env=self.worker_env(key),
                stdin=subprocess.DEVNULL,
                stdout=slot.log_fh,
                stderr=subprocess.STDOUT,
                **_no_window(),
            )
        except OSError as exc:
            slot.log_fh.close()
            slot.log_fh = None
            slot.state = "start_failed"
            slot.next_start = time.monotonic() + slot.backoff
            self.log(f"{slot.worker_id} could not start: {type(exc).__name__}")
            return
        slot.state = "running"
        slot.started_at = _now()
        slot.started_mono = time.monotonic()
        self.log(f"{slot.worker_id} started pid={slot.proc.pid}")

    def reap(self, slot: Slot) -> None:
        if slot.proc is None or slot.proc.poll() is None:
            return
        code = slot.proc.returncode
        slot.last_exit = code
        slot.proc = None
        if slot.log_fh:
            slot.log_fh.close()
            slot.log_fh = None
        slot.restarts += 1
        if code == EXIT_ENV_VIOLATION:
            slot.state = "refused_policy"
            slot.next_start = float("inf")
            self.log(f"{slot.worker_id} refused: provider variables present; slot stays stopped")
        elif code == EXIT_PREFLIGHT_FAILED:
            slot.state = "waiting_subscription"
            slot.next_start = time.monotonic() + self.args.preflight_retry_seconds
            self.log(
                f"{slot.worker_id} preflight failed (subscription not verified); "
                f"retrying in {self.args.preflight_retry_seconds}s"
            )
        else:
            slot.state = "restarting"
            slot.next_start = time.monotonic() + slot.backoff
            self.log(f"{slot.worker_id} exited {code}; restart in {slot.backoff:.0f}s")
            slot.backoff = min(slot.backoff * 2, 300.0)

    def ensure_workers(self) -> None:
        key = self.read_key()
        for slot in self.slots:
            self.reap(slot)
            if slot.proc is not None:
                if time.monotonic() - slot.started_mono > 120:
                    slot.backoff = 5.0  # it stayed up, so the next crash starts fresh
                continue
            if key is None:
                slot.state = "no_access_key"
                continue
            if not self.api_ok:
                slot.state = "waiting_api"
                continue
            if time.monotonic() >= slot.next_start:
                self.start_worker(slot, key)

    # --- lifecycle -----------------------------------------------------------

    def write_status(self, state: str) -> None:
        status = {
            "state": state,
            "updated_at": _now(),
            "supervisor_started_at": self.started_at,
            "supervisor_pid": os.getpid(),
            "api_base": self.api_base,
            "api_ok": self.api_ok,
            "api_checked_at": self.api_checked_at,
            "api_error": self.api_error,
            "tunnel": {
                "target_configured": bool(self.args.ssh_target),
                "pid": self.tunnel.pid if self.tunnel and self.tunnel.poll() is None else None,
                "restarts": self.tunnel_restarts,
            },
            "access_key_present": self.read_key() is not None,
            "workers": [
                {
                    "worker_id": s.worker_id,
                    "state": s.state,
                    "pid": s.proc.pid if s.proc else None,
                    "started_at": s.started_at,
                    "restarts": s.restarts,
                    "last_exit": s.last_exit,
                    "log": str(s.log_path) if s.log_path else None,
                }
                for s in self.slots
            ],
        }
        tmp = self.state_dir / "status.json.tmp"
        tmp.write_text(json.dumps(status, indent=2), encoding="utf-8")
        tmp.replace(self.state_dir / "status.json")

    def stop_all(self) -> None:
        for slot in self.slots:
            if slot.proc and slot.proc.poll() is None:
                slot.proc.terminate()
        deadline = time.monotonic() + 20
        for slot in self.slots:
            if slot.proc:
                try:
                    slot.proc.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    slot.proc.kill()
                slot.state = "stopped"
                slot.proc = None
        if self.tunnel and self.tunnel.poll() is None:
            self.tunnel.terminate()

    def run(self) -> int:
        stop_file = self.state_dir / "STOP"
        self.log(
            f"supervisor started pid={os.getpid()} workers={len(self.slots)} "
            f"tunnel={'yes' if self.args.ssh_target else 'no'}"
        )
        try:
            while True:
                if stop_file.exists():
                    self.log("STOP file present; stopping workers and tunnel")
                    self.stop_all()
                    self.write_status("stopped_by_stop_file")
                    return 0
                self.ensure_tunnel()
                self.check_api()
                self.ensure_workers()
                self.write_status("running")
                time.sleep(self.args.check_seconds)
        finally:
            self.stop_all()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TCE subscription worker supervisor")
    parser.add_argument("--ssh-target", default=os.environ.get("TCE_SSH_TARGET", ""))
    parser.add_argument("--ssh-bin", default=os.environ.get("TCE_SSH_BIN", ""))
    parser.add_argument("--local-port", type=int, default=18200)
    parser.add_argument("--remote-port", type=int, default=8200)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--worker-prefix", default="pc-subscription")
    parser.add_argument("--key-file", default=str(_default_key_file()))
    parser.add_argument("--state-dir", default=str(_default_state_dir()))
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--check-seconds", type=float, default=15.0)
    parser.add_argument("--preflight-retry-seconds", type=float, default=600.0)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be at least 1")

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = SingleInstance(state_dir / "supervisor.lock")
    if not lock.acquire():
        return 0  # another copy is already supervising; the scheduler relaunch is a no-op
    return Supervisor(args).run()


if __name__ == "__main__":
    sys.exit(main())
