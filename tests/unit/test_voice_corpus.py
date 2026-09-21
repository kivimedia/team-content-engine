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
    text = "Most coaches blame the marketing. " + TEACHING
    run = runs_from([turn(0, text)])[0]

    assert run.opening == "Most coaches blame the marketing."
    assert "cup of water" not in run.opening


def test_a_sentence_that_continues_a_conversation_is_not_an_opening():
    # Half his runs begin mid-thought, and those are useless as a hook bank.
    for start in [
        "And the club is not your prosperous path.",
        "Anyway, you need to accept the invite first.",
        "Yeah, that is what I meant about the pricing.",
        "But the real problem is somewhere else entirely.",
        "It's the same thing we talked about last week.",
    ]:
        run = runs_from([turn(0, start + " " + TEACHING)])[0]
        assert run.opening == "", start
        assert run.first_sentence  # the text is still there, it is just not an opening


def test_the_ways_he_really_starts_are_kept():
    for start in [
        "Most coaches blame the marketing.",
        "Here is the thing about pricing.",
        "The problem is not the ads.",
        "Nobody tells you this part.",
        "So here is what I would do.",
    ]:
        run = runs_from([turn(0, start + " " + TEACHING)])[0]
        assert run.opening == start, start


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


def test_a_whole_call_is_not_a_mini_speech():
    # A 3,000 word "stretch" is a call whose other speaker the diarization dropped,
    # so it reads as Ziv interviewing himself.
    long_text = " ".join(["The point about pricing is that it moves with the booking."] * 80)
    run = runs_from([turn(0, long_text)])[0]

    kind, reason = vc.judge(run)

    assert kind == "merged"
    assert "call segment" in reason


def test_merged_dialogue_gives_itself_away_by_rhythm():
    # Real sample from his calls: the other speaker's turns are gone, so what is
    # left is his fragments strung together.
    fragments = "People? Yes. Okay. One real weak spot. Stranger messaging email. Save. "
    run = runs_from([turn(0, fragments * 6)])[0]

    kind, reason = vc.judge(run)

    assert kind == "merged"
    assert "merged dialogue" in reason


def test_a_live_demo_is_not_teaching():
    text = (
        "So on the right side you can see here five thousand dollars, that is how much "
        "I saved by using this system, it is basically just tasks that were done through "
        "the subscriptions that I have and the marketplace where I can add more agents "
        "to the fleet that is already running for me every single day of the week."
    )
    run = runs_from([turn(0, text)])[0]

    assert vc.judge(run)[0] == "operating"


def test_filler_is_removed_but_the_words_are_not():
    raw = "So, um, this brings us to, uh, yeah, the actual intelligence, right?"

    out = vc.clean_text(raw)

    assert "um" not in out.lower().split()
    assert "uh" not in out.lower().split()
    assert "this brings us to" in out
    assert "actual intelligence" in out


def test_a_stutter_collapses_to_one_word():
    assert vc.clean_text("I i i want to suggest something") == "I want to suggest something"
    assert vc.clean_text("agents, agents up") == "agents up"


def test_cleaning_never_eats_a_real_word():
    # "Mummy", "under", "human" all contain filler spellings.
    text = "Her mummy is under the human limit of what one person can do."
    assert vc.clean_text(text) == text


def test_runs_are_cleaned_as_they_are_built():
    run = runs_from([turn(0, "So, um, the point is, uh, about pricing and what it costs.")])[0]

    assert "um," not in run.text
    assert "the point is" in run.text


def test_running_a_standup_is_not_teaching():
    # Real shape from his calls: tasks handed round a team, items closed, thanks.
    text = (
        "This one is for you, Hilda, with the dashboard and making sure the CRM has "
        "terminal mode. Kath, we've sent logins to the hub and to Tim, and make sure "
        "that was closed. Thank you very much. Two nights of measurement exist now and "
        "the next thing is the inbox work that nobody has picked up yet this week."
    )
    run = runs_from([turn(0, text)])[0]

    kind, reason = vc.judge(run)

    assert kind == "standup"
    assert "team meeting" in reason
