"""A checked preview needs independent positive evidence for its caption wording."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tce.api.routers import production
from tce.production import qc


def timed(text):
    return [{"text": word, "start": i * .25, "end": i * .25 + .20} for i, word in enumerate(text.split())]


@pytest.mark.parametrize(("shown", "heard"), [
    ("keep all three words here", "totally different unrelated speech track"),
    ("you should not share it", "you should share it"),
    ("she owes us $1.50 today", "she owes us $150 today"),
    ("call Jennifer this coming Monday", "call Jessica this coming Monday"),
    ("our balance was -15", "our balance was 15"),
    ("stay at camp this week", "stay at camp and rescue clients this week"),
])
def test_different_tracks_and_material_changes_do_not_pass(shown, heard):
    found = qc.caption_playback({"mode": "wordbox", "boxes": timed(shown)}, timed(heard))
    assert found["state"] != "pass", found


@pytest.mark.parametrize(("shown", "heard"), [
    ("wrong answers made her leave", "wrong answer made her leave"),
    ("well you don’t owe $2,000", "well you don't owe $2000"),
])
def test_typographic_and_minor_recognizer_variants_are_tolerated(shown, heard):
    assert qc.caption_playback({"mode": "wordbox", "boxes": timed(shown)}, timed(heard))["state"] == "pass"


@pytest.mark.parametrize(("cue", "pixels"), [
    ("no leads", "leads"), ("pay 1.5 today", "pay 15 today"),
    ("Call Jen", "Call Jennifer"), ("you should do this", "you should not do this"),
    ("pay five dollars", "never pay five dollars"), ("call Jen", "call Jen Smith"),
    ("room 1 5", "room 15"), ("balance -15", "balance 15"),
])
async def test_partial_or_changed_frame_wording_does_not_pass(cue, pixels):
    data = {"cues": [{"start": 0, "end": 1, "text": cue}]}
    out = await qc.sample_caption_frames("synthetic", data, "en", reader=AsyncMock(return_value=pixels))
    assert out["state"] != "pass"


async def test_wordbox_ocr_linewrap_and_fused_words_still_match():
    data = {"cues": [{"start": 0, "end": 1, "text": "Sometimes a no matters"}]}
    out = await qc.sample_caption_frames("synthetic", data, "en", reader=AsyncMock(return_value="Sometimesa\nno matters"))
    assert out["state"] == "pass"


@pytest.mark.parametrize("playback", ["skipped", "pass"])
def test_versionless_preview_is_never_a_verified_pass(playback):
    result = qc.decide({"captions": {"state": "skipped", "problems": [], "playback_state": playback}}, round_no=0)
    assert result["state"] == "report"


def test_missing_structural_evidence_remains_incomplete_with_readable_frames_and_audio():
    result = qc.decide({"captions": {"state": "skipped", "why": "source word data missing",
                        "problems": [], "frames": {"state": "pass"}, "playback_state": "pass"}}, round_no=0)
    assert result["state"] == "report"
    assert "source word data missing" in result["line"]


async def test_voice_stem_cannot_authorize_positive_final_mix_agreement(monkeypatch):
    video, stem = Path("delivered.mp4"), Path("voice-only.wav")
    good = ([{"text": "yes"}], None)
    failed = (None, "could not hear the final mix")
    hook = AsyncMock(side_effect=lambda path, *args: good if path == stem else failed)
    monkeypatch.setattr(production, "_qc_listen", hook)
    diagnosis, mixed = await production._qc_render_listens(video, stem, 5, None)
    assert diagnosis == good and mixed == failed
    assert hook.await_count == 2
    hook.reset_mock()
    both = await production._qc_render_listens(video, video, 5, None)
    assert both == (failed, failed) and hook.await_count == 1
