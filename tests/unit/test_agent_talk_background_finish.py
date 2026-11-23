"""Finishing an agent talk in the background (23-Nov, wait-less item B9, the TCE side).

The contract shared with the KM BOT relay, in short: a finish that sends "background": true
is claimed and answered 202 before its join;
the join runs behind the answer, under the same per-talk lock, in its own database
session; GET /agent-talks/{id} says in "finish" how it ended. Without the field the
finish is the one it always was. Same routes and test app as test_agent_talks.py, real
ffmpeg on tiny recordings made here; the join can be held at a gate to see what happens
while it runs. Synthetic data only.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from tce.api.routers import agent_talks as talk_routes
from tce.api.routers import production as prod
from tce.models.editorial import RecordingUpload
from tce.models.recording_session import AgentTalk
from tce.production import agent_talks
from tests.unit.test_agent_talk_guards import _age, disk_with
from tests.unit.test_agent_talks import (  # noqa: F401 - the fixtures are used by name
    AUTH,
    BASE,
    TRANSCRIPT,
    WS,
    _new_talk,
    _record,
    _send,
    client,
    needs_ffmpeg,
    spawned,
)

pytestmark = needs_ffmpeg

BEING_JOINED = "This talk is being joined into its video right now; a piece sent now would not be in it"
FINISH = {"ended_at": "2026-10-03T11:52:11Z", "duration_ms": 2100}


@pytest.fixture
def gate(monkeypatch):
    """The join waits at a gate until the test opens it; every join is counted."""
    real = agent_talks.join
    held = SimpleNamespace(open=asyncio.Event(), calls=[])

    async def join(folder, extension, **kw):
        held.calls.append(str(folder))
        await held.open.wait()
        return await real(folder, extension, **kw)

    monkeypatch.setattr(agent_talks, "join", join)
    return held


async def _bg(client, talk: str, body: dict):
    """A background finish: its answer must come while the join is still held at the gate."""
    return await asyncio.wait_for(
        client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={**body, "background": True}), timeout=10)


async def _talk_with_video(client, tmp_path, call_id: str) -> str:
    talk = await _new_talk(client, call_id=call_id)
    await _send(client, talk, _record(tmp_path / f"{call_id}.webm", "webm", seconds=2.0))
    return talk


async def _row(sm, talk: str) -> AgentTalk:
    async with sm() as s:
        return await s.get(AgentTalk, uuid.UUID(talk))


async def _uploads(sm) -> int:
    async with sm() as s:
        return (await s.execute(select(func.count()).select_from(RecordingUpload))).scalar_one()


async def _until(check, seconds: float = 5.0) -> None:
    for _ in range(int(seconds / 0.01)):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("never happened")


async def _joined(talk: str) -> None:
    """Wait for the background join of this talk to end, if one runs."""
    task = talk_routes._claim_tasks.get(uuid.UUID(talk))
    if task is not None:
        done, _pending = await asyncio.wait({task}, timeout=60)
        assert done, "the background join never ended"


def _restart() -> None:
    """What a deploy leaves: no task, no lock, only what the database holds."""
    for task in list(talk_routes._claim_tasks.values()):
        task.cancel()
    talk_routes._claim_tasks.clear()
    talk_routes._finish_locks.clear()
    talk_routes._claim_locks.clear()


# ---------------------------------------------------------------------------
# Without the field: the finish it always was


async def test_without_the_field_the_finish_waits_for_the_join_and_writes_no_claim(
    client, editorial_sessionmaker, tmp_path, spawned
):
    for call_id, extra in (("call-plain", {}), ("call-false", {"background": False})):
        talk = await _talk_with_video(client, tmp_path, call_id)
        r = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={**FINISH, **extra})
        assert r.status_code == 200, r.text
        assert r.json()["upload_id"] and r.json()["already_finished"] is False
        row = await _row(editorial_sessionmaker, talk)
        assert row.status == "finished" and "claim" not in row.join_meta and "finish" not in row.join_meta
        assert set(row.join_meta) == {"pieces", "bytes", "missing", "missing_count", "container", "streams",
                                      "joined_at", "edit"}
    assert talk_routes._claim_tasks == {}


# ---------------------------------------------------------------------------
# With the field: the answer first, the join behind it


async def test_a_background_finish_answers_before_the_join_and_the_join_still_runs(
    client, editorial_sessionmaker, tmp_path, spawned, gate
):
    talk = await _talk_with_video(client, tmp_path, "call-bg")
    r = await _bg(client, talk, {**FINISH, "edit": True})
    assert r.status_code == 202, r.text
    assert r.json() == {
        "talk_id": talk, "state": "finishing", "status": "finishing", "upload_id": None, "edit": True,
        "choice_kept": False, "detail": "The talk with Atlas is being put together into its video now.",
    }
    # Written down before the answer: a restart from here loses nothing.
    row = await _row(editorial_sessionmaker, talk)
    assert row.status == "finishing" and row.upload_id is None
    claim = row.join_meta["claim"]
    assert claim["edit"] is True and claim["transcript"] == [] and claim["duration_ms"] == 2100
    assert claim["status_before"] == "recording"
    await _until(lambda: len(gate.calls) == 1)

    got = (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()
    assert got["status"] == "finishing" and got["finish"] == {"state": "finishing"}
    # A piece is refused, in the words a piece during a join always got.
    late = await client.put(f"{BASE}/{talk}/chunks/99", headers=AUTH, content=b"late")
    assert late.status_code == 409 and late.json()["detail"] == BEING_JOINED
    # A second finish while it joins: the same 202, the first choice kept, no second join,
    # and the transcript the first one lacked is kept for the video.
    again = await _bg(client, talk, {"edit": False, "transcript": TRANSCRIPT})
    assert again.status_code == 202 and again.json()["edit"] is True and again.json()["choice_kept"] is True
    # A finish without the field waits for that join, and then answers as a second finish.
    plain = asyncio.create_task(client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={}))
    await asyncio.sleep(0.2)
    assert not plain.done()
    assert len(gate.calls) == 1 and await _uploads(editorial_sessionmaker) == 0

    gate.open.set()
    await _joined(talk)
    waited = await asyncio.wait_for(plain, timeout=30)
    assert waited.status_code == 200 and waited.json()["already_finished"] is True

    got = (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()
    assert got["status"] == "finished" and got["finish"]["state"] == "finished"
    result = got["finish"]["result"]
    assert result["upload_id"] == waited.json()["upload_id"] and result["edit"] is True
    assert result["edit_started"] is True and result["archived"] is False and result["status"] == "uploaded"
    assert result["title"] == "Talk with Atlas, 3 Oct" and result["missing_pieces"] == []
    async with editorial_sessionmaker() as s:
        upload = await s.get(RecordingUpload, uuid.UUID(result["upload_id"]))
    # The upload row is the one a held finish makes, with the later finish's transcript.
    assert upload.source == "agent_talk" and upload.agent_name == "Atlas" and upload.archived_at is None
    assert upload.call_transcript == [{**line, "t_ms": float(line["t_ms"])} for line in TRANSCRIPT]
    assert "Jennifer starts the edit now" in upload.status_detail
    assert len(gate.calls) == 1 and await _uploads(editorial_sessionmaker) == 1
    assert [c.__name__ for c in spawned] == ["auto_edit"]  # one edit, started after the commit
    row = await _row(editorial_sessionmaker, talk)
    assert "claim" not in row.join_meta and row.join_meta["edit"] is True
    # Finished: a late piece gets the finished refusal, a finish the same video.
    late = await client.put(f"{BASE}/{talk}/chunks/99", headers=AUTH, content=b"late")
    assert late.status_code == 409 and "finished" in late.json()["detail"]
    done = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={"background": True})
    assert done.status_code == 200 and done.json()["upload_id"] == result["upload_id"]


async def test_two_background_finishes_at_once_make_one_claim_one_join_and_keep_one_choice(
    client, editorial_sessionmaker, tmp_path, spawned, gate
):
    talk = await _talk_with_video(client, tmp_path, "call-twice")
    first, second = await asyncio.gather(
        _bg(client, talk, {**FINISH, "edit": False}), _bg(client, talk, {**FINISH, "edit": True}))
    assert first.status_code == second.status_code == 202
    kept = first.json()["edit"]
    assert second.json()["edit"] is kept
    assert sorted([first.json()["choice_kept"], second.json()["choice_kept"]]) == [False, True]
    gate.open.set()
    await _joined(talk)
    assert len(gate.calls) == 1 and await _uploads(editorial_sessionmaker) == 1
    result = (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()["finish"]["result"]
    assert result["edit"] is kept and result["archived"] is (not kept)
    # Edit false archives, exactly as a held finish does.
    assert [c.__name__ for c in spawned] == (["auto_edit"] if kept else [])


async def test_a_refused_join_reads_failed_and_the_talk_takes_pieces_again(client, editorial_sessionmaker):
    held_talk = await _new_talk(client, call_id="call-junk-held")
    bg_talk = await _new_talk(client, call_id="call-junk-bg")
    for talk in (held_talk, bg_talk):
        for seq, junk in enumerate((b"not a recording", b"nor is this")):
            assert (await client.put(f"{BASE}/{talk}/chunks/{seq}", headers=AUTH, content=junk)).status_code == 200
    refused = await client.post(f"{BASE}/{held_talk}/finish", headers=AUTH, json={})
    assert refused.status_code == 422
    r = await client.post(f"{BASE}/{bg_talk}/finish", headers=AUTH, json={"edit": True, "background": True})
    assert r.status_code == 202
    await _joined(bg_talk)
    got = (await client.get(f"{BASE}/{bg_talk}", headers=AUTH)).json()
    # Today's words, on the GET: the refusal a held finish answers 422 with (ffmpeg's own
    # line in it names this talk's file, so only the sentence around it is compared).
    words = "The pieces could not be joined into a video that plays ("
    assert got["status"] == "failed" and set(got["finish"]) == {"state", "error"}
    assert got["finish"]["state"] == "failed" and got["finish"]["error"]["status"] == 422
    assert refused.json()["detail"].startswith(words) and got["finish"]["error"]["detail"].startswith(words)
    assert got["detail"] == f"The talk with Atlas could not be joined: {got['finish']['error']['detail']}"[:500]
    held_row = await _row(editorial_sessionmaker, held_talk)
    assert held_row.status == "failed" and held_row.status_detail.startswith(f"The talk with Atlas could not be joined: {words}")
    # The talk takes pieces again, as after a held finish's refusal.
    assert (await client.put(f"{BASE}/{bg_talk}/chunks/2", headers=AUTH, content=b"more")).status_code == 200
    got = (await client.get(f"{BASE}/{bg_talk}", headers=AUTH)).json()
    assert got["status"] == "recording" and got["finish"] == {"state": "none"}
    # A finish after the failure is a new claim with its own choice.
    r = await client.post(f"{BASE}/{bg_talk}/finish", headers=AUTH, json={"edit": False, "background": True})
    assert r.status_code == 202 and r.json()["edit"] is False and r.json()["choice_kept"] is False
    await _joined(bg_talk)
    assert (await client.get(f"{BASE}/{bg_talk}", headers=AUTH)).json()["finish"]["state"] == "failed"
    assert await _uploads(editorial_sessionmaker) == 0


async def test_what_needs_no_join_is_refused_at_once_as_before(client, editorial_sessionmaker, tmp_path, monkeypatch):
    bg = {"background": True}
    no_zero = await _new_talk(client, call_id="call-no-zero")
    await client.put(f"{BASE}/{no_zero}/chunks/1", headers=AUTH, content=b"a later piece")
    r = await client.post(f"{BASE}/{no_zero}/finish", headers=AUTH, json=bg)
    assert r.status_code == 409 and "Piece 0" in r.json()["detail"]
    empty = await _new_talk(client, call_id="call-nothing")
    r = await client.post(f"{BASE}/{empty}/finish", headers=AUTH, json=bg)
    assert r.status_code == 409 and "nothing to join" in r.json()["detail"]
    r = await client.post(f"{BASE}/{no_zero}/finish", headers=AUTH, json={**bg, "ended_at": "yesterday"})
    assert r.status_code == 400
    assert (await client.post(f"{BASE}/{uuid.uuid4()}/finish", headers=AUTH, json=bg)).status_code == 404
    other = {"Authorization": AUTH["Authorization"], "X-Workspace-Id": str(uuid.uuid4())}
    assert (await client.post(f"{BASE}/{no_zero}/finish", headers=other, json=bg)).status_code == 404
    talk = await _talk_with_video(client, tmp_path, "call-full-disk")
    monkeypatch.setattr(agent_talks.shutil, "disk_usage", disk_with(agent_talks.MIN_FREE_BYTES + 300))
    r = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json=bg)
    assert r.status_code == 507 and "The pieces are kept" in r.json()["detail"]
    monkeypatch.setattr(agent_talks, "ffmpeg_path", lambda: None)
    r = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json=bg)
    assert r.status_code == 503
    # None of them claimed the talk: each is as it was, and takes pieces.
    for t in (no_zero, empty, talk):
        row = await _row(editorial_sessionmaker, t)
        assert row.status == "recording" and "claim" not in row.join_meta
    assert talk_routes._claim_tasks == {}


async def test_a_restart_mid_join_is_joined_at_startup_and_a_piece_waits_until_then(
    client, editorial_sessionmaker, tmp_path, spawned, gate
):
    talk = await _talk_with_video(client, tmp_path, "call-restart")
    r = await _bg(client, talk, {**FINISH, "edit": False, "transcript": TRANSCRIPT})
    assert r.status_code == 202
    await _until(lambda: len(gate.calls) == 1)
    _restart()
    await asyncio.sleep(0.05)
    # Across the restart the talk is still claimed: a piece is refused, the GET says so.
    late = await client.put(f"{BASE}/{talk}/chunks/99", headers=AUTH, content=b"late")
    assert late.status_code == 409 and late.json()["detail"] == BEING_JOINED
    assert (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()["finish"] == {"state": "finishing"}
    gate.open.set()
    await prod.resume_auto_work()  # the boot-time resumes
    await _joined(talk)
    got = (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()
    assert got["status"] == "finished" and got["finish"]["state"] == "finished"
    assert got["finish"]["result"]["edit"] is False and got["finish"]["result"]["archived"] is True
    async with editorial_sessionmaker() as s:
        upload = await s.get(RecordingUpload, uuid.UUID(got["upload_id"]))
    assert upload.archived_at is not None and [line["text"] for line in upload.call_transcript] == [
        line["text"] for line in TRANSCRIPT]
    assert len(gate.calls) == 2 and await _uploads(editorial_sessionmaker) == 1
    assert "auto_edit" not in [c.__name__ for c in spawned]


async def test_a_held_finish_after_a_restart_joins_the_claim_and_keeps_its_choice(
    client, editorial_sessionmaker, tmp_path, spawned, gate
):
    talk = await _talk_with_video(client, tmp_path, "call-restart-held")
    r = await _bg(client, talk, {**FINISH, "edit": False})
    assert r.status_code == 202
    await _until(lambda: len(gate.calls) == 1)
    _restart()
    gate.open.set()
    # No resume ran yet. An older caller's finish asks the other way: the claim's join
    # runs, its choice stands, and this finish is answered as a second one.
    plain = await asyncio.wait_for(client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={"edit": True}), 30)
    assert plain.status_code == 200, plain.text
    got = plain.json()
    assert got["already_finished"] is True and got["edit"] is False and got["choice_kept"] is True
    assert len(gate.calls) == 2 and await _uploads(editorial_sessionmaker) == 1
    assert spawned == []


async def test_the_idle_backstop_never_joins_a_claimed_talk(client, editorial_sessionmaker, tmp_path, gate):
    talk = await _talk_with_video(client, tmp_path, "call-idle-claimed")
    assert (await _bg(client, talk, {})).status_code == 202
    await _until(lambda: len(gate.calls) == 1)
    await _age(editorial_sessionmaker, talk, 7)
    assert await talk_routes.finish_idle_talks(WS) == []
    assert len(gate.calls) == 1
    gate.open.set()
    await _joined(talk)
    assert (await _row(editorial_sessionmaker, talk)).status == "finished"


async def test_a_crash_behind_the_answer_is_written_on_the_talk(client, editorial_sessionmaker, tmp_path, monkeypatch):
    talk = await _talk_with_video(client, tmp_path, "call-crash")
    real = agent_talks.sha256_of

    def broken(path):
        raise OSError("the disk went away")

    monkeypatch.setattr(agent_talks, "sha256_of", broken)
    assert (await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={"background": True})).status_code == 202
    await _joined(talk)
    got = (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()
    assert got["status"] == "failed" and got["finish"]["state"] == "failed"
    assert got["finish"]["error"]["status"] == 500
    assert got["finish"]["error"]["detail"] == got["detail"]
    assert "could not be joined: the server ran into an error while putting it together" in got["detail"]
    # Finished again, it is made from the file the first join left.
    monkeypatch.setattr(agent_talks, "sha256_of", real)
    assert (await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={"background": True})).status_code == 202
    await _joined(talk)
    assert (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()["finish"]["state"] == "finished"
    assert await _uploads(editorial_sessionmaker) == 1
