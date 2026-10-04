"""Agent talks under stress (3-Oct review of contract C4, the TCE side).

What a relay that misbehaves, a full disk or a call that never finishes can do to the
intake: a piece sent without a length, a piece number far out, a disk under its floor,
and a talk whose finish never came. Same routes and test app as test_agent_talks.py;
synthetic data only.
"""

from __future__ import annotations

import uuid
from collections import namedtuple
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tce.api.routers import agent_talks as talk_routes
from tce.api.routers import production as prod
from tce.models.editorial import RecordingUpload
from tce.models.recording_session import AgentTalk
from tce.production import agent_talks
from tests.unit.test_agent_talks import (  # noqa: F401 - the fixtures are used by name
    AUTH,
    BASE,
    WS,
    _new_talk,
    _record,
    _split,
    client,
    needs_ffmpeg,
    spawned,
)

Usage = namedtuple("Usage", "total used free")


def disk_with(free: int):
    return lambda _path: Usage(10**12, 10**12 - free, free)


# ---------------------------------------------------------------------------
# A piece's size


async def test_a_piece_sent_without_a_length_is_refused_before_it_is_held_whole(client, monkeypatch):
    talk = await _new_talk(client)
    monkeypatch.setattr(agent_talks, "MAX_CHUNK_BYTES", 1000)
    sent: list[int] = []

    async def body():
        for _ in range(50):  # 50 KB offered in parts, no Content-Length: chunked
            sent.append(1)
            yield b"x" * 1000

    r = await client.put(f"{BASE}/{talk}/chunks/0", headers=AUTH, content=body())
    assert r.status_code == 413 and "larger than" in r.json()["detail"]
    assert len(sent) < 50, "the reading stopped at the limit instead of taking the whole body"
    status = (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()
    assert status["pieces"] == 0 and status["bytes_total"] == 0
    # The same piece within the limit, sent the same way, is kept.

    async def small():
        yield b"y" * 600
        yield b"y" * 300

    r = await client.put(f"{BASE}/{talk}/chunks/0", headers=AUTH, content=small())
    assert r.status_code == 200 and r.json()["bytes_total"] == 900


async def test_a_declared_length_over_the_limit_is_refused_at_once(client, monkeypatch):
    talk = await _new_talk(client)
    monkeypatch.setattr(agent_talks, "MAX_CHUNK_BYTES", 10)
    r = await client.put(f"{BASE}/{talk}/chunks/0", headers=AUTH, content=b"z" * 11)
    assert r.status_code == 413


def test_talk_ids_and_piece_numbers_cannot_reach_outside_the_talk(tmp_path):
    """A talk id is a UUID (the route refuses anything else), and a piece's file name is
    its number: neither can name a path outside the talk's own folder."""
    folder = agent_talks.talk_folder(tmp_path, uuid.uuid4(), uuid.uuid4())
    with pytest.raises(agent_talks.TalkError):
        agent_talks.store_piece(folder, -1, b"x")
    with pytest.raises(agent_talks.TalkError):
        agent_talks.store_piece(folder, agent_talks.MAX_SEQUENCE + 1, b"x")
    stored = agent_talks.store_piece(folder, 7, b"x")
    assert stored.created and [p.name for p in (folder / "pieces").iterdir()] == ["0000007.part"]


async def test_a_talk_id_that_is_not_a_uuid_is_refused(client):
    for bad in ("..", "..%2F..%2Fetc", "not-a-uuid"):
        r = await client.put(f"{BASE}/{bad}/chunks/0", headers=AUTH, content=b"x")
        assert r.status_code in (404, 405, 422), (bad, r.status_code)


# ---------------------------------------------------------------------------
# The disk


async def test_a_piece_that_would_take_the_disk_under_its_floor_is_refused(client, monkeypatch):
    talk = await _new_talk(client)
    monkeypatch.setattr(agent_talks.shutil, "disk_usage", disk_with(agent_talks.MIN_FREE_BYTES + 5))
    r = await client.put(f"{BASE}/{talk}/chunks/0", headers=AUTH, content=b"0123456789")
    assert r.status_code == 507
    assert r.json()["detail"].startswith("The server's disk is nearly full")
    status = (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()
    assert status["pieces"] == 0
    # Room again: the relay's retry of the same piece is kept.
    monkeypatch.setattr(agent_talks.shutil, "disk_usage", disk_with(agent_talks.MIN_FREE_BYTES * 4))
    r = await client.put(f"{BASE}/{talk}/chunks/0", headers=AUTH, content=b"0123456789")
    assert r.status_code == 200


async def test_a_join_that_needs_more_room_than_there_is_keeps_the_pieces(client, monkeypatch):
    talk = await _new_talk(client)
    for seq, data in enumerate((b"a" * 100, b"b" * 100)):
        assert (await client.put(f"{BASE}/{talk}/chunks/{seq}", headers=AUTH, content=data)).status_code == 200
    # Room for the pieces, not for writing them twice more.
    monkeypatch.setattr(agent_talks.shutil, "disk_usage", disk_with(agent_talks.MIN_FREE_BYTES + 300))
    monkeypatch.setattr(agent_talks, "ffmpeg_path", lambda: "ffmpeg")
    r = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={})
    assert r.status_code == 507 and "The pieces are kept" in r.json()["detail"]
    status = (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()
    assert status["status"] == "recording" and status["pieces"] == 2  # not failed, nothing lost


def test_missing_pieces_far_out_are_counted_without_a_list_of_a_million():
    kept, count = agent_talks._missing([0, 2, agent_talks.MAX_SEQUENCE])
    assert count == agent_talks.MAX_SEQUENCE - 2
    assert kept[:2] == [1, 3] and len(kept) == agent_talks.MAX_MISSING_KEPT
    assert agent_talks._missing([0, 1, 2]) == ([], 0)
    assert talk_routes._missing_line(kept, count).startswith(f" {count} pieces never arrived (number 1, 3, 4")


# ---------------------------------------------------------------------------
# A talk whose finish never came


async def _age(sm, talk_id: str, hours: float) -> None:
    async with sm() as s:
        row = await s.get(AgentTalk, uuid.UUID(talk_id))
        row.last_chunk_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
        await s.commit()


@needs_ffmpeg
async def test_a_talk_idle_for_hours_is_finished_by_tce_itself(client, editorial_sessionmaker, tmp_path, spawned):
    data = _record(tmp_path / "source.webm", "webm")
    idle = await _new_talk(client, call_id="call-idle")
    for seq, piece in enumerate(_split(data)):
        assert (await client.put(f"{BASE}/{idle}/chunks/{seq}", headers=AUTH, content=piece)).status_code == 200
    fresh = await _new_talk(client, call_id="call-fresh")
    assert (await client.put(f"{BASE}/{fresh}/chunks/0", headers=AUTH, content=data[:500])).status_code == 200
    empty = await _new_talk(client, call_id="call-empty")
    await _age(editorial_sessionmaker, idle, 7)
    await _age(editorial_sessionmaker, empty, 7)
    await _age(editorial_sessionmaker, fresh, 1)  # within the relay's own time: left alone

    done = await talk_routes.finish_idle_talks(WS)
    assert done == [uuid.UUID(idle)]
    async with editorial_sessionmaker() as s:
        rows = {str(r.id): r for r in (await s.execute(select(AgentTalk))).scalars().all()}
        upload = await s.get(RecordingUpload, rows[idle].upload_id)
    assert rows[idle].status == "finished" and upload.source == "agent_talk"
    assert rows[fresh].status == "recording" and rows[fresh].upload_id is None
    # Nothing ever arrived for this one: it says so instead of waiting forever.
    assert rows[empty].status == "failed" and "No piece arrived for 6 hours" in rows[empty].status_detail
    # 4-Oct (C4.1): no choice ever came for it, so it is archived, never edited.
    assert spawned == []
    assert upload.archived_at is not None and "No choice came for it" in upload.status_detail

    # The relay comes back later with the call's transcript: the same video keeps it.
    r = await client.post(f"{BASE}/{idle}/finish", headers=AUTH,
                          json={"transcript": [{"who": "agent", "text": "Hello.", "t_ms": 0}]})
    assert r.status_code == 200 and r.json()["upload_id"] == str(upload.id)
    async with editorial_sessionmaker() as s:
        assert (await s.get(RecordingUpload, upload.id)).call_transcript[0]["text"] == "Hello."


async def test_a_new_talk_starts_the_backstop_only_when_a_talk_is_idle(client, editorial_sessionmaker, spawned):
    first = await _new_talk(client, call_id="call-a")
    assert spawned == []  # nothing idle: nothing started
    await _age(editorial_sessionmaker, first, 7)
    await _new_talk(client, call_id="call-b")
    assert [c.__name__ for c in spawned] == ["finish_idle_talks"]


async def test_startup_finishes_idle_talks_too(client, editorial_sessionmaker, spawned, monkeypatch):
    monkeypatch.setattr(prod.settings, "production_auto_edit", False)
    talk = await _new_talk(client, call_id="call-restart")
    await _age(editorial_sessionmaker, talk, 7)
    await prod.resume_auto_work()
    assert "finish_idle_talks" in [c.__name__ for c in spawned]


def test_the_backstop_never_races_the_relays_own_sweeper():
    # C4: the relay finishes a talk idle for 10 minutes; TCE waits far longer.
    assert talk_routes.IDLE_FINISH_S >= 6 * 3600
