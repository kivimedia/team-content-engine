"""The 28-Sep edit: word decisions and a cut placed by the audio. Synthetic data.

"the editing is not as punchy as the TJ digital video editing (inaccurate cuts that
leave more silent space that is boring)" and "when I repeat a line twice (even
partially) the editor is supposed to choose one that is full. If I call my dogs maple,
rain bou that needs to be edited out. if I say no no no rain that needs to be taken
out." Each shape below is one that the "Selling is the first step" edit got wrong.
"""

from __future__ import annotations

from tce.production import tightcut
from tce.production.retakes import build_cues, plan_edit
from tce.production.tightcut import Activity, find_activity, parse_levels, tight_keep

DOGS = ["Maple", "Rain"]


def said(text: str, start: float, step: float = 0.3, gap_after: float = 0.0) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start_s": round(t, 3), "end_s": round(t + step - 0.05, 3),
                    "precision": "word"})
        t += step
    return out


def kept_text(plan: dict) -> str:
    return plan["kept_text"]


def test_a_lone_word_before_a_pause_joins_its_sentence_instead_of_being_a_false_start():
    # 28-Sep: "A" ... 7 s ... "coach is a person..." was cut as a false start and the
    # caption read "coach is a person that takes you from point A to point B."
    words = (
        said("A coach is a guide who makes your life better.", 0.0)
        + said("A", 10.0)
        + said("coach is a person that takes you from point A to point B.", 17.0)
    )
    script = ["A coach is a guide who makes your life better."]
    plan = plan_edit(words, script, aside_names=DOGS)
    assert "A coach is a person that takes you" in kept_text(plan)
    assert kept_text(plan).startswith("A coach is a guide")


def test_a_partial_repeat_keeps_the_complete_take():
    words = (
        said("Strategy sessions can be free too.", 0.0)
        + said("So go and work for free", 3.0)  # he stops and says it again, whole
        + said("So go and work for free for a while.", 7.0)
        + said("Bring people value.", 11.0)
    )
    plan = plan_edit(words, [], aside_names=DOGS)
    assert kept_text(plan).count("So go and work for free") == 1
    assert "for a while." in kept_text(plan)
    assert plan["meaning_check"]["status"] == "ok"
    assert [r["reason"] for r in plan["removed"]] == ["false_start"]


def test_when_the_rules_decide_two_takes_that_differ_in_a_word_both_stay():
    # "before" vs "after" may be a second point, not a retake: the rules keep both
    # (the editor's review is the one that chooses), and nothing is blocked.
    words = said("Call them before you pitch.", 0.0) + said("Call them after you pitch.", 3.0)
    plan = plan_edit(words, [], aside_names=DOGS)
    assert kept_text(plan) == "Call them before you pitch. Call them after you pitch."
    assert plan["meaning_check"]["status"] == "ok"


def test_the_editors_reworded_retake_is_a_note_but_a_lost_not_still_blocks():
    words = said("So go and work for free until you do.", 0.0) + said(
        "So go and work for free for a while.", 4.0
    )
    removals = [{"start": 0.0, "end": 2.6, "text": "So go and work for free until you do.",
                 "kind": "retake", "keeper_start": 4.0}]
    plan = plan_edit(words, [], aside_names=DOGS, removals=removals)
    assert plan["meaning_check"]["status"] == "ok"
    assert [n["kind"] for n in plan["meaning_check"]["notes"]] == ["content_dropped"]
    assert kept_text(plan) == "So go and work for free for a while."


def test_rain_in_a_sentence_is_not_a_dog():
    words = said("It looks like rain today.", 0.0) + said("Okay, here we go.", 2.5) + said(
        "Maple syrup is great.", 5.0
    )
    plan = plan_edit(words, [], aside_names=DOGS)
    assert kept_text(plan) == "It looks like rain today. Okay, here we go. Maple syrup is great."


def test_an_abandoned_restart_keeps_the_full_take_that_came_first():
    words = (
        said("If you trust your sales process, people will trust you as well.", 0.0)
        + said("If you trust your sales", 5.0)  # trails off, never finished
        + said("Bring people value.", 9.0)
    )
    plan = plan_edit(words, [], aside_names=DOGS)
    assert "people will trust you as well." in kept_text(plan)
    assert kept_text(plan).count("If you trust your sales") == 1


def test_a_start_split_by_a_pause_and_then_said_again_goes_as_one_take():
    words = (
        said("Which", 0.0)
        + said("means that the sales call is the first step of the transformation.", 11.0)
        + said("Which means that the sales call is the first step in the transformation.", 19.0)
    )
    plan = plan_edit(words, [], aside_names=DOGS)
    assert kept_text(plan) == "Which means that the sales call is the first step in the transformation."


def test_talking_to_the_dogs_and_no_no_no_are_cut():
    words = (
        said("It reminds them of a used car lot.", 0.0)
        + said("Hey, Maple Rain, boy!", 4.0)
        + said("Boy, from here!", 6.0)
        + said("We're here, we're here.", 7.5)
        + said("But that is not how they see themselves.", 12.0)
        + said("No, no, no, no.", 20.0)
        + said("A coach takes you from point A to point B.", 30.0)
    )
    plan = plan_edit(words, [], aside_names=DOGS)
    text = kept_text(plan)
    for gone in ("Maple", "Boy", "from here", "We're here", "No, no"):
        assert gone not in text, gone
    assert text == (
        "It reminds them of a used car lot. But that is not how they see themselves. "
        "A coach takes you from point A to point B."
    )
    assert {r["reason"] for r in plan["removed"]} == {"aside"}
    # Dropping "No, no, no" is not a dropped negation: it had nothing to supersede.
    assert plan["meaning_check"]["status"] == "ok"


def test_a_short_no_answer_that_is_part_of_the_point_stays():
    words = said("Is selling evil?", 0.0) + said("No.", 1.5) + said("It is the first step.", 2.5)
    plan = plan_edit(words, [], aside_names=DOGS)
    assert kept_text(plan) == "Is selling evil? No. It is the first step."


def test_recogniser_junk_and_fillers_are_cut():
    words = said("They want to work with you.", 0.0)
    words += [
        {"text": t, "start_s": 1.8 + i * 0.02, "end_s": 1.82 + i * 0.02, "precision": "word"}
        for i, t in enumerate("don't want your sales don't need".split())
    ]
    words += said("So um you win.", 3.0)
    plan = plan_edit(words, [], aside_names=DOGS)
    assert kept_text(plan) == "They want to work with you. So you win."
    assert plan["stats"]["fillers"] == 1
    assert any(r["reason"] == "junk" for r in plan["removed"])


def test_his_restore_brings_back_what_a_rule_cut():
    words = said("Hey, Maple Rain, boy!", 0.0) + said("Selling is the first step.", 3.0)
    plan = plan_edit(words, [], aside_names=DOGS, overrides={"restore": [[0.0, 1.2]], "cut": []})
    assert kept_text(plan).startswith("Hey, Maple Rain, boy!")
    plan = plan_edit(words, [], aside_names=DOGS, overrides={"cut": [[3.0, 3.6]], "restore": []})
    assert kept_text(plan) == "the first step."


def test_review_removals_decide_instead_of_the_rules_and_keep_the_meaning_check():
    words = said("Do not send a price list first.", 0.0) + said("Do send a price list first.", 3.0)
    removals = [{"start": 0.0, "end": 2.0, "text": "Do not send a price list first.",
                 "kind": "retake", "keeper_start": 3.0}]
    plan = plan_edit(words, [], aside_names=DOGS, removals=removals)
    assert plan["decided_by"] == "editor_review"
    assert plan["meaning_check"]["status"] == "blocked"  # a dropped "not" still needs his eyes
    assert any(i["kind"] == "negation_dropped" for i in plan["meaning_check"]["issues"])


# ---------------------------------------------------------------------------
# The cut, placed by the audio


def speech_levels(spans: list[tuple[float, float]], total: float, hop: float = 0.01) -> list[float]:
    """-15 dB where he speaks, digital zero elsewhere (his phone gates the mic)."""
    out = []
    for i in range(int(total / hop)):
        t = i * hop
        out.append(-15.0 if any(a <= t < b for a, b in spans) else tightcut.SILENT_DB)
    return out


def test_levels_parse_the_ffmpeg_print_and_silence():
    text = (
        "frame:0 pts:0 pts_time:0\nlavfi.astats.Overall.RMS_level=-inf\n"
        "frame:1 pts:80 pts_time:0.01\nlavfi.astats.Overall.RMS_level=-23.5\n"
    )
    assert parse_levels(text) == [tightcut.SILENT_DB, -23.5]


def test_edges_snap_to_the_speech_not_to_the_recognisers_clock():
    # The recogniser starts "Which" 0.4 s early and runs "It" 0.5 s into silence.
    words = [
        {"text": "It", "start_s": 1.0, "end_s": 1.9, "precision": "word"},
        {"text": "works.", "start_s": 1.9, "end_s": 2.3, "precision": "word"},
        {"text": "Which", "start_s": 5.6, "end_s": 6.3, "precision": "word"},
        {"text": "helps.", "start_s": 6.3, "end_s": 6.8, "precision": "word"},
    ]
    act = find_activity(speech_levels([(1.0, 1.4), (1.5, 2.0), (6.0, 6.7)], 8.0))
    keep, timed = tight_keep(words, [True] * 4, act, 8.0)
    # Two pieces: the first ends a breath after the speech, the second starts just before.
    assert len(keep) == 2
    assert 2.0 < keep[0][1] <= 2.2 and 5.9 <= keep[1][0] < 6.0
    # Every edge is on the 30 fps grid, so picture and sound cut at the same instant.
    for s, e in keep:
        assert abs(s * 30 - round(s * 30)) < 1e-3 and abs(e * 30 - round(e * 30)) < 1e-3
    which = next(w for w in timed if w["text"] == "Which")
    assert which["start"] >= 5.95  # the box lights with his voice, not 0.4 s before


def test_a_long_pause_inside_a_sentence_becomes_a_breath_and_a_short_one_stays():
    words = said("one two three", 0.0, step=0.4) + said("four five", 4.0, step=0.4)
    spans = [(0.0, 0.35), (0.4, 0.75), (0.8, 1.15), (1.35, 1.55), (4.0, 4.35), (4.4, 4.75)]
    act = find_activity(speech_levels(spans, 6.0))
    keep, _ = tight_keep(words, [True] * 5, act, 6.0)
    stats = tightcut.pause_stats(keep, act)
    assert stats["max_pause_s"] <= 0.3 and stats["pauses_over_half_second"] == 0
    # The 0.2 s gap inside "three" stays whole; the 2.45 s pause before "four" is gone.
    total = sum(e - s for s, e in keep)
    assert total < 3.0  # 4.75 s of recording


def test_a_bark_in_a_pause_is_not_kept_as_speech():
    words = said("one two", 0.0, step=0.4) + said("three four", 6.0, step=0.4)
    spans = [(0.0, 0.75), (3.0, 3.3), (6.0, 6.75)]  # 3.0-3.3 is the dog
    act = find_activity(speech_levels(spans, 8.0))
    keep, _ = tight_keep(words, [True] * 4, act, 8.0)
    assert not any(s <= 3.1 <= e for s, e in keep)


def test_a_quiet_word_the_envelope_misses_is_still_kept():
    words = said("loud", 0.0) + said("whisper", 2.0)
    act = Activity(regions=[(0.0, 0.25)], high_db=-40.0, low_db=-50.0)
    keep, timed = tight_keep(words, [True, True], act, 3.0)
    assert any(s <= 2.1 <= e for s, e in keep)
    assert [w["text"] for w in timed] == ["loud", "whisper"]


def test_the_plan_with_audio_reports_pauses_and_captions_only_kept_words():
    words = said("So um here is the point.", 0.0) + said("Hey Maple, come!", 3.0) + said(
        "Selling is the first step.", 6.0
    )
    spans = [(0.0, 1.75), (3.0, 4.0), (6.0, 7.5)]
    act = find_activity(speech_levels(spans, 9.0))
    plan = plan_edit(words, [], duration_s=9.0, activity=act, aside_names=DOGS)
    assert plan["timing"]["snapped_to_audio"] is True
    assert plan["stats"]["pauses"]["pauses_over_half_second"] == 0
    cues = " ".join(" ".join(c["lines"]) for c in build_cues(plan))
    assert "um" not in cues.split() and "Maple" not in cues
    assert "Selling is the first step." in cues


def test_a_stop_inside_a_kept_word_is_not_where_it_ends():
    # 29-Sep, "at 1:28 we cut me saying coached so it sounds like coa": the audio of
    # "coached." dips for 20 ms at the "t" of "coa-ched", and the cut went there. The
    # recogniser had "coached." and the dropped "Which" touching at 1.84, which was right.
    words = [
        {"text": "coached.", "start_s": 1.0, "end_s": 1.84, "precision": "word"},
        {"text": "Which", "start_s": 1.84, "end_s": 2.9, "precision": "word"},
    ]
    levels = [tightcut.SILENT_DB] * 400
    for k in range(100, 160):
        levels[k] = -15.0  # "coa"
    for k in range(160, 164):
        levels[k] = -60.0  # the stop before "-ched"
    for k in range(164, 180):
        levels[k] = -25.0  # "-ched"
    for k in range(180, 188):
        levels[k] = -45.0  # the soft tail into the next word
    for k in range(188, 196):
        levels[k] = -15.0  # "Which"
    act = find_activity(levels)
    keep, _ = tight_keep(words, [True, False], act, 4.0)
    assert len(keep) == 1
    assert 1.79 <= keep[0][1] <= 1.88, keep  # "-ched" stays, "Which" does not


def test_words_the_recogniser_invented_are_not_a_boundary():
    # The walk ended "...work with you." then six 0.02 s words over the fading "you".
    words = said("with you.", 0.0, step=0.3) + [
        {"text": t, "start_s": 0.56 + k * 0.02, "end_s": 0.58 + k * 0.02, "precision": "word"}
        for k, t in enumerate("don't want your".split())
    ]
    act = find_activity(speech_levels([(0.0, 0.8)], 2.0))
    keep, _ = tight_keep(words, [True, True, False, False, False], act, 2.0,
                         audible=[True, True, False, False, False])
    assert keep[-1][1] >= 0.8  # the decay of "you" stays


def test_a_far_neighbour_lets_the_edge_follow_a_late_recogniser():
    # "A" is heard 0.4 s after he starts saying it; the word before was 19 s earlier.
    words = said("no.", 0.0) + [{"text": "A", "start_s": 19.87, "end_s": 20.39, "precision": "word"}]
    act = find_activity(speech_levels([(0.0, 0.25), (19.47, 19.98)], 21.0))
    keep, _ = tight_keep(words, [False, True], act, 21.0)
    assert keep[0][0] <= 19.47


def test_a_short_dropped_um_stays_out_and_a_short_kept_word_stays_in():
    # Review, 28-Sep: the dip search reached past the far edge of a short word.
    hop = 0.01
    levels = [tightcut.SILENT_DB] * 500
    for k in range(100, 118):  # "um" 1.00-1.18, after a pause
        levels[k] = -20.0
    for k in range(118, 200):  # "so the point" straight after it
        levels[k] = -15.0
    words = [
        {"text": "um", "start_s": 1.0, "end_s": 1.18, "precision": "word"},
        {"text": "so", "start_s": 1.18, "end_s": 1.4, "precision": "word"},
        {"text": "the", "start_s": 1.4, "end_s": 1.6, "precision": "word"},
        {"text": "point.", "start_s": 1.6, "end_s": 2.0, "precision": "word"},
    ]
    act = find_activity(levels, hop)
    keep, _ = tight_keep(words, [False, True, True, True], act, 5.0)
    kept_um = sum(max(0.0, min(e, 1.18) - max(s, 1.0)) for s, e in keep)
    assert kept_um < 0.06, keep  # at most the join, never the whole "um"

    levels = [tightcut.SILENT_DB] * 500
    for k in range(100, 200):  # "The point"
        levels[k] = -15.0
    for k in range(206, 220):  # "is" after a 60 ms gap
        levels[k] = -18.0
    for k in range(220, 240):  # a dropped "um" straight after
        levels[k] = -20.0
    words = [
        {"text": "The", "start_s": 1.0, "end_s": 1.4, "precision": "word"},
        {"text": "point", "start_s": 1.4, "end_s": 2.0, "precision": "word"},
        {"text": "is", "start_s": 2.06, "end_s": 2.2, "precision": "word"},
        {"text": "um", "start_s": 2.2, "end_s": 2.4, "precision": "word"},
    ]
    act = find_activity(levels, hop)
    keep, _ = tight_keep(words, [True, True, True, False], act, 5.0)
    kept_is = sum(max(0.0, min(e, 2.2) - max(s, 2.06)) for s, e in keep)
    assert kept_is > 0.1, keep


def test_a_quiet_word_right_after_a_loud_one_is_kept_whole():
    # Review, 28-Sep: a quiet "cat" right after "the" lost 0.28 s of its 0.34 s: it touched
    # the breath padded onto "the", so it never got its own span.
    levels = [tightcut.SILENT_DB] * 400
    for k in range(100, 130):
        levels[k] = -20.0  # "the"
    for k in range(130, 164):
        levels[k] = -60.0  # "cat", too quiet for the speech detector to hear
    for k in range(170, 220):
        levels[k] = -18.0  # "sat."
    words = [
        {"text": "the", "start_s": 1.0, "end_s": 1.3, "precision": "word"},
        {"text": "cat", "start_s": 1.3, "end_s": 1.64, "precision": "word"},
        {"text": "sat.", "start_s": 1.7, "end_s": 2.2, "precision": "word"},
    ]
    act = find_activity(levels)
    keep, _ = tight_keep(words, [True, True, True], act, 4.0)
    kept_cat = sum(max(0.0, min(e, 1.64) - max(s, 1.3)) for s, e in keep)
    assert kept_cat >= 0.3, keep


def test_subtitles_keep_a_word_that_ends_on_a_cut():
    # Review, 28-Sep: "coached." ending at 10.467 against a cut at 10.466667 vanished.
    plan = {
        "keep": [[9.0, 10.466667], [12.0, 13.0]],
        "words": [
            {"index": 0, "text": "We", "start": 9.1, "end": 9.4},
            {"index": 1, "text": "coached.", "start": 9.9, "end": 10.467},
            {"index": 2, "text": "Which", "start": 12.1, "end": 12.5},
        ],
    }
    text = " ".join(" ".join(c["lines"]) for c in build_cues(plan))
    assert text == "We coached. Which"


def test_the_meaning_check_still_blocks_before_turned_into_after():
    # Review, 28-Sep: "before", "after", "until" were added to the words the meaning
    # check ignores, and a dropped "before" take stopped blocking on every path.
    from tce.production.retakes import plan_edit as plan

    rows = [
        {"start_s": 0.0, "end_s": 2.0, "text": "Call them before you pitch."},
        {"start_s": 2.5, "end_s": 4.5, "text": "Call them after you pitch."},
    ]
    result = plan(rows, ["Call them after you pitch."])
    assert result["meaning_check"]["status"] == "blocked"
    assert any(i["kind"] == "content_dropped" for i in result["meaning_check"]["issues"])


def test_speaking_script_points_in_his_own_order_is_not_a_reorder():
    # 28-Sep: the reviewed "Selling" edit was blocked with "the cut would reorder the
    # script" although nothing was cut between the two points; he just said them his way.
    script = ["Selling is the first step.", "Every coach sees themselves as benevolent."]
    words = said("Every coach sees themselves as benevolent.", 0.0) + said(
        "Selling is the first step.", 3.0
    )
    assert plan_edit(words, script, aside_names=DOGS)["meaning_check"]["status"] == "ok"
    removals = []
    assert plan_edit(words, script, aside_names=DOGS, removals=removals)["meaning_check"]["status"] == "ok"


def test_a_retake_choice_that_moves_a_line_after_another_still_needs_his_eyes():
    script = ["Selling is the first step.", "Every coach sees themselves as benevolent."]
    words = (
        said("Selling is the first step.", 0.0)
        + said("Every coach sees themselves as benevolent.", 2.0)
        + said("Selling is the first step.", 5.0)  # said again: the rules keep the last take
    )
    plan = plan_edit(words, script, aside_names=DOGS)
    assert plan["meaning_check"]["status"] == "blocked"
    assert [i["kind"] for i in plan["meaning_check"]["issues"]] == ["script_order"]


def test_a_take_split_by_a_long_pause_is_one_item_on_the_card():
    words = (
        said("Which", 0.0)
        + said("means that the sales call is the first step of the transformation.", 11.0)
        + said("Which means that the sales call is the first step in the transformation.", 19.0)
    )
    removed = plan_edit(words, [], aside_names=DOGS)["removed"]
    assert [r["text"] for r in removed] == [
        "Which means that the sales call is the first step of the transformation."
    ]


def _walk_levels(pairs: dict[int, float], n: int = 20000) -> list[float]:
    # Talk elsewhere so the thresholds land where the walk's did (-41 and -51 dB).
    levels = [-14.0 if (k // 30) % 2 == 0 else -120.0 for k in range(10000)] + [-120.0] * (n - 10000)
    for k, db in pairs.items():
        levels[k] = db
    return levels


def test_a_quiet_word_ending_after_a_dip_is_kept():
    # 30-Sep, "live" at 0:36 of the course video (real 10 ms levels): speech to 36.48, a
    # 100 ms dip under -51 dB, then the "v" at -55..-48 dB, then the phone's silence. The
    # edit cut at 36.60, before the "v". The next kept word is 0.7 s later.
    real = [-13, -14, -15, -18, -22, -28, -34, -36, -37, -38, -39, -50, -60, -63, -65, -64,
            -64, -60, -57, -56, -56, -55, -55, -52, -48, -55, -67, -80, -85, -95]
    levels = _walk_levels({}, 20000)
    for k, db in enumerate(real):
        levels[16338 + k] = float(db)  # 163.38 s on
    for k in range(16420, 16480):
        levels[k] = -13.0  # "program", 0.7 s later
    words = [
        {"text": "live", "start_s": 163.38, "end_s": 163.62, "precision": "word"},
        {"text": "program,", "start_s": 164.20, "end_s": 164.80, "precision": "word"},
    ]
    act = find_activity(levels)
    assert -53 < act.low_db < -50  # the walk's was -51
    keep, _ = tight_keep(words, [True, True], act, 200.0)
    first = next(r for r in keep if r[0] <= 163.4 <= r[1])
    assert first[1] >= 163.63, keep  # the "v" at 163.62 is in


def test_a_tail_never_reaches_into_a_dropped_word():
    levels = _walk_levels({}, 20000)
    for k in range(16338, 16350):
        levels[k] = -13.0  # "so"
    for k in range(16350, 16357):
        levels[k] = -60.0  # a short dip
    for k in range(16357, 16400):
        levels[k] = -50.0  # a quiet dropped "um", right after
    words = [
        {"text": "so", "start_s": 163.38, "end_s": 163.50, "precision": "word"},
        {"text": "um", "start_s": 163.57, "end_s": 164.00, "precision": "word"},
    ]
    keep, _ = tight_keep(words, [True, False], find_activity(levels), 200.0)
    assert keep and keep[-1][1] <= 163.6, keep


def test_a_hold_gives_a_word_more_room():
    from tce.production.tightcut import apply_holds

    keep = [[1.0, 2.0], [2.5, 3.0]]
    assert apply_holds(keep, [[1.95, "end", 0.3]], 10.0) == [[1.0, 2.25], [2.5, 3.0]]
    assert apply_holds(keep, [[1.95, "end", 0.6]], 10.0) == [[1.0, 3.0]]  # meets the next: joined
    assert apply_holds(keep, [[2.52, "start", 0.2]], 10.0) == [[1.0, 2.0], [2.32, 3.0]]
    assert apply_holds(keep, [[5.0, "end", 0.3]], 10.0) == keep  # no edge near: nothing moves


def test_a_tail_never_follows_the_wind():
    # 30-Sep: with echo cancellation off the phone keeps its wind (median -46 dB, never
    # digital silence). A tail floor inside that noise followed it to TAIL_MAX_S on every
    # cut: pauses went from 0.29 to 0.67 s. Only sound above the gap's own noise is a tail.
    levels = [(-20.0 if (k // 30) % 2 == 0 else -60.0) for k in range(10000)] + [-60.0] * 10000
    for k in range(16300, 16350):
        levels[k] = -15.0  # "so"
    for k in range(16350, 16500):
        levels[k] = -58.0 + (k % 3)  # wind, around the speech floor
    for k in range(16500, 16550):
        levels[k] = -15.0  # "go", 1.5 s later
    words = [
        {"text": "so", "start_s": 163.00, "end_s": 163.50, "precision": "word"},
        {"text": "go.", "start_s": 165.00, "end_s": 165.50, "precision": "word"},
    ]
    act = find_activity(levels)
    keep, _ = tight_keep(words, [True, True], act, 200.0)
    first = next(r for r in keep if r[0] <= 163.1 <= r[1])
    assert first[1] <= 163.5 + 0.15, keep  # a breath, not 0.3 s of wind
