"""T-26202: the owner's 22-Nov tap, replayed end to end with real writer state.

He pressed Record now, picked an opening whose script was not written yet,
and was told the script writer was
resting on his Claude limit. The cause: his PC writers (one login) hit their
weekly limit and the whole queue parked. This replays that tap through the
choose-hook route with REAL writer-group rows (no stand-in for the park check):
the PC group parked on a weekly limit, the server's pool worker live with room.

The pick must go ahead (not refused), and the job the limit stopped must be
taken by the pool worker. When every group is at its limit, the refusal is still
said plainly. Synthetic data only, no real claude.
"""

from __future__ import annotations

from datetime import timedelta

from tce.editorial import status as job_status
from tce.llm import queue
from tce.llm.provider import LLMRequest
from tests.unit.test_hook_whole_script import fake_writer
from tests.unit.test_recording_hook_choice import AUTH, client, seed_v2  # noqa: F401

PC = "pc-subscription-1"
POOL = "vps-pool-1"
WEEKLY = "You've hit your weekly limit - resets Nov 23, 7pm (Asia/Jerusalem)"


async def _pc_hits_weekly_limit(sm, *, pool_live: bool):
    async with sm() as s:
        if pool_live:
            # The pool worker asks for work every few seconds, which keeps it live.
            assert await queue.lease_job(s, POOL, 600) is None
            await s.commit()
        job = await queue.enqueue(
            s,
            LLMRequest(
                job_type="news_appraisal",
                agent_name="tester",
                messages=[{"role": "user", "content": "synthetic appraisal"}],
                system="be brief",
            ),
        )
        await s.commit()
        leased = await queue.lease_job(s, PC, 600)
        assert leased is not None and leased.id == job.id
        failed = await queue.fail_job(
            s,
            leased.id,
            leased.attempt_id,
            error_code="capacity",
            error_detail=WEEKLY,
            retry_at=queue.utcnow() + timedelta(hours=10),
        )
        await s.commit()
        return failed


async def test_opening_pick_goes_ahead_when_pc_limit_hit_and_pool_has_room(
    client, editorial_sessionmaker, monkeypatch  # noqa: F811
):
    cand, original = await seed_v2(editorial_sessionmaker, scripts=False)
    fake_writer(monkeypatch)
    stopped = await _pc_hits_weekly_limit(editorial_sessionmaker, pool_live=True)

    r = await client.post(
        f"/api/v1/editorial/packets/{original.id}/choose-hook",
        json={"hook_id": "hook-2"},
        headers=AUTH,
    )
    assert r.status_code != 409, f"refused like 22-Nov: {r.text}"
    assert r.status_code in (200, 202), r.text

    async with editorial_sessionmaker() as s:
        assert await job_status.capacity_park(s) is None
        # The PC writers stay at their limit; the pool worker takes the stopped job.
        assert await queue.lease_job(s, "pc-subscription-2", 600) is None
        taken = await queue.lease_job(s, POOL, 600)
        assert taken is not None and taken.id == stopped.id and taken.lease_owner == POOL


async def test_opening_pick_still_says_the_limit_when_no_writer_has_room(
    client, editorial_sessionmaker, monkeypatch  # noqa: F811
):
    cand, original = await seed_v2(editorial_sessionmaker, scripts=False)
    fake_writer(monkeypatch)
    await _pc_hits_weekly_limit(editorial_sessionmaker, pool_live=False)

    r = await client.post(
        f"/api/v1/editorial/packets/{original.id}/choose-hook",
        json={"hook_id": "hook-2"},
        headers=AUTH,
    )
    assert r.status_code == 409, r.text
    assert "Claude limit" in r.json()["detail"]
