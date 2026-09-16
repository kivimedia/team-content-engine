"""Local, free media steps: probe, transcribe, cut. No metered API is reachable from here.

- Transcription: a self-hosted faster-whisper worker over WebSocket (the protocol of
  the VPS `courseiq-whisperx` worker: send JSON meta, then the audio bytes; it answers
  status messages and finally `transcript_md` with `[HH:MM:SS] text` lines). When no
  URL is configured the step is `unavailable` with the reason.
- Render: ffmpeg trim + concat of the kept ranges, SRT/VTT written as sidecars.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

StatusCallback = Callable[[str], Awaitable[None]]

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus", ".flac"}


class StepUnavailableError(RuntimeError):
    """A production step cannot run on this host. The message is shown to the editor."""


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return "unknown length"
    seconds = int(round(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


async def probe_duration(path: str | Path) -> float | None:
    probe = ffprobe_path()
    if not probe:
        return None
    proc = await asyncio.create_subprocess_exec(
        probe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except ValueError:
        return None


_LINE_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]\s*(.+)$")


def parse_transcript_md(md: str, duration_s: float | None = None) -> list[dict[str, Any]]:
    """Turn `[HH:MM:SS] text` lines into [{start_s, end_s, text}].

    The worker only reports whole-second starts, so each end is the next start
    (or the file duration for the last line).
    """
    rows: list[tuple[float, str]] = []
    for line in (md or "").splitlines():
        m = _LINE_RE.match(line.strip())
        if m:
            h, mi, s, text = m.groups()
            rows.append((int(h) * 3600 + int(mi) * 60 + int(s), text.strip()))
    out: list[dict[str, Any]] = []
    for i, (start, text) in enumerate(rows):
        if i + 1 < len(rows):
            end = max(start + 0.5, rows[i + 1][0])
        else:
            end = max(start + 1.0, duration_s or start + max(1.0, len(text.split()) * 0.4))
        out.append({"start_s": float(start), "end_s": float(end), "text": text})
    return out


async def transcribe_local(
    path: str | Path,
    *,
    ws_url: str,
    language: str | None,
    duration_s: float | None,
    on_status: StatusCallback,
    timeout_s: float = 3600.0,
) -> list[dict[str, Any]]:
    if not ws_url:
        raise StepUnavailableError(
            "Transcription unavailable: no local transcription worker is configured "
            "(TCE_PRODUCTION_TRANSCRIBE_WS_URL). Paid transcription is intentionally not used."
        )
    import aiohttp

    p = Path(path)
    await on_status(
        f"Connecting to local faster-whisper worker for {fmt_duration(duration_s)} file"
    )
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s)) as session:
            async with session.ws_connect(ws_url, max_msg_size=0) as ws:
                await ws.send_str(
                    json.dumps(
                        {
                            "lesson_id": p.stem,
                            "title": "",
                            "filename": p.name,
                            "video_seconds": duration_s or 0,
                            "language": language or None,
                        }
                    )
                )
                await on_status(
                    f"Sending {p.stat().st_size // 1_000_000} MB to local faster-whisper worker"
                )
                await ws.send_bytes(p.read_bytes())
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = json.loads(msg.data)
                    state = data.get("status")
                    if state == "transcribing":
                        await on_status(
                            f"Transcribing {fmt_duration(duration_s)} file "
                            "with local faster-whisper"
                        )
                    elif state == "complete":
                        return parse_transcript_md(data.get("transcript_md", ""), duration_s)
                    elif state == "error":
                        raise RuntimeError(f"Local transcription failed: {data.get('message')}")
    except aiohttp.ClientError as exc:
        raise StepUnavailableError(
            f"Local transcription worker unreachable: {exc.__class__.__name__}"
        ) from exc
    raise RuntimeError("Local transcription worker closed the connection without a transcript")


async def render_edit(
    src: str | Path,
    keep: list[list[float]],
    out_path: str | Path,
    *,
    on_status: StatusCallback,
) -> Path:
    ff = ffmpeg_path()
    if not ff:
        raise StepUnavailableError("Render unavailable: ffmpeg is not installed on this server")
    if not keep:
        raise RuntimeError("Nothing to render: the edit plan keeps no ranges")
    src = Path(src)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    audio_only = src.suffix.lower() in AUDIO_EXTS
    parts: list[str] = []
    labels: list[str] = []
    for i, (s, e) in enumerate(keep):
        if not audio_only:
            parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]" if audio_only else f"[v{i}][a{i}]")
    n = len(keep)
    if audio_only:
        parts.append("".join(labels) + f"concat=n={n}:v=0:a=1[outa]")
        maps = ["-map", "[outa]"]
    else:
        parts.append("".join(labels) + f"concat=n={n}:v=1:a=1[outv][outa]")
        maps = ["-map", "[outv]", "-map", "[outa]"]
    await on_status(f"Cutting {n} kept range{'s' if n != 1 else ''} with ffmpeg")
    proc = await asyncio.create_subprocess_exec(
        ff,
        "-y",
        "-i",
        str(src),
        "-filter_complex",
        ";".join(parts),
        *maps,
        str(out),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        tail = err.decode(errors="replace").strip().splitlines()[-1:] or ["no output"]
        raise RuntimeError(f"ffmpeg exited {proc.returncode}: {tail[0][:200]}")
    return out
