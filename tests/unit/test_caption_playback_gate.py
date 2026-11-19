from tce.production import qc


def timed(texts):
    return [
        {"text": text, "start": n * 0.25, "end": n * 0.25 + 0.24}
        for n, text in enumerate(texts.split())
    ]


def test_caption_invented_at_a_join_is_reported_against_final_audio():
    boxes = timed("the answer he was asking to feel in control")
    heard = [w for w in boxes if w["text"] not in {"he", "was", "asking"}]
    match = qc.caption_playback({"boxes": boxes, "mode": "wordbox"}, heard)
    assert match["problems"][0]["kind"] == "caption_audio_mismatch"


def test_one_recognition_error_is_insufficient_and_missing_audio_is_explicit():
    boxes = timed("wrong answers made her leave")
    heard = [{**w, "text": "answer" if w["text"] == "answers" else w["text"]} for w in boxes]
    assert qc.caption_playback({"mode": "wordbox", "boxes": boxes}, heard)["state"] == "pass"
    assert qc.caption_playback({"mode": "wordbox", "boxes": boxes}, None)["state"] == "skipped"
