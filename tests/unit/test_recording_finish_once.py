"""Finish runs once (8-Oct, T-10566 and T-10568). Synthetic data.

On 8-Oct Ziv pressed Finish on an 8 min 43 s take, saw only the thin top line,
and pressed it again. The second request read the take set before the first had
saved, built the same video a second time and failed on the duplicate: a 500
after the take had already saved. His words: "you don't want to allow me to
click on finish twice."

Finish now answers as soon as the work is claimed and builds the video in the
background, and a second Finish while it builds is told so, never an error.
"""

from __future__ import annotations

import asyncio
import functools
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tce.api.routers import production as prod
from tce.models.editorial import RecordingUpload
from tce.models.recording_session import RecordingSession
from tce.production import sessions
from tests.editorial_db import create_tables
from tests.unit.test_recording_sessions import packet_fixture, ready_clip


@pytest.fixture
async def filedb(tmp_path):
    """Two presses need two real connections; the shared in-memory one is one."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tce.db'}")
    await create_tables(engine)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await engine.dispose()


class Gate:
    """An assembler that waits until the test lets it finish."""

    def __init__(self, fail: str | None = None) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0
        self.fail = fail

    async def __call__(self, paths, output):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        if self.fail:
            raise sessions.RecordingSessionError(self.fail)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"|".join(p.name.encode() for p in paths))
        return {"duration_s": 523.4}


def wire(monkeypatch, sm, tmp_path, gate):
    # Builds spawned by other tests ran on other event loops; this test waits on its own.
    monkeypatch.setattr(prod, "_background", set())
    monkeypatch.setattr(prod, "session_factory", lambda: sm)
    monkeypatch.setattr(prod.settings, "production_auto_edit", False)
    monkeypatch.setattr(prod, "_recording_root", lambda: tmp_path)
    monkeypatch.setattr(
        prod.recording_sessions,
        "finalize_session",
        functools.partial(sessions.finalize_session, assembler=gate),
    )


async def seed(sm, tmp_path):
    ws = uuid.uuid4()
    async with sm() as s:
        candidate, packet = await packet_fixture(s, ws)
        recording = await sessions.create_session(s, ws, candidate.id, packet.id)
        clip = await ready_clip(s, ws, recording, "walk", 523.5, tmp_path)
        await s.commit()
    return ws, recording.id, clip.id


async def press(sm, ws, session_id, clip_id):
    async with sm() as s:
        body = prod.RecordingSessionFinish(selected_clip_ids=[clip_id])
        response = prod.Response()
        response.status_code = 200
        payload = await prod.finish_recording_session_route(
            session_id, body, response=response, ws=ws, db=s
        )
        return response.status_code, payload


async def drain():
    while prod._background:
        await asyncio.gather(*list(prod._background), return_exceptions=True)


async def uploads(sm, ws):
    async with sm() as s:
        return list((await s.execute(select(RecordingUpload).where(RecordingUpload.workspace_id == ws))).scalars())


async def session_row(sm, ws, session_id):
    async with sm() as s:
        return (
            await s.execute(
                select(RecordingSession).where(
                    RecordingSession.id == session_id, RecordingSession.workspace_id == ws
                )
            )
        ).scalar_one()


async def test_a_second_finish_while_the_video_builds_is_not_an_error(
    monkeypatch, filedb, tmp_path
):
    sm = filedb
    gate = Gate()
    wire(monkeypatch, sm, tmp_path, gate)
    ws, session_id, clip_id = await seed(sm, tmp_path)

    first = asyncio.create_task(press(sm, ws, session_id, clip_id))
    await asyncio.wait_for(gate.entered.wait(), 5)
    # The first press is still building the video when the second one lands.
    try:
        status, again = await asyncio.wait_for(press(sm, ws, session_id, clip_id), 10)
    finally:
        gate.release.set()
    first_status, started = await asyncio.wait_for(first, 10)
    await drain()

    assert first_status == 202, "the first Finish answers once the work is claimed"
    assert started["started"] is True and started["session"]["status"] == "finalizing"
    assert status == 200 and again["started"] is False
    assert again["session"]["status"] == "finalizing", "the second press is told it is already building"
    assert gate.calls == 1, "the video is built once"
    rows = await uploads(sm, ws)
    assert len(rows) == 1
    done = await session_row(sm, ws, session_id)
    assert done.status == "uploaded" and done.canonical_upload_id == rows[0].id
    # Finish after it saved hands back the same video, still not an error.
    status, third = await press(sm, ws, session_id, clip_id)
    assert status == 200 and third["upload"]["id"] == str(rows[0].id)


async def test_a_build_that_fails_says_why_and_can_be_finished_again(
    monkeypatch, filedb, tmp_path
):
    sm = filedb
    gate = Gate(fail="the clips could not be joined")
    gate.release.set()
    wire(monkeypatch, sm, tmp_path, gate)
    ws, session_id, clip_id = await seed(sm, tmp_path)

    status, _ = await press(sm, ws, session_id, clip_id)
    await drain()
    row = await session_row(sm, ws, session_id)
    assert status == 202
    assert row.status == "recording", "a failed build gives the take set back"
    assert "the clips could not be joined" in (row.error_detail or "")
    assert await uploads(sm, ws) == []

    gate.fail = None
    status, payload = await press(sm, ws, session_id, clip_id)
    await drain()
    row = await session_row(sm, ws, session_id)
    assert status == 202 and payload["started"] is True
    assert row.status == "uploaded" and row.error_detail is None


async def test_a_build_left_behind_by_a_restart_can_be_finished_again(
    monkeypatch, filedb, tmp_path
):
    sm = filedb
    gate = Gate()
    gate.release.set()
    wire(monkeypatch, sm, tmp_path, gate)
    ws, session_id, clip_id = await seed(sm, tmp_path)
    async with sm() as s:
        row = (await s.execute(select(RecordingSession).where(RecordingSession.id == session_id))).scalar_one()
        row.status = "finalizing"
        row.updated_at = sessions.utcnow() - sessions.FINALIZE_STALE - timedelta(minutes=1)
        await s.commit()

    status, payload = await press(sm, ws, session_id, clip_id)
    await drain()
    assert status == 202 and payload["started"] is True
    assert (await session_row(sm, ws, session_id)).status == "uploaded"
