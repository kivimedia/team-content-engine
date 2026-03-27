"""Tests for anti-clone enforcement (PRD Section 14.3)."""

from tce.services.anti_clone import (
    SIMILARITY_THRESHOLD,
    AntiCloneChecker,
)


def test_similarity_threshold():
    assert SIMILARITY_THRESHOLD == 0.85


def test_clean_content_passes():
    checker = AntiCloneChecker()
    result = checker.check("This is original content about AI.")
    assert result["passes"]
    assert result["issue_count"] == 0


def test_blacklisted_phrase_detected():
    profiles = [{"disallowed_clone_markers": ["magic formula", "secret trick"]}]
    checker = AntiCloneChecker(creator_profiles=profiles)
    result = checker.check("Here is the magic formula for success.")
    assert not result["passes"]
    assert any(i["type"] == "blacklisted_phrase" for i in result["issues"])


def test_high_similarity_detected():
    examples = [
        {
            "creator_name": "TestCreator",
            "hook_text": "the big shift in AI is happening now",
            "post_text_raw": "the big shift in AI is happening now",
        }
    ]
    checker = AntiCloneChecker(corpus_examples=examples)
    # Almost identical text
    result = checker.check("the big shift in AI is happening now today")
    # High similarity should be flagged
    high_sim = [i for i in result["issues"] if i["type"] == "high_similarity"]
    assert len(high_sim) > 0


def test_word_overlap_similarity():
    sim = AntiCloneChecker._word_overlap_similarity(
        "the cat sat on the mat",
        "the cat sat on the mat",
    )
    assert sim == 1.0

    sim = AntiCloneChecker._word_overlap_similarity("hello world", "goodbye universe")
    assert sim == 0.0


def test_rhythm_match_identical():
    sentences_a = [
        "Short.",
        "Also short.",
        "A bit longer sentence.",
        "Medium length one here.",
        "Final one.",
    ]
    assert AntiCloneChecker._rhythm_match(sentences_a, sentences_a)


def test_rhythm_match_different():
    short = ["Hi.", "Ok.", "Yes.", "No.", "Go."]
    long = [
        "This is a very long sentence with many words.",
        "Another long sentence that goes on and on.",
        "Yet another lengthy sentence for testing.",
        "One more long sentence to compare.",
        "Final long sentence in the sequence.",
    ]
    assert not AntiCloneChecker._rhythm_match(short, long)


def test_empty_content():
    checker = AntiCloneChecker()
    result = checker.check("")
    assert result["passes"]
