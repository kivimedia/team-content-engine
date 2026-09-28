"""Local, free media steps: probe, transcribe, cut. No metered API is reachable from here.

- Transcription: a configured self-hosted faster-whisper worker over WebSocket. Send
  JSON meta, then media bytes. A worker may return precise `words` or the legacy
  `transcript_md` whole-second format. Precision is stored on every timing row.
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


async def probe_media(path: str | Path) -> dict[str, Any]:
    """Return container, duration and audible/video stream proof from ffprobe."""
    exe = ffprobe_path()
    if not exe:
        raise StepUnavailableError("ffprobe is not installed")
    proc = await asyncio.create_subprocess_exec(
        exe,
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _err = await proc.communicate()
    if proc.returncode != 0:
        raise ValueError("ffprobe could not read the assembled recording")
    data = json.loads(out.decode("utf-8", "replace") or "{}")
    streams = data.get("streams") or []
    duration = (data.get("format") or {}).get("duration")
    return {
        "duration_s": float(duration) if duration not in (None, "N/A") else None,
        "has_audio": any(item.get("codec_type") == "audio" for item in streams),
        "has_video": any(item.get("codec_type") == "video" for item in streams),
        "format_name": (data.get("format") or {}).get("format_name"),
        "streams": [
            {
                "type": item.get("codec_type"),
                "codec": item.get("codec_name"),
                "width": item.get("width"),
                "height": item.get("height"),
            }
            for item in streams
        ],
    }
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


def parse_precise_words(words: Any) -> list[dict[str, Any]]:
    if not isinstance(words, list):
        return []
    out: list[dict[str, Any]] = []
    for item in words:
        if not isinstance(item, dict):
            return []
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            return []
        text = str(item.get("word") or item.get("text") or "").strip()
        if not text or start < 0 or end <= start:
            return []
        out.append({"start_s": start, "end_s": end, "text": text, "precision": "word"})
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
                        precise = parse_precise_words(data.get("words"))
                        if precise:
                            return precise
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


FPS = 30  # every edit is cut and encoded on this frame grid
SAMPLE_RATE = 48000
FADE_S = 0.006  # a click-proof edge on every cut
# 28-Sep: the old edit was 7.8 Mbps; his phone stalled at 1:04 when the first 61.9 MB
# ran out, and his later requests ran at 1.5-2.5 Mbps. The master stays sharp for the
# platforms (about 5-6 Mbps); the preview (about 1.5 Mbps) plays on a walking signal.
MASTER_VIDEO = ["-c:v", "libx264", "-preset", "fast", "-crf", "21", "-maxrate", "6M",
                "-bufsize", "12M", "-g", str(2 * FPS), "-pix_fmt", "yuv420p"]
PREVIEW_VIDEO = ["-vf", "scale='min(720,iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
                 "-maxrate", "1400k", "-bufsize", "2800k", "-g", str(2 * FPS), "-pix_fmt", "yuv420p"]


def preview_path(edited: str | Path) -> Path:
    """The light copy the Library player streams, beside the edit."""
    p = Path(edited)
    return p.with_name(f"{p.stem}-preview{p.suffix}")


async def render_edit(
    src: str | Path,
    keep: list[list[float]],
    out_path: str | Path,
    *,
    on_status: StatusCallback,
    ass_text: str | None = None,
    srt_text: str | None = None,
    caption_band: dict[str, Any] | None = None,
    make_preview: bool = False,
) -> Path:
    """Cut the kept ranges into `out_path` (MP4 when captions are given).

    Video is put on a 30 fps grid first and every range is trimmed by frame number,
    audio by sample number, so each piece's picture and sound are exactly as long as
    each other and the joins never drift or pad silence. Each audio piece fades in and
    out over 6 ms, so a cut never clicks.

    `caption_band` ({"list": ffconcat, "y": top}) is his word-box captions, laid over
    once; `ass_text` is the plain fallback burned in; `srt_text` is muxed as a soft
    subtitle track. The output is written to a temporary name and only renamed into
    place when ffmpeg succeeds, so a crash or restart never leaves a half file under
    the real name.
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
    captioned = ass_text is not None or srt_text is not None or bool(caption_band)
    frames = [(round(s * FPS), round(e * FPS)) for s, e in keep]
    frames = [(a, b) for a, b in frames if b > a]
    if not frames:
        raise RuntimeError("Nothing to render: every kept range is shorter than a frame")
    n = len(frames)
    total = sum(b - a for a, b in frames) / FPS
    per_frame = SAMPLE_RATE // FPS
    parts: list[str] = []
    labels: list[str] = []
    if not audio_only:
        parts.append(
            f"[0:v]fps={FPS}:start_time=0,split={n}" + "".join(f"[vs{i}]" for i in range(n))
        )
    parts.append(
        f"[0:a]aresample={SAMPLE_RATE}:first_pts=0,asplit={n}" + "".join(f"[as{i}]" for i in range(n))
    )
    for i, (a, b) in enumerate(frames):
        dur = (b - a) / FPS
        fade = min(FADE_S, dur / 4)
        if not audio_only:
            parts.append(f"[vs{i}]trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS[v{i}]")
        parts.append(
            f"[as{i}]atrim=start_sample={a * per_frame}:end_sample={b * per_frame},"
            f"asetpts=PTS-STARTPTS,afade=t=in:d={fade:.4f},"
            f"afade=t=out:st={dur - fade:.4f}:d={fade:.4f}[a{i}]"
        )
        labels.append(f"[a{i}]" if audio_only else f"[v{i}][a{i}]")
    inputs = ["-i", str(src)]
    if audio_only:
        parts.append("".join(labels) + f"concat=n={n}:v=0:a=1[outa]")
        video = None
        if captioned:
            w, h = AUDIO_ONLY_CANVAS
            inputs += ["-f", "lavfi", "-i", f"color=c=0x101418:s={w}x{h}:r={FPS}:d={total:.3f}"]
            video = "[1:v]"
    else:
        parts.append("".join(labels) + f"concat=n={n}:v=1:a=1[outv][outa]")
        video = "[outv]"

    # Its own temp names per render: two renders of one video must not share files.
    tmp_tag = f".{out.stem}.rendering-{os.urandom(4).hex()}"
    burn = out.parent / f"{tmp_tag}.ass"
    soft = out.parent / f"{tmp_tag}.srt"
    part = out.parent / f"{tmp_tag}{out.suffix}"
    graph = out.parent / f"{tmp_tag}.graph"
    try:
        maps: list[str] = []
        if video is not None and ass_text is not None and not caption_band:
            burn.write_text(ass_text, encoding="utf-8")
            # Relative name + cwd: no drive-letter colons to escape inside the filtergraph.
            parts.append(f"{video}ass=filename={burn.name}[capv]")
            video = "[capv]"
        if video is not None and caption_band:
            index = inputs.count("-i")
            inputs += ["-f", "concat", "-safe", "0", "-i", str(Path(caption_band["list"]).resolve())]
            # shortest=1: the caption stream is padded past the end, and without it the
            # picture ran on, frozen and silent, after the sound stopped (review, 28-Sep).
            parts.append(
                f"[{index}:v]format=rgba[band];"
                f"{video}[band]overlay=x=0:y={int(caption_band['y'])}:format=auto:shortest=1[capv]"
            )
            video = "[capv]"
        if video is not None:
            maps += ["-map", video]
        maps += ["-map", "[outa]"]
        codecs: list[str] = []
        if captioned:
            codecs += MASTER_VIDEO + ["-c:a", "aac", "-b:a", "160k", "-ar", str(SAMPLE_RATE)]
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
        # A graph with a hundred cuts is longer than a Windows command line allows.
        graph.write_text(";\n".join(parts), encoding="utf-8")
        await _ffmpeg(
            ff, ["-y", *inputs, "-filter_complex_script", graph.name, *maps, *codecs, str(part)],
            cwd=out.parent,
        )
        os.replace(part, out)
        if make_preview and not audio_only:
            await on_status("Making the light copy your phone plays")
            light = preview_path(out)
            light_part = out.parent / f"{tmp_tag}-preview{out.suffix}"
            try:
                await _ffmpeg(
                    ff,
                    ["-y", "-i", str(out), "-map", "0:v:0", "-map", "0:a:0", *PREVIEW_VIDEO,
                     "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(light_part)],
                    cwd=out.parent,
                )
                os.replace(light_part, light)
            except RuntimeError as exc:
                # The edit itself is done; without a fresh light copy the player streams it.
                await on_status(f"Edit ready; the light copy for your phone failed ({exc})")
            finally:
                light_part.unlink(missing_ok=True)
    finally:
        for f in (burn, soft, part, graph):
            f.unlink(missing_ok=True)
    return out


async def _ffmpeg(ff: str, args: list[str], *, cwd: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        ff, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(cwd)
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        tail = err.decode(errors="replace").strip().splitlines()[-1:] or ["no output"]
        raise RuntimeError(f"ffmpeg exited {proc.returncode}: {tail[0][:200]}")
