"""The second listen (29-Sep): what the first transcription dropped comes back. Synthetic.

Ziv on the "Selling is the first step" edit: "at sec 09 i say 'and then that question'
and then at sec 12 I say 'and then that question stopped me'", "sec 38-39 i say
'הולכים משם' to my dogs", "the word make at 2:43 need to be cut out". The transcript held
none of the three, so the editor could not remove them.
"""

from __future__ import annotations

import asyncio

from tce.production import relisten
from tce.production.autoedit import review_transcript
from tce.production.retakes import build_cues, plan_edit


def w(text: str, start: float, end: float, **extra) -> dict:
    return {"text": text, "start_s": start, "end_s": end, "precision": "word", **extra}


# The first pass on 28-Sep: one 2.78 s "question" over "question, and ... then that question".
FIRST_PASS = [
    w("I", 55.62, 55.98), w("was", 55.98, 56.14), w("preparing", 56.14, 56.52),
    w("a", 56.52, 56.76), w("session", 56.76, 57.14), w("about", 57.14, 57.62),
    w("selling,", 57.62, 58.14),
    w("and", 63.72, 64.10), w("then", 64.10, 64.30), w("that", 64.30, 64.62),
    w("question", 66.19, 68.97), w("stopped", 68.97, 69.37), w("me", 69.37, 69.69),
    w("cold", 69.69, 70.15), w("because", 70.15, 71.35),
    w("I", 78.20, 78.46), w("hear", 78.46, 78.80), w("it.", 78.80, 78.96),
]


def test_an_overlong_word_is_heard_again_with_the_utterance_before_it():
    wins = relisten.windows(FIRST_PASS)
    target = next(x for x in wins if x.first <= 10 <= x.last)
    # "and then that" (1.57 s earlier) is heard with it: the repeat straddles the pause.
    assert target.first == 7 and target.last == 14
    assert target.start < 63.72 and target.end > 71.35
    assert any("and then that" in why and "stands on its own" in why for why in target.why)


def test_words_heard_again_replace_the_first_pass_when_there_are_more_of_them():
    wins = relisten.windows(FIRST_PASS)
    k = next(n for n, x in enumerate(wins) if x.first <= 10 <= x.last)
    base = wins[k].start
    clip = "And then that question, and then that question stopped me cold because".split()
    times = [63.54, 64.14, 64.34, 64.62, 65.34, 68.04, 68.20, 68.48, 68.98, 69.42, 69.72, 70.2]
    heard: list = [None] * len(wins)
    heard[k] = {
        "language": "en", "language_probability": 1.0,
        "words": [{"word": t, "start": s - base, "end": s - base + 0.2} for t, s in zip(clip, times)],
    }
    words, report = relisten.merge(FIRST_PASS, wins, heard)
    said = " ".join(x["text"] for x in words)
    assert "And then that question, and then that question stopped me cold because" in said
    assert said.startswith("I was preparing a session about selling,")  # outside the stretch: untouched
    assert [r["result"] for r in report if r["result"] != "same"] == ["more words"]


def test_a_stretch_heard_as_another_language_is_marked_not_replaced():
    words = [w("benevolent.", 196.0, 196.5), w("A", 201.87, 202.39), w("coach", 209.75, 210.27),
             w("is", 210.27, 210.43), w("a", 210.43, 210.55), w("person.", 210.55, 210.89)]
    wins = relisten.windows(words)
    k = next(n for n, x in enumerate(wins) if x.first <= 1 <= x.last)
    assert wins[k].why == ['"A" stands on its own']
    assert wins[k].start < 201.5  # the Hebrew starts 0.4 s before the recogniser's "A"
    heard: list = [None] * len(wins)
    heard[k] = {"language": "en", "language_probability": 0.23, "hebrew": "בואו הולכים משם",
                "words": [{"word": "Well,", "start": 0.0, "end": 0.5}]}
    out, report = relisten.merge(words, wins, heard)
    assert out[1]["text"] == "A" and out[1]["lang"] == "other"
    assert out[1]["heard_as"] == "בואו הולכים משם"
    assert report[0]["result"] == "not English"
    # The rules cut it as talk to the dogs, and never glue it onto "coach is a person".
    plan = plan_edit(out, [], aside_names=["Maple", "Rain"])
    assert plan["kept_text"] == "benevolent. coach is a person."
    assert any(r["reason"] == "aside" and r["text"] == "A" for r in plan["removed"])
    # The editor is told what it is.
    assert "NOT ENGLISH" in review_transcript(out) and "בואו הולכים משם" in review_transcript(out)


# The real 28-Sep walk at 9:15, 10 ms levels from 555.46: "make" 555.49-555.67, the "k"
# stop 555.68-555.73, "-ke" 555.74-555.87, the pause 555.88-555.94, "Bring" from 555.95.
# The recogniser wrote only "Bring", 555.68-556.20.
MAKE_BRING = [
    -120, -120, -120, -67, -39, -24, -18, -15, -14, -8, -9, -10, -11, -13, -14, -19, -23, -27,
    -30, -37, -41, -47, -55, -59, -63, -63, -68, -64, -48, -33, -33, -30, -26, -29, -31, -27,
    -30, -30, -34, -46, -51, -50, -63, -68, -78, -86, -88, -85, -60, -43, -36, -31, -34, -34,
    -38, -41, -48, -58, -53, -32, -19, -13, -14, -13, -13, -14, -12, -11, -12, -11, -11, -12,
    -13, -15, -16, -16, -16, -17, -19, -24, -33, -34, -37, -45, -52, -58, -62, -70, -64, -37,
    -33, -16, -12, -12, -13, -13, -13, -13, -13, -14, -21, -34, -44, -48,
]


def make_bring_levels() -> list[float]:
    # Talk before it, half speech and half the phone's digital silence, as on the walk,
    # so the thresholds come out where the walk's did (-42 and -52 dB).
    levels = [-14.0 if (k // 30) % 2 == 0 else -120.0 for k in range(50000)] + [-120.0] * 6000
    for k in range(55410, 55440):
        levels[k] = -15.0  # "it."
    for k, db in enumerate(MAKE_BRING):
        levels[55546 + k] = float(db)
    return levels


BRING = [w("it.", 554.16, 554.50), w("Bring", 555.68, 556.20), w("people", 556.20, 556.60)]


def hearing(said: dict[tuple[float, float], list[tuple[str, float, float]]]):
    """The recogniser, answering each clip with what `said` holds for it (absolute times)."""
    asked: list[tuple[float, float, str]] = []

    async def hear(a: float, b: float, why: str):
        asked.append((round(a, 2), round(b, 2), why))
        got = said.get((round(a, 2), round(b, 2)))
        if got is None:
            return None
        return {"language": "en", "language_probability": 1.0,
                "words": [{"word": t, "start": s - a, "end": e - a} for t, s, e in got]}

    return hear, asked


# What the recogniser really heard on the VPS on 29-Sep, clip by clip.
WALK_HEARD = {
    (555.40, 556.25): [("but", 555.40, 555.70), ("bring", 555.70, 556.04)],
    (555.92, 556.25): [("bring", 555.90, 556.14)],
    (555.71, 556.25): [("bring", 555.70, 556.08)],
}


def leads_of(words):
    from tce.production.tightcut import find_activity

    levels = make_bring_levels()
    act = find_activity(levels)
    return relisten.lead_candidates(words, levels, act.low_db, act.high_db, act.regions), act


def test_a_false_start_heard_before_a_word_is_cut_at_the_pause_not_the_stop():
    leads, act = leads_of(BRING)
    assert [x.index for x in leads] == [1]
    assert abs(leads[0].start - 555.49) < 0.03  # from where the sound starts, not the stamp
    assert leads[0].runs == [(555.68, 555.74), (555.88, 555.95)]  # the "k", then before "B"
    hear, asked = hearing(WALK_HEARD)
    cuts = asyncio.run(relisten.find_cuts(BRING, leads, hear))
    # The recogniser's own boundary (555.70) is the "k"; the rest is heard as "bring"
    # from the later silence too, so that is where it goes.
    assert [(c[1], c[2]) for c in cuts] == [((555.88, 555.95), "but")]
    assert [x[:2] for x in asked] == [(555.40, 556.25), (555.92, 556.25)]
    assert 'the start of "Bring" at 9:15.50' in asked[0][2]
    out, report = relisten.split_leading_sounds(BRING, cuts)
    assert [x["text"] for x in out] == ["it.", "[sound]", "Bring", "people"]
    assert out[1]["end_s"] == 555.88 and out[2]["start_s"] == 555.95
    assert report[0]["before"] == "Bring" and report[0]["heard_as"] == "but"
    plan = plan_edit(out, [], duration_s=560.0, activity=act, aside_names=[])
    assert plan["kept_text"] == "it. Bring people"
    assert [r["reason"] for r in plan["removed"]] == ["sound"]
    assert not any(s <= 555.8 <= e for s, e in plan["keep"])  # no "-ke" left in the edit
    assert any(s <= 555.96 and e >= 556.5 for s, e in plan["keep"])  # "Bring" whole
    assert "[sound]" not in " ".join(" ".join(c["lines"]) for c in build_cues(plan))


def test_the_cut_moves_earlier_when_the_rest_is_not_heard_as_the_word():
    # A stop inside the word itself ("may-be"): from the later silence the rest is heard
    # as something shorter, so the cut goes at the earlier one; never whole, never cut.
    leads, _ = leads_of(BRING)
    hear, _ = hearing({**WALK_HEARD, (555.92, 556.25): [("ring", 555.95, 556.14)]})
    assert [c[1] for c in asyncio.run(relisten.find_cuts(BRING, leads, hear))] == [(555.68, 555.74)]
    hear, _ = hearing({**WALK_HEARD, (555.92, 556.25): [("ring", 555.95, 556.14)],
                       (555.71, 556.25): [("ring", 555.75, 556.14)]})
    assert asyncio.run(relisten.find_cuts(BRING, leads, hear)) == []


def test_a_long_word_heard_again_as_itself_is_left_whole():
    leads, _ = leads_of(BRING)
    for said in ({(555.40, 556.25): [("Bring", 555.52, 556.2)]},  # alone
                 {(555.40, 556.25): [("Well,", 555.5, 555.7), ("ring", 555.9, 556.1)]},  # something else
                 {}):  # not heard
        hear, asked = hearing(said)
        assert asyncio.run(relisten.find_cuts(BRING, leads, hear)) == []
        assert len(asked) == 1  # and nothing more is asked
    assert relisten.split_leading_sounds(BRING, []) == (BRING, [])


def test_talk_to_the_dogs_is_not_a_lead():
    words = [dict(x) for x in BRING]
    words[1]["lang"] = "he"
    assert leads_of(words)[0] == []


def test_a_long_word_whose_early_part_is_quiet_is_not_a_lead():
    # "Which" stamped 0.38 s before he speaks: early, not hiding a word.
    words = [w("transformation.", 351.0, 351.88), w("Which", 355.63, 356.31)]
    levels = [-120.0] * 36000
    for k in range(35600, 35640):
        levels[k] = -15.0
    assert relisten.lead_candidates(words, levels, low_db=-52.0, high_db=-42.0) == []


def test_a_word_straight_after_another_is_never_a_lead():
    words = [w("manipulative.", 106.3, 106.96), w("It", 106.96, 107.88)]
    levels = [-15.0] * 11000
    assert relisten.lead_candidates(words, levels, low_db=-52.0, high_db=-42.0) == []


def test_an_unheard_stretch_changes_nothing():
    wins = relisten.windows(FIRST_PASS)
    out, report = relisten.merge(FIRST_PASS, wins, [None] * len(wins))
    assert out == FIRST_PASS and report == []
