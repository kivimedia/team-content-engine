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

HELPERS = ("payoffPhrase", "hookChooserModel", "packetToIdea", "runWords")
CONSTS = ("RUN_WORDS",)


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
        # The decisions he actually makes live in the recorder now, not the
        # developer dashboard: which idea gets a script, and which is put away.
        "ideasSection",
        "ideasList",
        "moreIdeasButton",
    ):
        assert f'id="{element_id}"' in html
    assert 'class="camera-timer"' in html
    # The strip that said "Phone copy is safe" and counted clips is gone.
    assert "Phone copy is safe" not in html


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


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        ({"state": "queued", "stages": []}, "Queued. It starts within five minutes."),
        ({"state": "collecting"}, "Collecting evidence from Fathom and GitHub."),
        ({"state": "exporting"}, "Writing the Google Docs."),
        ({"state": "ready"}, "Ready. Reload this page to see the new scripts."),
    ],
)
def test_run_words_say_what_is_happening_now(run, expected):
    assert run_js("runWords(run)", run=run) == expected


def test_waiting_states_show_the_real_reason_not_the_word_queued():
    """Ziv clicked Produce now and read \"Run queued. You can leave this page\"
    while the run was actually parked on a stopped worker (20-Sep-2026)."""
    detail = "No subscription worker has reported in the last 3 minutes."
    for state in ("waiting_worker", "waiting_capacity"):
        assert run_js("runWords(run)", run={"state": state, "error_detail": detail}) == detail
    assert (
        run_js("runWords(run)", run={"state": "waiting_worker"})
        == "Waiting for the desktop subscription worker."
    )
    failed = {"state": "failed", "error_detail": "boom"}
    assert run_js("runWords(run)", run=failed) == "Stopped: boom"


def test_the_recorder_offers_a_script_and_an_archive_for_a_waiting_idea():
    js = JS.read_text(encoding="utf-8")
    assert "Write the script" in js
    assert "Put it away" in js
    # Both go to the engine's own routes, not to a dashboard page.
    assert "/editorial/candidates/${candidate.id}/packet" in js
    assert "/editorial/candidates/${candidate.id}/archive" in js
    # A long queue is reported, never spun on forever.
    assert "Still queued after twelve minutes" in js


def test_an_ideas_state_survives_its_neighbours_changing():
    """Ziv, 20-Sep: "I mark a few as write the script. then mark ONE as put it
    away - it reloads and removes ALL the markings of work on write the
    script." Rows are reused by id and the phase lives outside the DOM."""
    js = JS.read_text(encoding="utf-8")
    assert "state.phases" in js and "state.rows" in js
    # The list is no longer wiped and rebuilt on every change. Only renderIdeas is
    # read: the archive and recorded lists hold no live state and may rebuild.
    body = js.split("  function renderIdeas(")[1]
    render = body[: body.index("\n  function ")]
    assert "list.replaceChildren()" not in render
    assert "row.remove(); state.rows.delete(id);" in js
    # A decided idea stops offering the same two choices.
    assert '.idea-row-actions").hidden = phase !== "waiting"' in js
    # And a mistake is undoable.
    assert "Bring it back" in js
    assert "restoreIdea" in js
    # A poll that finds its idea archived stops instead of writing over it.
    assert 'if (ideaPhase(candidate.id).phase !== "writing") return;' in js


def test_an_idea_says_where_it_came_from_and_the_engine_says_if_it_can_act():
    js = JS.read_text(encoding="utf-8")
    # Provenance, from citations the API already returns.
    assert "function ideaSource" in js
    assert "piece${code === 1" in js and "From ${names" in js
    # What he put away survives a reload, with a way back.
    assert "function renderAway" in js and "awaySummary" in js
    # Withdrawn ideas are hidden from the default listing, so they are fetched
    # by name - otherwise Put away looked like deletion after a refresh.
    assert "candidates?status=withdrawn" in js
    assert "function loadAwayIdeas" in js
    # And whether pressing anything will actually start work.
    assert "loadEngineState" in js
    assert "will start when it checks in" in js


def test_asking_for_a_script_puts_the_idea_in_the_queue():
    """The row said 'It is in the queue above' while the recording queue only
    shows approved ideas, so the script existed and the queue stayed empty."""
    js = JS.read_text(encoding="utf-8")
    done = js.split('if (job.state === "done")')[1].split('if (job.state === "failed")')[0]
    assert "/feedback" in done
    assert '"kind": "approve"' in done or '"approve"' in done
    assert 'created_by: "ziv"' in done or '"created_by": "ziv"' in done
    assert "loadQueue()" in done


def test_an_idea_whose_script_exists_offers_the_queue_not_another_write():
    """Three packets were written and invisible because nothing approved them,
    and offering Write the script again would pay for the same words twice."""
    js = JS.read_text(encoding="utf-8")
    assert "const written = (candidate.packet_count || 0) > 0;" in js
    assert 'written ? "Put it in the queue" : "Write the script"' in js
    assert "function queueIdea" in js
