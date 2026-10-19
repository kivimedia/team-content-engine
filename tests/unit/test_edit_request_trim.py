"""The editor can take out a long pause between two kept words (19-Oct).

A team member's notes "long pause from 1:32 to 1:38, remove that clip" were all answered
"I didn't cut anything here ... my tools can only cut whole words": the quiet sat inside
one kept range, between two words, so no `cut` (words) could reach it. The render already
takes `trim` overrides (Jennifer's check, 3-Oct); the editor now has the same tool, and
the transcript it reads shows each long quiet stretch as /quiet Ns/.
"""

from __future__ import annotations

from tce.production import autoedit

# "... pay more. I [4.9 s of nothing] recommend switching" - one kept range runs straight
# through the quiet, as in the video the notes were about.
WORDS = [
    {"text": "pay", "start_s": 227.40, "end_s": 227.58},
    {"text": "more.", "start_s": 227.58, "end_s": 227.94},
    {"text": "I", "start_s": 227.94, "end_s": 229.14},  # the recogniser stretched it
    {"text": "recommend", "start_s": 234.01, "end_s": 234.41},
    {"text": "switching", "start_s": 234.41, "end_s": 235.45},
]
KEEP = [[227.30, 236.00]]


def note(n, **kw):
    base = {"note": n, "reply": "", "needs_you": False, "question": "",
            "corrections": [], "cut": [], "restore": [], "hold": [], "trim": []}
    return {**base, **kw}


def test_the_transcript_shows_the_quiet_the_viewer_hears():
    text = autoedit.numbered_transcript(WORDS, KEEP)
    # "I" owns 1.2 s at most; the rest up to "recommend" plays as silence.
    assert "2:I /quiet 4.9s/ 3:recommend" in text
    assert "/quiet" not in text.split("2:I")[0]  # touching words get no marker


def test_a_trim_takes_the_quiet_out_and_keeps_both_words():
    out = autoedit.apply_batch(
        WORDS, None, {"notes": [note(1, reply="Took out the pause.", trim=[{"after": 2, "why": "his note"}])]},
        1, keep=KEEP,
    )
    assert out["changed"] and out["notes"][0]["outcome"] == "change"
    (ts, te), = out["overrides"]["trim"]
    assert 229.14 < ts < 229.4  # a breath after "I" stays
    assert 233.9 < te < 234.01  # ... and before "recommend"
    plan = autoedit.apply_overrides({"keep": KEEP}, out["overrides"])
    played = sum(e - s for s, e in plan["keep"])
    assert played < (KEEP[0][1] - KEEP[0][0]) - 4.0


def test_a_trim_with_no_real_pause_or_bad_index_is_refused_with_a_reason():
    out = autoedit.apply_batch(
        WORDS, None, {"notes": [
            note(1, reply="x", trim=[{"after": 0, "why": "touching words"}]),
            note(2, reply="y", trim=[{"after": 4, "why": "last word"}]),
            note(3, reply="z", trim=[{"after": 40, "why": "outside"}]),
        ]}, 3, keep=KEEP,
    )
    assert [n["outcome"] for n in out["notes"]] == ["refused", "refused", "refused"]
    assert not out["changed"] and out["overrides"] is None


def test_the_single_request_path_turns_a_trim_into_a_range():
    trims, skipped = autoedit.word_trims(WORDS, [{"after": 2, "why": "w"}], KEEP)
    assert len(trims) == 1 and not skipped


def test_the_editor_is_told_it_has_the_trim_tool():
    assert "- trim:" in autoedit.EDIT_REQUEST_SYSTEM
    assert "trim" in autoedit.EDIT_REQUEST_SCHEMA["properties"]
    assert "trim" in autoedit.EDIT_BATCH_SCHEMA["properties"]["notes"]["items"]["properties"]
