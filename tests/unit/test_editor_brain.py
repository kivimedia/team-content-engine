"""The editing-request editor sees what it could not before (30-Sep).

Ziv, on the course-outline video: "when I say course you twice edited me so it sounds like
cou", then "in sec 39 I say cou", "sounds clipped", "0:38". Seven requests, six questions
back: the editor was told of one removed stumble ("the only cut is at 0:42") in an edit of
61 pieces, could not hear that the phone had cut the "s", and read each note as new.
"""

from __future__ import annotations

import pytest

from tce.production import autoedit
from tce.production.retakes import plan_edit


def w(text: str, start: float, end: float) -> dict:
    return {"text": text, "start_s": start, "end_s": end, "precision": "word"}


# The real 10 ms levels of "the course?" at 1:28.81 (the recording lost the "s").
COURSE = [-16, -19, -20, -27, -37, -41, -47, -55, -54, -54, -47, -23, -20, -30, -20, -13, -15, -16,
          -18, -14, -21, -23, -33, -27, -29, -32, -24, -35, -44, -48, -47, -51, -55, -59, -65, -79,
          -79, -78, -91, -93, -94, -92, -88, -84, -89, -88, -91, -91, -90, -89, -90, -92, -92]


def course_levels() -> list[float]:
    levels = [-120.0] * 10000
    for k, db in enumerate(COURSE):
        levels[8881 + k] = float(db)
    for k in range(8700, 8880):
        levels[k] = -15.0  # "watching the"
    return levels


# The same stretch above 3.5 kHz (the hiss band, 16 kHz audio), from 1:28.81: the vowel's
# own hiss, then nothing where the "s" should be, then the phone's silence.
COURSE_HISS = [-75, -74, -71, -66, -75, -69, -47, -44, -58, -56, -49, -49, -50, -52, -50, -56, -59,
               -69, -62, -66, -69, -61, -75, -79, -83, -83, -83, -82, -79, -74, -74, -74, -78, -79,
               -85, -84, -82, -79, -75, -74, -76, -72, -74, -76, -73, -75, -75]


def course_hiss() -> list[float]:
    hiss = [-120.0] * 10000
    for k, db in enumerate(COURSE_HISS):
        hiss[8881 + k] = float(db)
    for k in range(8700, 8880):
        hiss[k] = -45.0  # the vowels of "watching the"
    return hiss


WORDS = [w("watching", 87.2, 87.9), w("the", 87.9, 88.2), w("course?", 88.86, 89.08),
         w("And", 93.14, 93.4), w("then", 93.4, 93.7)]


def test_a_word_the_phone_cut_short_is_marked():
    marks = autoedit.word_marks(WORDS, [[87.1, 89.27], [93.0, 94.0]], course_levels(), low_db=-51.0,
                                hiss=course_hiss())
    assert marks == {2: "phone cut its end short"}


def test_loudness_alone_never_marks_a_word():
    # "this" and "sales" at 8:37 end on a strong "s" and the phone's silence, like the lost one.
    assert autoedit.word_marks(WORDS, [[87.1, 89.27]], course_levels(), low_db=-51.0) == {}


def test_a_word_that_ends_on_its_hiss_is_not_marked():
    levels, hiss = course_levels(), course_hiss()
    # Say the whole word: the "s" hisses to 89.30 (-30 dB on both readings), then silence.
    for k in range(8908, 8930):
        levels[k] = -30.0
        hiss[k] = -30.0
    words = [dict(x) for x in WORDS]
    words[2]["end_s"] = 89.30
    assert autoedit.word_marks(words, [[87.1, 89.4]], levels, low_db=-51.0, hiss=hiss) == {}


def test_a_buzzing_s_is_never_checked():
    # "sales", "because", "courses" end on a voiced z: almost nothing above 3.5 kHz even when
    # said in full, so the check would call them cut (it did, on the 30-Sep walks).
    for text in ("sales.", "because", "courses?", "is", "coach."):
        words = [dict(x) for x in WORDS]
        words[2]["text"] = text
        assert autoedit.word_marks(words, None, course_levels(), low_db=-51.0, hiss=course_hiss()) == {}, text


def test_the_plan_lists_kept_words_the_phone_cut_for_the_card(monkeypatch):
    import asyncio
    import uuid
    from types import SimpleNamespace

    from tce.api.routers import production as P
    from tce.production import tightcut

    levels, hiss = course_levels(), course_hiss()

    async def fake_levels(_path, hiss_band=False, **kw):
        return hiss if (hiss_band or kw.get("hiss")) else levels

    monkeypatch.setattr(P, "_levels", fake_levels)
    monkeypatch.setattr(P, "_speech_activity", lambda _p: _activity(tightcut.find_activity(levels)))
    row = SimpleNamespace(edit_plan={}, transcript=WORDS, packet_id=None, storage_path="x.mp4",
                          duration_s=95.0, status="transcribed", status_detail=None)
    asyncio.run(P._compute_plan(None, uuid.uuid4(), row))
    assert [(c["text"], c["index"]) for c in row.edit_plan["phone_cut"]] == [("course?", 2)]
    assert row.edit_plan["phone_cut"][0]["edit_s"] > 0


async def _activity(act):
    return act


def test_a_cut_inside_a_sounding_word_is_marked():
    levels = [-120.0] * 1000
    for k in range(100, 180):
        levels[k] = -20.0
    marks = autoedit.word_marks([w("can", 1.0, 1.8)], [[0.9, 1.5]], levels, low_db=-51.0)
    assert marks == {0: "the edit ends inside this word"}


def test_every_join_is_shown_not_only_the_removed_words():
    words = [w("one", 1.0, 1.3), w("two", 1.3, 1.6), w("three", 3.0, 3.4), w("four", 3.4, 3.8)]
    text = autoedit.numbered_transcript(words, [[0.9, 1.7], [2.9, 3.9]], marks={2: "phone cut its end short"})
    assert "1:two /cut 1.2s/ 2:three (phone cut its end short) 3:four" in text


def test_the_editor_reads_every_earlier_note_on_the_video():
    history = [
        {"request": "when I say course you twice edited me so it sounds like cou", "reply": "",
         "question": "which two times do you hear cou?"},
        {"request": "0:38", "reply": "", "question": "What should I change at 0:38?"},
    ]
    prompt = autoedit.edit_request_prompt(WORDS, [[87.1, 89.27]], "Topic: courses", "sounds clipped",
                                          scope="whole", start_s=None, end_s=None, history=history)
    assert prompt.index("Earlier notes on this video") < prompt.index("His request now")
    assert "You asked him: What should I change at 0:38?" in prompt
    assert "/cut Ns/ is a join" in prompt


def test_the_editor_carries_his_standing_rules():
    system = autoedit.edit_request_system()
    assert "phone cut its end short" in system and "Maple and Rain" in system and "- hold:" in system
    assert "HIS STANDING RULES" in autoedit.review_system(["Maple", "Rain"])
    assert "hold" in autoedit.EDIT_REQUEST_SCHEMA["required"]


def test_a_hold_reaches_the_plan_and_survives_re_plans():
    words = [w("I", 0.0, 0.2), w("can", 0.3, 0.9), w("go.", 2.5, 3.0)]
    holds = autoedit.word_holds(words, [{"index": 1, "side": "end", "extra_ms": 250, "why": "clipped n"},
                                         {"index": 9, "side": "end", "extra_ms": 250, "why": "no word"},
                                         {"index": 1, "side": "end", "extra_ms": 5000, "why": "too much"}])
    assert holds == [[0.9, "end", 0.25], [0.9, "end", 0.6]]
    overrides = autoedit.merge_overrides({"cut": [], "restore": []}, [], [], holds)
    assert overrides["hold"] == [[0.9, "end", 0.6]]  # the newest on the same edge wins
    plan = plan_edit(words, [], pause_threshold_s=1.2, pad_s=0.05, duration_s=5.0, overrides=overrides)
    assert any(a <= 0.9 and b >= 1.49 for a, b in plan["keep"]), plan["keep"]


# ---------------------------------------------------------------------------
# The clock (talk to the editor, step 1): a second he paused on in the edit points
# back at the recording, and back again, through the keep that made the file.

from tce.production import media  # noqa: E402
from tce.production.retakes import (  # noqa: E402
    EDIT_FPS,
    edit_length,
    frame_keep,
    map_to_edit,
    map_to_source,
)

# 61 pieces on the 30-Sep course video; three are enough to hold every case.
KEEP = [[1.5, 4.25], [6.0, 10.0], [12.75, 13.5]]


def test_a_second_on_the_recording_comes_back_to_itself():
    for t in (1.5, 2.0, 4.0, 6.0, 7.33, 9.99, 12.75, 13.0, 13.5):
        assert abs(map_to_source(map_to_edit(t, KEEP), KEEP) - t) < 1e-9, t


def test_a_second_in_the_edit_comes_back_to_itself():
    total = edit_length(KEEP)
    assert total == 7.5
    steps = [k / 100 for k in range(int(total * 100) + 1)]
    for t in steps:
        assert abs(map_to_edit(map_to_source(t, KEEP), KEEP) - t) < 1e-9, t


def test_a_join_points_at_the_piece_he_is_seeing():
    # 2.75 s into the edit the first piece has ended and the second begins: the frame on
    # screen is the recording at 6.0, not 4.25.
    assert map_to_source(2.75, KEEP) == 6.0
    assert map_to_source(2.7499, KEEP) == pytest.approx(4.2499)
    assert map_to_source(7.5, KEEP) == 13.5  # the last frame


def test_outside_the_edit_is_no_second_at_all():
    assert map_to_source(-0.1, KEEP) is None
    assert map_to_source(7.6, KEEP) is None
    assert map_to_source(0.0, []) is None
    assert map_to_edit(5.0, KEEP) is None  # a cut second on the recording


def test_the_frame_keep_is_what_the_render_cuts():
    assert EDIT_FPS == media.FPS
    keep = [[0.0, 1.016], [2.005, 2.015], [3.349, 5.0]]
    frames = [(round(s * media.FPS), round(e * media.FPS)) for s, e in keep]
    cut = [[a / media.FPS, b / media.FPS] for a, b in frames if b > a]
    assert frame_keep(keep) == cut
    # 2.005-2.015 rounds to one frame number at both ends: the render drops it, and so
    # does the clock.
    assert len(frame_keep(keep)) == 2
    assert frame_keep(keep)[1] == [100 / 30, 150 / 30]


def test_the_frame_keep_round_trips_on_the_files_own_clock():
    fk = frame_keep(KEEP + [[20.004, 21.49]])
    for t in (1.5, 3.0, 8.0, 13.2, 20.5):
        assert abs(map_to_source(map_to_edit(t, fk), fk) - t) < 1e-9
    assert edit_length(fk) * EDIT_FPS == pytest.approx(round(edit_length(fk) * EDIT_FPS))
