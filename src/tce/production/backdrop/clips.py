"""ffmpeg work: cut one scene out of the engine's base picture, fit the redrawn scene back to
the exact same frames, and put the base picture together again.

The base picture (``base.mp4``) is what the engine's later stages read: 30 fps, no sound, no
B-frames, a keyframe a second. Everything written here uses the same encoder settings, so the
pieces join by stream copy and the frame count never moves.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# The engine's own settings for the base picture (creatorz_reel/cut.py, video_segment_cmd).
_X264 = [
    "-c:v",
    "libx264",
    "-crf",
    "12",
    "-preset",
    "veryfast",
    "-bf",
    "0",
    "-threads",
    "4",
    "-pix_fmt",
    "yuv420p",
    "-an",
]


class ClipError(RuntimeError):
    pass


def _run(cmd: list[str], *, binary: bool = False) -> bytes | str:
    done = subprocess.run(cmd, capture_output=True, check=False)  # noqa: S603
    if done.returncode != 0:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no message"]
        raise ClipError(f"{Path(cmd[0]).name} failed: {tail[0][:200]}")
    return done.stdout if binary else done.stdout.decode("utf-8", "replace")


def info(path: str | Path) -> dict[str, float]:
    """width, height, frames (counted, not read from the header) and seconds of the picture."""
    out = str(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-count_packets",
                "-show_entries",
                "stream=width,height,nb_read_packets:format=duration",
                "-of",
                "default=nw=1",
                str(path),
            ]
        )
    )
    found = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    try:
        return {
            "width": int(found["width"]),
            "height": int(found["height"]),
            "frames": int(found["nb_read_packets"]),
            "seconds": float(found["duration"]),
        }
    except (KeyError, ValueError):
        raise ClipError(f"could not read {Path(path).name}") from None


def has_sound(path: str | Path) -> bool:
    out = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    return bool(str(out).strip())


def frame_times(path: str | Path) -> list[float]:
    """When each frame of the picture is shown, in order. The base picture is joined from many
    short pieces and its clock runs a little fast (14 ms early by the end of a 74 s cut, 19-Nov),
    so frame n is NOT at n / fps: every frame is found by its number through this list."""
    out = str(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "packet=pts_time",
                "-of",
                "csv=p=0",
                str(path),
            ]
        )
    )
    try:
        return sorted(
            float(x) for x in (line.strip().rstrip(",") for line in out.splitlines()) if x
        )
    except ValueError:
        raise ClipError(f"could not read the frame times of {Path(path).name}") from None


def _seek(times: list[float], frame: int) -> str:
    """A seek that lands exactly on frame ``frame``: halfway between the frame before it and
    the frame itself, by their real times."""
    if frame <= 0:
        return "0"
    if frame >= len(times):
        raise ClipError(f"frame {frame} is past the end of the picture ({len(times)} frames)")
    return f"{(times[frame - 1] + times[frame]) / 2:.6f}"


def _even(fps: int) -> str:
    # The frames that come out are numbered again on an even clock, so none is dropped or doubled.
    return f"setpts=N/({fps}*TB)"


def scene_clip(
    base: str | Path,
    voice: str | Path,
    a: int,
    b: int,
    fps: int,
    out: str | Path,
    times: list[float],
) -> None:
    """Frames a..b of the base picture with the voice that plays under them: what the model gets.
    The voice has no drift (it is cut by the shots' own lengths), so it is taken by time."""
    _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            _seek(times, a),
            "-i",
            str(base),
            "-ss",
            f"{a / fps:.6f}",
            "-t",
            f"{(b - a) / fps:.6f}",
            "-i",
            str(voice),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            _even(fps),
            "-frames:v",
            str(b - a),
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-crf",
            "16",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )


def real_piece(
    base: str | Path, a: int, b: int, fps: int, out: str | Path, times: list[float]
) -> None:
    """Frames a..b of the base picture as their own piece, untouched in content."""
    _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            _seek(times, a),
            "-i",
            str(base),
            "-map",
            "0:v:0",
            "-vf",
            _even(fps),
            "-frames:v",
            str(b - a),
            "-r",
            str(fps),
            "-g",
            str(fps),
            *_X264,
            str(out),
        ]
    )


def conform(src: str | Path, frames: int, fps: int, size: tuple[int, int], out: str | Path) -> None:
    """The model's video as exactly ``frames`` frames at the base picture's rate and size. A
    result a few frames short holds its last frame; a longer one loses its tail."""
    w, h = size
    _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-vf",
            f"fps={fps},tpad=stop_mode=clone:stop_duration=2,scale={w}:{h}:flags=lanczos,setsar=1,format=yuv420p",
            "-frames:v",
            str(frames),
            "-r",
            str(fps),
            "-g",
            str(fps),
            *_X264,
            str(out),
        ]
    )


def join(pieces: list[str | Path], out: str | Path) -> None:
    """Pieces back to back by stream copy (they share one encoder setup)."""
    out = Path(out)
    listing = out.with_suffix(".txt")
    listing.write_text(
        "".join(f"file '{Path(p).resolve().as_posix()}'\n" for p in pieces), encoding="utf-8"
    )
    try:
        _run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c",
                "copy",
                str(out),
            ]
        )
    finally:
        listing.unlink(missing_ok=True)


def rebuild(
    base: str | Path, swaps: list[tuple[int, int, str | Path]], fps: int, work: str | Path
) -> Path:
    """The base picture with the frame ranges in ``swaps`` (a, b, clip of exactly b-a frames)
    replaced. Returns the new file; the caller swaps it in. Raises when the count moves by even
    one frame, because every later stage addresses the picture by frame number."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    times = frame_times(base)
    total = len(times)
    pieces: list[Path] = []

    def real(a: int, b: int, piece: Path) -> None:
        real_piece(base, a, b, fps, piece, times)
        if int(info(piece)["frames"]) != b - a:
            raise ClipError(f"a real stretch came out with the wrong number of frames ({a}-{b})")
        pieces.append(piece)

    at = 0
    for n, (a, b, clip) in enumerate(sorted(swaps)):
        if a < at or b <= a or b > total:
            raise ClipError("the scenes to replace overlap or run past the end")
        if a > at:
            real(at, a, work / f"real{n:03d}.mkv")
        if int(info(clip)["frames"]) != b - a:
            raise ClipError("a redrawn scene does not have the frames of the scene it replaces")
        pieces.append(Path(clip))
        at = b
    if at < total:
        real(at, total, work / "real-end.mkv")
    out = work / "base.new.mp4"
    join(pieces, out)
    if int(info(out)["frames"]) != total:
        raise ClipError(
            f"the rebuilt picture has {int(info(out)['frames'])} frames, the cut has {total}"
        )
    return out


def sound(path: str | Path, rate: int = 8000):
    """The first sound track as mono float samples (numpy)."""
    import numpy as np

    raw = _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-f",
            "f32le",
            "-",
        ],
        binary=True,
    )
    return np.frombuffer(raw, dtype=np.float32)


def jpeg(path: str | Path, at_s: float, width: int = 720) -> bytes:
    """One frame as a JPEG."""
    data = _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{max(0.0, at_s):.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            "-f",
            "image2pipe",
            "-c:v",
            "mjpeg",
            "-q:v",
            "4",
            "-",
        ],
        binary=True,
    )
    if not data:
        raise ClipError(f"no frame at {at_s:.2f} s of {Path(path).name}")
    return bytes(data)


def replace(new: str | Path, target: str | Path, keep_as: str | Path | None = None) -> None:
    """Swap ``new`` in for ``target`` in one step, so a reader finds the old picture or the new
    one and never a missing file. The old one stays readable under ``keep_as``."""
    if keep_as:
        Path(keep_as).unlink(missing_ok=True)
        try:
            os.link(target, keep_as)
        except OSError:
            shutil.copy2(target, keep_as)
    os.replace(new, target)
