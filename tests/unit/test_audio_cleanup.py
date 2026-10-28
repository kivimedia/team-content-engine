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


# A line from a live narration script (27-Oct-2026): the script says "like" here.
HAMMER = (
    "Think about it like this - you can sell someone a hammer for $20, or you "
    "can give them the hammer and charge $20,000 to build their house."
)


def _timed(text, start=0.0, step=0.3):
    """One engine word per word of text, 0.25 s long, 0.05 s apart."""
    words = []
    for i, word in enumerate(text.split()):
        at = start + i * step
        words.append({"word": word, "start": round(at, 2), "end": round(at + 0.25, 2)})
    return words


def test_like_the_script_says_is_kept():
    words = _timed("Think about it like this you can sell someone a hammer")
    assert _svc()._find_filler_intervals(words, [{"narratorText": HAMMER}]) == []


def test_like_the_reader_added_is_still_cut():
    words = _timed("so it was like really fast")
    cuts = _svc()._find_filler_intervals(words, [{"narratorText": "So it was really fast."}])
    assert len(cuts) == 1
    assert cuts[0][0] < words[3]["start"] and words[3]["end"] < cuts[0][1]


def test_um_next_to_a_scripted_like_is_still_cut():
    words = _timed("Think about it um like this")
    cuts = _svc()._find_filler_intervals(words, [{"narratorText": HAMMER}])
    assert len(cuts) == 1
    assert cuts[0][0] < words[3]["start"] and words[3]["end"] < cuts[0][1]


def test_script_word_after_a_line_break_still_counts():
    """A line that opens with Like keeps it: the script's words pair across lines."""
    words = _timed("We shipped it Like a rocket it flew")
    segments = [{"narratorText": "We shipped it."}, {"narratorText": "Like a rocket, it flew."}]
    assert _svc()._find_filler_intervals(words, segments) == []


async def test_clean_audio_leaves_a_scripted_like_in(tmp_path, monkeypatch):
    """The cleanup itself hands the script to the filler check, so nothing is cut."""
    audio = tmp_path / "take.wav"
    audio.write_bytes(b"RIFF")
    edits = []

    async def record_edits(self, src, out, cuts, gaps):
        edits.append(cuts)

    monkeypatch.setattr(AudioCleanupService, "_apply_edits", record_edits)
    words = _timed("Step two test offline first Download something like Ollama or LM Studio")
    segments = [
        {"narratorText": "Step two - test offline first."},
        {"narratorText": "Download something like Ollama or LM Studio and run it locally."},
    ]
    path, _ = await _svc().clean_audio(str(audio), {"words": words}, segments)
    assert edits == []
    assert path == str(audio)


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
