"""Mining Ziv's mini speeches out of diarized call turns.

The turns below are shaped like the real ones: 58 characters on average, a speaker
email that identifies him exactly, and long stretches where he is driving a computer
out loud rather than saying anything about the work.
"""

from __future__ import annotations

import uuid

import pytest

from tce.editorial import voice_corpus as vc

SOURCE = uuid.uuid4()


def turn(index, text, *, who=vc.ZIV_EMAIL, start=None, end=None, lang="en"):
    start = index * 10.0 if start is None else start
    return {
        "index": index,
        "text": text,
        "speaker_email": who,
        "speaker": "Ziv Raviv" if who == vc.ZIV_EMAIL else "Someone Else",
        "start_s": start,
        "end_s": (start + 8.0) if end is None else end,
        "language": lang,
    }


def runs_from(turns, **kw):
    return vc.build_runs(turns, source_id=SOURCE, source_title="A call", **kw)


TEACHING = (
    "So she will make it possible for you to get more results out of your ten hours, "
    "but you still need to put in the effort. If I look at this list of projects and "
    "expect them all to happen at the same time by a person who is only giving you one "
    "cup of water, there is not enough water inside the cup. In real life she walks way "
    "more than a cup of water, almost every day on your account. It is just that people "
    "are slow and the tasks are many, so you have to choose which ones matter."
)
OPERATING = (
    "Okay so I am going to click here, and then paste it here, and connect. I will need "
    "to really look at this, I am not sure why it was refused, but it will work. We will "
    "also hide the API base, that should not be something we show on the screen. Once "
    "this is connected you click here and hit record, then scroll down to the dashboard "
    "and refresh the browser tab to see it load."
)


def test_consecutive_turns_by_him_become_one_mini_speech():
    parts = TEACHING.split(". ")
    turns = [turn(i, p + ".") for i, p in enumerate(parts)]

    out = runs_from(turns)

    assert len(out) == 1
    assert out[0].turn_count == len(parts)
    assert out[0].first_turn_index == 0
    assert "cup of water" in out[0].text


def test_someone_else_speaking_ends_the_run():
    turns = [
        turn(0, "Here is the thing about the funnel and where people actually drop off."),
        turn(1, "Right, that makes sense.", who="client@example.com"),
        turn(2, "So the fix belongs to the next stage, not to the ads."),
    ]

    out = runs_from(turns)

    assert len(out) == 2
    assert out[0].turn_count == 1 and out[1].turn_count == 1
    assert out[1].first_turn_index == 2


def test_a_long_silence_ends_the_run_even_when_nobody_interrupts():
    turns = [
        turn(0, "One thought about pricing.", start=0.0, end=5.0),
        turn(1, "A completely separate thought.", start=90.0, end=95.0),
    ]

    out = runs_from(turns)

    assert len(out) == 2


def test_a_short_pause_does_not():
    turns = [
        turn(0, "One thought about pricing.", start=0.0, end=5.0),
        turn(1, "And the part that follows from it.", start=8.0, end=12.0),
    ]

    assert len(runs_from(turns)) == 1


def test_him_teaching_is_kept():
    run = runs_from([turn(0, TEACHING)])[0]

    kind, reason = vc.judge(run)

    assert kind == "teaching", reason
    assert run.word_count > vc.MIN_WORDS


def test_him_driving_a_computer_is_not():
    run = runs_from([turn(0, OPERATING)])[0]

    kind, reason = vc.judge(run)

    assert kind == "operating"
    assert reason


def test_narrating_an_action_is_caught_even_in_a_short_burst():
    text = (
        "Let me just show you something here, because I think it explains the whole "
        "problem better than I can say it, and then we can talk about what it means for "
        "the way you are running the follow up calls with your clients this month."
    )
    run = runs_from([turn(0, text)])[0]

    assert vc.judge(run)[0] == "operating"


def test_a_short_reply_is_not_a_mini_speech():
    run = runs_from([turn(0, "Yeah, exactly, that is what I meant.")])[0]

    kind, reason = vc.judge(run)

    assert kind == "thin"
    assert "reply" in reason


def test_hebrew_is_kept_out_of_the_english_writing_corpus():
    long_he = " ".join(["מילה"] * 60)
    run = runs_from([turn(0, long_he, lang="he")])[0]

    assert vc.judge(run)[0] == "other_language"


def test_a_run_that_switches_language_is_marked_mixed():
    turns = [
        turn(0, "So the point is about pricing.", lang="en", start=0.0, end=5.0),
        turn(1, "וזה בדיוק", lang="he", start=6.0, end=9.0),
    ]

    assert runs_from(turns)[0].language == "mixed"


def test_the_opening_is_the_first_sentence():
    run = runs_from([turn(0, TEACHING)])[0]

    assert run.opening.startswith("So she will make it possible")
    assert run.opening.endswith(".")
    assert "cup of water" not in run.opening


def test_prepare_tags_everything_and_keywords_only_for_the_good_ones():
    good = runs_from([turn(0, TEACHING)])[0]
    junk = runs_from([turn(0, OPERATING)])[0]

    vc.prepare([good, junk])

    assert good.kind == "teaching" and good.keywords
    assert junk.kind == "operating" and junk.keywords == []
    assert "water" in good.keywords


def test_another_persons_speech_is_never_collected():
    turns = [turn(i, TEACHING, who="client@example.com") for i in range(3)]

    assert runs_from(turns) == []


@pytest.mark.parametrize("missing", ["start_s", "end_s"])
def test_turns_without_timings_still_group(missing):
    turns = [turn(0, "First part of a thought about pricing and value."), turn(1, "And the rest.")]
    for t in turns:
        t[missing] = None

    assert len(runs_from(turns)) == 1
