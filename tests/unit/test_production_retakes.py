"""Deterministic edit planning: retakes, pauses, meaning check, captions. Synthetic text only."""

from tce.production.retakes import build_cues, negations_in, plan_edit, to_srt, to_vtt

SCRIPT = [
    "Most small studios lose leads in the first hour.",
    "Answer every new inquiry within ten minutes.",
    "Do not send a price list before the first call.",
]


def seg(start, end, text):
    return {"start_s": start, "end_s": end, "text": text}


def test_retake_keeps_last_complete_take_and_drops_false_start():
    timings = [
        seg(0.0, 3.0, "Most small studios lose leads in the first hour."),
        seg(3.5, 4.5, "Answer every new"),  # false start
        seg(6.5, 9.0, "Answer every new inquiry within ten minutes."),  # take 1
        seg(9.5, 12.0, "Answer every new inquiry within ten minutes."),  # take 2 (kept)
        seg(12.3, 15.0, "Do not send a price list before the first call."),
    ]
    plan = plan_edit(timings, SCRIPT)
    kept = [u for u in plan["units"] if u["kept"]]
    assert [u["start"] for u in kept] == [0.0, 9.5, 12.3]
    reasons = {d["start"]: d["reason"] for d in plan["dropped"] if d["text"]}
    assert reasons == {3.5: "false_start", 6.5: "retake"}
    assert plan["meaning_check"]["status"] == "ok"
    # The dropped takes are cut out of the timeline
    for s, e in plan["keep"]:
        assert not (s < 9.0 and e > 6.5)


def test_dropped_negation_blocks_plan():
    timings = [
        seg(0.0, 3.0, "Do not send a price list before the first call."),
        seg(3.5, 6.0, "Do send a price list before the first call."),
    ]
    plan = plan_edit(timings, SCRIPT)
    mc = plan["meaning_check"]
    assert mc["status"] == "blocked"
    kinds = {i["kind"] for i in mc["issues"]}
    assert "negation_dropped" in kinds
    detail = next(i["detail"] for i in mc["issues"] if i["kind"] == "negation_dropped")
    assert "not" in detail and "0:03" in detail


def test_hebrew_negation_with_prefix_blocks_plan():
    script = ["אל תשלחו מחירון לפני השיחה הראשונה"]
    timings = [
        seg(0.0, 3.0, "ולא לשלוח מחירון לפני השיחה הראשונה"),
        seg(3.4, 6.0, "לשלוח מחירון לפני השיחה הראשונה"),
    ]
    assert negations_in("ולא לשלוח") == ["לא"]
    plan = plan_edit(timings, script)
    assert plan["meaning_check"]["status"] == "blocked"
    assert any(i["kind"] == "negation_dropped" for i in plan["meaning_check"]["issues"])


def test_unmatched_free_speech_is_kept():
    timings = [
        seg(0.0, 3.0, "Most small studios lose leads in the first hour."),
        seg(3.3, 7.0, "By the way, this happened to me on a rainy Tuesday walk."),
        seg(7.2, 10.0, "Answer every new inquiry within ten minutes."),
    ]
    plan = plan_edit(timings, SCRIPT)
    assert all(u["kept"] for u in plan["units"])
    assert "rainy Tuesday" in plan["kept_text"]
    assert plan["meaning_check"]["status"] == "ok"


def test_truncated_kept_take_blocks():
    timings = [
        seg(0.0, 4.0, "Answer every new inquiry within ten minutes, even on weekends."),
        seg(4.5, 7.0, "Answer every new inquiry within ten minutes."),
    ]
    plan = plan_edit(timings, ["Answer every new inquiry within ten minutes, even on weekends."])
    kinds = {i["kind"] for i in plan["meaning_check"]["issues"]}
    assert "truncated_take" in kinds
    assert plan["meaning_check"]["status"] == "blocked"


def test_long_pause_trimmed_and_word_level_grouping():
    words = [
        {"start": 0.0, "end": 0.4, "word": "Answer"},
        {"start": 0.45, "end": 0.8, "word": "every"},
        {"start": 0.85, "end": 1.2, "word": "inquiry."},
        {"start": 5.0, "end": 5.4, "word": "Then"},
        {"start": 5.45, "end": 5.9, "word": "follow"},
        {"start": 5.95, "end": 6.3, "word": "up."},
    ]
    plan = plan_edit(words, [], pause_threshold_s=1.0)
    assert len(plan["units"]) == 2
    assert len(plan["keep"]) == 2
    assert any(d["reason"] == "pause" and d["start"] < 2 and d["end"] > 4 for d in plan["dropped"])
    assert plan["stats"]["kept_seconds"] < 3.5  # 6.3 s of audio, ~3.8 s pause removed


def test_captions_retimed_non_overlapping_and_short_lines():
    long_line = (
        "Most small studios lose leads in the first hour because nobody owns the inbox "
        "and every message waits for the owner to finish a session."
    )
    timings = [
        seg(0.0, 2.0, "Answer every new"),
        seg(10.0, 16.0, long_line),
        seg(20.0, 23.0, "Answer every new inquiry within ten minutes."),
    ]
    plan = plan_edit(timings, SCRIPT, pause_threshold_s=1.0)
    cues = build_cues(plan)
    assert cues[0]["start"] < 0.5  # re-timed onto the edited timeline
    total = plan["stats"]["kept_seconds"]
    for a, b in zip(cues, cues[1:], strict=False):
        assert a["end"] <= b["start"]
    for c in cues:
        assert c["end"] <= total + 0.01
        assert all(len(line) <= 42 for line in c["lines"])
        assert len(c["lines"]) <= 2
    srt = to_srt(cues)
    vtt = to_vtt(cues)
    assert srt.startswith("1\n00:00:00,")
    assert vtt.startswith("WEBVTT")
    assert cues[0]["lines"][0].startswith("Most small studios")  # false start not captioned


def test_distinct_complete_sentence_is_flagged_not_silently_dropped():
    first = "I coach small business owners to make better decisions."
    second = "I coach small business owners to build better teams."
    plan = plan_edit([seg(0, 4, first), seg(5, 9, second)], [first])
    mc = plan["meaning_check"]
    assert mc["status"] == "blocked"
    issue = next(i for i in mc["issues"] if i["kind"] == "content_dropped")
    assert "decisions" in issue["detail"] and "make" in issue["detail"]
