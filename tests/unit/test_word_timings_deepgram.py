"""Narration word timings can come from Deepgram instead of whisper-1 (T-13374).

OpenAI retires whisper-1 on 26-Feb-2027 and its replacement gives no word timings,
so narration alignment needs another engine. TCE_WORD_TIMINGS_PROVIDER picks it and
stays "openai" until a comparison on this server's own keys has passed. Deepgram's
answer is turned into Whisper's shape, so the alignment, the filler cuts and the
saved transcript read it unchanged. Every call here is answered by a fake.
"""

from __future__ import annotations

import io
import json
import tempfile
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tce.services.audio_alignment import AudioAlignmentService, deepgram_to_whisper
from tce.services.audio_cleanup import AudioCleanupService
from tce.settings import Settings, settings

WHISPER = {
    "task": "transcribe",
    "language": "english",
    "duration": 3.2,
    "text": "Hello world. Goodbye now.",
    "words": [
        {"word": "Hello", "start": 0.0, "end": 0.3},
        {"word": "world", "start": 0.3, "end": 0.7},
        {"word": "Goodbye", "start": 1.5, "end": 1.9},
        {"word": "now", "start": 1.9, "end": 2.2},
    ],
}

# The shape Deepgram's pre-recorded endpoint answers with smart_format and
# filler_words on: lowercase word, formatted punctuated_word, fillers as words.
DEEPGRAM = {
    "metadata": {"request_id": "test", "duration": 3.21, "channels": 1},
    "results": {
        "channels": [
            {
                "detected_language": "en",
                "alternatives": [
                    {
                        "transcript": "Hello, world. Um, goodbye now.",
                        "confidence": 0.98,
                        "words": [
                            {"word": "hello", "start": 0.04, "end": 0.28,
                             "confidence": 0.99, "punctuated_word": "Hello,"},
                            {"word": "world", "start": 0.32, "end": 0.68,
                             "confidence": 0.99, "punctuated_word": "world."},
                            {"word": "um", "start": 0.9, "end": 1.2,
                             "confidence": 0.9, "punctuated_word": "Um,"},
                            {"word": "goodbye", "start": 1.54, "end": 1.88,
                             "confidence": 0.99, "punctuated_word": "goodbye"},
                            {"word": "now", "start": 1.92, "end": 2.18,
                             "confidence": 0.99, "punctuated_word": "now."},
                        ],
                    }
                ],
            }
        ]
    },
}

SEGMENTS = [
    {"narratorText": "Hello world.", "visualType": "animated_text", "visualProps": {}},
    {"narratorText": "Goodbye now.", "visualType": "reveal_text", "visualProps": {}},
]


def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 800)
    return buf.getvalue()


@pytest.fixture
def clip(tmp_path) -> Path:
    path = tmp_path / "take.wav"
    path.write_bytes(_wav_bytes())
    return path


@pytest.fixture
def web(monkeypatch):
    """Answers api.openai.com and api.deepgram.com from the fakes above; records each call."""
    calls: list[httpx.Request] = []
    answers = {"api.openai.com": (200, WHISPER), "api.deepgram.com": (200, DEEPGRAM)}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        status, body = answers[request.url.host]
        return httpx.Response(status, json=body)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    return calls, answers


def _svc(tmp_path, **kw) -> AudioAlignmentService:
    return AudioAlignmentService(openai_api_key="sk-test", audio_dir=str(tmp_path / "a"), **kw)


def test_the_switch_ships_off():
    assert Settings(_env_file=None).word_timings_provider == "openai"
    assert Settings(_env_file=None).deepgram_model == "nova-3"


@pytest.mark.asyncio
async def test_off_still_asks_whisper_1_exactly_as_before(tmp_path, clip, web):
    calls, _ = web
    result = await _svc(tmp_path).transcribe_with_timestamps(str(clip))

    assert result == WHISPER
    assert len(calls) == 1
    req = calls[0]
    assert str(req.url) == "https://api.openai.com/v1/audio/transcriptions"
    assert req.headers["authorization"] == "Bearer sk-test"
    body = req.content.decode("latin-1")
    for field, value in (("model", "whisper-1"), ("response_format", "verbose_json"),
                         ("timestamp_granularities[]", "word")):
        assert f'name="{field}"\r\n\r\n{value}\r\n' in body


@pytest.mark.asyncio
async def test_deepgram_is_asked_for_fillers_numerals_and_the_language(tmp_path, clip, web):
    calls, _ = web
    svc = _svc(tmp_path, provider="deepgram", deepgram_api_key="dg-test")
    await svc.transcribe_with_timestamps(str(clip))

    assert len(calls) == 1
    req = calls[0]
    assert (req.url.scheme, req.url.host, req.url.path) == (
        "https", "api.deepgram.com", "/v1/listen",
    )
    assert dict(req.url.params) == {
        "model": "nova-3",
        "smart_format": "true",
        "filler_words": "true",
        "detect_language": "true",
    }
    assert req.headers["authorization"] == "Token dg-test"
    assert req.headers["content-type"] == "audio/wav"
    assert req.content == clip.read_bytes()


@pytest.mark.asyncio
async def test_each_upload_format_is_named_to_deepgram(tmp_path, web):
    calls, _ = web
    svc = _svc(tmp_path, provider="deepgram", deepgram_api_key="dg-test")
    for ext, mime in ((".mp3", "audio/mpeg"), (".m4a", "audio/mp4"), (".ogg", "audio/ogg")):
        path = tmp_path / f"take{ext}"
        path.write_bytes(b"not really audio")
        await svc.transcribe_with_timestamps(str(path))
        assert calls[-1].headers["content-type"] == mime


@pytest.mark.asyncio
async def test_deepgram_answer_reads_like_whisper(tmp_path, clip, web):
    result = await _svc(
        tmp_path, provider="deepgram", deepgram_api_key="dg-test"
    ).transcribe_with_timestamps(str(clip))

    assert result["provider"] == "deepgram"
    assert result["duration"] == 3.21
    assert result["text"] == "Hello, world. Um, goodbye now."
    assert result["language"] == "en"
    assert result["words"] == [
        {"word": "Hello", "start": 0.04, "end": 0.28},
        {"word": "world", "start": 0.32, "end": 0.68},
        {"word": "Um", "start": 0.9, "end": 1.2},
        {"word": "goodbye", "start": 1.54, "end": 1.88},
        {"word": "now", "start": 1.92, "end": 2.18},
    ]
    json.dumps(result)  # saved as JSONB on the narration


def test_deepgram_words_without_punctuation_or_language_still_map():
    payload = json.loads(json.dumps(DEEPGRAM))
    channel = payload["results"]["channels"][0]
    del channel["detected_language"]
    for w in channel["alternatives"][0]["words"]:
        del w["punctuated_word"]
    result = deepgram_to_whisper(payload)
    assert [w["word"] for w in result["words"]] == ["hello", "world", "um", "goodbye", "now"]
    assert "language" not in result


def test_an_empty_deepgram_answer_is_an_empty_transcript():
    assert deepgram_to_whisper({"metadata": {"duration": 1.0}, "results": {"channels": []}}) == {
        "provider": "deepgram", "text": "", "duration": 1.0, "words": [],
    }


@pytest.mark.asyncio
async def test_deepgram_fillers_reach_the_cleanup_cuts(tmp_path, clip, web):
    result = await _svc(
        tmp_path, provider="deepgram", deepgram_api_key="dg-test"
    ).transcribe_with_timestamps(str(clip))
    cuts = AudioCleanupService()._find_filler_intervals(result["words"])
    assert cuts == [(pytest.approx(0.88), pytest.approx(1.22))]


@pytest.mark.asyncio
async def test_deepgram_words_time_the_script_like_whisper_words(tmp_path, clip, web):
    svc = _svc(tmp_path, provider="deepgram", deepgram_api_key="dg-test")
    aligned, result = await svc.align_script(str(clip), SEGMENTS)
    by_whisper = svc.align_segments(SEGMENTS, WHISPER["words"])

    for dg, wh in zip(aligned, by_whisper):
        assert dg["startSec"] == pytest.approx(wh["startSec"], abs=0.06)
        assert dg["endSec"] == pytest.approx(wh["endSec"], abs=0.06)
    assert result["provider"] == "deepgram"


@pytest.mark.asyncio
async def test_a_deepgram_refusal_is_an_error_not_an_empty_transcript(tmp_path, clip, web):
    _, answers = web
    answers["api.deepgram.com"] = (
        401, {"err_code": "INVALID_AUTH", "err_msg": "Invalid credentials."},
    )
    svc = _svc(tmp_path, provider="deepgram", deepgram_api_key="dg-wrong")
    with pytest.raises(RuntimeError, match=r"Deepgram API error \(401\).*INVALID_AUTH"):
        await svc.transcribe_with_timestamps(str(clip))


@pytest.mark.asyncio
async def test_deepgram_switched_on_without_a_key_asks_nobody(tmp_path, clip, web):
    calls, _ = web
    with pytest.raises(RuntimeError, match="TCE_DEEPGRAM_API_KEY is empty"):
        await _svc(tmp_path, provider="deepgram").transcribe_with_timestamps(str(clip))
    assert calls == []


@pytest.mark.asyncio
async def test_a_misspelt_switch_is_refused_not_guessed(tmp_path, clip, web):
    calls, _ = web
    with pytest.raises(RuntimeError, match="'deepgrm'"):
        await _svc(tmp_path, provider="deepgrm").transcribe_with_timestamps(str(clip))
    assert calls == []


def test_the_narration_service_follows_the_settings(monkeypatch, tmp_path):
    from tce.api.routers import narration

    monkeypatch.setattr(settings, "audio_upload_dir", str(tmp_path / "a"))
    monkeypatch.setattr(settings, "word_timings_provider", "deepgram")
    monkeypatch.setattr(settings, "deepgram_api_key", SecretStr("dg-from-env"))
    monkeypatch.setattr(settings, "deepgram_model", "nova-3")
    svc = narration._get_alignment_service()
    assert (svc.provider, svc.deepgram_api_key, svc.deepgram_model) == (
        "deepgram", "dg-from-env", "nova-3",
    )
    assert narration._get_alignment_service(provider="openai").provider == "openai"


def test_compare_pairs_the_words_and_measures_the_gaps(tmp_path):
    report = _svc(tmp_path).compare_timings(WHISPER, deepgram_to_whisper(DEEPGRAM), SEGMENTS)

    assert report["matched_words"] == 4
    assert report["matched_share"] == 1.0
    # Deepgram starts 40, 20, 40, 20 ms later and ends 20, 20, 20, 20 ms earlier.
    assert report["start_ms"] == {"bias": 30, "mean": 30, "p90": 40, "max": 40}
    assert report["end_ms"] == {"bias": -20, "mean": 20, "p90": 20, "max": 20}
    assert report["openai"]["fillers"] == []
    assert report["deepgram"]["fillers"] == [{"word": "Um", "start": 0.9}]
    assert (report["openai"]["words"], report["deepgram"]["words"]) == (4, 5)
    assert [row["text"] for row in report["segments"]] == ["Hello world.", "Goodbye now."]
    # The first segment starts at 0 for both (the 0.15 s lead-in is clamped at the
    # clip's start); the second skips Deepgram's "Um" and starts on "goodbye".
    assert [row["start_ms"] for row in report["segments"]] == [0, 40]
    assert [row["end_ms"] for row in report["segments"]] == [-20, -20]


def test_compare_with_nothing_heard_does_not_divide_by_zero(tmp_path):
    report = _svc(tmp_path).compare_timings({"words": []}, {"words": []})
    assert report["matched_words"] == 0
    assert report["matched_share"] is None
    assert report["start_ms"] is None and report["end_ms"] is None
    assert report["segments"] == []


def _client():
    from tce.api.app import app

    return TestClient(app, raise_server_exceptions=False)


def _post_clip(client, **data):
    return client.post(
        "/api/v1/narration/word-timings/compare",
        files={"file": ("take.wav", _wav_bytes(), "audio/wav")},
        data=data,
    )


def test_compare_route_names_the_missing_key_and_spends_nothing(monkeypatch, tmp_path, web):
    calls, _ = web
    monkeypatch.setattr(settings, "audio_upload_dir", str(tmp_path / "a"))
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "deepgram_api_key", SecretStr(""))
    response = _post_clip(_client())
    assert response.status_code == 409
    assert "TCE_DEEPGRAM_API_KEY" in response.json()["detail"]
    assert "TCE_OPENAI_API_KEY" not in response.json()["detail"]
    assert calls == []


def test_compare_route_refuses_a_format_upload_audio_refuses(monkeypatch, tmp_path, web):
    calls, _ = web
    response = _client().post(
        "/api/v1/narration/word-timings/compare",
        files={"file": ("take.flac", b"x", "audio/flac")},
    )
    assert response.status_code == 400
    assert calls == []


def test_compare_route_times_one_clip_with_both_and_keeps_nothing(monkeypatch, tmp_path, web):
    calls, _ = web
    monkeypatch.setattr(settings, "audio_upload_dir", str(tmp_path / "a"))
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "deepgram_api_key", SecretStr("dg-test"))
    monkeypatch.setattr(settings, "word_timings_provider", "openai")
    temp_root = Path(tempfile.gettempdir())
    before = set(temp_root.glob("tce-word-timings-*"))

    response = _post_clip(_client(), script_text="Hello world.\n\nGoodbye now.\n")

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["matched_words"] == 4
    assert [row["start_ms"] for row in report["segments"]] == [0, 40]
    assert sorted(c.url.host for c in calls) == ["api.deepgram.com", "api.openai.com"]
    assert set(temp_root.glob("tce-word-timings-*")) == before
    assert list((tmp_path / "a").iterdir()) == []


def test_compare_route_says_which_engine_failed(monkeypatch, tmp_path, web):
    _, answers = web
    answers["api.deepgram.com"] = (402, {"err_code": "ASR_PAYMENT_REQUIRED"})
    monkeypatch.setattr(settings, "audio_upload_dir", str(tmp_path / "a"))
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "deepgram_api_key", SecretStr("dg-test"))
    response = _post_clip(_client())
    assert response.status_code == 502
    assert "Deepgram API error (402)" in response.json()["detail"]
