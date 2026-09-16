"""Local media steps: transcript parsing, worker protocol, ffmpeg cut. Synthetic media."""

from __future__ import annotations

import json
import subprocess

import pytest
from aiohttp import web

from tce.production import media


def test_parse_transcript_md_infers_ends():
    md = "# Transcript: x\n- Model: synthetic\n\n[00:00:01] First line.\n[00:00:04] Second line."
    rows = media.parse_transcript_md(md, duration_s=7.5)
    assert rows == [
        {"start_s": 1.0, "end_s": 4.0, "text": "First line."},
        {"start_s": 4.0, "end_s": 7.5, "text": "Second line."},
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
