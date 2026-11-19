from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tce.production import delivery


def evidence():
    return {
        "render_ref": "new", "duration": 4.0, "keep": [[0.0, 2.0], [3.0, 5.0]],
        "captions": {"mode": "wordbox", "boxes": [
            {"start": 0.3, "end": 0.8, "text": "cancelled"},
            {"start": 1.0, "end": 1.4, "text": "today"},
            {"start": 2.1, "end": 2.5, "text": "again"},
        ]},
        "visible": {("caption", .55): "cancelled"},
        "heard": [{"start": 0.3, "end": 0.8, "text": "cancelled"},
                  {"start": 1.0, "end": 1.4, "text": "today"},
                  {"start": 2.1, "end": 2.5, "text": "again"}],
    }


def check(e, outcome):
    return delivery.verify(outcome, e, before_ref="old", source_s=0.3, edit_s=None)


def test_captions_and_actual_audio_must_agree_at_the_correct_occurrence():
    target = {"corrections": [{"heard": "cancel", "replacement": "cancelled", "source": [0.3, 0.8]}]}
    e = evidence()
    assert check(e, target)["state"] == "verified"
    e["heard"][0]["text"] = "cancel"
    e["heard"].append({"text": "cancelled", "start": 3.2, "end": 3.6})
    r = check(e, target)
    assert r["state"] == "needs_review" and r["clip"]["start_s"] == 0
    assert "cancelled" in r["question"]
    e = evidence()
    e["captions"]["boxes"][0]["text"] = "cancel"
    assert check(e, target)["state"] == "needs_review"


def test_missing_and_unchanged_render_cannot_prove_a_change():
    e = evidence()
    target = {"cut": [[2.0, 3.0]]}
    assert check(e, target)["state"] == "verified"
    assert delivery.verify(target, e, before_ref="new", source_s=2, edit_s=None)["state"] == "needs_review"
    assert check({}, target)["state"] == "needs_review"
    assert check(e, {"cut": [[1.0, 1.5]]})["state"] == "needs_review"


def test_restored_audio_missing_or_not_displayed_is_unresolved():
    target = {"restore": [[0.3, 0.8]], "restore_words": [{"source": [0.3, 0.8], "text": "cancelled"}]}
    assert check(evidence(), target)["state"] == "verified"
    e = evidence()
    e["heard"] = []
    assert check(e, target)["state"] == "needs_review"


def test_no_edit_receipt_for_an_action_disguised_as_a_reply():
    assert delivery.requires_change("The caption should say cancelled.")
    assert delivery.requires_change("Can you remove the pause here?")
    assert not delivery.requires_change("Why was that take removed?")
    assert delivery.requires_change("Why is this wrong? Please fix the caption.")
    assert delivery.requires_change("תתקני בבקשה את הכתוביות")
    assert delivery.requires_change("למה יש שתיקה? בבקשה להסיר אותה")
    assert not delivery.requires_change("למה הכתובית הוסרה?")
    assert delivery.request_moment("please fix the join at 1:07.5") == 67.5


def test_only_pixels_can_prove_the_caption_and_caption_only_preserves_different_speech():
    target = {"corrections": [{"heard": "cancel", "replacement": "cancelled", "source": [.3, .8]}]}
    e = evidence()
    e["visible"] = {}
    assert check(e, target)["state"] == "needs_review"
    e = evidence()
    e["heard"][0]["text"] = "cancel"
    target["caption_only"] = delivery.caption_only("Change the caption only. Leave my voice alone.")
    assert check(e, target)["state"] == "verified"
    assert delivery.caption_only("לשנות רק את הכתוביות")


def test_requested_truncation_cannot_be_verified_by_a_substring_of_the_old_spoken_phrase():
    t = {"corrections": [{"heard": "not cancelled", "replacement": "cancelled", "source": [.3, .8]}]}
    e = evidence()
    e["heard"].insert(0, {"text": "not", "start": .14, "end": .3})
    assert check(e, t)["state"] == "needs_review"


def test_a_superseded_anchor_or_wrong_new_page_fails_at_its_own_moment():
    e = evidence()
    anchor = {"word_s": .3, "at_s": .3, "text": "cancelled"}
    assert check(e, {"caption_anchors": [anchor]})["state"] == "needs_review"
    e["caption_anchors"] = [{**anchor, "edit_s": .3}]
    e["visible"][("caption", .39)] = "cancelled"
    assert check(e, {"caption_anchors": [anchor]})["state"] == "verified"
    e["captions"]["boxes"][0]["start"] = .5
    assert check(e, {"caption_anchors": [anchor]})["state"] == "needs_review"


async def test_same_ref_or_missing_file_never_closes_the_standalone_request(tmp_path, monkeypatch):
    from tce.api.routers import production

    row = SimpleNamespace(status="edited", render_ref="stale", edited_path=str(tmp_path / "absent.mp4"),
                          rendered_keep=[[0, 2]], qc={}, status_detail="")
    settle = AsyncMock()
    monkeypatch.setattr(production, "start_rule_learning", lambda *a: pytest.fail("unverified change taught a rule"))
    await production._finish_request(None, None, None, row, {"before_render_ref": "stale", "cut": [[0, 1]]}, settle)
    assert settle.await_args.args[0] == "needs_you"


async def test_artifact_reader_rejects_stale_sidecar_and_prefers_cached_actual_audio(tmp_path, monkeypatch):
    from tce.api.routers import production as p

    f = tmp_path / "render.mp4"
    f.write_bytes(b"test-media")
    row = SimpleNamespace(render_ref="new", rendered_keep=[[0, 1]], edited_path=str(f))
    monkeypatch.setattr(p.media, "probe_duration", AsyncMock(return_value=1))
    monkeypatch.setattr(p, "_qc_listen", AsyncMock(side_effect=AssertionError("already listened to this MP4")))
    d = {"render_ref": "old", "keep": [[0, 1]], "file_size": f.stat().st_size,
         "file_mtime_ns": f.stat().st_mtime_ns, "delivered_audio_words": [{"text": "yes"}]}
    p._write_render_sidecar(f, d)
    assert not await p._delivery_evidence(row, None, outcomes=[])
    p._write_render_sidecar(f, {**d, "render_ref": "new"})
    assert (await p._delivery_evidence(row, None, outcomes=[]))["heard"] == [{"text": "yes"}]
    f.write_bytes(b"replacement")
    assert not await p._delivery_evidence(row, None, outcomes=[])
