"""Continue recording (25-Nov): a take stopped partway through, sent back from the
Library to the studio's "To continue recording" tab, then joined into one video."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import uuid
from datetime import datetime

import pytest

from tce.editorial import continuation, library, today
from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate, VideoPublication
from tce.production import sessions

LINES = [
    "Most coaches price by the hour",
    "That tells the client your time is the product",
    "But the client is buying the change",
    "So price the change, not the hour",
    "Book a strategy session to see how",
]


async def seed(db, ws, *, heard: list[str] | None, status: str = "edited", source: str | None = None):
    candidate = TopicCandidate(
        workspace_id=ws, week_start=datetime(2026, 11, 23), moment_ids=[str(uuid.uuid4())],
        title="Price the change", lesson="Price outcomes", audience="coaches",
        public_angle="angle", gates={}, status="selected",
    )
    db.add(candidate)
    await db.flush()
    packet = RecordingPacket(
        workspace_id=ws, candidate_id=candidate.id, version=1, bullets=["a"],
        script_phrases=LINES, hook_options=[], selected_hook_id=None, beats=[], status="ready",
    )
    db.add(packet)
    await db.flush()
    transcript = None
    if heard is not None:
        transcript = [{"start_s": i * 3.0, "end_s": i * 3.0 + 2.5, "text": t} for i, t in enumerate(heard)]
    upload = RecordingUpload(
        workspace_id=ws, candidate_id=candidate.id, packet_id=packet.id,
        original_filename="first.mp4", storage_path="/tmp/first.mp4", sha256=uuid.uuid4().hex * 2,
        duration_s=42.0, transcript=transcript, status=status, source=source,
        edited_path="/tmp/first-edit.mp4" if status == "edited" else None,
    )
    db.add(upload)
    await db.commit()
    return candidate, packet, upload


def keys(item):
    return [a["key"] for a in item["actions"]]


# ------------------------------------------------------------------ where he stopped


def test_reads_the_last_line_he_finished():
    heard = [
        "most coaches uh price by the hour",
        "that tells the client your time is the product okay",
        "but the client is",  # cut off mid-line: not said
    ]
    point = continuation.resume_point(LINES, [{"text": t} for t in heard])
    assert point == {"resume_index": 2, "last_said_index": 1, "detected": True}


def test_a_misheard_word_still_counts_and_a_skipped_line_does_not_stop_the_walk():
    heard = ["most coaches prize by the hour", "but the client is buying the change"]
    point = continuation.resume_point(LINES, [{"text": t} for t in heard])
    assert point["last_said_index"] == 2


def test_nothing_heard_starts_at_the_top_and_says_it_did_not_detect():
    assert continuation.resume_point(LINES, None) == {
        "resume_index": 0, "last_said_index": -1, "detected": False,
    }


# --------------------------------------------------------------------- the Library


async def test_send_back_takes_it_out_of_the_library_and_take_back_returns_it(editorial_session):
    db, ws = editorial_session, uuid.uuid4()
    _, _, upload = await seed(db, ws, heard=LINES[:2])

    item = (await library.list_library(db, ws))["items"][0]
    assert keys(item).index("send_back") == keys(item).index("re_record") - 1

    preview = await continuation.preview(db, ws, upload.id)
    assert preview["last_said_index"] == 1 and preview["lines"] == LINES

    await continuation.send_back(db, ws, upload.id)
    await db.commit()
    listing = await library.list_library(db, ws)
    assert listing["items"] == []
    assert listing["continuing"][0]["upload_id"] == str(upload.id)
    assert upload.continuation["resume_index"] == 2
    assert upload.continuation["repeat_line"] == LINES[1]
    assert upload.continuation["detected"] is True

    await continuation.take_back(db, ws, upload.id)
    await db.commit()
    listing = await library.list_library(db, ws)
    assert [i["upload_id"] for i in listing["items"]] == [str(upload.id)]
    assert listing["continuing"] == []


async def test_the_team_can_correct_the_line(editorial_session):
    db, ws = editorial_session, uuid.uuid4()
    _, _, upload = await seed(db, ws, heard=LINES[:2])
    await continuation.send_back(db, ws, upload.id, last_said_index=0)
    assert upload.continuation["resume_index"] == 1
    assert upload.continuation["detected"] is False  # a person chose it, not the reading
    with pytest.raises(continuation.ContinuationError):
        await continuation.send_back(db, ws, upload.id)  # already waiting


async def test_every_line_said_leaves_nothing_to_record(editorial_session):
    db, ws = editorial_session, uuid.uuid4()
    _, _, upload = await seed(db, ws, heard=LINES)
    with pytest.raises(continuation.ContinuationError, match="nothing left"):
        await continuation.send_back(db, ws, upload.id)


async def test_a_posted_video_never_comes_back(editorial_session):
    db, ws = editorial_session, uuid.uuid4()
    candidate, _, upload = await seed(db, ws, heard=LINES[:2])
    db.add(VideoPublication(workspace_id=ws, upload_id=upload.id, candidate_id=candidate.id,
                            platform="instagram", status="scheduled", copy={}))
    await db.commit()
    listing = await library.list_library(db, ws, filter_key="published")
    assert "send_back" not in keys(listing["items"][0])
    with pytest.raises(continuation.ContinuationError, match="posted or scheduled"):
        await continuation.send_back(db, ws, upload.id)


async def test_no_button_while_it_is_being_edited_or_without_a_script(editorial_session):
    db, ws = editorial_session, uuid.uuid4()
    await seed(db, ws, heard=LINES[:2], status="rendering")
    await seed(db, ws, heard=LINES[:2], status="uploaded", source="solo_take")
    items = (await library.list_library(db, ws))["items"]
    assert all("send_back" not in keys(i) for i in items)


# ------------------------------------------------------------------- the studio


async def _ready_clip(db, ws, recording, root, seconds):
    clip = await sessions.create_clip(db, ws, recording.id, "rest-1", "video/webm", "webm")
    body = b"synthetic-rest"
    await sessions.store_chunk(db, ws, clip.id, 0, body, hashlib.sha256(body).hexdigest(), root)

    async def valid(_path):
        return {"has_audio": True, "has_video": True, "duration_s": seconds}

    return await sessions.finalize_clip(db, ws, clip.id, root, active_duration_s=seconds, prober=valid)


async def test_the_rest_is_recorded_and_joined_into_one_video(editorial_session, tmp_path):
    db, ws = editorial_session, uuid.uuid4()
    candidate, packet, upload = await seed(db, ws, heard=LINES[:2])
    # A newer script since: the rest still records the version the first part used.
    packet.status = "superseded"
    await continuation.send_back(db, ws, upload.id)
    await db.commit()

    tab = await continuation.waiting_list(db, ws)
    assert [t["continue_upload_id"] for t in tab] == [str(upload.id)]
    assert tab[0]["resume_index"] == 2 and tab[0]["repeat_line"] == LINES[1]
    assert tab[0]["script_phrases"] == LINES

    nxt = today._next_action(week={}, waiting=3, pending_reviews=1, continuing=tab)
    assert nxt["key"] == "continue_recording"
    assert nxt["href"] == f"/record?continue={upload.id}"

    rest = await sessions.create_session(db, ws, candidate.id, packet.id, continues_upload_id=upload.id)
    again = await sessions.create_session(db, ws, candidate.id, packet.id, continues_upload_id=upload.id)
    assert again.id == rest.id
    assert upload.continuation["state"] == "recording"
    # A plain take of the same topic never reuses the continuation's draft.
    with pytest.raises(sessions.RecordingSessionError, match="replaced"):
        await sessions.create_session(db, ws, candidate.id, packet.id)

    clip = await _ready_clip(db, ws, rest, tmp_path, 30.0)
    seen: list = []

    async def joined(paths, output):
        seen.extend(paths)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"joined")
        return {"duration_s": 72.0}

    finished, video = await sessions.finalize_session(db, ws, rest.id, [clip.id], tmp_path, assembler=joined)
    await db.commit()

    assert str(seen[0]) == upload.storage_path, "the first recording goes first"
    assert len(seen) == 2
    assert upload.status == "superseded" and upload.continuation["state"] == "joined"
    assert upload.continuation["joined_upload_id"] == str(video.id)
    assert video.continuation == {
        "state": "joined_result", "from_upload_id": str(upload.id),
        "seam_s": 42.0, "repeat_line": LINES[1],
    }
    assert finished.timeline_map[0]["part"] == "first_recording"
    assert finished.timeline_map[1]["timeline_start_s"] == 42.0

    listing = await library.list_library(db, ws)
    assert [i["upload_id"] for i in listing["items"]] == [str(video.id)]
    assert listing["continuing"] == []
    assert await continuation.waiting_list(db, ws) == []

    told = continuation.jennifer_context(video)
    assert "0:42" in told and LINES[1] in told


async def test_taken_back_after_the_rest_is_joined_is_refused(editorial_session, tmp_path):
    db, ws = editorial_session, uuid.uuid4()
    candidate, packet, upload = await seed(db, ws, heard=LINES[:2])
    await continuation.send_back(db, ws, upload.id)
    rest = await sessions.create_session(db, ws, candidate.id, packet.id, continues_upload_id=upload.id)
    rest.status = "finalizing"
    await db.commit()
    with pytest.raises(continuation.ContinuationError, match="already recorded"):
        await continuation.take_back(db, ws, upload.id)


# ---------------------------------------------------- the real join, real ffmpeg

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _clip(path, size, vcodec, acodec, seconds):
    subprocess.run(
        [shutil.which("ffmpeg"), "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=blue:s={size}:d={seconds}:r=15",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=48000",
         "-c:v", vcodec, "-c:a", acodec, "-shortest", str(path)],
        check=True, capture_output=True,
    )
    return path


@needs_ffmpeg
async def test_parts_from_another_device_are_made_the_same_then_joined(tmp_path):
    first = _clip(tmp_path / "first.mp4", "64x114", "libx264", "aac", 2)
    rest = _clip(tmp_path / "rest.webm", "96x96", "libvpx", "libopus", 2)
    out = tmp_path / "out" / "canonical.mp4"
    proof = await sessions.assemble_continuation([first, rest], out)
    assert proof["has_audio"] and proof["has_video"]
    assert 3.5 < proof["duration_s"] < 4.6
    video = next(s for s in proof["streams"] if s["type"] == "video")
    assert (video["width"], video["height"]) == (64, 114)


@needs_ffmpeg
async def test_parts_from_the_same_device_join_by_copying(tmp_path):
    first = _clip(tmp_path / "first.mp4", "64x114", "libx264", "aac", 2)
    rest = _clip(tmp_path / "rest.mp4", "64x114", "libx264", "aac", 2)
    proof = await sessions.assemble_continuation([first, rest], tmp_path / "out" / "c.mp4")
    assert proof["has_audio"] and 3.5 < proof["duration_s"] < 4.6


async def test_a_take_set_for_a_video_taken_back_is_not_joined(editorial_session, tmp_path):
    db, ws = editorial_session, uuid.uuid4()
    candidate, packet, upload = await seed(db, ws, heard=LINES[:2])
    await continuation.send_back(db, ws, upload.id)
    rest = await sessions.create_session(db, ws, candidate.id, packet.id, continues_upload_id=upload.id)
    clip = await _ready_clip(db, ws, rest, tmp_path, 10.0)
    await continuation.take_back(db, ws, upload.id)
    await db.commit()

    async def joined(paths, output):  # never reached
        raise AssertionError("joined a video that was taken back")

    with pytest.raises(sessions.RecordingSessionError, match="taken back"):
        await sessions.finalize_session(db, ws, rest.id, [clip.id], tmp_path, assembler=joined)
    assert upload.status == "edited"
