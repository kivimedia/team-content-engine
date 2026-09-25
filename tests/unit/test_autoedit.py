"""TCE edits by itself: applying proofreads and editing requests. Synthetic data."""

from __future__ import annotations

from tce.production import autoedit


def words(text: str, start: float = 0.0, step: float = 0.5) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start_s": t, "end_s": t + step - 0.1, "precision": "word"})
        t += step
    return out


def test_the_not_that_flipped_his_point_is_removed_when_quoted_exactly():
    w = words("It is really smart. Not after you've finished your service.")
    fixed, applied = autoedit.apply_corrections(
        w, [{"first": 4, "last": 5, "heard": "Not after", "replacement": "After", "why": "x"}]
    )
    assert " ".join(x["text"] for x in fixed) == "It is really smart. After you've finished your service."
    assert len(applied) == 1 and applied[0]["heard"] == "Not after"
    # The replacement keeps the span's timing, so captions stay in sync.
    assert fixed[4]["start_s"] == w[4]["start_s"] and fixed[4]["end_s"] == w[5]["end_s"]


def test_a_correction_that_misquotes_the_words_is_refused():
    w = words("The secret is not to ask them")
    fixed, applied = autoedit.apply_corrections(
        w, [{"first": 3, "last": 3, "heard": "never", "replacement": "", "why": "x"}]
    )
    assert fixed == w and applied == []


def test_overlapping_or_out_of_range_corrections_are_dropped():
    w = words("one two three four")
    _fixed, applied = autoedit.apply_corrections(
        w,
        [
            {"first": 1, "last": 2, "heard": "two three", "replacement": "2 3", "why": ""},
            {"first": 2, "last": 3, "heard": "three four", "replacement": "x", "why": ""},
            {"first": 9, "last": 9, "heard": "nine", "replacement": "x", "why": ""},
        ],
    )
    assert [a["first"] for a in applied] == [1]


def test_cut_and_restore_survive_a_replan_and_the_newest_wins():
    plan = {
        "keep": [[0.0, 10.0], [20.0, 30.0]],
        "units": [
            {"start": 2.5, "end": 3.5, "kept": True, "text": "a"},
            {"start": 12.0, "end": 14.0, "kept": False, "text": "b"},
        ],
        "stats": {},
    }
    over = autoedit.merge_overrides(None, cut=[[2.0, 4.0]], restore=[[12.0, 14.0]])
    out = autoedit.apply_overrides(plan, over)
    assert out["keep"] == [[0.0, 2.0], [4.0, 10.0], [12.0, 14.0], [20.0, 30.0]]
    assert [u["kept"] for u in out["units"]] == [False, True]
    assert out["overrides"] == over
    # He changes his mind: bring back what the earlier request cut.
    again = autoedit.merge_overrides(over, cut=[], restore=[[2.0, 4.0]])
    assert again["cut"] == []
    assert autoedit.apply_overrides(plan, again)["keep"][0] == [0.0, 10.0]


def test_the_request_prompt_speaks_in_edited_time_and_marks_cut_words():
    w = words("keep this. drop this. keep that.", step=1.0)
    keep = [[0.0, 2.0], [4.0, 6.0]]
    text = autoedit.numbered_transcript(w, keep)
    assert "~~2:drop~~" in text and "~~3:this.~~" in text
    assert text.splitlines()[-1].startswith("[0:02 in the edit]")
