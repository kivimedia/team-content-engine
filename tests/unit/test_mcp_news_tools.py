"""The terminal commands for the news lane, driven with a fake engine through Node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "mcp-server"

HARNESS = r"""
import { register } from './tools/news.mjs';
import { reply, failure, shortId } from './tools.mjs';

const scenario = JSON.parse(process.argv[2]);
const tools = {};
register({ tool: (name, d, s, fn) => { tools[name] = fn; } },
  async (method, path) => {
    const key = `${method} ${path}`;
    const hit = Object.keys(scenario.responses).find((k) => key.startsWith(k));
    return hit ? scenario.responses[hit] : { ok: false, status: 404, data: { error: 'no fake' } };
  },
  { reply, failure, shortId });
const out = await tools[scenario.tool](scenario.args || {});
console.log(JSON.stringify(out.content[0].text));
"""


def run(tool, args, responses):
    if shutil.which("node") is None:  # pragma: no cover
        pytest.skip("node is not installed")
    script = ROOT / "_news_harness.mjs"
    script.write_text(HARNESS, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", str(script), json.dumps({"tool": tool, "args": args, "responses": responses})],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
    finally:
        script.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_non_match_says_so_and_what_was_checked():
    text = run("tce_news_check", {"url": "https://v.example/x"}, {
        "POST /news/check": {"ok": True, "data": {
            "status": "no_match", "why": "only a capability matched", "checked": "40 anchors"}},
    })
    assert "Nothing of yours is touched by this" in text
    assert "checked 40 anchors" in text


def test_a_writeup_is_refused_with_the_reason():
    text = run("tce_news_check", {"url": "https://techcrunch.com/x"}, {
        "POST /news/check": {"ok": True, "data": {
            "status": "unverified", "why": "That is a news site's write-up"}},
    })
    assert "write-up" in text


def test_a_match_reports_the_verdict_and_what_happens_next():
    text = run("tce_news_check", {"url": "https://v.example/r", "wait_seconds": 5}, {
        "POST /news/check": {"ok": True, "data": {
            "status": "matched", "item_id": "11111111-2222-3333-4444-555555555555",
            "why": "matches twilio (vendor)"}},
        "GET /news/items/": {"ok": True, "data": {"appraisal": {
            "verdict": "publish", "reason": "Changes a shop's calls.",
            "format": "changes_my_product", "expires_at": "2026-09-26T08:00:00Z",
            "do_differently": ["Check where an unanswered call ends up."],
            "next": "It joins the next weekly selection as a candidate."}}},
    })
    assert "It matched: matches twilio (vendor)." in text
    assert "Verdict: publish." in text
    assert "changes my product" in text
    assert "next weekly selection" in text


def test_feeds_tell_quiet_from_dead():
    text = run("tce_news_feeds", {}, {
        "GET /news/overview": {"ok": True, "data": {"feeds": [
            {"name": "Dead", "tier": "1a", "down": True, "consecutive_failures": 4,
             "error": "HTTP 500"},
            {"name": "Quiet", "tier": "1a", "down": False, "status": "unchanged"},
        ]}},
    })
    assert "1 DOWN" in text
    assert "!! [1a] Dead: DOWN, 4 failures in a row (HTTP 500)" in text
    assert "   [1a] Quiet: unchanged" in text


def test_the_lane_state_is_said_first():
    text = run("tce_news", {}, {
        "GET /news/overview": {"ok": True, "data": {
            "lane_on": False, "anchor_count": 0, "anchors": {}, "standing_facts": [],
            "feed_alarms": [], "watchlist": []}},
    })
    assert text.startswith("The news lane is OFF")
