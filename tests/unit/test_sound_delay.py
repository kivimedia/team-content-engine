"""Lips that trail the sound (19-Nov): a recording with few pictures a second gets its sound
played a moment later, by an amount set from the recording itself; a recording that keeps up is
rendered exactly as before. A click at a known moment proves the sound really moves, by exactly
that much, in both styles, and that the file stays as long as its picture."""

from __future__ import annotations

import array
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from tce.api.routers import production as prod
from tce.production import media
from tce.production.creatorz import reels
from tce.production.creatorz.engine.creatorz_reel import mix
from tce.settings import settings
from tests.unit.test_creatorz_style import (  # noqa: F401 - `wired` is a fixture
    KEEP,
    WS,
    fake_engine,
    load,
    seed,
    wired,
)

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
SRT = "1\n00:00:00,000 --> 00:00:02,000\nhello\n"


def test_the_delay_follows_how_slow_the_recording_is():
    assert media.sound_delay_for(None) == 0
    assert media.sound_delay_for(33.3) == 0  # 30 pictures a second: untouched
    assert media.sound_delay_for(40.0) == 0  # 25 a second: untouched
    assert media.sound_delay_for(86.0) == 60  # the owner's top video, 12.7 a second
    assert media.sound_delay_for(60.0) == 42  # 16.6 a second
    assert media.sound_delay_for(400.0) == 80  # never more than this


def _clip(path: Path, *, fps: float, seconds: float = 3.0, click_at: float = 1.0) -> Path:
    """A picture at `fps` with one loud click in otherwise silent sound."""
    wav = path.with_suffix(".wav")
    samples = array.array("h", [0] * int(48000 * seconds))
    for i in range(int(48000 * click_at), int(48000 * click_at) + 480):
        samples[i] = 28000 if (i // 24) % 2 else -28000
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(48000)
        f.writeframes(samples.tobytes())
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=s=160x284:r={fps}:d={seconds}",
            "-i",
            str(wav),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(path),
        ],
        check=True,
    )
    return path


def _click_ms(path: Path) -> float:
    """When the click is heard in a file, in ms."""
    raw = subprocess.run(
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
            "48000",
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    samples = array.array("h", raw)
    loud = next(i for i, v in enumerate(samples) if abs(v) > 9000)
    return loud / 48.0


def _seconds(path: Path, stream: str) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            stream,
            "-show_entries",
            "stream=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


@needs_ffmpeg
async def test_a_slow_recording_is_measured_and_a_normal_one_is_left_alone(tmp_path):
    slow = _clip(tmp_path / "slow.mp4", fps=12.5)
    normal = _clip(tmp_path / "normal.mp4", fps=30)
    assert await media.picture_gap_ms(slow) == pytest.approx(80.0, abs=1.0)
    assert await media.picture_gap_ms(normal) == pytest.approx(33.3, abs=1.0)
    assert media.sound_delay_for(await media.picture_gap_ms(slow)) == 56
    assert media.sound_delay_for(await media.picture_gap_ms(normal)) == 0
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video")
    assert await media.picture_gap_ms(junk) is None  # the render then goes out as it always did


@needs_ffmpeg
async def test_the_pill_render_plays_the_sound_exactly_that_much_later(tmp_path):
    src = _clip(tmp_path / "walk.mp4", fps=12.5)

    async def status(_text):
        return None

    made: dict = {}
    plain = await media.render_edit(
        src,
        [[0.0, 3.0]],
        tmp_path / "plain.mp4",
        on_status=status,
        srt_text=SRT,
        loudness=False,
    )
    late = await media.render_edit(
        src,
        [[0.0, 3.0]],
        tmp_path / "late.mp4",
        on_status=status,
        srt_text=SRT,
        loudness=False,
        sound_delay_ms=60,
        report=made,
    )
    assert _click_ms(late) - _click_ms(plain) == pytest.approx(60.0, abs=2.0)
    assert made["sound_delay_ms"] == 60
    # the file is as long as it was: the sound does not run on past the picture
    assert _seconds(late, "a:0") == pytest.approx(_seconds(plain, "a:0"), abs=0.03)
    assert _seconds(late, "v:0") == pytest.approx(_seconds(plain, "v:0"), abs=0.001)


@needs_ffmpeg
def test_the_creatorz_engine_s_last_step_plays_the_sound_later_and_keeps_the_length(tmp_path):
    src = _clip(tmp_path / "walk.mp4", fps=30)
    overlay, sound = tmp_path / "overlay.mp4", tmp_path / "mix.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-c:v", "copy", str(overlay)],
        check=True,
    )
    shutil.copy(src.with_suffix(".wav"), sound)
    assert "-af" not in mix.final_cmd("o", "m", "out", 0) and "-af" not in mix.final_cmd(
        "o", "m", "out", None
    )
    plain, late = tmp_path / "plain.mp4", tmp_path / "late.mp4"
    subprocess.run(mix.final_cmd(str(overlay), str(sound), str(plain)), check=True)
    subprocess.run(mix.final_cmd(str(overlay), str(sound), str(late), 60), check=True)
    assert _click_ms(late) - _click_ms(plain) == pytest.approx(60.0, abs=2.0)
    assert _seconds(late, "v:0") == pytest.approx(_seconds(plain, "v:0"), abs=0.001)
    assert _seconds(late, "a:0") <= _seconds(late, "v:0") + 0.03


def test_the_engine_plan_carries_the_delay_only_when_there_is_one(tmp_path):
    base = dict(
        src=tmp_path / "raw.mp4",
        words_path=tmp_path / "w.json",
        keep=KEEP,
        lang="en",
        work=tmp_path,
        moments=[],
        punchline=None,
        bed=None,
    )
    assert "sound_delay_ms" not in reels.reel_plan(**base)
    assert "sound_delay_ms" not in reels.reel_plan(**base, sound_delay_ms=0)
    assert reels.reel_plan(**base, sound_delay_ms=60)["sound_delay_ms"] == 60


async def test_a_slow_recording_s_pill_render_is_told_the_delay_and_the_file_says_so(
    wired, tmp_path, monkeypatch
):
    async def slow(_src):
        return 86.0

    monkeypatch.setattr(prod.media, "picture_gap_ms", slow)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    uid, attempt = await seed(wired["sm"], src)
    await prod._run_render(uid, WS, attempt, "cut")
    assert wired["calls"]["pill"][0]["kw"]["sound_delay_ms"] == 60
    row = await load(wired["sm"], uid)
    assert prod._read_render_sidecar(row.edited_path)["sound_delay_ms"] == 60


async def test_a_slow_recording_s_creatorz_render_is_told_the_delay(wired, tmp_path, monkeypatch):
    async def slow(_src):
        return 86.0

    monkeypatch.setattr(prod.media, "picture_gap_ms", slow)
    fake_engine(monkeypatch, wired)
    monkeypatch.setattr(settings, "production_creatorz_workspaces", str(WS))
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    uid, attempt = await seed(wired["sm"], src, overrides={"style": "creatorz"})
    await prod._run_render(uid, WS, attempt, "cut")
    assert wired["calls"]["reel"][0]["sound_delay_ms"] == 60
    row = await load(wired["sm"], uid)
    assert prod._read_render_sidecar(row.edited_path)["sound_delay_ms"] == 60


async def test_a_recording_that_keeps_up_renders_with_no_new_argument_at_all(
    wired, tmp_path, monkeypatch
):
    async def normal(_src):
        return 33.3

    monkeypatch.setattr(prod.media, "picture_gap_ms", normal)
    fake_engine(monkeypatch, wired)
    monkeypatch.setattr(settings, "production_creatorz_workspaces", str(WS))
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"raw")
    uid, attempt = await seed(wired["sm"], src)
    await prod._run_render(uid, WS, attempt, "cut")
    assert "sound_delay_ms" not in wired["calls"]["pill"][0]["kw"]
    assert "sound_delay_ms" not in prod._read_render_sidecar(
        (await load(wired["sm"], uid)).edited_path
    )
    uid2, attempt2 = await seed(wired["sm"], src, overrides={"style": "creatorz"})
    await prod._run_render(uid2, WS, attempt2, "cut")
    assert "sound_delay_ms" not in wired["calls"]["reel"][0]
