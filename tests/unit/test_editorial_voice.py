"""The banned vocabulary is enforced, and stays tied to the doc Ziv maintains."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tce.editorial import voice

DOC = Path(__file__).resolve().parents[2] / "docs" / "super-coaching-strategy.md"


def banned_in_doc() -> set[str]:
    """Every quoted phrase under the doc's "Banned vocabulary" heading."""
    text = DOC.read_text(encoding="utf-8")
    start = text.index("### Banned vocabulary")
    section = text[start:]
    end = section.find("\n### ", 4)
    if end != -1:
        section = section[:end]
    quoted = {m.group(1).strip().lower() for m in re.finditer(r'"([^"]+)"', section)}
    # The section also quotes the dash he WANTS ("Use a single dash with spaces: \" - \"").
    # A prescription is not a ban.
    return {q for q in quoted if q and q != "-"}


def test_every_banned_phrase_in_his_doc_is_enforced_in_code():
    # If he adds a phrase to the doc, this fails until the code catches it too.
    missing = banned_in_doc() - {p.lower() for p in voice.BANNED_PHRASES}
    assert not missing, f"banned in the doc but not enforced: {sorted(missing)}"


@pytest.mark.parametrize(
    "text",
    [
        "This is a game-changer for coaches.",
        "The window is closing on this one.",
        "Smart coaches who act now will win.",
        "It seamlessly integrates with your stack.",
        "In today's fast-paced world, bookings move fast.",
        "Translation: you are losing money.",
    ],
)
def test_the_phrases_he_banned_are_caught(text):
    assert voice.banned_hits(text)


def test_dashes_are_caught_in_every_form():
    assert voice.banned_hits("one — two")  # em dash
    assert voice.banned_hits("one – two")  # en dash
    assert voice.banned_hits("one -- two")  # double dash
    assert not voice.banned_hits("one - two")  # the one he uses


def test_a_clean_line_passes():
    assert voice.banned_hits("Check the stage where people drop off - not the ads.") == []


def test_it_does_not_fire_inside_an_unrelated_word():
    assert voice.banned_hits("She held a smartphone and a smart-looking notebook.") == []


def test_case_does_not_matter():
    assert voice.banned_hits("GAME-CHANGING results")


def test_first_banned_reports_the_first_offender_across_fields():
    assert (
        voice.first_banned(["clean line", "a paradigm shift", "game-changer"]) == "paradigm shift"
    )
    assert voice.first_banned(["clean", "also clean"]) is None


def test_the_hook_rule_forbids_the_curiosity_gap():
    # The old instruction asked for "the unresolved viewer question", which is the
    # AI house style he recognised on sight.
    rule = voice.HOOK_RULE.lower()
    assert "unresolved viewer question" not in rule
    assert "not a question" in rule
    assert "disagrees with what the viewer currently believes" in rule
