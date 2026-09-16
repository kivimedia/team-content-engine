"""Local, free media steps: probe, transcribe, cut. No metered API is reachable from here.

- Transcription: a self-hosted faster-whisper worker over WebSocket (the protocol of
  the VPS `courseiq-whisperx` worker: send JSON meta, then the audio bytes; it answers
  status messages and finally `transcript_md` with `[HH:MM:SS] text` lines). When no
  URL is configured the step is `unavailable` with the reason.
- Render: ffmpeg trim + concat of the kept ranges into an H.264 MP4 with the captions
  burned in (readable anywhere) and also carried as a soft mov_text track. The caller
  keeps SRT/VTT sidecars. An audio-only upload gets a plain dark background.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

StatusCallback = Callable[[str], Awaitable[None]]

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus", ".flac"}
AUDIO_ONLY_CANVAS = (1280, 720)


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
    """Turn `[HH:MM:SS] text` lines into [{start_s, end_s, text, precision}].

    The worker floors each segment start to a whole second and reports no end, so each
    end is the next start (or the file duration for the last line). Every row says so,
    and the edit planner treats its cut edges as uncertain.
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
        out.append(
            {
                "start_s": float(start),
                "end_s": float(end),
                "text": text,
                "precision": "whole_second_start_inferred_end",
            }
        )
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


async def probe_video_size(path: str | Path) -> tuple[int, int] | None:
    probe = ffprobe_path()
    if not probe:
        return None
    proc = await asyncio.create_subprocess_exec(
        probe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        w, h = out.decode().strip().splitlines()[0].split(",")[:2]
        return int(w), int(h)
    except (ValueError, IndexError):
        return None


async def render_edit(
    src: str | Path,
    keep: list[list[float]],
    out_path: str | Path,
    *,
    on_status: StatusCallback,
    ass_text: str | None = None,
    srt_text: str | None = None,
) -> Path:
    """Cut the kept ranges into `out_path` (MP4 when captions are given).

    `ass_text` is burned into the picture; `srt_text` is muxed as a soft subtitle
    track. The output is written to a temporary name and only renamed into place when
    ffmpeg succeeds, so a crash or restart never leaves a half file under the real name.
    """
    ff = ffmpeg_path()
    if not ff:
        raise StepUnavailableError("Render unavailable: ffmpeg is not installed on this server")
    if not keep:
        raise RuntimeError("Nothing to render: the edit plan keeps no ranges")
    src = Path(src).resolve()
    out = Path(out_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    audio_only = src.suffix.lower() in AUDIO_EXTS
    captioned = ass_text is not None or srt_text is not None
    parts: list[str] = []
    labels: list[str] = []
    n = len(keep)
    total = sum(e - s for s, e in keep)
    for i, (s, e) in enumerate(keep):
        if not audio_only:
            parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]" if audio_only else f"[v{i}][a{i}]")
    inputs = ["-i", str(src)]
    if audio_only:
        parts.append("".join(labels) + f"concat=n={n}:v=0:a=1[outa]")
        video = None
        if captioned:
            w, h = AUDIO_ONLY_CANVAS
            inputs += ["-f", "lavfi", "-i", f"color=c=0x101418:s={w}x{h}:r=25:d={total:.3f}"]
            video = "[1:v]"
    else:
        parts.append("".join(labels) + f"concat=n={n}:v=1:a=1[outv][outa]")
        video = "[outv]"

    tmp_tag = f".{out.stem}.rendering"
    burn = out.parent / f"{tmp_tag}.ass"
    soft = out.parent / f"{tmp_tag}.srt"
    part = out.parent / f"{tmp_tag}{out.suffix}"
    try:
        maps: list[str] = []
        if video is not None and ass_text is not None:
            burn.write_text(ass_text, encoding="utf-8")
            # Relative name + cwd: no drive-letter colons to escape inside the filtergraph.
            parts.append(f"{video}ass=filename={burn.name}[capv]")
            video = "[capv]"
        if video is not None:
            maps += ["-map", video]
        maps += ["-map", "[outa]"]
        codecs: list[str] = []
        if captioned:
            codecs += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
            codecs += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k"]
            codecs += ["-movflags", "+faststart"]
        if srt_text is not None and video is not None:
            soft.write_text(srt_text, encoding="utf-8")
            sub_index = inputs.count("-i")
            inputs += ["-i", soft.name]
            maps += ["-map", f"{sub_index}:s:0"]
            codecs += ["-c:s", "mov_text", "-metadata:s:s:0", "title=Captions"]
        await on_status(
            f"Cutting {n} kept range{'s' if n != 1 else ''} with ffmpeg"
            + (" and burning in captions" if captioned else "")
        )
        proc = await asyncio.create_subprocess_exec(
            ff,
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(parts),
            *maps,
            *codecs,
            str(part),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(out.parent),
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            tail = err.decode(errors="replace").strip().splitlines()[-1:] or ["no output"]
            raise RuntimeError(f"ffmpeg exited {proc.returncode}: {tail[0][:200]}")
        os.replace(part, out)
    finally:
        for f in (burn, soft, part):
            f.unlink(missing_ok=True)
    return out
