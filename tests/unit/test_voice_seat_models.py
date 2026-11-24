"""T-22622: everyday Talk to TCE calls run on the faster model, the video editor keeps hers.

Ziv asked that no Talk to TCE reply take more than 10 seconds. On Opus 5.5 the seat's
answers ran a median of about 8 s with a fifth to a third over 10 s (test calls 20 to 24
November, and his own call of 24 November 09:21 UTC: 12.5, 12.5 and 10.8 s). The same
"put it away" reply timed on the box came back in 5 to 7 s on Sonnet 5.5 against 5 to 10 s
on Opus. The video screen (Jennifer) was moved back to the seat's own model on
13 October and is left exactly as it is.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEAT = json.loads((ROOT / "deploy" / "voice-seat" / "tce.json").read_text(encoding="utf-8"))
FAST = "claude-sonnet-5-5"


def test_every_everyday_screen_runs_on_the_fast_model():
    for kind in ("default", "week", "topic"):
        assert kind in SEAT["contexts"], kind
        assert SEAT["byContext"][kind] == {"model": FAST}, kind


def test_the_video_screen_keeps_its_voice_and_the_seat_model():
    assert SEAT["byContext"]["video"] == {"speaker": "marin"}


def test_no_screen_names_a_model_it_has_no_words_for():
    assert set(SEAT["byContext"]) <= set(SEAT["contexts"])
