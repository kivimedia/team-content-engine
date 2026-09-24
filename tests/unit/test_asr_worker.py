"""The TCE faster-whisper worker's pure parts, and the editor's acceptance of them.

No model is loaded: transcription is a stub, so these run anywhere.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

from tce.production.media import parse_precise_words, parse_transcript_md

WORKER = Path(__file__).resolve().parents[2] / "scripts" / "tce_asr_worker.py"


@pytest.fixture(scope="module")
def worker():
    """Import the worker with faster_whisper stubbed out (no model, no GPU)."""
    stub = types.ModuleType("faster_whisper")
    stub.WhisperModel = object
    sys.modules.setdefault("faster_whisper", stub)
    spec = importlib.util.spec_from_file_location("tce_asr_worker", WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_timestamps_are_hh_mm_ss(worker):
    assert worker.timestamp(0) == "00:00:00"
    assert worker.timestamp(61.4) == "00:01:01"
    assert worker.timestamp(3671) == "01:01:11"
    assert worker.timestamp(-5) == "00:00:00"


def test_transcript_md_is_the_coarse_format_the_editor_parses(worker):
    segments = [
        {"start": 0.0, "end": 2.5, "text": " Answer every enquiry within an hour."},
        {"start": 2.5, "end": 5.0, "text": "  "},
        {"start": 61.0, "end": 64.0, "text": "Then decide what each lesson is for."},
    ]
    md = worker.build_transcript_md(segments)
    assert md.splitlines() == [
        "[00:00:00] Answer every enquiry within an hour.",
        "[00:01:01] Then decide what each lesson is for.",
    ]
    # The editor reads it back as coarse timings, blank segment dropped.
    parsed = parse_transcript_md(md, 70.0)
    assert [row["text"] for row in parsed] == [
        "Answer every enquiry within an hour.",
        "Then decide what each lesson is for.",
    ]
    assert {row["precision"] for row in parsed} == {"whole_second_start_inferred_end"}


def test_word_list_the_worker_sends_is_accepted_as_word_precision():
    words = [
        {"start": 0.0, "end": 0.4, "word": "Answer"},
        {"start": 0.4, "end": 0.8, "word": "every"},
        {"start": 0.8, "end": 1.4, "word": "enquiry"},
    ]
    parsed = parse_precise_words(words)
    assert [row["text"] for row in parsed] == ["Answer", "every", "enquiry"]
    assert {row["precision"] for row in parsed} == {"word"}


def test_a_zero_length_word_would_void_the_whole_list_so_the_worker_drops_it(worker):
    """parse_precise_words returns [] for the entire reply if one word has
    end <= start, which would silently downgrade a good transcript to coarse."""
    assert parse_precise_words([{"start": 1.0, "end": 1.0, "word": "x"}]) == []

    class Word:
        def __init__(self, start, end, word):
            self.start, self.end, self.word = start, end, word

    class Segment:
        start, end, text, avg_logprob = 0.0, 2.0, " hello world ", -0.2
        words = [Word(0.0, 0.5, " hello"), Word(0.5, 0.5, " "), Word(0.5, 1.2, " world")]

    class Info:
        language, duration = "en", 2.0

    worker._model = object()
    worker.model = lambda: types.SimpleNamespace(transcribe=lambda *a, **k: ([Segment()], Info()))
    result = worker.transcribe_file(Path("unused.wav"), None)
    assert [w["word"] for w in result["words"]] == ["hello", "world"]
    assert parse_precise_words(result["words"])  # survives the editor's check
    assert result["word_count"] == 2
    assert result["transcript_md"] == "[00:00:00] hello world"


def test_a_long_walk_recording_fits_through_the_socket(worker):
    """24-Sep: a 5m41s walk (182 MB) failed with "Connection lost". The file goes
    over in one WebSocket message and uvicorn drops anything over 16 MB unless
    told otherwise, so only short takes could ever be transcribed."""
    assert getattr(worker, "WS_MAX_BYTES", 0) >= 2 * 1024**3
    assert "ws_max_size=WS_MAX_BYTES" in WORKER.read_text(encoding="utf-8")
