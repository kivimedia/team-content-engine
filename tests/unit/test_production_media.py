"""Local media steps: transcript parsing, worker protocol, ffmpeg cut. Synthetic media."""

from __future__ import annotations

import json
import subprocess

import pytest
from aiohttp import web

from tce.production import media
from tce.production.retakes import build_cues, to_ass, to_srt


def test_parse_transcript_md_infers_ends():
    md = "# Transcript: x\n- Model: synthetic\n\n[00:00:01] First line.\n[00:00:04] Second line."
    rows = media.parse_transcript_md(md, duration_s=7.5)
    w = "whole_second_start_inferred_end"
    assert rows == [
        {"start_s": 1.0, "end_s": 4.0, "text": "First line.", "precision": w},
        {"start_s": 4.0, "end_s": 7.5, "text": "Second line.", "precision": w},
    ]


async def test_transcribe_unavailable_without_url(tmp_path):
    f = tmp_path / "a.wav"
    f.write_bytes(b"x")

    async def status(_):
        return None

    with pytest.raises(media.StepUnavailableError, match="Paid transcription"):
        await media.transcribe_local(f, ws_url="", language=None, duration_s=1, on_status=status)


async def test_transcribe_local_worker_protocol(tmp_path, unused_tcp_port):
    received = {}

    async def handler(request):
        ws = web.WebSocketResponse(max_msg_size=0)
        await ws.prepare(request)
        received["meta"] = json.loads(await ws.receive_str())
        await ws.send_str(json.dumps({"status": "receiving_audio"}))
        received["bytes"] = await ws.receive_bytes()
        await ws.send_str(json.dumps({"status": "transcribing"}))
        await ws.send_str(
            json.dumps({"status": "complete", "transcript_md": "[00:00:00] Hello there."})
        )
        await ws.close()
        return ws

    app = web.Application()
    app.router.add_get("/transcribe", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()
    statuses: list[str] = []

    async def status(text):
        statuses.append(text)

    f = tmp_path / "clip.wav"
    f.write_bytes(b"synthetic")
    try:
        rows = await media.transcribe_local(
            f,
            ws_url=f"ws://127.0.0.1:{unused_tcp_port}/transcribe",
            language="he",
            duration_s=102,
            on_status=status,
        )
    finally:
        await runner.cleanup()
    assert rows[0]["text"] == "Hello there." and rows[0]["end_s"] == 102
    assert received["meta"]["language"] == "he" and received["bytes"] == b"synthetic"
    assert "Transcribing 1m42s file with local faster-whisper" in statuses


@pytest.mark.skipif(not media.ffmpeg_path(), reason="ffmpeg not installed")
async def test_render_edit_cuts_kept_ranges(tmp_path):
    src = tmp_path / "tone.wav"
    subprocess.run(
        [media.ffmpeg_path(), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", str(src)],
        check=True,
        capture_output=True,
    )
    statuses: list[str] = []

    async def status(text):
        statuses.append(text)

    out = await media.render_edit(
        src, [[0.0, 1.0], [2.5, 3.5]], tmp_path / "out.wav", on_status=status
    )
    duration = await media.probe_duration(out)
    assert duration is not None and abs(duration - 2.0) < 0.15
    assert statuses == ["Cutting 2 kept ranges with ffmpeg"]


def test_fmt_duration():
    assert media.fmt_duration(102) == "1m42s"
    assert media.fmt_duration(None) == "unknown length"


def _gray_frame(path, t, size):
    """Raw 8-bit gray pixels of the frame at `t` seconds."""
    w, h = size
    raw = subprocess.run(
        [
            media.ffmpeg_path(),
            "-v",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    assert len(raw) == w * h
    return raw


def _bright_in_lower_third(raw, size):
    w, h = size
    start = (h * 2 // 3) * w
    return sum(1 for b in raw[start:] if b > 180)


@pytest.mark.skipif(not media.ffmpeg_path(), reason="ffmpeg not installed")
async def test_render_burns_captions_on_the_edited_timeline(tmp_path):
    size = (360, 640)
    src = tmp_path / "walk.mp4"
    subprocess.run(
        [
            media.ffmpeg_path(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={size[0]}x{size[1]}:r=25:d=6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=6",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    plan = {
        "keep": [[0.0, 2.0], [4.0, 6.0]],
        "units": [
            {"start": 0.5, "end": 1.5, "text": "Kept before the cut", "kept": True},
            {"start": 2.5, "end": 3.5, "text": "Dropped retake", "kept": False},
            {"start": 4.5, "end": 5.5, "text": "Kept after the cut", "kept": True},
        ],
    }
    cues = build_cues(plan)
    assert [(c["start"], c["end"]) for c in cues] == [(0.5, 1.5), (2.5, 3.5)]

    async def status(_):
        return None

    out = await media.render_edit(
        src,
        plan["keep"],
        tmp_path / "walk-edited.mp4",
        on_status=status,
        ass_text=to_ass(cues, *size),
        srt_text=to_srt(cues),
    )
    assert out.suffix == ".mp4" and not list(tmp_path.glob(".*rendering*"))
    duration = await media.probe_duration(out)
    assert duration is not None and abs(duration - 4.0) < 0.2
    streams = subprocess.run(
        [
            media.ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert {"h264", "aac", "mov_text"} <= set(streams)
    assert await media.probe_video_size(out) == size
    # Caption pixels exist exactly while a cue is on screen, measured after the cut
    assert _bright_in_lower_third(_gray_frame(out, 1.0, size), size) > 200
    assert _bright_in_lower_third(_gray_frame(out, 2.1, size), size) == 0
    assert _bright_in_lower_third(_gray_frame(out, 3.0, size), size) > 200
    assert _bright_in_lower_third(_gray_frame(out, 3.8, size), size) == 0


@pytest.mark.skipif(not media.ffmpeg_path(), reason="ffmpeg not installed")
async def test_render_audio_only_upload_becomes_captioned_mp4(tmp_path):
    src = tmp_path / "walk.m4a"
    subprocess.run(
        [media.ffmpeg_path(), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(src)],
        check=True,
        capture_output=True,
    )
    cues = [{"start": 0.2, "end": 2.5, "lines": ["Audio only walk"]}]

    async def status(_):
        return None

    size = media.AUDIO_ONLY_CANVAS
    out = await media.render_edit(
        src,
        [[0.0, 3.0]],
        tmp_path / "walk-edited.mp4",
        on_status=status,
        ass_text=to_ass(cues, *size),
        srt_text=to_srt(cues),
    )
    assert await media.probe_video_size(out) == size
    assert _bright_in_lower_third(_gray_frame(out, 1.0, size), size) > 200


@pytest.mark.skipif(not media.ffmpeg_path(), reason="ffmpeg not installed")
async def test_failed_render_leaves_no_partial_file(tmp_path):
    src = tmp_path / "broken.mp4"
    src.write_bytes(b"not a video")

    async def status(_):
        return None

    with pytest.raises(RuntimeError, match="ffmpeg exited"):
        await media.render_edit(
            src,
            [[0.0, 1.0]],
            tmp_path / "broken-edited.mp4",
            on_status=status,
            ass_text=to_ass([], 360, 640),
            srt_text="",
        )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["broken.mp4"]


def test_ass_captions_fit_portrait_width():
    cues = [
        {
            "start": 0.0,
            "end": 4.0,
            "lines": [
                "Most small studios lose leads in the first",
                "hour because nobody owns the inbox",
            ],
        }
    ]
    ass = to_ass(cues, 720, 1280)
    assert "PlayResX: 720" in ass and "PlayResY: 1280" in ass
    dialogue = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue) == 2  # re-wrapped for the narrow frame, two lines per screen
    for line in dialogue:
        for text in line.split(",,", 1)[1].split(r"\N"):
            assert len(text) <= 30
