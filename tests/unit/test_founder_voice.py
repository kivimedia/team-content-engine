"""Tests for founder voice extractor (PRD Section 50)."""

import tce.agents.founder_voice_extractor  # noqa: F401
from tce.agents.founder_voice_extractor import FounderVoiceExtractor
from tce.agents.registry import agent_registry


def test_founder_voice_extractor_registered():
    registry = agent_registry()
    assert "founder_voice_extractor" in registry


def test_founder_voice_extractor_model():
    assert FounderVoiceExtractor.default_model == "claude-sonnet-4-20250514"


def test_merge_profiles_empty():
    extractor = FounderVoiceExtractor.__new__(FounderVoiceExtractor)
    assert extractor._merge_profiles([]) == {}


def test_merge_profiles_single():
    extractor = FounderVoiceExtractor.__new__(FounderVoiceExtractor)
    profile = {"values_and_beliefs": ["truth"], "taboos": ["hype"]}
    assert extractor._merge_profiles([profile]) == profile


def test_merge_profiles_multiple():
    extractor = FounderVoiceExtractor.__new__(FounderVoiceExtractor)
    p1 = {
        "values_and_beliefs": ["truth"],
        "taboos": ["hype"],
        "metaphor_families": ["sports"],
    }
    p2 = {
        "values_and_beliefs": ["depth"],
        "taboos": ["fake"],
        "metaphor_families": ["construction"],
    }
    merged = extractor._merge_profiles([p1, p2])
    assert "truth" in merged["values_and_beliefs"]
    assert "depth" in merged["values_and_beliefs"]
    assert "hype" in merged["taboos"]
    assert "fake" in merged["taboos"]
    assert "sports" in merged["metaphor_families"]
    assert "construction" in merged["metaphor_families"]


def test_chunk_text():
    extractor = FounderVoiceExtractor.__new__(FounderVoiceExtractor)
    text = "A" * 100
    chunks = extractor._chunk_text(text, max_chars=50)
    assert len(chunks) == 2
    assert len(chunks[0]) == 50


def test_chunk_text_short():
    extractor = FounderVoiceExtractor.__new__(FounderVoiceExtractor)
    text = "Short text"
    chunks = extractor._chunk_text(text, max_chars=1000)
    assert len(chunks) == 1
    assert chunks[0] == text
