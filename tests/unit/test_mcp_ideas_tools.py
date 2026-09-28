"""The terminal's ideas tools, driven with a fake engine through Node."""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "mcp-server"

HARNESS = r"""
import { register } from './tools/ideas.mjs';
import { reply, failure, shortId } from './tools.mjs';

const scenario = JSON.parse(process.argv[2]);
const tools = {};
const sent = [];
register({ tool: (name, d, s, fn) => { tools[name] = fn; } },
  async (method, path) => {
    const key = `${method} ${path}`;
    sent.push(key);
    // The longest matching fake wins, so a named lookup has its own answer.
    const hits = Object.keys(scenario.responses).filter((k) => key.startsWith(k));
    hits.sort((a, b) => b.length - a.length);
    if (!hits.length) return { ok: false, status: 404, data: { error: 'no fake' } };
    return scenario.responses[hits[0]];
  },
  { reply, failure, shortId });
const out = await tools[scenario.tool](scenario.args || {});
const data = out.structuredContent?.data ?? null;
console.log(JSON.stringify({ text: out.content[0].text, data, sent }));
"""


def run(tool, args, responses):
    if shutil.which("node") is None:  # pragma: no cover
        pytest.skip("node is not installed")
    script = ROOT / f"_ideas_harness_{uuid.uuid4().hex[:8]}.mjs"
    script.write_text(HARNESS, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", str(script), json.dumps({"tool": tool, "args": args, "responses": responses})],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
        )
    finally:
        script.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


FILMED = "11111111-2222-3333-4444-555555555555"
NEXT = "22222222-0000-0000-0000-000000000000"
PACKET = "99999999-8888-7777-6666-555555555555"


def idea(candidate_id, title):
    return {
        "candidate_id": candidate_id,
        "packet_id": PACKET,
        "packet_version": 2,
        "title": title,
        "big_idea": "Check the result before you call it done.",
        "bullets": ["Nobody opens the report.", "Open it first."],
        "script_phrases": ["Your AI said done.", "Nobody checked."],
        "hook_options": [{"id": "h1", "text": "Your AI said done.", "question": "Did it?"}],
        "selected_hook_id": "h1",
    }


def queue(*ideas):
    return {"ok": True, "status": 200, "data": {"ideas": list(ideas), "count": len(ideas)}}


WEEK = {
    "ok": True,
    "status": 200,
    "data": {
        "primary": [
            {"candidate_id": FILMED, "title": "Filmed on Sunday", "script_state": "ready",
             "packet_id": PACKET, "filmed": True},
            {"candidate_id": NEXT, "title": "Next to film", "script_state": "ready",
             "packet_id": PACKET, "filmed": False},
        ],
        "reserve": [
            {"candidate_id": "33333333-0000-0000-0000-000000000000",
             "title": "Spare in draft", "script_state": "draft", "filmed": False},
        ],
    },
}


def test_a_filmed_topics_script_is_still_read_and_says_it_was_filmed():
    """28-Sep review: the studio queue holds only what he has still to film, and
    tce_script looked nowhere else, so the script of a topic he filmed this week
    answered "not in the recording queue ... tce_approve moves one in", sending
    the session to approve a topic already chosen and filmed."""
    out = run(
        "tce_script",
        {"title": "filmed on sunday"},
        {
            "GET /production/recording-queue?candidate=": queue(
                idea(FILMED, "Filmed on Sunday"), idea(NEXT, "Next to film")
            ),
            "GET /production/recording-queue": queue(idea(NEXT, "Next to film")),
            "GET /editorial/weeks/current/lineup": WEEK,
        },
    )
    assert out["text"].startswith("Filmed on Sunday (filmed already")
    assert "Walking points:" in out["text"] and "Nobody opens the report." in out["text"]
    assert "tce_approve" not in out["text"]
    assert out["data"]["candidate_id"] == FILMED and out["data"]["filmed"] is True
    assert f"GET /production/recording-queue?candidate={FILMED}" in out["sent"]


def test_a_script_not_in_the_week_says_so_honestly():
    out = run(
        "tce_script",
        {"title": "something else"},
        {
            "GET /production/recording-queue": queue(idea(NEXT, "Next to film")),
            "GET /editorial/weeks/current/lineup": WEEK,
        },
    )
    assert "not in this week's list" in out["text"]
    assert "tce_approve" not in out["text"]
    assert out["data"]["found"] is False


def test_a_week_topic_without_a_ready_script_says_where_its_script_is():
    out = run(
        "tce_script",
        {"title": "spare in draft"},
        {
            "GET /production/recording-queue": queue(idea(NEXT, "Next to film")),
            "GET /editorial/weeks/current/lineup": WEEK,
        },
    )
    assert '"Spare in draft" is in this week\'s list, but its script is in draft' in out["text"]
    assert "tce_approve" not in out["text"]
