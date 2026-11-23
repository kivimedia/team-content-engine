"""Subscription worker: the held lease and the background sign-in check (faked, no network).

23-Nov-2026: an idle worker found a new job only at its next poll, and between the
jobs of a batch it stopped for 10 to 18 s to run `claude auth status`. It now asks
the server to hold its lease, and the sign-in check runs in the background before
the kept result expires. The meaning of the check is unchanged.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request

import pytest

from tce.llm import worker as w
from tests.unit.test_llm_worker import AUTH_OK, BASE_ENV, FakePopen, FakeProc, job, stream

LOGGED_OUT = {**AUTH_OK, "loggedIn": False}


def job_n(n: int) -> dict:
    out = job()
    out["id"] = f"11111111-1111-1111-1111-{n:012d}"
    out["attempt_id"] = f"22222222-2222-2222-2222-{n:012d}"
    return out


class Clock:
    """A fake monotonic clock plus a record of every sleep the worker asked for."""

    def __init__(self, monkeypatch, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []
        monkeypatch.setattr(w.time, "monotonic", lambda: self.now)
        monkeypatch.setattr(w.time, "sleep", self.sleeps.append)


class Runner:
    """`claude auth status` / `--version` stand-in that records which thread asked."""

    def __init__(self, *answers: dict) -> None:
        self.answers = list(answers) or [AUTH_OK]
        self.auth_threads: list[str] = []

    def __call__(self, cmd, **kwargs):
        import json
        import subprocess

        if "auth" in cmd:
            self.auth_threads.append(threading.current_thread().name)
            auth = self.answers[min(len(self.auth_threads), len(self.answers)) - 1]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(auth), stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="2.1.270 (Claude Code)", stderr="")


class LeaseApi:
    """Answers /lease from a script; each entry is (status, body, seconds the server held)."""

    def __init__(self, clock: Clock, script: list, heartbeats: list[int] | None = None) -> None:
        self.clock = clock
        self.script = list(script)
        self.posts: list[tuple[str, dict]] = []
        self.leases: list[dict] = []
        self.heartbeat_answers = list(heartbeats or [])  # then 200
        self.heartbeats: list[tuple[str, dict, dict, int]] = []

    def post(self, path, body, **kw):
        self.posts.append((path, body))
        if path.endswith("/heartbeat"):
            status = self.heartbeat_answers.pop(0) if self.heartbeat_answers else 200
            self.heartbeats.append((path, dict(body), kw, status))
            return status, ({"leased_until": "later"} if status == 200 else {})
        if path != "/lease":
            return 200, {"status": "ok"}
        self.leases.append(dict(body))
        if not self.script:
            return 200, {"job": None}
        status, answer, held_s = self.script.pop(0)
        self.clock.now += held_s
        return status, answer


@pytest.fixture(autouse=True)
def no_background_check_unless_asked(monkeypatch):
    # The background thread is started by run(); here it only runs when a test asks.
    monkeypatch.setattr(w, "PREFLIGHT_REFRESH_POLL_S", 3600.0, raising=False)


def make_worker(api, runner, **kw):
    kw.setdefault("popen", FakePopen(FakeProc(stream())))
    return w.Worker(api, "w1", env=BASE_ENV, runner=runner, log=lambda _: None, heartbeat_s=3600, **kw)


# --- the held lease ----------------------------------------------------------------


def test_an_idle_worker_asks_to_be_held_and_does_not_poll_after_a_held_empty_answer(monkeypatch):
    clock = Clock(monkeypatch)
    api = LeaseApi(clock, [(200, {"job": None}, 25.0), (200, {"job": job_n(1)}, 3.0)])
    worker = make_worker(api, Runner())
    assert worker.run(max_jobs=1, poll_seconds=10.0) == w.EXIT_OK
    assert [lease.get("wait_seconds") for lease in api.leases] == [25.0, 25.0]
    assert api.leases[0]["worker_id"] == "w1" and api.leases[0]["lease_seconds"] == 600
    assert clock.sleeps == [0.0], "the 25 s hold was the poll's wait; no 10 s sleep after it"
    assert [p for p, _ in api.posts if p.endswith("/complete")] == [f"/{job_n(1)['id']}/complete"]


def test_against_a_server_without_the_wait_the_worker_polls_as_before(monkeypatch):
    clock = Clock(monkeypatch)
    # An old server ignores wait_seconds and answers at once.
    api = LeaseApi(clock, [(200, {"job": None}, 0.0), (200, {"job": job_n(1)}, 0.0)])
    worker = make_worker(api, Runner())
    assert worker.run(max_jobs=1, poll_seconds=10.0) == w.EXIT_OK
    assert clock.sleeps == [10.0]


def test_a_lease_error_after_a_hold_keeps_todays_back_off(monkeypatch):
    clock = Clock(monkeypatch)
    api = LeaseApi(
        clock,
        [
            (0, {"detail": "transport error: RemoteDisconnected"}, 10.0),  # restart mid-hold
            (502, {"detail": "bad gateway"}, 0.0),
            (200, {"job": job_n(1)}, 0.0),
        ],
    )
    worker = make_worker(api, Runner())
    assert worker.run(max_jobs=1, poll_seconds=10.0) == w.EXIT_OK
    assert clock.sleeps == [10.0, 10.0], "an error never shortens the back-off"


def test_an_unexpected_lease_answer_falls_back_to_polling(monkeypatch):
    clock = Clock(monkeypatch)
    api = LeaseApi(
        clock,
        [
            (200, ["not", "a", "lease"], 0.0),
            (200, {"job": "not-a-job"}, 25.0),
            (200, {"job": job_n(1)}, 0.0),
        ],
    )
    worker = make_worker(api, Runner())
    assert worker.run(max_jobs=1, poll_seconds=10.0) == w.EXIT_OK
    assert clock.sleeps == [10.0, 10.0]


def test_only_the_idle_lease_is_held_and_a_batch_leases_at_once(monkeypatch):
    clock = Clock(monkeypatch)
    api = LeaseApi(
        clock,
        [
            (200, {"job": job_n(1)}, 2.0),
            (200, {"job": job_n(2)}, 0.0),
            (200, {"job": None}, 0.0),
            (200, {"job": job_n(3)}, 4.0),
        ],
    )
    worker = make_worker(api, Runner())
    assert worker.run(max_jobs=3, poll_seconds=10.0) == w.EXIT_OK
    assert ["wait_seconds" in lease for lease in api.leases] == [True, False, False, True]
    assert clock.sleeps == [1.0], "after a batch, the short pause of today"


def test_once_never_asks_to_be_held_and_starts_no_background_thread(monkeypatch):
    clock = Clock(monkeypatch)
    names: list[list[str]] = []
    # Only a thread this run starts counts: one left by an earlier test is not this worker's.
    before = set(threading.enumerate())

    class Api(LeaseApi):
        def post(self, path, body):
            names.append([t.name for t in threading.enumerate() if t not in before])
            return super().post(path, body)

    api = Api(clock, [(200, {"job": job_n(1)}, 0.0)])
    assert make_worker(api, Runner()).run(once=True) == w.EXIT_OK
    assert all("wait_seconds" not in lease for lease in api.leases)
    assert not any("sign-in-refresh" in seen for seen in names)


def test_once_is_not_blamed_for_a_refresh_thread_left_by_another_worker(monkeypatch):
    # In a full run a daemon refresh thread from an earlier test can still be alive.
    stop = threading.Event()
    left = threading.Thread(target=stop.wait, name="sign-in-refresh", daemon=True)
    left.start()
    try:
        test_once_never_asks_to_be_held_and_starts_no_background_thread(monkeypatch)
    finally:
        stop.set()
        left.join(timeout=5)


def test_lease_wait_zero_is_plain_polling(monkeypatch):
    clock = Clock(monkeypatch)
    api = LeaseApi(clock, [(200, {"job": None}, 0.0), (200, {"job": job_n(1)}, 0.0)])
    worker = make_worker(api, Runner(), lease_wait_s=0)
    assert worker.run(max_jobs=1, poll_seconds=10.0) == w.EXIT_OK
    assert all("wait_seconds" not in lease for lease in api.leases)
    assert clock.sleeps == [10.0]


def test_a_hold_never_outlives_the_kept_sign_in_check(monkeypatch):
    clock = Clock(monkeypatch)
    worker = make_worker(LeaseApi(clock, []), Runner())
    assert worker._lease_wait() == 0.0, "never checked: no hold"
    assert worker.check().ok
    assert worker._lease_wait() == 25.0
    clock.now += 110
    assert worker._lease_wait() == pytest.approx(9.0), "ends before the 120 s window does"
    clock.now += 9.5
    assert worker._lease_wait() == 0.0
    failed = make_worker(LeaseApi(clock, []), Runner(LOGGED_OUT))
    assert not failed.check().ok and failed._lease_wait() == 0.0


def test_the_read_timeout_outlasts_the_hold(monkeypatch):
    seen: list[float] = []

    def fake_urlopen(req, timeout=None):
        seen.append(timeout)
        raise urllib.error.URLError("synthetic")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = w.ApiClient("http://127.0.0.1:1", "synthetic-key")
    assert client.post("/lease", {"worker_id": "w", "wait_seconds": 25.0})[0] == 0
    assert client.post("/lease", {"worker_id": "w"})[0] == 0
    assert client.post("/x/heartbeat", {"attempt_id": "a"})[0] == 0
    assert seen[0] > 25.0 + 10 and seen[1] == 30.0 and seen[2] == 30.0


# --- the background sign-in check ------------------------------------------------------


def slow_job_proc(clock: Clock, *, before: float, after: float):
    """A job that runs `before + after` fake seconds and lets the background thread
    work in the middle (real time, so the thread really runs)."""

    class Proc(FakeProc):
        def communicate(self, input=None, timeout=None):  # noqa: A002
            clock.now += before
            time_real_sleep(0.4)
            clock.now += after
            return super().communicate(input=input, timeout=timeout)

    return Proc(stream())


def time_real_sleep(seconds: float) -> None:
    threading.Event().wait(seconds)


def test_a_fresh_background_check_means_no_blocking_check_on_the_job_path(monkeypatch):
    clock = Clock(monkeypatch)
    monkeypatch.setattr(w, "PREFLIGHT_REFRESH_POLL_S", 0.02, raising=False)
    runner = Runner()
    api = LeaseApi(clock, [(200, {"job": job_n(1)}, 0.0), (200, {"job": job_n(2)}, 0.0)])
    worker = make_worker(api, runner, popen=FakePopen(slow_job_proc(clock, before=40, after=30)))
    assert worker.run(max_jobs=2, poll_seconds=10.0) == w.EXIT_OK
    main = [name for name in runner.auth_threads if name != "sign-in-refresh"]
    assert main == ["MainThread"], f"only the first check may block: {runner.auth_threads}"
    assert runner.auth_threads.count("sign-in-refresh") >= 2
    assert len([p for p, _ in api.posts if p.endswith("/complete")]) == 2


def test_without_the_background_check_the_job_path_blocks_as_before(monkeypatch):
    """The control: the same 70 s jobs with no background check need the blocking one."""
    clock = Clock(monkeypatch)
    runner = Runner()
    api = LeaseApi(clock, [(200, {"job": job_n(1)}, 0.0), (200, {"job": job_n(2)}, 0.0)])
    worker = make_worker(api, runner, popen=FakePopen(slow_job_proc(clock, before=40, after=30)))
    assert worker.run(max_jobs=2, poll_seconds=10.0) == w.EXIT_OK
    assert runner.auth_threads == ["MainThread"] * 3, "the first check plus one after each job"


def test_a_failed_background_check_means_the_blocking_check_runs_and_stops(monkeypatch):
    clock = Clock(monkeypatch)
    monkeypatch.setattr(w, "PREFLIGHT_REFRESH_POLL_S", 0.02, raising=False)
    runner = Runner(AUTH_OK, LOGGED_OUT)
    api = LeaseApi(clock, [(200, {"job": job_n(1)}, 0.0), (200, {"job": job_n(2)}, 0.0)])
    popen = FakePopen(slow_job_proc(clock, before=40, after=30))
    worker = make_worker(api, runner, popen=popen)
    assert worker.run(max_jobs=2, poll_seconds=10.0) == w.EXIT_PREFLIGHT_FAILED
    assert "sign-in-refresh" in runner.auth_threads
    assert runner.auth_threads[-1] == "MainThread", "a failed refresh is checked again, blocking"
    assert len(popen.calls) == 1 and len(api.leases) == 1, "no job runs on a bad sign-in"


def test_a_job_leased_after_a_logout_was_found_is_handed_back_unstarted(monkeypatch):
    clock = Clock(monkeypatch)
    runner = Runner(AUTH_OK, LOGGED_OUT)
    popen = FakePopen(FakeProc(stream()))

    class Api(LeaseApi):
        def post(self, path, body):
            if path == "/lease":
                # The background check finished during the hold and found a logout.
                worker._keep_preflight(w.Preflight(False, "claude CLI is not logged in"), clock.now)
            return super().post(path, body)

    api = Api(clock, [(200, {"job": job_n(1)}, 5.0)])
    worker = make_worker(api, runner, popen=popen)
    assert worker.run(max_jobs=1, poll_seconds=10.0) == w.EXIT_PREFLIGHT_FAILED
    assert popen.calls == [], "the job never started"
    fails = [b for p, b in api.posts if p == f"/{job_n(1)['id']}/fail"]
    assert len(fails) == 1 and fails[0]["error_code"] == "preflight"
    assert fails[0]["attempt_id"] == job_n(1)["attempt_id"]
    assert runner.auth_threads == ["MainThread", "MainThread"]


def test_refresh_runs_only_close_to_expiry_and_only_on_an_ok_result(monkeypatch):
    clock = Clock(monkeypatch)
    runner = Runner()
    worker = make_worker(LeaseApi(clock, []), runner)
    assert worker.refresh_once() is None, "never checked: the job loop checks, blocking"
    worker.check()
    worker._busy = True
    clock.now += w.PREFLIGHT_RECHECK_BETWEEN_JOBS_S - w.PREFLIGHT_REFRESH_LEAD_S - 1
    assert worker.refresh_once() is None
    clock.now += 1
    assert worker.refresh_once().ok and len(runner.auth_threads) == 2
    worker._busy = False
    clock.now += w.PREFLIGHT_CACHE_S - w.PREFLIGHT_REFRESH_LEAD_S - 1
    assert worker.refresh_once() is None, "idle, the 120 s window applies"
    clock.now += 1
    assert worker.refresh_once().ok and len(runner.auth_threads) == 3

    bad = make_worker(LeaseApi(clock, []), Runner(LOGGED_OUT))
    bad.check()
    clock.now += 500
    assert bad.refresh_once() is None, "a failed check stays the blocking path's"


def test_a_late_background_result_never_replaces_a_newer_check(monkeypatch):
    clock = Clock(monkeypatch)
    worker = make_worker(LeaseApi(clock, []), Runner())
    worker.check()
    newer = worker.preflight
    worker._keep_preflight(w.Preflight(False, "an older check, finished late"), clock.now - 5)
    assert worker.preflight is newer and worker.check() is newer


# --- the confirm of a held lease (review, 23-Nov-2026) ----------------------------------
#
# A held lease is first granted only a short term by the server, so a job handed to a
# connection nobody reads is free again in under a minute. The worker confirms it at
# once with a heartbeat that extends it to the full lease.


def heartbeat_paths(api: LeaseApi) -> list[str]:
    return [path for path, _body, _kw, _status in api.heartbeats]


def test_a_job_from_a_held_lease_is_confirmed_once_and_a_plain_one_never(monkeypatch):
    clock = Clock(monkeypatch)
    api = LeaseApi(clock, [(200, {"job": job_n(1)}, 3.0), (200, {"job": job_n(2)}, 0.0)])
    worker = make_worker(api, Runner())
    assert worker.run(max_jobs=2, poll_seconds=10.0) == w.EXIT_OK
    assert "wait_seconds" in api.leases[0] and "wait_seconds" not in api.leases[1]
    assert heartbeat_paths(api) == [f"/{job_n(1)['id']}/heartbeat"]
    _path, body, _kw, _status = api.heartbeats[0]
    assert body == {"attempt_id": job_n(1)["attempt_id"], "lease_seconds": 600}
    first_run = [i for i, (p, _) in enumerate(api.posts) if p == f"/{job_n(1)['id']}/complete"][0]
    confirm = api.posts.index((f"/{job_n(1)['id']}/heartbeat", body))
    assert confirm < first_run, "the confirm goes out before the job's result"


def test_a_lost_confirm_is_tried_again_and_the_running_job_keeps_its_lease(monkeypatch):
    clock = Clock(monkeypatch)
    monkeypatch.setattr(w, "LEASE_CONFIRM_RETRY_WAITS_S", (0.05, 0.05, 0.05, 0.05), raising=False)
    api = LeaseApi(clock, [(200, {"job": job_n(1)}, 1.0)], heartbeats=[0, 502])
    popen = FakePopen(slow_job_proc(clock, before=5, after=5))
    worker = make_worker(api, Runner(), popen=popen)
    assert worker.run(max_jobs=1, poll_seconds=10.0) == w.EXIT_OK
    statuses = [status for _p, _b, _kw, status in api.heartbeats]
    assert statuses == [0, 502, 200], "tried again until one landed, then back to the slow beat"
    assert all(kw.get("timeout") == w.LEASE_CONFIRM_TIMEOUT_S for _p, _b, kw, _s in api.heartbeats)
    assert len(popen.calls) == 1, "the job started while the confirm was tried again"
    assert [p for p, _ in api.posts].count(f"/{job_n(1)['id']}/complete") == 1


def test_a_409_on_the_confirm_means_the_lease_is_lost_and_the_job_never_runs(monkeypatch):
    clock = Clock(monkeypatch)
    api = LeaseApi(
        clock, [(200, {"job": job_n(1)}, 30.0), (200, {"job": job_n(2)}, 0.0)], heartbeats=[409]
    )
    popen = FakePopen(FakeProc(stream()))
    worker = make_worker(api, Runner(), popen=popen)
    assert worker.run(max_jobs=1, poll_seconds=10.0) == w.EXIT_OK
    assert len(popen.calls) == 1, "only the second job ran"
    done = [p for p, _ in api.posts if p.endswith(("/complete", "/fail"))]
    assert done == [f"/{job_n(2)['id']}/complete"], "nothing is sent for the lost lease"


def test_every_confirm_try_starts_inside_the_short_first_lease():
    from tce.api.routers import llm_jobs

    waits = w.LEASE_CONFIRM_RETRY_WAITS_S
    # Worst case: every try hangs for its whole timeout before the next one starts.
    last_start = len(waits) * w.LEASE_CONFIRM_TIMEOUT_S + sum(waits)
    assert last_start + w.LEASE_CONFIRM_TIMEOUT_S <= llm_jobs.HELD_FIRST_LEASE_S
    # One lost request: the second try starts well inside the term.
    assert w.LEASE_CONFIRM_TIMEOUT_S + waits[0] <= llm_jobs.HELD_FIRST_LEASE_S / 3
