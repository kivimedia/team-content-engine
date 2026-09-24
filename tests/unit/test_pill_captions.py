"""Walking-video pill captions: his orange/cyan look, word-timed, never across a cut. Synthetic.

24-Sep: "did you add captions in the style of my other walking videos" - the edit
came out with plain white-on-black libass boxes. His walking videos use Outfit
Black in an orange pill, a cyan pill for a second line, lower third.
"""

from __future__ import annotations

import subprocess

import pytest

pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from tce.production import pills  # noqa: E402
from tce.production.media import ffmpeg_path, render_edit  # noqa: E402


def words(text: str, start: float, step: float = 0.3) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"start_s": t, "end_s": t + step - 0.05, "text": w, "precision": "word"})
        t += step
    return out


def test_phrases_drop_fillers_keep_four_words_a_line_and_never_cross_a_cut():
    spoken = words("So um in essence, it's kind of like a reminder call.", 0.0) + words(
        "Uh after the event you ask them again", 10.0
    )
    keep = [[0.0, 4.0], [10.0, 13.0]]
    items = pills.phrases(spoken, keep)
    text = " ".join(p["top"] + " " + p["bottom"] for p in items)
    assert "um" not in text.split() and "Uh" not in text.split()
    for p in items:
        assert len(p["top"].split()) <= 4 and len(p["bottom"].split()) <= 4, p
        assert p["end"] - p["start"] <= pills.PHRASE_MAX_S + 1e-6
    # The first kept range is 4 s long on the edited timeline: nothing from it may
    # still be on screen after 4.0, and the second range's words start at 4.0.
    first = [p for p in items if p["start"] < 4.0]
    second = [p for p in items if p["start"] >= 4.0]
    assert first and second
    assert all(p["end"] <= 4.0 for p in first), first
    assert second[0]["top"].startswith("after"), second
    for a, b in zip(items, items[1:], strict=False):
        assert a["end"] <= b["start"], (a, b)


def test_a_comma_is_where_the_second_line_starts():
    items = pills.phrases(words("In essence, it's kind of like", 0.0), [[0.0, 5.0]])
    assert items[0]["top"] == "In essence," and items[0]["bottom"] == "it's kind of like", items


def test_hebrew_keeps_the_plain_captions():
    assert pills.usable(words("hello there", 0))
    assert not pills.usable(words("שלום לכולם", 0))
    assert not pills.usable([{"start_s": 0, "end_s": 1, "text": "hi", "precision": "whole_second"}])


def test_pills_are_round_orange_then_cyan_and_a_long_line_shrinks_instead_of_clipping(tmp_path):
    items = [
        {"start": 0.0, "end": 2.0, "top": "So in essence,", "bottom": "kind of like"},
        {"start": 2.1, "end": 4.0, "top": "Extraordinarily unbelievably incomprehensibly", "bottom": ""},
    ]
    placed = pills.overlays(items, 1080, 1920, tmp_path)
    assert len(placed) == 3
    bottom_pill, top_pill, long_pill = placed
    for item in placed:
        image = Image.open(item["path"]).convert("RGBA")
        w, h = image.size
        assert w <= 1080 * pills.MAX_PILL_FRACTION + 1
        assert image.getpixel((0, 0))[3] == 0, "square corner: not a pill"
        assert image.getpixel((w // 2, 2))[3] == 255
        # The ends of the pill are background colour, never letters: nothing clipped.
        mid = h // 2
        edge = image.getpixel((h // 4, mid))[:3]
        assert edge in (pills.ORANGE[:3], pills.CYAN[:3]), edge
        assert item["x"] >= 0 and item["x"] + w <= 1080
    assert Image.open(top_pill["path"]).convert("RGB").getpixel((5, 30)) == pills.ORANGE[:3]
    assert Image.open(bottom_pill["path"]).convert("RGB").getpixel((5, 30)) == pills.CYAN[:3]
    # Stacked: the orange line sits above the cyan one, cyan ends 288px above the bottom.
    bh = Image.open(bottom_pill["path"]).size[1]
    assert bottom_pill["y"] + bh == 1920 - pills.BOTTOM_MARGIN
    assert top_pill["y"] < bottom_pill["y"]


async def test_the_render_burns_the_pills_into_the_frame(tmp_path):
    ff = ffmpeg_path()
    if not ff:
        pytest.skip("ffmpeg not installed")
    src = tmp_path / "walk.mp4"
    subprocess.run(
        [ff, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x224466:s=540x960:d=6:r=15",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=6", "-shortest",
         "-c:v", "libx264", "-c:a", "aac", str(src)],
        check=True,
    )
    keep = [[0.0, 2.0], [3.0, 6.0]]
    placed = pills.overlays(
        pills.phrases(words("So in essence it is", 0.2) + words("after the event", 3.2), keep),
        540, 960, tmp_path / "pills",
    )

    async def status(_text: str) -> None:
        return None

    out = await render_edit(src, keep, tmp_path / "out.mp4", on_status=status,
                            srt_text="1\n00:00:00,000 --> 00:00:01,000\nx\n", overlays=placed)
    first = next(p for p in placed if p["start"] < 1)
    at = (first["start"] + first["end"]) / 2
    frame = tmp_path / "frame.png"
    subprocess.run([ff, "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(out),
                    "-frames:v", "1", str(frame)], check=True)
    image = Image.open(frame).convert("RGB")
    showing = [p for p in placed if p["start"] <= at <= p["end"]]
    assert len(showing) == 2, "a two-line phrase shows an orange AND a cyan pill"
    seen = set()
    for p in showing:
        pill = Image.open(p["path"]).convert("RGB")
        want = pill.getpixel((pill.size[1] // 3, pill.size[1] // 2))
        got = image.getpixel((p["x"] + pill.size[1] // 3, p["y"] + pill.size[1] // 2))
        assert all(abs(a - b) < 24 for a, b in zip(got, want, strict=True)), (got, want)
        seen.add("orange" if want[0] > 200 else "cyan")
    assert seen == {"orange", "cyan"}
