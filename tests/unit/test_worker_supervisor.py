"""Supervisor ownership and pinning regressions. Synthetic processes only."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "tce_worker_supervisor.py"
SPEC = importlib.util.spec_from_file_location("tce_worker_supervisor", SCRIPT)
assert SPEC and SPEC.loader
supervisor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = supervisor
SPEC.loader.exec_module(supervisor)


class FakeProc:
    def __init__(self, pid=4321):
        self.pid = pid
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def kill(self):
        self.killed = True
        self.returncode = -9


def args(tmp_path):
    key = tmp_path / "key"
    key.write_text("synthetic", encoding="utf-8")
    return argparse.Namespace(
        state_dir=str(tmp_path),
        key_file=str(key),
        ssh_target="",
        ssh_bin="",
        local_port=18200,
        remote_port=8200,
        workers=1,
        worker_prefix="test",
        poll_seconds=1.0,
        check_seconds=1.0,
        preflight_retry_seconds=1.0,
        claude_bin=str(tmp_path / "verified-vscode-claude.exe"),
    )


def test_worker_environment_contains_only_the_pinned_claude_path(tmp_path):
    app = supervisor.Supervisor(args(tmp_path))
    env = app.worker_env("synthetic")
    assert env["TCE_CLAUDE_BIN"].endswith("verified-vscode-claude.exe")


def test_stop_uses_owned_tree_terminator(tmp_path, monkeypatch):
    app = supervisor.Supervisor(args(tmp_path))
    proc = FakeProc()
    app.slots[0].proc = proc
    calls = []
    monkeypatch.setattr(supervisor, "terminate_owned_tree", lambda p, log: calls.append(p.pid))
    app.stop_all()
    assert calls == [4321]
