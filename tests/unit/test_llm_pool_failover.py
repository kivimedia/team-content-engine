"""T-24600: one subscription at its limit no longer stops TCE.

23-Nov-2026 08:52 Israel: the owner picked opening 1 after Record now and was told
to wait for his subscription window. All three writers were on his PC under one
login; one weekly limit parked the whole queue until 19:00, while the KM BOT agents
moved to the next account with room. These tests replay that morning: the desktop
group parks, the server's pool worker still takes the job, and a pool account at
its limit hands over to the next one. Synthetic data only, no real claude.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from tce.editorial import status as job_status
from tce.llm import pool_worker as pw
from tce.llm import queue
from tce.llm import worker as w
from tce.llm.provider import LLMRequest

from .test_llm_worker import AUTH_OK, FakeApi, FakePopen, FakeProc, job, runner_for, stream

PC = "pc-subscription-1"
POOL = "vps-pool-1"
WEEKLY = "You've hit your weekly limit - resets Nov 23, 7pm (Asia/Jerusalem)"


def req(n: int = 0) -> LLMRequest:
    return LLMRequest(
        job_type="editorial.choose_hook",
        agent_name="tester",
        messages=[{"role": "user", "content": f"synthetic opening {n}"}],
        system="be brief",
    )


async def _enqueue(session, n=0):
    job_row = await queue.enqueue(session, req(n))
    await session.commit()
    return job_row


async def _pc_hits_weekly_limit(session, retry_at):
    leased = await queue.lease_job(session, PC, 600)
    failed = await queue.fail_job(
        session,
        leased.id,
        leased.attempt_id,
        error_code="capacity",
        error_detail=WEEKLY,
        retry_at=retry_at,
    )
    await session.commit()
    return failed


async def test_desktop_limit_before_any_pool_worker_still_parks(editorial_session):
    """The old behaviour holds when there is no second group: nothing to move to."""
    await _enqueue(editorial_session)
    retry_at = queue.utcnow() + timedelta(hours=10)
    failed = await _pc_hits_weekly_limit(editorial_session, retry_at)
    assert failed.status == "waiting_capacity"
    assert await queue.lease_job(editorial_session, "pc-subscription-2", 600) is None
    assert await job_status.capacity_park(editorial_session) == retry_at


async def test_pool_worker_takes_the_job_the_desktop_limit_parked(editorial_session):
    # The pool worker has been asking for work (it is live), then the PC hits its limit.
    assert await queue.lease_job(editorial_session, POOL, 600) is None
    await editorial_session.commit()
    await _enqueue(editorial_session)
    retry_at = queue.utcnow() + timedelta(hours=10)
    failed = await _pc_hits_weekly_limit(editorial_session, retry_at)

    # Another group has room, so the job is plain queued work, not "wait for the reset".
    assert failed.status == "queued" and failed.retry_at is None
    assert failed.attempt_count == 0
    # No group-wide park: picking an opening is not refused.
    assert await job_status.capacity_park(editorial_session) is None
    # The desktop group itself stays parked; the pool worker takes the job.
    assert await queue.lease_job(editorial_session, "pc-subscription-2", 600) is None
    taken = await queue.lease_job(editorial_session, POOL, 600)
    assert taken is not None and taken.id == failed.id and taken.lease_owner == POOL


async def test_a_job_already_parked_is_taken_by_a_pool_worker_that_arrives_later(
    editorial_session,
):
    await _enqueue(editorial_session)
    retry_at = queue.utcnow() + timedelta(hours=10)
    failed = await _pc_hits_weekly_limit(editorial_session, retry_at)
    assert failed.status == "waiting_capacity"
    taken = await queue.lease_job(editorial_session, POOL, 600)
    assert taken is not None and taken.id == failed.id


async def test_park_is_reported_only_when_every_live_group_is_parked(editorial_session):
    now = queue.utcnow()
    assert await queue.lease_job(editorial_session, POOL, 600, now=now) is None
    await _enqueue(editorial_session, 1)
    await _enqueue(editorial_session, 2)
    pc_retry = now + timedelta(hours=10)
    await _pc_hits_weekly_limit(editorial_session, pc_retry)
    assert await job_status.capacity_park(editorial_session, now=now) is None

    # Every pool account at its limit too: the earliest reset is what he is told.
    pool_job = await queue.lease_job(editorial_session, POOL, 600, now=now)
    pool_retry = now + timedelta(minutes=30)
    await queue.fail_job(
        editorial_session,
        pool_job.id,
        pool_job.attempt_id,
        error_code="capacity",
        error_detail=pw.NO_ROOM,
        retry_at=pool_retry,
        now=now,
    )
    await editorial_session.commit()
    assert await job_status.capacity_park(editorial_session, now=now) == pool_retry

    # A pool worker that stopped asking (gone, not parked) no longer counts.
    later = now + timedelta(minutes=31)
    stale = later + timedelta(seconds=queue.GROUP_LIVE_SECONDS + 1)
    assert await job_status.capacity_park(editorial_session, now=stale) == pc_retry


async def test_pool_park_of_seconds_resumes_on_the_next_account(editorial_session):
    now = queue.utcnow()
    await _enqueue(editorial_session)
    first = await queue.lease_job(editorial_session, POOL, 600, now=now)
    await queue.fail_job(
        editorial_session,
        first.id,
        first.attempt_id,
        error_code="capacity",
        error_detail=WEEKLY + " (account a at its limit; next account b)",
        retry_at=now + pw.NEXT_ACCOUNT_DELAY,
        now=now,
    )
    await editorial_session.commit()
    assert await queue.lease_job(editorial_session, POOL, 600, now=now) is None
    again = await queue.lease_job(
        editorial_session, POOL, 600, now=now + pw.NEXT_ACCOUNT_DELAY + timedelta(seconds=1)
    )
    assert again is not None and again.id == first.id
    assert again.attempt_count == 1  # the limit did not spend one of its attempts


async def test_policy_refusal_stops_only_the_group_that_was_refused(editorial_session):
    await _enqueue(editorial_session, 1)
    await _enqueue(editorial_session, 2)
    bad = await queue.lease_job(editorial_session, POOL, 600)
    await queue.fail_job(
        editorial_session, bad.id, bad.attempt_id, error_code="policy_violation", error_detail="x"
    )
    await editorial_session.commit()
    assert await queue.lease_job(editorial_session, POOL, 600) is None
    assert await queue.lease_job(editorial_session, PC, 600) is not None


# --- the pool worker itself -----------------------------------------------------

POOL_ENV = {
    "PATH": "/usr/bin",
    "HOME": "/home/tester",
    "TCE_CLAUDE_BIN": "/opt/fake/claude",
    "TCE_WORKER_ALLOWED_AUTH": "oauth_token",
}
AUTH_POOL = {**AUTH_OK, "authMethod": "oauth_token"}


def _worker(tmp_path, picks, proc):
    seq = list(picks)

    def picker():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    popen = FakePopen(proc)
    worker = pw.PoolWorker(
        FakeApi(),
        POOL,
        picker=picker,
        pool_dir=str(tmp_path),
        env=dict(POOL_ENV),
        popen=popen,
        runner=runner_for(AUTH_POOL),
        log=lambda _: None,
        heartbeat_s=3600,
    )
    return worker, popen


def test_pool_env_strips_metered_switches_and_pins_the_wrapper():
    env = pw.pool_env(
        {
            "ANTHROPIC_API_KEY": "sk-metered",
            "CLAUDE_CODE_OAUTH_TOKEN": "pinned",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "PATH": "/usr/bin",
        }
    )
    assert w.env_violations(env) == []
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert env["TCE_CLAUDE_BIN"] == pw.WRAPPER_BIN
    assert w.allowed_auth_methods(env) == frozenset({"claude.ai", "oauth_token"})


def test_no_account_with_room_means_no_lease(tmp_path):
    worker, _ = _worker(tmp_path, [None], FakeProc(stream()))
    pf = worker.check()
    assert not pf.ok and pf.reason == pw.NO_ROOM
    assert worker.run() == w.EXIT_PREFLIGHT_FAILED
    assert not any(path == "/lease" for path, _ in worker.api.posts)


def test_each_job_is_pinned_to_the_account_the_picker_chose(tmp_path):
    worker, popen = _worker(tmp_path, ["85-magicianbusiness"], FakeProc(stream()))
    pf = worker.check()
    assert pf.ok, pf.reason
    outcome = worker.execute(job(), pf)
    assert outcome.kind == "complete"
    _, kwargs = popen.calls[0]
    assert kwargs["env"]["SUB_ACCOUNTS"] == "85-magicianbusiness"
    assert w.env_violations(kwargs["env"]) == []


def test_weekly_limit_benches_that_account_and_hands_over_in_seconds(tmp_path):
    limited = stream(WEEKLY, is_error=True, api_error_status=429)
    worker, _ = _worker(tmp_path, ["85-magicianbusiness", "70-kids-entertainer-hub"], FakeProc(limited))
    pf = worker.check()
    before = datetime.now(UTC).replace(tzinfo=None)
    outcome = worker.execute(job(), pf)
    assert outcome.body["error_code"] == "capacity"
    retry = datetime.fromisoformat(outcome.body["retry_at"])
    assert retry <= before + pw.NEXT_ACCOUNT_DELAY + timedelta(seconds=5)
    assert "next account 70-kids-entertainer-hub" in outcome.body["error_detail"]

    caps = json.loads((tmp_path / "observed-caps.json").read_text())
    entry = caps["85-magicianbusiness"]
    assert entry["by"] == "tce"
    until = datetime.fromisoformat(entry["until"].replace("Z", "+00:00"))
    assert until > datetime.now(UTC) + timedelta(minutes=1)


def test_last_account_at_its_limit_keeps_the_reset_time(tmp_path):
    limited = stream(
        "Claude usage limit reached. Your limit will reset at 2099-01-01T05:00:00Z",
        is_error=True,
        api_error_status=429,
    )
    worker, _ = _worker(tmp_path, ["85-magicianbusiness", None], FakeProc(limited))
    pf = worker.check()
    outcome = worker.execute(job(), pf)
    assert outcome.body["retry_at"].startswith("2099-01-01T05:00:00")


def test_an_overload_alone_does_not_bench_the_account(tmp_path):
    overloaded = stream("Overloaded", is_error=True, api_error_status=529)
    worker, _ = _worker(tmp_path, ["85-magicianbusiness"], FakeProc(overloaded))
    outcome = worker.execute(job(), worker.check())
    assert outcome.body["error_code"] == "capacity"
    assert not (tmp_path / "observed-caps.json").exists()


def test_observed_cap_merges_and_never_shortens(tmp_path):
    path = tmp_path / "observed-caps.json"
    path.write_text(json.dumps({"02-dailycookie": {"until": "2099-01-01T00:00:00Z", "by": "x"}}))
    far = datetime(2099, 6, 1, tzinfo=UTC)
    assert pw.record_observed_cap("80-zivi-kivi", datetime(2026, 11, 23, 17, tzinfo=UTC), pool_dir=str(tmp_path))
    assert pw.record_observed_cap("02-dailycookie", datetime(2026, 11, 23, 17, tzinfo=UTC), pool_dir=str(tmp_path))
    data = json.loads(path.read_text())
    assert data["02-dailycookie"]["until"] == "2099-01-01T00:00:00Z"
    assert data["80-zivi-kivi"]["until"] == "2026-11-23T17:00:00Z"
    assert pw.record_observed_cap("80-zivi-kivi", far, pool_dir=str(tmp_path))
    assert json.loads(path.read_text())["80-zivi-kivi"]["until"].startswith("2099-06-01")


def test_pool_worker_is_off_unless_the_server_turns_it_on():
    assert pw.pool_worker_enabled({}) is False
    assert pw.pool_worker_enabled({"TCE_POOL_WORKER": "1", "TCE_DISABLE_SCHEDULER": "1"}) is False
    assert pw.pool_worker_enabled({"TCE_POOL_WORKER": "0"}) is False


def test_pool_worker_ids_belong_to_the_pool_group():
    assert queue.group_for_worker(POOL) == queue.POOL_GROUP_KEY
    assert queue.group_for_worker(PC) == queue.WORKER_GROUP_KEY
    assert queue.group_for_worker("DESKTOP-5GMJP7D-1234") == queue.WORKER_GROUP_KEY
