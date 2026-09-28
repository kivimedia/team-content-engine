"""Captions in TJ Robertson's look: the word being said sits on an orange box (28-Sep).

"the pills are not pretty (i want the same caption animation and style that he
uses)". Measured frame by frame on three of TJ's reels (1080x1920, 30 fps):

- Roboto Bold (OFL), 116 px on a 1080-wide frame, white, a soft shadow under the
  letters, no outline. His "jump through" is 701 px wide; ours is 702. His shadow is
  fainter, but he walks past dark shirts and shade; Ziv walks in bright sun over pale
  gravel, where white needs a little more under it to stay readable.
- A page is at most two lines of at most 12 characters, filled greedily ("We had to"
  / "jump through", "see a good" / "benchmark", then "for" / "measuring"). A sentence
  end starts a new page.
- The block is centred on a baseline at 76.2 % of the height; two lines sit 1.2 em
  apart around it.
- The word being said sits on an orange (#FF762D) rounded box: its advance width plus
  17 px each side, from 0.87 em above the baseline to 0.29 em below.
- The box snaps from word to word - no pop, no slide - is off during a pause inside a
  page, stays on the last word until the next page, and the page leaves when he stops.

Drawing: every state (a page with one word boxed, or plain) is one PNG of the caption
band, and an ffconcat list says how long each shows. ffmpeg lays that one stream over
the video with a single overlay, however many words there are.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FONT_PATH = Path(__file__).resolve().parent / "fonts" / "Roboto-Bold.ttf"

WHITE = (255, 255, 255, 255)
ORANGE = (255, 118, 45, 255)  # #FF762D, sampled from his reels
SHADOW = (0, 0, 0, 150)

BASE_W = 1080
FONT_SIZE = 116  # at a 1080-wide frame
LINE_PITCH_EM = 1.2
CENTER_Y = 0.762  # baseline of a one-line page, share of the frame height
BOX_PAD_EM = 17 / 116
BOX_UP_EM = 0.87
BOX_DOWN_EM = 0.29
BOX_RADIUS_EM = 0.09
SHADOW_DY_EM = 0.03
SHADOW_BLUR_EM = 0.05
MAX_LINE_CHARS = 12
MAX_LINE_WIDTH = 0.92  # share of the frame width; a longer line shrinks the page

PAGE_GAP_S = 0.6  # a pause this long ends the page
LINGER_S = 0.35  # the page stays this long after its last word when he pauses
HOLD_GAP_S = 0.2  # the box stays on through a gap shorter than this

FILLERS = {"um", "uh", "ah", "er", "erm", "hmm", "mm", "umm", "uhh", "ehh", "uhm"}
_BARE = re.compile(r"[^\w']+")
# The bundled Roboto is the Latin-1 build (review, 28-Sep: ā, č, ł drew as empty
# boxes); a word it cannot draw keeps the plain libass captions.
_LATIN = re.compile(r"^[\x00-\xff\u2018-\u201f\u2026]*$")


def usable(words: list[dict[str, Any]]) -> bool:
    """Every caption word has its own timing and can be drawn in Roboto."""
    return bool(words) and all(_LATIN.match(str(w.get("text") or "")) for w in words)


@dataclass
class Page:
    start: float
    end: float
    lines: list[list[dict[str, Any]]] = field(default_factory=list)

    @property
    def words(self) -> list[dict[str, Any]]:
        return [w for line in self.lines for w in line]


def _ends_sentence(text: str) -> bool:
    return str(text).rstrip().rstrip("\"')]").endswith((".", "?", "!"))


def pages(words: list[dict[str, Any]]) -> list[Page]:
    """Group words already on the EDITED timeline ({text, start, end}) into pages."""
    spoken = [
        w for w in words
        if str(w.get("text") or "").strip() and _BARE.sub("", str(w["text"])).lower() not in FILLERS
    ]
    out: list[Page] = []
    cur: Page | None = None
    for w in spoken:
        text = str(w["text"]).strip()
        item = {"text": text, "start": float(w["start"]), "end": float(w["end"])}
        if cur is not None:
            last = cur.lines[-1][-1]
            if item["start"] - last["end"] > PAGE_GAP_S or _ends_sentence(last["text"]):
                out.append(cur)
                cur = None
        if cur is None:
            cur = Page(item["start"], item["end"], [[item]])
            continue
        line = cur.lines[-1]
        if len(" ".join([x["text"] for x in line] + [text])) <= MAX_LINE_CHARS:
            line.append(item)
        elif len(cur.lines) < 2:
            cur.lines.append([item])
        else:
            out.append(cur)
            cur = Page(item["start"], item["end"], [[item]])
    if cur is not None:
        out.append(cur)
    for page, nxt in zip(out, out[1:] + [None], strict=True):
        last_end = page.words[-1]["end"]
        page.end = last_end + LINGER_S
        if nxt is not None and nxt.start - last_end <= PAGE_GAP_S:
            page.end = nxt.start  # he keeps talking: the next page replaces this one
        elif nxt is not None:
            page.end = min(page.end, nxt.start)
    return out


def timeline(items: list[Page]) -> list[tuple[float, float, int | None, int | None]]:
    """(start, end, page, boxed word) states, blank between pages (page None)."""
    states: list[tuple[float, float, int | None, int | None]] = []
    t = 0.0
    for p_index, page in enumerate(items):
        if page.start > t:
            states.append((t, page.start, None, None))
        ws = page.words
        cursor = page.start
        for k, w in enumerate(ws):
            s = max(w["start"], cursor)
            if s > cursor:
                states.append((cursor, s, p_index, None))
            if k + 1 == len(ws):
                e = page.end
            elif ws[k + 1]["start"] - w["end"] <= HOLD_GAP_S:
                e = ws[k + 1]["start"]
            else:
                e = w["end"] + 0.05
            e = max(e, s)
            if e > s:
                states.append((s, e, p_index, k))
            cursor = max(cursor, e)
        if page.end > cursor:
            states.append((cursor, page.end, p_index, None))
        t = max(t, page.end)
    merged: list[tuple[float, float, int | None, int | None]] = []
    for st in states:
        if st[1] - st[0] <= 1e-4:
            continue
        if merged and merged[-1][2:] == st[2:] and abs(merged[-1][1] - st[0]) < 1e-6:
            merged[-1] = (merged[-1][0], st[1], st[2], st[3])
        else:
            merged.append(st)
    return merged


class _Layout:
    def __init__(self, frame_w: int, frame_h: int) -> None:
        self.w, self.h = frame_w, frame_h
        self.size = FONT_SIZE * frame_w / BASE_W
        self.center = frame_h * CENTER_Y
        pitch = LINE_PITCH_EM * self.size
        top = self.center - pitch / 2 - BOX_UP_EM * self.size - 0.3 * self.size
        bottom = self.center + pitch / 2 + BOX_DOWN_EM * self.size + 0.3 * self.size
        self.band_y = max(0, int(top))
        self.band_h = min(frame_h, int(bottom) + 1) - self.band_y
        self._fonts: dict[int, Any] = {}

    def font(self, size: int) -> Any:
        from PIL import ImageFont

        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(str(FONT_PATH), size)
        return self._fonts[size]

    def place(self, page: Page) -> tuple[int, list[tuple[float, float, dict[str, Any]]]]:
        """Font size for the page and each word's (x, baseline) in band coordinates."""
        size = round(self.size)
        while True:
            font = self.font(size)
            space = font.getlength(" ")
            widths = [
                sum(font.getlength(w["text"]) for w in line) + space * (len(line) - 1)
                for line in page.lines
            ]
            if max(widths) <= self.w * MAX_LINE_WIDTH or size <= self.size * 0.6:
                break
            size -= 2
        pitch = LINE_PITCH_EM * size
        n = len(page.lines)
        placed: list[tuple[float, float, dict[str, Any]]] = []
        for li, (line, width) in enumerate(zip(page.lines, widths, strict=True)):
            baseline = self.center + (li - (n - 1) / 2) * pitch - self.band_y
            x = (self.w - width) / 2
            for w in line:
                placed.append((x, baseline, w))
                x += font.getlength(w["text"]) + space
        return size, placed

    def draw(self, page: Page, boxed: int | None, path: Path) -> None:
        from PIL import Image, ImageDraw, ImageFilter

        size, placed = self.place(page)
        font = self.font(size)
        image = Image.new("RGBA", (self.w, self.band_h), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (self.w, self.band_h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        dy = SHADOW_DY_EM * size
        for x, y, w in placed:
            sd.text((x, y + dy), w["text"], font=font, fill=SHADOW, anchor="ls")
        image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR_EM * size)))
        draw = ImageDraw.Draw(image)
        if boxed is not None:
            x, y, w = placed[boxed]
            pad = BOX_PAD_EM * size
            draw.rounded_rectangle(
                (x - pad, y - BOX_UP_EM * size, x + font.getlength(w["text"]) + pad,
                 y + BOX_DOWN_EM * size),
                radius=BOX_RADIUS_EM * size,
                fill=ORANGE,
            )
        for x, y, w in placed:
            draw.text((x, y), w["text"], font=font, fill=WHITE, anchor="ls")
        image.save(path, compress_level=1)


def render_band(
    items: list[Page], frame_w: int, frame_h: int, folder: Path, duration_s: float
) -> dict[str, Any]:
    """Draw every caption state and write the ffconcat list that times them.

    Returns {"list": path, "y": band top on the frame, "h": band height,
    "states": count}. One stream, laid over the video with one overlay.
    """
    from PIL import Image

    folder.mkdir(parents=True, exist_ok=True)
    layout = _Layout(frame_w, frame_h)
    blank = folder / "blank.png"
    Image.new("RGBA", (frame_w, layout.band_h), (0, 0, 0, 0)).save(blank)
    names: dict[tuple[int, int | None], str] = {}
    entries: list[tuple[str, float]] = []
    for s, e, p_index, boxed in timeline(items):
        if p_index is None:
            name = blank.name
        else:
            key = (p_index, boxed)
            if key not in names:
                names[key] = f"p{p_index:04d}-{'plain' if boxed is None else f'w{boxed:02d}'}.png"
                layout.draw(items[p_index], boxed, folder / names[key])
            name = names[key]
        entries.append((name, e - s))
    total = sum(d for _n, d in entries)
    if duration_s > total:
        entries.append((blank.name, duration_s - total + 1.0))
    lines = ["ffconcat version 1.0"]
    for name, d in entries:
        lines += [f"file '{name}'", f"duration {d:.4f}"]
    lines.append(f"file '{blank.name}'")  # the demuxer ignores the last duration
    listing = folder / "captions.ffconcat"
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"list": listing, "y": layout.band_y, "h": layout.band_h, "states": len(entries)}


def on_edit_timeline(words: list[dict[str, Any]], keep: list[list[float]]) -> list[dict[str, Any]]:
    """Kept words moved onto the edited clock (shared with the subtitles)."""
    from tce.production.retakes import words_on_edit

    return words_on_edit(words, keep)
