"""Tests for AudioCleanupService - filler detection, gap finding, best-take."""

from tce.services.audio_cleanup import AudioCleanupService


def _svc():
    return AudioCleanupService()


def test_find_filler_intervals_basic():
    words = [
        {"word": "um", "start": 1.0, "end": 1.3},
        {"word": "hello", "start": 1.5, "end": 2.0},
        {"word": "uh", "start": 3.0, "end": 3.2},
    ]
    intervals = _svc()._find_filler_intervals(words)
    assert len(intervals) == 2
    assert intervals[0][0] < 1.0  # padded
    assert intervals[0][1] > 1.3


def test_find_filler_intervals_none():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 0.6, "end": 1.0},
    ]
    intervals = _svc()._find_filler_intervals(words)
    assert len(intervals) == 0


def test_find_filler_punctuation_stripped():
    words = [{"word": "um.", "start": 1.0, "end": 1.3}]
    intervals = _svc()._find_filler_intervals(words)
    assert len(intervals) == 1


def test_merge_overlapping():
    intervals = [(0.0, 1.0), (0.5, 1.5), (2.0, 3.0)]
    merged = AudioCleanupService._merge_overlapping(intervals)
    assert merged == [(0.0, 1.5), (2.0, 3.0)]


def test_merge_overlapping_empty():
    assert AudioCleanupService._merge_overlapping([]) == []


def test_compute_keep_segments_no_cuts():
    keeps = _svc()._compute_keep_segments(10.0, [])
    assert keeps == [(0, 10.0)]


def test_compute_keep_segments_with_cuts():
    cuts = [(2.0, 3.0), (5.0, 6.0)]
    keeps = _svc()._compute_keep_segments(10.0, cuts)
    assert keeps == [(0.0, 2.0), (3.0, 5.0), (6.0, 10.0)]


def test_find_silence_gaps():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 1.5, "end": 2.0},  # 1.0s gap
        {"word": "test", "start": 2.1, "end": 2.5},   # 0.1s gap (ok)
    ]
    gaps = _svc()._find_silence_gaps(words, [])
    assert len(gaps) == 1
    assert gaps[0][0] == 0.5
    assert gaps[0][1] == 1.5


def test_find_matching_windows_exact():
    words = [
        {"word": "the", "start": 0.0, "end": 0.2},
        {"word": "quick", "start": 0.3, "end": 0.5},
        {"word": "brown", "start": 0.6, "end": 0.8},
        {"word": "fox", "start": 0.9, "end": 1.0},
    ]
    matches = _svc()._find_matching_windows(words, ["the", "quick", "brown", "fox"])
    assert len(matches) == 1
    assert matches[0] == (0, 4)


def test_find_matching_windows_duplicate():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.3},
        {"word": "world", "start": 0.4, "end": 0.7},
        {"word": "test", "start": 0.8, "end": 1.0},
        {"word": "hello", "start": 2.0, "end": 2.3},
        {"word": "world", "start": 2.4, "end": 2.7},
        {"word": "test", "start": 2.8, "end": 3.0},
    ]
    matches = _svc()._find_matching_windows(words, ["hello", "world", "test"])
    assert len(matches) == 2
