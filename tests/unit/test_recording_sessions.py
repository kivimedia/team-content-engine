"""Mobile recording session ownership, append and chunk recovery contracts."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

import pytest

from tce.models.editorial import RecordingPacket, TopicCandidate
from tce.production import sessions


async def packet_fixture(db, ws):
    candidate = TopicCandidate(
        workspace_id=ws,
        week_start=datetime(2026, 9, 7),
        moment_ids=[str(uuid.uuid4())],
        title="Synthetic idea",
        lesson="Synthetic lesson",
        audience="coaches",
        public_angle="Synthetic angle",
        gates={},
        status="selected",
    )
    db.add(candidate)
    await db.flush()
    packet = RecordingPacket(
        workspace_id=ws,
        candidate_id=candidate.id,
        version=1,
        bullets=["a", "b", "c", "d", "e"],
        script_phrases=["one", "two", "three", "four", "five", "book a strategy session"],
        hook_options=[],
        selected_hook_id=None,
        beats=[],
        status="ready",
    )
    db.add(packet)
    await db.commit()
    return candidate, packet


async def test_session_is_bound_to_workspace_candidate_and_immutable_packet(editorial_session):
    ws = uuid.uuid4()
    candidate, packet = await packet_fixture(editorial_session, ws)
    row = await sessions.create_session(editorial_session, ws, candidate.id, packet.id)
    second = await sessions.create_session(editorial_session, ws, candidate.id, packet.id)
    assert (row.packet_version, row.retake_index, second.retake_index) == (1, 1, 2)
    with pytest.raises(sessions.RecordingSessionError):
        await sessions.create_session(editorial_session, uuid.uuid4(), candidate.id, packet.id)


async def test_a_b_a_clips_append_and_local_id_is_idempotent(editorial_session):
    ws = uuid.uuid4()
    candidate, packet = await packet_fixture(editorial_session, ws)
    a = await sessions.create_session(editorial_session, ws, candidate.id, packet.id)
    a1 = await sessions.create_clip(editorial_session, ws, a.id, "local-a1", "video/webm", "webm")
    again = await sessions.create_clip(
        editorial_session, ws, a.id, "local-a1", "video/webm", "webm"
    )
    a2 = await sessions.create_clip(editorial_session, ws, a.id, "local-a2", "video/webm", "webm")
    assert a1.id == again.id and (a1.position, a2.position) == (0, 1)


async def test_chunks_are_idempotent_and_missing_sequences_block_finalize(
    editorial_session, tmp_path
):
    ws = uuid.uuid4()
    candidate, packet = await packet_fixture(editorial_session, ws)
    recording = await sessions.create_session(editorial_session, ws, candidate.id, packet.id)
    clip = await sessions.create_clip(
        editorial_session, ws, recording.id, "local-a1", "video/webm", "webm"
    )
    body = b"synthetic-media-chunk"
    digest = hashlib.sha256(body).hexdigest()
    first = await sessions.store_chunk(editorial_session, ws, clip.id, 1, body, digest, tmp_path)
    same = await sessions.store_chunk(editorial_session, ws, clip.id, 1, body, digest, tmp_path)
    assert first.id == same.id
    with pytest.raises(sessions.RecordingSessionError, match="different bytes"):
        other = b"different"
        await sessions.store_chunk(
            editorial_session,
            ws,
            clip.id,
            1,
            other,
            hashlib.sha256(other).hexdigest(),
            tmp_path,
        )
    with pytest.raises(sessions.RecordingSessionError, match="missing"):
        await sessions.finalize_clip(
            editorial_session,
            ws,
            clip.id,
            tmp_path,
            active_duration_s=1.0,
            prober=lambda _path: None,  # never reached
        )


async def test_finalize_clip_requires_audio_and_preserves_source_chunks(
    editorial_session, tmp_path
):
    ws = uuid.uuid4()
    candidate, packet = await packet_fixture(editorial_session, ws)
    recording = await sessions.create_session(editorial_session, ws, candidate.id, packet.id)
    clip = await sessions.create_clip(
        editorial_session, ws, recording.id, "local-a1", "video/webm", "webm"
    )
    body = b"synthetic-container"
    await sessions.store_chunk(
        editorial_session, ws, clip.id, 0, body, hashlib.sha256(body).hexdigest(), tmp_path
    )

    async def no_audio(_path):
        return {"has_audio": False, "has_video": True, "duration_s": 2.0}

    with pytest.raises(sessions.RecordingSessionError, match="audible"):
        await sessions.finalize_clip(
            editorial_session, ws, clip.id, tmp_path, active_duration_s=2.0, prober=no_audio
        )

    async def valid(_path):
        return {"has_audio": True, "has_video": True, "duration_s": 2.0}

    ready = await sessions.finalize_clip(
        editorial_session,
        ws,
        clip.id,
        tmp_path,
        active_duration_s=1.7,
        take_markers=[{"beat_id": "b01", "at_s": 0.5}],
        prober=valid,
    )
    assert ready.status == "ready" and ready.active_duration_s == 1.7
    assert list((tmp_path / str(ws) / str(recording.id) / str(clip.id)).glob("*.part"))
