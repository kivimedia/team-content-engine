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


def _function(source: str, name: str) -> str:
    m = re.search(rf"^function {name}\(.*?^\}}\r?$", source, re.M | re.S)
    assert m, name
    return m.group(0)


def run_js(expr: str, **bindings):
    source = JS.read_text(encoding="utf-8")
    script = "\n".join(_function(source, n) for n in HELPERS)
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
    ):
        assert f'id="{element_id}"' in html


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
