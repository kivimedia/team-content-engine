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
    # Opening the same packet again with nothing recorded is the SAME take set, not
    # a second empty one: two opens used to read the same retake index and collide.
    second = await sessions.create_session(editorial_session, ws, candidate.id, packet.id)
    assert (row.packet_version, row.retake_index) == (1, 1)
    assert second.id == row.id
    with pytest.raises(sessions.RecordingSessionError):
        await sessions.create_session(editorial_session, uuid.uuid4(), candidate.id, packet.id)


async def test_a_real_retake_still_gets_its_own_number(editorial_session):
    # Once a take set has a clip it is spent, and the next open is take two.
    ws = uuid.uuid4()
    candidate, packet = await packet_fixture(editorial_session, ws)
    first = await sessions.create_session(editorial_session, ws, candidate.id, packet.id)
    await sessions.create_clip(editorial_session, ws, first.id, "local-1", "video/webm", "webm")

    second = await sessions.create_session(editorial_session, ws, candidate.id, packet.id)

    assert second.id != first.id
    assert (first.retake_index, second.retake_index) == (1, 2)


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


async def uploading_clip(db, ws, recording, local_id, root):
    clip = await sessions.create_clip(db, ws, recording.id, local_id, "video/webm", "webm")
    body = f"synthetic-{local_id}".encode()
    await sessions.store_chunk(db, ws, clip.id, 0, body, hashlib.sha256(body).hexdigest(), root)
    return clip


async def make_ready(db, ws, clip, seconds, root):
    async def valid(_path):
        return {"has_audio": True, "has_video": True, "duration_s": seconds}

    return await sessions.finalize_clip(
        db, ws, clip.id, root, active_duration_s=seconds, prober=valid
    )


async def ready_clip(db, ws, recording, local_id, seconds, root):
    clip = await uploading_clip(db, ws, recording, local_id, root)
    return await make_ready(db, ws, clip, seconds, root)


async def test_a_clip_that_became_ready_after_finish_is_not_lost(editorial_session, tmp_path):
    """24-Sep walk: Finish was pressed while the 338 s clip was still uploading its
    last pieces, so the session was built from the 3 s clip alone, and the second
    Finish handed back that 2.9 s video because a finished session was locked."""
    ws = uuid.uuid4()
    candidate, packet = await packet_fixture(editorial_session, ws)
    recording = await sessions.create_session(editorial_session, ws, candidate.id, packet.id)
    short = await ready_clip(editorial_session, ws, recording, "short", 3.0, tmp_path)
    # The long clip exists and is still sending its last pieces when Finish lands.
    long = await uploading_clip(editorial_session, ws, recording, "long", tmp_path)

    async def joined(paths, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"|".join(p.name.encode() for p in paths) + str(len(paths)).encode())
        return {"duration_s": 3.0 * len(paths)}

    _, first = await sessions.finalize_session(
        editorial_session, ws, recording.id, [short.id], tmp_path, assembler=joined
    )
    first_bytes = open(first.storage_path, "rb").read()
    long = await make_ready(editorial_session, ws, long, 338.0, tmp_path)

    again, second = await sessions.finalize_session(
        editorial_session, ws, recording.id, [short.id, long.id], tmp_path, assembler=joined
    )

    assert second.id != first.id, "the rebuilt session must be a new video, not the old one"
    assert again.canonical_upload_id == second.id
    assert again.active_duration_s == 341.0
    assert first.status == "superseded", "the short-only video must leave the Library"
    assert open(first.storage_path, "rb").read() == first_bytes, "the old file is kept, untouched"
    assert second.storage_path != first.storage_path
    # The same selection a third time is the same video, not a third build.
    _, third = await sessions.finalize_session(
        editorial_session, ws, recording.id, [short.id, long.id], tmp_path, assembler=joined
    )
    assert third.id == second.id


def _make_clip(exe, path, audio_first):
    import subprocess

    maps = ["-map", "1:a", "-map", "0:v"] if audio_first else ["-map", "0:v", "-map", "1:a"]
    subprocess.run(
        [exe, "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=blue:s=64x114:d=2:r=15",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2:sample_rate=48000",
         *maps, "-c:v", "libvpx-vp9", "-deadline", "realtime", "-c:a", "libopus", "-ac", "1",
         str(path)],
        check=True,
    )


async def test_clips_whose_tracks_come_in_different_orders_keep_their_sound(tmp_path):
    """24-Sep walk: the 3 s clip was stored audio-then-video, the 338 s clip
    video-then-audio (Chrome does not keep one order). The join matched tracks by
    position, so after the first clip the audio track was filled with video: the
    5m41s video had 2.9 s of sound and transcribed to 0 words."""
    import subprocess

    from tce.production.media import ffmpeg_path

    exe = ffmpeg_path()
    if not exe:
        pytest.skip("ffmpeg not installed")
    first, second = tmp_path / "a.webm", tmp_path / "b.webm"
    _make_clip(exe, first, audio_first=True)
    _make_clip(exe, second, audio_first=False)
    out = tmp_path / "canonical.mp4"
    await sessions.assemble_clips([first, second], out)
    decode = subprocess.run(
        [exe, "-v", "error", "-i", str(out), "-map", "0:a", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    assert decode.stderr.strip() == "", f"the joined audio does not decode: {decode.stderr[:300]}"
    heard = subprocess.run(
        [exe, "-v", "error", "-i", str(out), "-map", "0:a", "-f", "s16le", "-ac", "1", "-ar", "8000", "-"],
        capture_output=True,
    ).stdout
    assert len(heard) / 2 / 8000 > 3.5, f"only {len(heard) / 16000:.1f}s of sound in a 4s join"
