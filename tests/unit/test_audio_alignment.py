"""Tests for AudioAlignmentService - segment alignment logic."""

import pytest

from tce.services.audio_alignment import AudioAlignmentService, estimate_duration, WPS_ESTIMATE


def test_estimate_duration_normal():
    """Normal text returns word_count / WPS."""
    text = "This is a five word sentence"
    result = estimate_duration(text)
    assert result == len(text.split()) / WPS_ESTIMATE


def test_estimate_duration_empty():
    """Empty text returns minimum 0.5s."""
    assert estimate_duration("") == 0.5


def test_align_segments_empty_whisper():
    """With no Whisper words, segments are returned unchanged."""
    svc = AudioAlignmentService(openai_api_key="test")
    segments = [{"narratorText": "Hello world", "visualType": "animated_text"}]
    result = svc.align_segments(segments, [])
    assert result == segments


def test_align_segments_basic():
    """Basic alignment maps words to timestamps."""
    svc = AudioAlignmentService(openai_api_key="test")
    segments = [
        {"narratorText": "Hello world", "visualType": "animated_text", "visualProps": {}},
        {"narratorText": "Goodbye now", "visualType": "reveal_text", "visualProps": {}},
    ]
    whisper_words = [
        {"word": "Hello", "start": 0.0, "end": 0.3},
        {"word": "world", "start": 0.3, "end": 0.7},
        {"word": "Goodbye", "start": 1.0, "end": 1.4},
        {"word": "now", "start": 1.4, "end": 1.7},
    ]
    result = svc.align_segments(segments, whisper_words)
    assert len(result) == 2
    assert "startSec" in result[0]
    assert "endSec" in result[0]
    assert result[0]["startSec"] < result[0]["endSec"]
    assert result[1]["startSec"] >= result[0]["endSec"] - 0.3  # may overlap by padding


def test_align_segments_more_segments_than_words():
    """When segments exceed whisper words, remaining get estimated times."""
    svc = AudioAlignmentService(openai_api_key="test")
    segments = [
        {"narratorText": "Hello", "visualType": "animated_text", "visualProps": {}},
        {"narratorText": "Extra segment here", "visualType": "reveal_text", "visualProps": {}},
    ]
    whisper_words = [
        {"word": "Hello", "start": 0.0, "end": 0.3},
    ]
    result = svc.align_segments(segments, whisper_words)
    assert len(result) == 2
    # Second segment should still have timing (estimated)
    assert "startSec" in result[1]
    assert "endSec" in result[1]
    assert result[1]["endSec"] > result[1]["startSec"]


def test_align_segments_empty_narrator_text():
    """Segment with empty narratorText gets a 0.5s window."""
    svc = AudioAlignmentService(openai_api_key="test")
    segments = [
        {"narratorText": "", "visualType": "brand_footer", "visualProps": {}},
    ]
    whisper_words = [
        {"word": "Hello", "start": 0.0, "end": 0.3},
    ]
    result = svc.align_segments(segments, whisper_words)
    assert len(result) == 1
    assert result[0]["endSec"] - result[0]["startSec"] == 0.5


def test_match_score_exact():
    """Exact word match scores 2 per word."""
    svc = AudioAlignmentService(openai_api_key="test")
    narrator = ["hello", "world"]
    whisper = [{"word": "hello"}, {"word": "world"}]
    assert svc._match_score(narrator, whisper, 0) == 4


def test_match_score_partial():
    """Partial match (substring) scores 1."""
    svc = AudioAlignmentService(openai_api_key="test")
    narrator = ["testing"]
    whisper = [{"word": "test"}]
    assert svc._match_score(narrator, whisper, 0) == 1


def test_match_score_punctuation_stripped():
    """Punctuation is stripped for matching."""
    svc = AudioAlignmentService(openai_api_key="test")
    narrator = ["hello"]
    whisper = [{"word": "hello,"}]
    assert svc._match_score(narrator, whisper, 0) == 2


def _timed(text, start=0.0, step=0.3):
    """One engine word per word of text, 0.25 s long, 0.05 s apart."""
    words = []
    for i, word in enumerate(text.split()):
        at = start + i * step
        words.append({"word": word, "start": round(at, 2), "end": round(at + 0.25, 2)})
    return words


def test_dash_in_a_line_does_not_move_where_it_ends():
    """House style writes " - " between words. Nobody says it, so a line ends on
    its own last word and the next line starts on its own first word."""
    svc = AudioAlignmentService(openai_api_key="test")
    segments = [
        {"narratorText": "Step two - test offline first."},
        {"narratorText": "Download something like Ollama or LM Studio and run it locally."},
    ]
    words = _timed(
        "Step two test offline first Download something like Ollama or LM Studio and run it locally"
    )
    result = svc.align_segments(segments, words)
    assert result[0]["endSec"] == pytest.approx(words[4]["end"] + 0.15)  # "first"
    assert result[1]["startSec"] == pytest.approx(words[5]["start"] - 0.15)  # "Download"
    assert result[1]["endSec"] == pytest.approx(words[-1]["end"] + 0.15)  # "locally"


def test_en_dash_and_ellipsis_are_not_words_either():
    svc = AudioAlignmentService(openai_api_key="test")
    segments = [
        {"narratorText": "Fast \u2013 cheap \u2026 done."},
        {"narratorText": "Next line."},
    ]
    words = _timed("Fast cheap done Next line")
    result = svc.align_segments(segments, words)
    assert result[0]["endSec"] == pytest.approx(words[2]["end"] + 0.15)  # "done"
    assert result[1]["startSec"] == pytest.approx(words[3]["start"] - 0.15)  # "Next"


def test_a_symbol_read_out_loud_still_counts():
    """Salt & pepper is read as three words, so the line still ends on pepper."""
    svc = AudioAlignmentService(openai_api_key="test")
    segments = [{"narratorText": "Salt & pepper."}, {"narratorText": "Then serve."}]
    words = _timed("salt and pepper then serve")
    result = svc.align_segments(segments, words)
    assert result[0]["endSec"] == pytest.approx(words[2]["end"] + 0.15)
    assert result[1]["startSec"] == pytest.approx(words[3]["start"] - 0.15)


def test_spoken_words_leave_out_marks_nobody_says():
    from tce.services.audio_alignment import spoken_words

    line = "Phase three - scaling \u2014 metrics \u2026 $20,000 & 50% ...is (like) it."
    assert spoken_words(line) == [
        "phase", "three", "scaling", "metrics", "$20,000", "&", "50%", "...is", "(like)", "it.",
    ]
