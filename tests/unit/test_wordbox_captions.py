"""Captions in TJ's look: pages of two short lines, the spoken word on an orange box.

28-Sep: "the pills are not pretty (i want the same caption animation and style that
he uses)". The numbers come from his reels, measured frame by frame. Synthetic data.
"""

from __future__ import annotations

import subprocess

import pytest

pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from tce.production import media, wordbox  # noqa: E402


def timed(text: str, start: float, step: float = 0.3) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start": round(t, 3), "end": round(t + step - 0.05, 3)})
        t += step
    return out


def test_pages_fill_two_lines_of_twelve_characters_like_his():
    # His own pages: "We had to" / "jump through", then "a lot of" / "hoops just".
    pages = wordbox.pages(timed("We had to jump through a lot of hoops just", 0.0))
    assert [[" ".join(w["text"] for w in line) for line in p.lines] for p in pages] == [
        ["We had to", "jump through"],
        ["a lot of", "hoops just"],
    ]
    pages = wordbox.pages(timed("see a good benchmark for measuring", 0.0))
    assert [[" ".join(w["text"] for w in line) for line in p.lines] for p in pages] == [
        ["see a good", "benchmark"],
        ["for", "measuring"],
    ]


def test_a_sentence_end_or_a_pause_starts_a_new_page_and_fillers_never_show():
    words = timed("It works. So um it", 0.0) + timed("sells.", 3.0)
    pages = wordbox.pages(words)
    texts = [" ".join(w["text"] for w in p.words) for p in pages]
    assert texts == ["It works.", "So it", "sells."]


def test_the_box_snaps_word_to_word_and_stays_on_the_last_word():
    pages = wordbox.pages(timed("We had to jump through", 0.0) + timed("next page.", 1.6))
    states = wordbox.timeline(pages)
    first = [s for s in states if s[2] == 0]
    assert [s[3] for s in first] == [0, 1, 2, 3, 4]  # one box at a time, in order
    assert first[-1][1] == pytest.approx(pages[1].start)  # the last word stays boxed
    # Between pages he keeps talking: no blank flash.
    assert not [s for s in states if s[2] is None and 0 < s[0] < pages[1].start]


def test_the_page_leaves_when_he_pauses():
    pages = wordbox.pages(timed("Stop here.", 0.0) + timed("Go on.", 3.0))
    states = wordbox.timeline(pages)
    blank = [s for s in states if s[2] is None]
    assert blank and blank[0][0] == pytest.approx(pages[0].words[-1]["end"] + wordbox.LINGER_S)


def test_hebrew_keeps_the_plain_captions():
    assert wordbox.usable(timed("hello there", 0))
    assert not wordbox.usable(timed("שלום לכולם", 0))


def test_the_state_images_put_an_orange_box_behind_the_spoken_word(tmp_path):
    pages = wordbox.pages(timed("We had to jump through", 0.0))
    band = wordbox.render_band(pages, 1080, 1920, tmp_path, 3.0)
    assert band["y"] < 1920 * wordbox.CENTER_Y < band["y"] + band["h"]
    layout = wordbox._Layout(1080, 1920)
    size, placed = layout.place(pages[0])
    assert size == wordbox.FONT_SIZE
    image = Image.open(tmp_path / "p0000-w01.png").convert("RGBA")  # "had" boxed
    x, y, w = placed[1]
    assert w["text"] == "had"
    # Inside the box, left of the letters: orange. Same spot on "We": clear.
    assert image.getpixel((int(x - 8), int(y - 20)))[:3] == wordbox.ORANGE[:3]
    x0, y0, _w0 = placed[0]
    assert image.getpixel((int(x0 - 8), int(y0 - 20)))[3] < 40
    # White letters, and TJ's width: "jump through" is 702 px at 1080 (his is 701).
    font = layout.font(size)
    assert 690 <= font.getlength("jump through") <= 715
    listing = band["list"].read_text(encoding="utf-8").splitlines()
    assert listing[0] == "ffconcat version 1.0" and listing[-1] == "file 'blank.png'"


def test_a_line_too_wide_shrinks_instead_of_running_off_the_frame():
    page = wordbox.Page(0.0, 1.0, [[{"text": "Incomprehensibilities", "start": 0.0, "end": 1.0}]])
    layout = wordbox._Layout(1080, 1920)
    size, placed = layout.place(page)
    assert size < wordbox.FONT_SIZE
    x, _y, w = placed[0]
    assert x >= 0 and x + layout.font(size).getlength(w["text"]) <= 1080


def test_on_edit_timeline_moves_kept_words_and_drops_cut_ones():
    words = timed("keep this", 0.0) + timed("cut that", 5.0) + timed("and this", 10.0)
    keep = [[0.0, 1.0], [10.0, 11.0]]
    out = wordbox.on_edit_timeline(words, keep)
    assert [w["text"] for w in out] == ["keep", "this", "and", "this"]
    assert out[2]["start"] == pytest.approx(1.0)


def _frame(path, t, size):
    raw = subprocess.run(
        [media.ffmpeg_path(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True,
    ).stdout
    assert len(raw) == size[0] * size[1] * 3
    return raw


def _orange_count(raw, size, box):
    w = size[0]
    x0, y0, x1, y1 = (int(v) for v in box)
    n = 0
    for y in range(max(0, y0), min(size[1], y1)):
        for x in range(max(0, x0), min(w, x1)):
            i = (y * w + x) * 3
            r, g, b = raw[i], raw[i + 1], raw[i + 2]
            if r > 200 and 80 < g < 160 and b < 100:
                n += 1
    return n


@pytest.mark.skipif(not media.ffmpeg_path(), reason="ffmpeg not installed")
async def test_the_render_boxes_the_word_being_said_and_cuts_on_the_frame_grid(tmp_path):
    size = (540, 960)
    src = tmp_path / "walk.mp4"
    subprocess.run(
        [media.ffmpeg_path(), "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=0x224466:s={size[0]}x{size[1]}:d=8:r=15",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=8", "-shortest",
         "-c:v", "libx264", "-c:a", "aac", str(src)],
        check=True,
    )
    keep = [[0.0, 2.0], [4.0, 6.0]]  # on the 1/30 s grid
    words = timed("We had to jump through", 0.2, step=0.35) + timed("a lot of hoops", 4.2, step=0.35)
    on_edit = wordbox.on_edit_timeline(words, keep)
    pages = wordbox.pages(on_edit)
    band = wordbox.render_band(pages, *size, tmp_path / "band", 4.0)

    async def status(_t):
        return None

    out = await media.render_edit(
        src, keep, tmp_path / "walk-edited.mp4", on_status=status,
        srt_text="1\n00:00:00,000 --> 00:00:01,000\nx\n", caption_band=band, make_preview=True,
    )
    # Picture and sound are the same length: the joins never drift.
    probe = subprocess.run(
        [media.ffprobe_path(), "-v", "error", "-show_entries", "stream=codec_type,duration,r_frame_rate",
         "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    video = next(line for line in probe if line.startswith("video"))
    audio = next(line for line in probe if line.startswith("audio"))
    assert video.split(",")[1] == "30/1"
    assert abs(float(audio.split(",")[2]) - 4.0) < 0.05
    # The picture stops with the sound: the caption stream is padded past the end and
    # once ran the video on, frozen and silent (review, 28-Sep). The stream duration
    # hides that; the last frame's time does not.
    last = subprocess.run(
        [media.ffprobe_path(), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "packet=pts_time", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    assert max(float(t) for t in last) < float(audio.split(",")[2]), last[-3:]
    # "had" is boxed while it is said, and "We" is not.
    layout = wordbox._Layout(*size)
    fsize, placed = layout.place(pages[0])
    had = next(w for w in on_edit if w["text"] == "had")
    t = (had["start"] + had["end"]) / 2
    raw = _frame(out, t, size)
    pad = wordbox.BOX_PAD_EM * fsize
    x, y, _w = placed[1]
    box_had = (x - pad, band["y"] + y - 0.8 * fsize, x - 2, band["y"] + y)
    x0, y0, _w0 = placed[0]
    box_we = (x0 - pad, band["y"] + y0 - 0.8 * fsize, x0 - 2, band["y"] + y0)
    assert _orange_count(raw, size, box_had) > 30
    assert _orange_count(raw, size, box_we) == 0
    # The light copy for the phone exists, never wider than 720 (this source is 540).
    light = media.preview_path(out)
    assert light.exists() and await media.probe_video_size(light) == size


def test_caption_lines_carry_no_period_at_the_end():
    # 29-Sep: "It looks odd when you add them."
    assert [wordbox.shown(t) for t in ["possible.", "actually...", "5.5", "call,", "why?", "go!"]] == [
        "possible", "actually", "5.5", "call,", "why?", "go!"
    ]


def test_a_restored_sound_is_heard_but_never_captioned():
    words = timed("Bring people", 1.0)
    words.insert(0, {"text": "[sound]", "start": 0.5, "end": 0.9})
    out = wordbox.on_edit_timeline(words, [[0.0, 3.0]])
    assert [w["text"] for w in out] == ["Bring", "people"]
