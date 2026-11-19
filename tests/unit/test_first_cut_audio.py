"""First-cut cleanup uses independent acoustic evidence and preserves word boundaries."""

import pytest

from tce.production import first_cut_audio


def recording(gap_level, gap_voice):
    words = [
        {"start_s": a, "end_s": b, "text": word}
        for a, b, word in [(0, 0.6, "One"), (2.9, 3.5, "two"), (5.9, 6.5, "three")]
    ]
    levels, voice = [gap_level] * 650, [gap_voice] * 650
    for word in words:
        for i in range(round(word["start_s"] * 100), round(word["end_s"] * 100)):
            levels[i], voice[i] = -17, -20
    return words, levels, voice


def test_wind_between_complete_words_is_trimmed_and_cleaned_before_preview():
    words, levels, voice = recording(-22, -49)
    result = first_cut_audio.cleanup(words, levels, voice, [])
    assert result["denoise"] == "light"
    assert len(result["trim"]) == 2
    for cut, left, right in zip(result["trim"], words, words[1:]):
        assert left["end_s"] + 0.1 <= cut[0] < cut[1] <= right["start_s"] - 0.1


def test_clean_room_keeps_original_sound_and_protected_laugh():
    words, levels, voice = recording(-68, -70)
    result = first_cut_audio.cleanup(words, levels, voice, [[1, 1.8, 0.9]])
    assert result["denoise"] is None
    assert len(result["trim"]) == 1
    assert result["trim"][0][0] > 3.5


def test_unrecognized_speech_inside_a_gap_is_kept():
    words, levels, voice = recording(-15, -23)
    assert first_cut_audio.cleanup(words, levels, voice, []) == {"trim": [], "denoise": None}
    # A short syllable inside an otherwise quiet span must survive too.
    words, levels, voice = recording(-68, -70)
    voice[125:131] = [-19] * 6
    assert all(a > 3.5 for a, _ in first_cut_audio.cleanup(words, levels, voice, [])["trim"])


def test_no_measurement_never_spends_a_word_or_changes_the_sound():
    words, levels, _ = recording(-12, -43)
    assert first_cut_audio.cleanup(words, levels, [], []) == {"trim": [], "denoise": None}


@pytest.mark.asyncio
async def test_planning_a_windy_source_applies_cleanup_once_and_preserves_a_later_restore(
    tmp_path, editorial_session, monkeypatch
):
    import math
    import uuid
    import wave
    from array import array

    from tce.api.routers import production
    from tce.models.editorial import RecordingUpload

    if not production.media.ffmpeg_path():
        pytest.skip("needs ffmpeg")
    words, _, _ = recording(-22, -49)
    for word in words:
        word["precision"] = "word"
    path = tmp_path / "walk.wav"
    rate = 16000
    samples = array("h")
    for i in range(round(rate * 6.5)):
        time = i / rate
        sound = 0.15 * math.sin(2 * math.pi * 80 * time)
        if any(w["start_s"] <= time < w["end_s"] for w in words):
            sound += 0.18 * math.sin(2 * math.pi * 1500 * time)
        samples.append(round(32767 * sound))
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(samples.tobytes())
    monkeypatch.setattr(production.laugh_rules, "configured", lambda: False)
    ws = uuid.uuid4()
    row = RecordingUpload(
        workspace_id=ws,
        candidate_id=uuid.uuid4(),
        original_filename="walk.wav",
        storage_path=str(path),
        sha256="0" * 64,
        status="transcribed",
        transcript=words,
        duration_s=6.5,
    )
    await production._compute_plan(editorial_session, ws, row)
    first = row.edit_plan["first_cut_audio"]
    assert len(first["trim"]) == 2 and first["denoise"] == "light"
    assert row.edit_plan["overrides"]["denoise"] == "light"
    row.edit_plan = {**row.edit_plan, "overrides": {"restore": first["trim"]}}
    await production._compute_plan(editorial_session, ws, row)
    assert row.edit_plan["overrides"] == {"restore": first["trim"]}
