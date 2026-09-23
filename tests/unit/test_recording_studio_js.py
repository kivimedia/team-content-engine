"""Recorder hook-chooser helpers, run in Node straight from recording.js. Synthetic values.

The helpers are top-level functions ahead of the studio closure so they can be
loaded without a DOM. They decide when the chooser shows, which option is
recommended and current, and how a choose-hook response rebinds the idea.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
JS = API / "recording.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node not installed")

HELPERS = ("payoffPhrase", "hookChooserModel", "packetToIdea")
CONSTS = ()


def _function(source: str, name: str) -> str:
    m = re.search(rf"^function {name}\(.*?^\}}\r?$", source, re.M | re.S)
    assert m, name
    return m.group(0)


def _const_block(source: str, name: str) -> str:
    """The top-level `const NAME = { ... };` block, lifted verbatim."""
    start = source.index(f"const {name} = {{")
    end = source.index("\n};", start) + len("\n};")
    return source[start:end]


def run_js(expr: str, **bindings):
    source = JS.read_text(encoding="utf-8")
    script = "\n".join(_const_block(source, n) for n in CONSTS)
    script += "\n" + "\n".join(_function(source, n) for n in HELPERS)
    for name, value in bindings.items():
        script += f"\nconst {name} = {json.dumps(value)};"
    script += f"\nprocess.stdout.write(JSON.stringify({expr}));"
    out = subprocess.run(
        [NODE, "-e", script], check=True, capture_output=True, text=True, timeout=30
    ).stdout
    return json.loads(out)


def idea(**over) -> dict:
    base = {
        "candidate_id": "c1",
        "packet_id": "p1",
        "packet_version": 1,
        "title": "Plan the course from the problems",
        "big_idea": "Start from the outcome.",
        "bullets": ["one", "two", "three", "four", "five"],
        "script_phrases": ["Opening one.", "Second line.", "Third line.", "Payoff line."],
        "hook_options": [
            {
                "id": "h1",
                "text": "Opening one.",
                "question": "Q1",
                "payoff_phrase_id": "p004",
                "rationale": "R1",
            },
            {
                "id": "h2",
                "text": "Opening two.",
                "question": "Q2",
                "payoff_phrase_id": "p002",
                "rationale": "R2",
            },
            {
                "id": "h3",
                "text": "Opening three.",
                "question": "Q3",
                "payoff_phrase_id": "p009",
                "rationale": "R3",
            },
        ],
        "selected_hook_id": "h1",
        "beats": [
            {
                "id": "b1",
                "label": "one",
                "bullet_index": 0,
                "start_phrase_id": "p001",
                "end_phrase_id": "p002",
            }
        ],
        "interviewer_prompt": "Ask about outcomes.",
        "packet_format": "v2",
        "active_session_id": None,
        "active_session_status": None,
    }
    base.update(over)
    return base


def test_recording_js_and_html_parse():
    subprocess.run([NODE, "--check", str(JS)], check=True, timeout=30)
    html = (API / "recording.html").read_text(encoding="utf-8")
    for element_id in (
        "hookChooser",
        "hookChooserTitle",
        "hookChooserHint",
        "hookOptions",
        "hookPanel",
        # The opening is its own step before the studio (Ziv, 20-Sep), with a
        # way to ask for more, and the timer lives on the camera.
        "hookView",
        "hookViewOptions",
        "moreHooksButton",
        "moreHooksState",
        "timer",
        # The same five destinations as the rest of the workspace: choosing what
        # to record must not feel like leaving the app.
        "bottomNav",
    ):
        assert f'id="{element_id}"' in html
    assert 'class="camera-timer"' in html
    # The strip that said "Phone copy is safe" and counted clips is gone.
    assert "Phone copy is safe" not in html
    # And the record page is the studio now, nothing else. The ideas inbox, the
    # engine-state line, Produce now, Recorded and Put away all live in the
    # workspace; a second copy here showed him seventeen undecided ideas
    # immediately after he had chosen one.
    for gone in ("ideasSection", "ideasList", "moreIdeasButton", "produceNowButton",
                 "recordedSection", "awaySection", "engineState"):
        assert f'id="{gone}"' not in html, f"{gone} is still on the record page"


def test_model_ranks_recommended_first_and_marks_the_current_opening():
    model = run_js("hookChooserModel(idea)", idea=idea(selected_hook_id="h2"))
    assert model["show"] is True and model["locked"] is False
    assert [o["rank"] for o in model["options"]] == [1, 2, 3]
    assert [o["recommended"] for o in model["options"]] == [True, False, False]
    assert [o["current"] for o in model["options"]] == [False, True, False]
    assert model["currentId"] == "h2"
    # Payoff phrases resolve by phrase id; an out-of-range id degrades to empty.
    assert [o["payoff"] for o in model["options"]] == ["Payoff line.", "Second line.", ""]
    assert all(o["question"] and o["rationale"] for o in model["options"])


def test_model_falls_back_to_the_first_option_when_nothing_is_selected():
    model = run_js("hookChooserModel(idea)", idea=idea(selected_hook_id=None))
    assert model["currentId"] == "h1"
    assert model["options"][0]["current"] is True


@pytest.mark.parametrize(
    "context, queue_status",
    [
        ({"sessionStatus": "recording"}, None),
        ({"sessionStatus": "finalizing"}, None),
        ({"clipCount": 1}, None),
        ({"recorderActive": True}, None),
        ({}, "recording"),
    ],
)
def test_model_locks_once_a_take_set_holds_clips(context, queue_status):
    model = run_js(
        "hookChooserModel(idea, context)",
        idea=idea(active_session_status=queue_status, packet_version=3),
        context=context,
    )
    assert model["show"] is False and model["locked"] is True
    assert "locked" in model["reason"] and "v3" in model["reason"]


def test_model_does_not_lock_on_a_draft_session():
    model = run_js(
        "hookChooserModel(idea, context)",
        idea=idea(active_session_id="s1", active_session_status="draft"),
        context={"sessionStatus": "draft", "clipCount": 0},
    )
    assert model["show"] is True and model["locked"] is False


def test_model_hides_for_legacy_packets_and_single_options():
    legacy = run_js(
        "hookChooserModel(idea)",
        idea=idea(packet_format="legacy", hook_options=[], selected_hook_id=None),
    )
    assert legacy["show"] is False and legacy["locked"] is False and legacy["options"] == []
    single = run_js("hookChooserModel(idea)", idea=idea(hook_options=[idea()["hook_options"][0]]))
    assert single["show"] is False and len(single["options"]) == 1


def test_choose_hook_response_rebinds_the_idea_to_the_new_version():
    packet = {
        "id": "p2",
        "candidate_id": "c1",
        "version": 2,
        "bullets": ["one", "two", "three", "four", "five"],
        "script_phrases": ["Opening two.", "Second line.", "Third line.", "Payoff line."],
        "hook_options": idea()["hook_options"],
        "selected_hook_id": "h2",
        "beats": idea()["beats"],
        "interviewer_prompt": None,
        "packet_format": "v2",
        "status": "ready",
    }
    merged = run_js(
        "packetToIdea(idea, packet)",
        idea=idea(active_session_id="s-old", active_session_status="draft"),
        packet=packet,
    )
    assert merged["packet_id"] == "p2" and merged["packet_version"] == 2
    assert merged["selected_hook_id"] == "h2"
    assert merged["script_phrases"][0] == "Opening two."
    # Queue-only fields survive; the old draft session is not carried over.
    assert merged["title"] == "Plan the course from the problems"
    assert merged["candidate_id"] == "c1"
    assert merged["interviewer_prompt"] == "Ask about outcomes."
    assert merged["active_session_id"] is None and merged["active_session_status"] is None


# The ideas inbox, the engine-state line, the "Produce now" run words and the
# recorded list were all removed from the recorder on 22-Sep: every one of them
# now lives in the workspace (Topics, Today, Library), and keeping a second copy
# on the record page meant being shown seventeen undecided ideas straight after
# choosing one. Their tests went with them rather than being left to describe a
# flow that no longer exists.


def test_a_landscape_camera_is_cropped_to_a_vertical_video():
    """22-Sep: every clip this phone recorded was 2288x1288. Upright, but framed
    landscape, cutting off the top of his head and unpostable as a vertical."""
    js = JS.read_text(encoding="utf-8")
    assert "function portraitStream(" in js
    assert "aspectRatio" in js, "the portrait camera is not even asked for"
    # The canvas is what gets recorded AND previewed, or he cannot see the crop.
    assert "canvas.captureStream" in js
    assert "state.stream = portraitStream(camera);" in js
    assert 'srcObject = state.stream;' in js
    # Measured from real frames: a camera that reports nothing is not portrait.
    assert "function measure(stream)" in js
    assert "element.videoWidth" in js
    body = js[js.index("function portraitStream("):]
    body = body[: body.index("\n  async function requestWakeLock")]
    assert "height >= width) return raw" in body, "a portrait camera must pass through untouched"
    assert "9 / 16" in body


def test_the_right_rail_is_text_size_not_a_scroll_slider():
    """The slider was "very un intuitive, first too slow then too fast" (23-Sep);
    plus and minus for the text size is what he adjusts mid-take."""
    html = (API / "recording.html").read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    for gone in ("scrollPosition", "scrollUp", "scrollDown", "textSizeButton"):
        assert f'id="{gone}"' not in html, f"{gone} is still on the page"
        assert f'$("{gone}")' not in js, f"{gone} is still wired in the script"
    assert 'id="textBigger"' in html and 'id="textSmaller"' in html
    assert 'changeTextSize(.1)' in js and 'changeTextSize(-.1)' in js
    # Bounded, not cycling: one tap too many must never throw the words back to
    # their smallest mid-take, which the old single button did.
    body = js[js.index("function changeTextSize(") :][:400]
    assert "Math.min(TEXT_MAX, Math.max(TEXT_MIN" in body
    assert 'localStorage.setItem("tce-reader-size"' in body


def test_the_phone_camera_uploads_through_the_clip_path_and_frees_the_camera():
    """Chrome on his phone never hands over a portrait frame, so the native selfie
    camera is the route to a vertical video without a crop."""
    html = (API / "recording.html").read_text(encoding="utf-8")
    assert 'id="nativeCameraInput" type="file" accept="video/*" capture="user"' in html
    js = JS.read_text(encoding="utf-8")
    body = js[js.index("async function uploadNativeVideo(") :][:3500]
    # The same checked path as a browser take: pieces with a checksum, then the
    # audio-and-video check, then sent for editing.
    assert '"X-Chunk-Sha256": digest' in body
    assert "/finish`" in body and "await finishSession();" in body
    # Radical transparency: which piece of how many, in megabytes.
    assert "piece ${index + 1} of ${pieces}" in body
    # And the native app cannot open a camera this page is still holding.
    opener = js[js.index("async function openNativeCamera(") :]
    opener = opener[: opener.index("\n  }\n")]
    assert opener.index("releaseBrowserCamera();") < opener.index('$("nativeCameraInput").click();')
    # The camera chooser is never opened after an await: a tap is permission for
    # one thing, and floating the script already spent it.
    before_click = opener[: opener.index('$("nativeCameraInput").click();')]
    assert "await" not in before_click, "an await before the camera click loses the tap"
    # And the floating window is told where to go: the top, under the lens.
    assert "TOP of the screen, right under the camera" in js


def test_the_opening_and_a_first_point_that_repeat_it_are_one_line():
    """Choosing the recommended opening usually gives back the first bullet almost
    word for word ("...back on the phone." / "...back on the phone after the
    event"), and the reader printed both."""
    js = JS.read_text(encoding="utf-8")
    assert "function sameLine(" in js
    body = js[js.index("function sameLine(") : js.index("function openingLine(")]
    # Unicode aware, or a Hebrew script compares as two empty strings and every
    # line merges with every other one.
    assert r"\p{L}" in body and "/gu" in body
    assert "startsWith" in body
    # One id per line: a standalone opening must not answer to point 1's jump.
    assert 'openingLine(idea, hook.text, "points-opening")' in js
    assert 'openingLine(idea, text, "points-0")' in js


def test_while_recording_the_right_hand_button_finishes_for_real():
    """"I cant finish! its not working": the only finish button on screen while
    recording was Finish clip, which closes the clip and sends nothing."""
    css = (API / "recording.css").read_text(encoding="utf-8")
    assert ".studio-view.is-recording #finishSessionButton small { display: none; }" in css
    # And beside it, Stop: keeps the take without sending it (23-Sep, "I am stuck").
    assert ".studio-view.is-recording #finishClipButton { display: block; }" in css
    # Above the video, which covered them in a split-screen half.
    assert ".studio-view.is-recording .controls { z-index: 30; }" in css
    js = JS.read_text(encoding="utf-8")
    # And it is never the greyed-out one.
    assert '$("finishSessionButton").disabled = false;' in js
    # The message about unsent video must name the button that is on screen.
    assert "press Finish again" in js
    assert "press Finish clip again" not in js
