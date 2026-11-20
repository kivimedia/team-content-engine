"""Regression tests for Angel's caption notes on the rendered clock."""

import pytest

from tce.production import autoedit, wordbox
from tce.production.creatorz import reels
from tce.production.retakes import build_cues, words_on_edit


def word(text, start, end):
    return {"text": text, "start": start, "end": end}


def test_small_pause_splits_caption_before_the_next_phrase_in_both_formats():
    words = [word("business", 0.1, 0.4), word("now", 0.82, 1.12)]
    keep = [[0, 2]]
    pages = wordbox.pages(words_on_edit(words, keep))
    cues = build_cues({"words": words, "keep": keep})
    assert [p.words[0]["text"] for p in pages] == ["business", "now"]
    assert [c["lines"] for c in cues] == [["business"], ["now"]]
    assert pages[1].start == cues[1]["start"] == 0.82


def test_caption_clock_uses_surviving_frames_across_many_short_cuts():
    keep = [[i + 0.011, i + 0.221] for i in range(8)]
    words = [word("wrong", 1.5, 1.8), word("retained", 7.05, 7.2)]
    # ffmpeg rounds each kept interval to seven frames; the last begins on source second 7.
    expected = 7 * 7 / 30 + 0.05
    timed = words_on_edit(words, keep)
    assert [w["text"] for w in timed] == ["retained"]
    assert timed[0]["start"] == pytest.approx(expected)
    assert build_cues({"words": words, "keep": keep})[0]["start"] == round(expected, 3)


def test_editor_can_request_shorter_phrases_without_cutting_any_audio():
    words = [
        {"text": "business", "start_s": 0.1, "end_s": 0.4},
        {"text": "now", "start_s": 0.68, "end_s": 0.92},
    ]
    answer = {
        "notes": [
            {"note": 1, "caption_gap": "short_pauses", "reply": "Split captions at short pauses."}
        ]
    }
    result = autoedit.apply_batch(words, {"style": "creatorz"}, answer, 1, keep=[[0, 2]])
    assert result["changed"] and result["notes"][0]["outcome"] == "change"
    assert result["overrides"]["cut"] == [] and result["words"] == words
    gap = result["overrides"]["caption_gap_s"]
    assert gap == result["notes"][0]["caption_gap_s"] and 0 < gap <= 0.28
    assert autoedit.merge_overrides(result["overrides"], [], [])["caption_gap_s"] == gap
    assert "caption_gap" in autoedit.EDIT_REQUEST_SCHEMA["properties"]
    assert "caption_gap" in autoedit.EDIT_BATCH_SCHEMA["properties"]["notes"]["items"]["properties"]
    edited = [word(w["text"], w["start_s"], w["end_s"]) for w in words]
    assert (
        len(build_cues({"words": edited, "keep": [[0, 2]], "overrides": result["overrides"]})) == 2
    )
    assert len(wordbox.pages(edited, gap_s=gap)) == 2


def test_creatorz_starts_on_the_spoken_word_and_splits_audible_pause(tmp_path):
    plan = reels.reel_plan(
        src=tmp_path / "source.mp4",
        words_path=tmp_path / "words.json",
        keep=[[0, 2]],
        lang="en",
        work=tmp_path,
        moments=[],
        punchline=None,
        bed=None,
    )
    shot = {
        "out_in": 0.0,
        "out_out": 2.0,
        "owords": [{"text": "business", "s": 0.2, "e": 0.4}, {"text": "now", "s": 0.82, "e": 1.1}],
    }
    assert plan.get("caption_gap_s") is not None
    captions = reels.compose_plan.captions([shot], "en", gap_s=plan["caption_gap_s"])
    assert [(c["text"], c["t0"]) for c in captions] == [("business", 0.2), ("now", 0.82)]
    assert captions[0]["t1"] <= 0.82


def test_subtitle_download_matches_the_last_render_while_the_next_cut_is_prepared(tmp_path):
    from types import SimpleNamespace

    from tce.api.routers.production import _caption_text

    srt = tmp_path / "video-edited.srt"
    vtt = srt.with_suffix(".vtt")
    srt.write_text("1\n00:00:00,700 --> 00:00:00,950\nDelivered take\n", encoding="utf8")
    vtt.write_text("WEBVTT\n\n00:00:00.700 --> 00:00:00.950\nDelivered take\n", encoding="utf8")
    row = SimpleNamespace(
        captions_path=str(srt), edit_plan={"keep": [[0, 1]], "words": [word("draft", 0.2, 0.5)]}
    )
    assert _caption_text(row, "srt") == srt.read_text()
    assert _caption_text(row, "vtt") == vtt.read_text()
    vtt.unlink()
    assert "draft" in _caption_text(row, "vtt")


def test_a_note_reanchors_only_the_target_kept_occurrence_and_not_the_audio():
    plan_words = [
        word("your", 0, 0.3),
        word("wrong", 0.5, 0.8),
        word("your", 1.4, 1.7),
        word("team", 1.73, 2),
    ]
    transcript = [{"text": w["text"], "start_s": w["start"], "end_s": w["end"]} for w in plan_words]
    keep = [[0, 0.4], [1.3, 2.1]]
    item = {"note": 1, "caption_anchor": [{"index": 2, "word": "your", "offset_ms": 100}]}
    out = autoedit.apply_batch(transcript, None, {"notes": [item]}, 1, keep=keep)
    assert out["changed"] is True
    anchors = out["overrides"]["caption_anchors"]
    assert out["notes"][0]["caption_anchors"] == anchors and out["overrides"]["cut"] == []
    assert autoedit.merge_overrides(out["overrides"], [], [])["caption_anchors"] == anchors
    assert out["words"] == transcript
    timed = words_on_edit(plan_words, keep, anchors)
    assert [w["text"] for w in timed] == ["your", "your", "team"]
    assert timed[0]["start"] == 0 and timed[1]["start"] == pytest.approx(0.60)
    assert timed[2]["start"] == pytest.approx(0.83)
    assert timed[1]["caption_anchor"]["edit_s"] == pytest.approx(0.6)
    pages = wordbox.pages(timed)
    assert [p.start for p in pages] == pytest.approx([0, 0.6])
    assert [
        c["start"]
        for c in build_cues({"words": plan_words, "keep": keep, "overrides": out["overrides"]})
    ] == [0, 0.6]
    # If the targeted occurrence subsequently leaves the cut, a homonym is never retimed.
    assert all("caption_anchor" not in w for w in words_on_edit(plan_words, [[0, 0.4]], anchors))
    assert "caption_anchor" in autoedit.EDIT_REQUEST_SCHEMA["properties"]


def test_a_stale_or_unreachable_caption_anchor_is_refused():
    transcript = [
        {"text": "right", "start_s": 0.0, "end_s": 0.25},
        {"text": "right", "start_s": 1.0, "end_s": 1.5},
    ]
    for index, spelling, offset in [(0, "right", 0), (1, "mismatch", 0), (1, "right", 600)]:
        note = {
            "note": 1,
            "caption_anchor": [{"index": index, "word": spelling, "offset_ms": offset}],
        }
        out = autoedit.apply_batch(transcript, None, {"notes": [note]}, 1, keep=[[0.9, 1.8]])
        assert out["notes"][0]["outcome"] == "refused" and not out["changed"]


def test_creatorz_honours_a_single_caption_anchor_inside_a_fluent_phrase():
    shot = {
        "out_in": 0.0,
        "out_out": 1.4,
        "owords": [
            {"text": "your", "s": 0.0, "e": 0.25},
            {"text": "team", "s": 0.31, "e": 0.72},
            {"text": "works", "s": 0.75, "e": 1.1},
        ],
    }
    anchors = [{"text": "team", "from_edit_s": 0.31, "edit_s": 0.39}]
    caps = reels.compose_plan.captions([shot], "en", gap_s=0.35, anchors=anchors)
    assert [(c["text"], c["t0"]) for c in caps] == [("your", 0.0), ("team works", 0.39)]


def test_caption_jobs_get_fresh_keys_and_old_note_answers_remain_readable():
    import hashlib
    import uuid

    from tce.api.routers import production as prod

    ref = uuid.UUID(int=1)

    def old_key(kind, version):
        digest = hashlib.sha256("\x1f".join([version, "system", "words"]).encode()).hexdigest()[:24]
        return f"{kind}:{ref}:{digest}"

    assert prod.edit_request_key(ref, "words", "system") != old_key("edit-request", "autoedit-v1")
    assert prod.talk_key(ref, "words", "system") != old_key("edit-batch", "edit-batch-v2")
    assert prod.talk_key(ref, "words", "system") == prod.talk_key(ref, "words", "system")
    result = autoedit.apply_batch(
        [], None, {"notes": [{"note": 1, "reply": "Already in the cut."}]}, 1
    )
    assert result["notes"][0]["outcome"] == "answer" and result["overrides"] is None
