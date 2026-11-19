"""Read the text visible in one decoded frame of the delivered video."""

from __future__ import annotations

import asyncio
import io
import math
import os
from pathlib import Path
import shutil

from tce.production import media
from tce.production import wordbox
from PIL import Image, ImageChops

_WORKERS = asyncio.Semaphore(2)


def _pill_glyph_mask(png: bytes) -> bytes:
    # Pill pages draw white glyphs even over the highlighted orange word.
    with Image.open(io.BytesIO(png)) as image:
        red, green, blue = image.convert("RGB").split()
        white = ImageChops.darker(red, ImageChops.darker(green, blue))
        mask = white.point(lambda value: 0 if value >= 210 else 255)
        out = io.BytesIO()
        mask.save(out, "PNG")
        return out.getvalue()


async def _run(*argv, data=None, timeout=12):
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate(data), timeout)
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
    return output if proc.returncode == 0 else None


async def read(path: str | Path, edit_s: float, *, language="en", region="caption") -> str | None:
    """Read burned-in words at one edit-clock moment. No external service or persisted frame."""
    ff, ocr = media.ffmpeg_path(), shutil.which("tesseract")
    if not ff or not ocr or not math.isfinite(edit_s) or edit_s < 0:
        return None
    # Reproduce the renderer's two-line band on portrait and landscape frames.
    size = wordbox.FONT_SIZE / wordbox.BASE_W
    above = size * (wordbox.LINE_PITCH_EM / 2 + wordbox.BOX_UP_EM + .3)
    below = size * (wordbox.LINE_PITCH_EM / 2 + wordbox.BOX_DOWN_EM + .3)
    top = f"max(0,ih*{wordbox.CENTER_Y}-iw*{above})"
    bottom = f"min(ih,ih*{wordbox.CENTER_Y}+iw*{below})"
    crop = {"title": "crop=iw:ih*0.35:0:0", "caption": "crop=iw:ih*0.62:0:ih*0.38",
            "pill": f"crop=iw:'{bottom}-{top}':0:'{top}'"}.get(region)
    if not crop:
        return None
    async with _WORKERS:
        try:
            png = await _run(ff, "-hide_banner", "-v", "error", "-threads", "1",
                             "-ss", f"{edit_s:.3f}", "-i", str(path), "-frames:v", "1",
                             "-vf", crop + ",scale=960:-2", "-threads", "1", "-f", "image2pipe",
                             "-c:v", "png", "pipe:1")
            if not png:
                return None
            if region == "pill":
                png = await asyncio.to_thread(_pill_glyph_mask, png)
            output = await _run(ocr, "stdin", "stdout", "-l", "heb+eng" if language == "he" else "eng",
                                "--psm", "6" if region == "pill" else "11", data=png)
            return output.decode("utf-8", errors="replace").strip() if output is not None else None
        except (OSError, asyncio.TimeoutError):
            return None
