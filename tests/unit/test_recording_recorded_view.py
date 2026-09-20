"""What the recorder offers after a recording, run in Node straight from recording.js.

He could take a video on the phone and the page said nothing back. These helpers
decide which links a finished recording gets - and, just as importantly, which it
does not, because a captions button that 404s under his finger is worse than no
captions button.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.unit.test_recording_studio_js import JS, _function

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node not installed")

HELPERS = ("recordedLinks", "recordedWhen", "recordedPending")


def run_js(expr: str, **bindings):
    source = JS.read_text(encoding="utf-8")
    script = "\n".join(_function(source, name) for name in HELPERS)
    for name, value in bindings.items():
        script += f"\nconst {name} = {json.dumps(value)};"
    script += f"\nprocess.stdout.write(JSON.stringify({expr}));"
    # encoding is explicit: text=True decodes with the Windows console codepage and
    # turns the middle dot this view prints into mojibake.
    out = subprocess.run(
        [NODE, "-e", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    ).stdout
    return json.loads(out)


def item(**over) -> dict:
    base = {
        "upload_id": "u1",
        "title": "Before you blame the marketing",
        "recorded_at": "2026-09-18T09:30:00",
        "duration_s": 74.4,
        "status": "uploaded",
        "video_url": "/api/v1/production/uploads/u1/video",
        "edited_url": None,
        "captions_srt_url": None,
        "has_transcript": False,
        "google_doc_url": None,
    }
    base.update(over)
    return base


def test_a_fresh_recording_offers_the_video_and_nothing_it_does_not_have():
    links = run_js("recordedLinks(item, '/tce')", item=item())

    assert [link["label"] for link in links] == ["Watch it"]
    assert links[0]["href"] == "/tce/api/v1/production/uploads/u1/video"


def test_everything_it_has_is_offered():
    links = run_js(
        "recordedLinks(item, '/tce')",
        item=item(
            captions_srt_url="/api/v1/production/uploads/u1/captions.srt",
            has_transcript=True,
            google_doc_url="https://docs.google.com/document/d/abc/edit",
        ),
    )

    assert [link["label"] for link in links] == ["Watch it", "Captions", "Open the script"]
    # the Doc is already absolute and must not be prefixed into a broken path
    assert links[-1]["href"] == "https://docs.google.com/document/d/abc/edit"
    assert links[1]["href"] == "/tce/api/v1/production/uploads/u1/captions.srt"


def test_an_edited_cut_replaces_the_raw_take_rather_than_sitting_beside_it():
    # Two "watch" buttons is a choice he should not have to make.
    links = run_js(
        "recordedLinks(item, '')",
        item=item(edited_url="/api/v1/production/uploads/u1/edited"),
    )

    assert [link["label"] for link in links] == ["Watch the edited cut"]


def test_the_prefix_is_applied_because_the_site_lives_under_tce():
    links = run_js("recordedLinks(item, '/tce')", item=item())

    assert links[0]["href"].startswith("/tce/")


DOT = chr(0xB7)  # written as a code point: a raw middle dot here is an encoding trap


def test_when_and_how_long():
    # A minute and a quarter reads as 1:14, never as 74s.
    assert run_js("recordedWhen(item)", item=item()) == f"Sep 18 {DOT} 1:14"
    assert run_js("recordedWhen(item)", item=item(duration_s=134)) == f"Sep 18 {DOT} 2:14"
    assert run_js("recordedWhen(item)", item=item(duration_s=9)) == f"Sep 18 {DOT} 9s"
    assert run_js("recordedWhen(item)", item=item(recorded_at=None, duration_s=None)) == ""
    # A timestamp the browser cannot parse must not print "Invalid Date" at him.
    assert run_js("recordedWhen(item)", item=item(recorded_at="not a date")) == "1:14"


def test_it_says_when_captions_are_still_missing():
    line = run_js("recordedPending(item)", item=item())

    assert "Captions are not made yet" in line


def test_a_superseded_take_says_it_is_the_old_one():
    line = run_js("recordedPending(item)", item=item(status="superseded"))

    assert "older take" in line


def test_a_complete_recording_says_nothing_extra():
    line = run_js(
        "recordedPending(item)",
        item=item(captions_srt_url="/c.srt", has_transcript=True),
    )

    assert line == ""
