"""What the 29-Sep review of the second listen found, one test each. Synthetic, with the
real 28-Sep numbers where they matter."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from tce.production import media, relisten, wordbox
from tce.production.retakes import build_cues, plan_edit, uncut_plan


def w(text: str, start: float, end: float, **extra) -> dict:
    return {"text": text, "start_s": start, "end_s": end, "precision": "word", **extra}


def clip(win: relisten.Window, said: list[tuple[str, float, float]], **extra) -> dict:
    return {"language": "en", "language_probability": 1.0, **extra,
            "words": [{"word": t, "start": s - win.start, "end": e - win.start} for t, s, e in said]}


# The walk at 1:03-1:12, as the recogniser first heard it, and the speech on the audio:
# the first take 64.00-65.57, 2.4 s of digital silence, the second take 67.93-70.30.
FIRST_PASS = [
    w("I", 55.62, 55.98), w("was", 55.98, 56.14), w("preparing", 56.14, 56.52),
    w("a", 56.52, 56.76), w("session", 56.76, 57.14), w("about", 57.14, 57.62),
    w("selling,", 57.62, 58.14),
    w("and", 63.72, 64.10), w("then", 64.10, 64.30), w("that", 64.30, 64.62),
    w("question", 66.19, 68.97), w("stopped", 68.97, 69.37), w("me", 69.37, 69.69),
    w("cold", 69.69, 70.15), w("because", 70.15, 71.35),
    w("I", 78.20, 78.46), w("hear", 78.46, 78.80), w("it.", 78.80, 78.96),
]
REGIONS = [(55.6, 58.2), (64.0, 65.57), (67.93, 70.3), (78.2, 79.0)]
# What the VPS heard over 63.22-71.85 on 29-Sep, word for word.
HEARD = [("And", 63.22, 64.14), ("then", 64.14, 64.34), ("that", 64.34, 64.64),
         ("question,", 64.64, 65.3), ("and", 65.5, 68.06), ("then", 68.06, 68.2),
         ("that", 68.2, 68.48), ("question", 68.48, 69.0), ("stopped", 69.0, 69.42),
         ("me", 69.42, 69.72), ("cold.", 69.72, 70.16)]


def heard_again() -> list[dict]:
    wins = relisten.windows(FIRST_PASS)
    k = next(n for n, x in enumerate(wins) if x.first <= 10 <= x.last)
    heard: list = [None] * len(wins)
    heard[k] = clip(wins[k], HEARD)
    out, _ = relisten.merge(FIRST_PASS, wins, heard, regions=REGIONS)
    return out


def test_a_word_heard_again_is_moved_onto_its_speech():
    out = heard_again()
    second_and = next(x for x in out if x["text"] == "and")
    assert (second_and["start_s"], second_and["end_s"]) == (67.93, 68.06)  # not 65.50-68.06
    assert next(x for x in out if x["text"] == "And")["start_s"] == 64.0  # not in the silence before


def test_note_1_the_rules_edit_keeps_only_the_complete_take():
    # When the editor's review is late, the rules render first: "and then that question,
    # and then that question stopped me cold" must come out once.
    plan = plan_edit(heard_again(), [], aside_names=[])
    assert "question, and then that question" not in plan["kept_text"]
    assert "and then that question stopped me cold." in plan["kept_text"]
    assert any(r["reason"] in ("false_start", "retake") and r["text"].startswith("And then that question")
               for r in plan["removed"])


def test_a_restart_glued_onto_a_sentence_is_taken_out_of_it():
    words = [w("I", 1.0, 1.2), w("was", 1.2, 1.4), w("preparing,", 1.4, 1.9),
             w("and", 2.6, 2.8), w("then", 2.8, 3.0), w("that", 3.0, 3.2), w("question,", 3.2, 3.7),
             w("and", 5.9, 6.1), w("then", 6.1, 6.3), w("that", 6.3, 6.5), w("question", 6.5, 6.9),
             w("stopped", 6.9, 7.2), w("me.", 7.2, 7.5)]
    plan = plan_edit(words, [], aside_names=[])
    assert plan["kept_text"] == "I was preparing, and then that question stopped me."


def test_a_hallucination_over_silence_is_not_more_words():
    # A clip heard over a quiet pad can add "Thank you." where nothing was said.
    words = [w("Here's", 91.9, 92.2), w("the", 92.2, 92.3), w("picture", 92.3, 92.7),
             w("in", 92.7, 92.8), w("their", 92.8, 93.0), w("head.", 93.0, 93.5)]
    wins = relisten.windows(words)
    said = [(x["text"], x["start_s"], x["end_s"]) for x in words] + [("Thank", 93.9, 94.2), ("you.", 94.2, 94.5)]
    out, report = relisten.merge(words, wins, [clip(wins[0], said)], regions=[(91.9, 93.5)])
    assert out == words and report[0]["result"] == "same"


def test_words_the_first_pass_invented_do_not_count_against_a_recovery():
    # Eight 20 ms words at the end of the walk were recognition noise; a clip that hears
    # the real speech plus a dropped word must still count as more words.
    real = [w("Bring", 555.9, 556.2), w("people", 556.2, 556.6), w("value.", 556.6, 557.1)]
    junk = [w(t, 561.48 + 0.02 * k, 561.50 + 0.02 * k) for k, t in enumerate("don't want your sales don't need So You".split())]
    words = [w("it.", 554.2, 554.5)] + real + junk
    win = relisten.Window(553.9, 562.5, 0, len(words) - 1, ["test"], [(0, len(words) - 1)])
    said = [("it.", 554.2, 554.5), ("make", 555.5, 555.8), ("Bring", 555.9, 556.2),
            ("people", 556.2, 556.6), ("value.", 556.6, 557.1)]
    # The invented words sit over real sound (wind, a step): only their length gives them away.
    regions = [(554.2, 554.5), (555.5, 557.1), (561.4, 562.0)]
    out, report = relisten.merge(words, [win], [clip(win, said)], regions=regions)
    assert report[0]["result"] == "more words"
    assert [x["text"] for x in out] == ["it.", "make", "Bring", "people", "value."]


def test_a_stretch_that_is_not_all_english_is_judged_line_by_line():
    # "Selling is the first step." / 1.5 s / Hebrew to the dogs / 1.5 s / "The sale is
    # where the coaching starts.": one verdict for the stretch would cut both English lines.
    words = [w("Selling", 10.0, 10.4), w("is", 10.4, 10.5), w("the", 10.5, 10.6), w("first", 10.6, 10.9),
             w("step.", 10.9, 11.3), w("A", 12.8, 13.2),
             w("The", 14.7, 14.9), w("sale", 14.9, 15.2), w("is", 15.2, 15.3), w("where", 15.3, 15.5),
             w("the", 15.5, 15.6), w("coaching", 15.6, 16.0), w("starts.", 16.0, 16.4)]
    wins = relisten.windows(words)
    assert len(wins) == 1 and len(wins[0].utts) == 3
    assert [round(a, 2) for a, _ in relisten.utterance_clips(words, wins[0])] == [9.5, 12.3, 14.2]
    en = {"language": "en", "language_probability": 0.99, "words": []}
    he = {"language": "he", "language_probability": 0.9, "words": [], "hebrew": "בואו"}
    res = {"language": "en", "language_probability": 0.45, "words": [], "parts": [en, he, en]}
    out, report = relisten.merge(words, wins, [res])
    assert [x["text"] for x in out if x.get("lang")] == ["A"]
    assert out[5]["heard_as"] == "בואו"
    plan = plan_edit(out, [], aside_names=[])
    assert plan["kept_text"] == "Selling is the first step. The sale is where the coaching starts."


def test_a_window_never_grows_past_what_the_recogniser_hears_at_once():
    # Twelve short lines 1.5 s apart used to chain into one 30 s window.
    words, t = [], 99.5
    for k in range(12):
        for tok in ("one", "two", "three."):
            words.append(w(tok, t, t + 0.3))
            t += 0.3
        t += 1.5 if k % 2 else 1.1
    wins = relisten.windows(words)
    assert wins and max(x.end - x.start for x in wins) <= relisten.MAX_WINDOW_S
    covered = sorted(i for x in wins for i in range(x.first, x.last + 1))
    assert covered == sorted(set(covered))  # no word heard twice


def test_a_silence_running_past_the_word_is_not_inside_it():
    # The Hebrew "A" at 3:21: its lead's only silence ran on 1.6 s past the word's end.
    words = [w("benevolent.", 196.0, 196.5), w("A", 201.87, 202.39)]
    levels = [-120.0] * 21000
    for k in range(19600, 19650):
        levels[k] = -15.0
    for k in range(20146, 20201):
        levels[k] = -20.0
    for k in range(20401, 20450):
        levels[k] = -15.0
    assert relisten.lead_candidates(words, levels, low_db=-52.0, high_db=-42.0) == []


def test_a_sound_word_does_not_hide_a_restart_from_the_rules():
    words = [w("So", 1.0, 1.2), w("go", 1.2, 1.4), w("and", 1.4, 1.6), w("work", 1.6, 1.9),
             w("for", 1.9, 2.1), w("free.", 2.1, 2.5),
             w("[sound]", 4.0, 4.23, sound=True),
             w("So", 4.3, 4.5), w("go", 4.5, 4.7), w("and", 4.7, 4.9), w("work", 4.9, 5.2),
             w("for", 5.2, 5.4), w("free", 5.4, 5.7), w("for", 5.7, 5.9), w("a", 5.9, 6.0), w("while.", 6.0, 6.4)]
    plan = plan_edit(words, [], aside_names=[])
    assert plan["kept_text"] == "So go and work for free for a while."
    cues = build_cues(uncut_plan(plan, 7.0))
    assert "[sound]" not in " ".join(" ".join(c["lines"]) for c in cues)


def test_a_clip_the_worker_never_answers_times_out(monkeypatch):
    async def silent(*_a, **_k):
        await asyncio.sleep(3600)

    monkeypatch.setattr(media, "_transcribe_clip", silent)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(media.transcribe_clip("x.mp4", 1.0, 2.0, ws_url="ws://x", timeout_s=0.2))
    with pytest.raises(ValueError):
        asyncio.run(media.transcribe_clip("x.mp4", 203.98, 202.44, ws_url="ws://x"))


def test_the_second_listen_record_survives_a_re_plan_and_a_new_transcript_clears_it():
    from tce.api.routers import production as P

    marker = {"state": "done", "windows": 9, "heard": 9, "changes": [], "sounds": []}
    words = FIRST_PASS
    row = SimpleNamespace(
        edit_plan={"second_listen": marker, "review": {"state": "done", "removals": []}},
        transcript=words, packet_id=None, storage_path=None,
        duration_s=80.0, status="transcribed", status_detail=None,
    )
    asyncio.run(P._compute_plan(None, uuid.uuid4(), row))
    assert row.edit_plan["second_listen"] == marker
    P._new_transcript(row, words)
    assert "second_listen" not in row.edit_plan


def test_a_line_is_filled_by_what_is_drawn():
    got = wordbox.pages([{"text": t, "start": k * 0.3, "end": k * 0.3 + 0.25}
                         for k, t in enumerate("We had to go.".split())])
    assert [[x["text"] for x in line] for line in got[0].lines] == [["We", "had", "to", "go."]]
    assert [wordbox.shown(t) for t in ["U.S.", "a.m.", "go.", "5.5", "wait..."]] == ["U.S.", "a.m.", "go", "5.5", "wait"]
