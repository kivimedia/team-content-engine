"""Ziv's walking-video captions: word-timed phrases in real pills, burned in.

The look is the one his walking videos already carry (VideoJobs
2026-04-26-walking-topics-edit, rebuild_captions.py): Outfit Black 60px on a
1080x1920 frame, the first line in an orange pill (#FCA529), a second line in a
cyan pill (#40DCE0) under it, near-black text, lower third (bottom pill 288px
above the frame bottom), at most 4 words a line, filler words dropped, never
longer than 4 s on screen, never across a cut.

libass cannot draw a rounded pill, so every line is its own PNG (Pillow) laid
over the video with ffmpeg `overlay ... enable=between(t,a,b)`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tce.production.retakes import map_to_edit

FONT_PATH = Path(__file__).resolve().parent / "fonts" / "Outfit-Black.ttf"

ORANGE = (252, 165, 41, 255)  # #FCA529 - first line
CYAN = (64, 220, 224, 255)  # #40DCE0 - second line
TEXT = (10, 10, 10, 255)  # #0A0A0A

# At a 1080-wide frame; everything scales with the frame width.
BASE_W = 1080
FONT_SIZE = 60
PAD_X = 28
PAD_Y = 14
PILL_GAP = 14
BOTTOM_MARGIN = 288
MAX_PILL_FRACTION = 0.86
MIN_FONT_FRACTION = 0.6

WORDS_PER_LINE = 4
MAX_WORDS = 2 * WORDS_PER_LINE
PHRASE_MAX_S = 4.0
PHRASE_MIN_S = 0.5
PHRASE_GAP_S = 0.05
LINGER_S = 0.4
SILENCE_BREAK_S = 0.6

FILLERS = {"um", "uh", "ah", "er", "hmm", "mm", "umm", "uhh", "ehh", "uhm"}
_BARE = re.compile(r"[^\w']+")
# Outfit carries Latin only; anything else keeps the plain libass captions.
_LATIN = re.compile(r"^[\x00-ɏ‘-‟…]*$")


def usable(words: list[dict[str, Any]]) -> bool:
    """Word timings exist and every word can be drawn in Outfit."""
    return bool(words) and all(
        w.get("precision") == "word" and _LATIN.match(str(w.get("text") or "")) for w in words
    )


def _range_of(t: float, keep: list[list[float]]) -> int | None:
    for index, (s, e) in enumerate(keep):
        if s <= t <= e:
            return index
    return None


def phrases(words: list[dict[str, Any]], keep: list[list[float]]) -> list[dict[str, Any]]:
    """Group kept words into on-screen phrases, timed on the EDITED timeline.

    A phrase never bridges a cut: it closes at every kept-range boundary, at a
    silence, at the end of a sentence, and at 8 words.
    """
    kept: list[dict[str, Any]] = []
    for w in words:
        s, e = float(w["start_s"]), float(w["end_s"])
        index = _range_of((s + e) / 2, keep)
        if index is None:
            continue
        text = str(w["text"]).strip()
        if not text or _BARE.sub("", text).lower() in FILLERS:
            continue
        rs, re_ = keep[index]
        start = map_to_edit(max(s, rs), keep)
        end = map_to_edit(min(e, re_), keep)
        range_end = map_to_edit(re_, keep)
        if start is None or end is None or range_end is None:
            continue
        kept.append(
            {"text": text, "start": start, "end": end, "range": index, "range_end": range_end}
        )

    groups: list[list[dict[str, Any]]] = []
    for w in kept:
        cur = groups[-1] if groups else None
        if (
            cur is None
            or w["range"] != cur[-1]["range"]
            or w["start"] - cur[-1]["end"] > SILENCE_BREAK_S
            or len(cur) >= MAX_WORDS
            or (len(cur) >= 3 and cur[-1]["text"][-1:] in ".?!")
        ):
            groups.append([w])
        else:
            cur.append(w)

    out: list[dict[str, Any]] = []
    for g in groups:
        top, bottom = _split(g)
        start = g[0]["start"]
        end = min(g[-1]["end"] + LINGER_S, start + PHRASE_MAX_S, g[-1]["range_end"])
        end = max(end, min(start + PHRASE_MIN_S, g[-1]["range_end"]))
        out.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "top": " ".join(w["text"] for w in top),
                "bottom": " ".join(w["text"] for w in bottom),
            }
        )
    for a, b in zip(out, out[1:], strict=False):
        if a["end"] > b["start"] - PHRASE_GAP_S:
            a["end"] = round(max(a["start"] + 0.2, b["start"] - PHRASE_GAP_S), 3)
    return [p for p in out if p["end"] > p["start"]]


def _split(group: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    n = len(group)
    if n <= WORDS_PER_LINE:
        return group, []
    # A comma is the natural break, when it leaves two or more words each side.
    for i in range(2, n - 1):
        if group[i - 1]["text"].endswith(",") and n - i <= WORDS_PER_LINE and i <= WORDS_PER_LINE:
            return group[:i], group[i:]
    cut = (n + 1) // 2
    return group[:cut], group[cut:]


def _pill(text: str, bg: tuple[int, int, int, int], frame_w: int, path: Path) -> tuple[int, int]:
    from PIL import Image, ImageDraw, ImageFont

    scale = frame_w / BASE_W
    pad_x, pad_y = round(PAD_X * scale), round(PAD_Y * scale)
    max_w = int(frame_w * MAX_PILL_FRACTION)
    size = round(FONT_SIZE * scale)
    # Never clip: a line too wide for the pill gets a smaller font, not a cut edge.
    while True:
        font = ImageFont.truetype(str(FONT_PATH), size)
        left, top, right, bottom = font.getbbox(text)
        if right - left + 2 * pad_x <= max_w or size <= FONT_SIZE * scale * MIN_FONT_FRACTION:
            break
        size -= 2
    ascent, descent = font.getmetrics()
    w = min(max_w, right - left + 2 * pad_x)
    h = ascent + descent + 2 * pad_y
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=bg)
    draw.text((w / 2, h / 2), text, font=font, fill=TEXT, anchor="mm")
    image.save(path)
    return w, h


def overlays(
    items: list[dict[str, Any]], frame_w: int, frame_h: int, folder: Path
) -> list[dict[str, Any]]:
    """One PNG per pill line, with where and when it shows."""
    folder.mkdir(parents=True, exist_ok=True)
    scale = frame_w / BASE_W
    bottom_edge = frame_h - round(BOTTOM_MARGIN * scale)
    gap = round(PILL_GAP * scale)
    out: list[dict[str, Any]] = []
    for index, p in enumerate(items):
        top_path = folder / f"pill-{index:04d}-a.png"
        tw, th = _pill(p["top"], ORANGE, frame_w, top_path)
        if p["bottom"]:
            bottom_path = folder / f"pill-{index:04d}-b.png"
            bw, bh = _pill(p["bottom"], CYAN, frame_w, bottom_path)
            by = bottom_edge - bh
            ty = by - gap - th
            out.append(_place(bottom_path, frame_w, bw, by, p))
        else:
            ty = bottom_edge - th
        out.append(_place(top_path, frame_w, tw, ty, p))
    return out


def _place(path: Path, frame_w: int, w: int, y: int, p: dict[str, Any]) -> dict[str, Any]:
    return {"path": path, "x": (frame_w - w) // 2, "y": y, "start": p["start"], "end": p["end"]}
