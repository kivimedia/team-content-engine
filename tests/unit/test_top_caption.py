"""A fixed line at the top of the whole video (20-Oct, Angel's note on Jack the CTO).

The request editor had no tool for it, so "Add this caption that shows at the top part of
the video" came back "my tools can't put a fixed caption at the top"."""

from __future__ import annotations

from pathlib import Path

from tce.production import autoedit, wordbox

TEXT = "This is what talking to your AI agent looks like. Meet Jack the CTO."


def test_editor_has_the_tool():
    assert "top_caption" in autoedit.EDIT_REQUEST_SCHEMA["required"]
    assert "top_caption" in autoedit.EDIT_BATCH_SCHEMA["properties"]["notes"]["items"]["required"]
    assert "top_caption" in autoedit.EDIT_REQUEST_SYSTEM


def test_change_set_off_unchanged():
    assert autoedit.top_caption_change(None, {"action": "set", "text": TEXT}) == TEXT
    assert autoedit.top_caption_change(TEXT, {"action": "set", "text": TEXT}) is None
    assert autoedit.top_caption_change(TEXT, {"action": "off", "text": ""}) == ""
    assert autoedit.top_caption_change(None, {"action": "off", "text": ""}) is None
    assert autoedit.top_caption_change(TEXT, {"action": "unchanged", "text": "x"}) is None
    assert autoedit.top_caption_change(None, None) is None


def test_merge_keeps_sets_and_clears():
    on = autoedit.merge_overrides(None, [], [], top_caption=TEXT)
    assert on["top_caption"] == TEXT
    # a later cut with no top-line change keeps the line
    later = autoedit.merge_overrides(on, [[1.0, 2.0]], [])
    assert later["top_caption"] == TEXT
    off = autoedit.merge_overrides(later, [], [], top_caption="")
    assert "top_caption" not in off


def test_batch_note_with_only_a_top_line_is_a_change():
    words = [{"text": "hi", "start_s": 0.0, "end_s": 0.4}]
    note = {
        "note": 1, "reply": "Added it.", "needs_you": False, "corrections": [], "cut": [],
        "restore": [], "hold": [], "trim": [], "denoise": "unchanged",
        "top_caption": {"action": "set", "text": TEXT},
    }
    out = autoedit.apply_batch(words, None, {"notes": [note], "summary": ""}, 1)
    assert out["changed"] is True
    assert out["notes"][0]["outcome"] == "change"
    assert out["overrides"]["top_caption"] == TEXT


def test_prompt_says_what_is_on_now():
    p = autoedit.edit_request_prompt(
        [{"text": "hi", "start_s": 0.0, "end_s": 0.4}], [[0.0, 0.4]], "ctx", "add a title",
        scope="whole", start_s=None, end_s=None, top_caption_now=TEXT,
    )
    assert f'Fixed line at the top of the video now: "{TEXT}"' in p


def test_draws_inside_the_frame(tmp_path: Path):
    from PIL import Image

    got = wordbox.render_top_caption(TEXT, 1080, 1920, tmp_path / "top.png")
    assert got is not None and got["lines"] <= wordbox.TOP_MAX_LINES
    img = Image.open(got["png"])
    assert img.width == 1080 and got["y"] + img.height < 1920 * 0.4
    assert img.getbbox() is not None  # something was drawn


def test_undrawable_text_is_left_off(tmp_path: Path):
    assert wordbox.render_top_caption("", 1080, 1920, tmp_path / "a.png") is None
    assert wordbox.render_top_caption("x" * 200, 1080, 1920, tmp_path / "b.png") is None
