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


def test_a_line_said_twice_keeps_the_complete_later_take():
    words = (
        said("Strategy sessions can be free too.", 0.0)
        + said("So go and work for free until you do.", 3.0)
        + said("So go and work for free for a while.", 7.0)
        + said("Bring people value.", 11.0)
    )
    plan = plan_edit(words, [], aside_names=DOGS)
    assert kept_text(plan).count("So go and work for free") == 1
    assert "for a while." in kept_text(plan) and "until you do" not in kept_text(plan)
    assert plan["meaning_check"]["status"] == "ok"
    assert [r["reason"] for r in plan["removed"]] == ["retake"]


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


def test_a_dropped_word_running_into_a_kept_one_is_cut_at_the_dip_between_them():
    # 28-Sep: "coached." ran into a dropped "Which"; cutting on the recogniser's
    # boundary (0.2 s late) left "Whi-" in the edit. The audio dips at 1.62-1.64.
    words = [
        {"text": "coached.", "start_s": 1.0, "end_s": 1.84, "precision": "word"},
        {"text": "Which", "start_s": 1.84, "end_s": 2.9, "precision": "word"},
    ]
    levels = [tightcut.SILENT_DB] * 400
    for k in range(100, 162):
        levels[k] = -15.0  # "coached"
    for k in range(162, 164):
        levels[k] = -60.0  # the dip
    for k in range(164, 200):
        levels[k] = -20.0  # "Which"
    act = find_activity(levels)
    keep, _ = tight_keep(words, [True, False], act, 4.0)
    assert len(keep) == 1
    assert 1.6 <= keep[0][1] <= 1.67, keep  # at the dip, not at 1.89


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
