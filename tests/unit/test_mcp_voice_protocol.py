"""The TCE tool server over the real MCP protocol.

The other voice tests call each family's handlers through a fake registrar,
which is exactly why they could not see that the real SDK refused every
JSON-Schema tool (nothing loaded but the two tools with no arguments). These
start `node mcp-server/index.mjs` over stdio with the SDK's own client, point it
at a fake TCE API on 127.0.0.1, and read back:

  - the tool list the brain would get,
  - what each call returned, and
  - `seen`: what Claude Code actually hands the model for that result. With
    structuredContent set, Claude Code gives the model JSON.stringify of it and
    drops the text blocks, so anything the brain must hear has to be in there.

A step `{"restart": true}` kills the server and starts a new one, the way a
brain rotation respawns it in the middle of a call.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "mcp-server"

HARNESS = r"""
import http from 'node:http';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const scenario = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const sent = [];
const counters = {};

const api = http.createServer(async (req, res) => {
  let raw = '';
  for await (const chunk of req) raw += chunk;
  const path = req.url.replace(/^\/api\/v1/, '');
  const key = `${req.method} ${path}`;
  sent.push({ key, body: raw ? JSON.parse(raw) : null, auth: req.headers.authorization || null });
  const hits = Object.keys(scenario.responses || {}).filter((k) => key.startsWith(k));
  hits.sort((a, b) => b.length - a.length);
  let value = hits.length
    ? scenario.responses[hits[0]]
    : { status: 404, data: { detail: 'no fake for ' + key } };
  if (Array.isArray(value)) {
    const n = counters[hits[0]] = (counters[hits[0]] ?? -1) + 1;
    value = value[Math.min(n, value.length - 1)];
  }
  res.writeHead(value.status ?? 200, { 'content-type': 'application/json' });
  res.end(JSON.stringify(value.data ?? {}));
});
await new Promise((resolve) => api.listen(0, '127.0.0.1', resolve));
const base = scenario.unreachable ? 'http://127.0.0.1:1' : `http://127.0.0.1:${api.address().port}`;

const stderr = [];
async function start() {
  const env = {
    TCE_API_BASE: base,
    TCE_PRIVATE_KEY: 'test-key',
    TCE_MCP_FAMILIES: scenario.families || '',
  };
  if (scenario.call_id) env.TCE_VOICE_CALL_ID = scenario.call_id;
  if (scenario.state_dir) env.TCE_VOICE_STATE_DIR = scenario.state_dir;
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [fileURLToPath(new URL('./index.mjs', import.meta.url))],
    cwd: fileURLToPath(new URL('.', import.meta.url)),
    env,
    stderr: 'pipe',
  });
  transport.stderr?.on('data', (chunk) => stderr.push(String(chunk)));
  const client = new Client({ name: 'tce-protocol-test', version: '0' });
  await client.connect(transport);
  return client;
}

function modelView(result) {
  // Claude Code's MCP result handling: structuredContent wins and every text
  // block is dropped; without it, the text blocks are what the model reads.
  if (result.structuredContent !== undefined) return JSON.stringify(result.structuredContent);
  return (result.content || []).filter((c) => c.type === 'text').map((c) => c.text).join('\n');
}

let client = await start();
const listed = (await client.listTools()).tools;
const results = [];
for (const step of scenario.steps || []) {
  if (step.restart) {
    await client.close();
    client = await start();
    continue;
  }
  const result = await client.callTool({ name: step.tool, arguments: step.args || {} });
  results.push({
    text: (result.content || []).map((c) => c.text).join('\n'),
    seen: modelView(result),
    isError: Boolean(result.isError),
  });
}
await client.close();
api.close();
console.log(JSON.stringify({
  tools: listed.map((t) => ({
    name: t.name, description: t.description, inputSchema: t.inputSchema,
  })),
  results,
  sent,
  stderr: stderr.join(''),
}));
process.exit(0);
"""


@pytest.fixture(scope="module")
def sdk_installed():
    """The server needs its node_modules. CI does not install them, so do it here."""
    if shutil.which("node") is None:  # pragma: no cover
        pytest.skip("node is not installed")
    if not (ROOT / "node_modules" / "@modelcontextprotocol" / "sdk").exists():  # pragma: no cover
        npm = shutil.which("npm")
        if npm is None:
            pytest.skip("npm is not installed, so the MCP SDK cannot be installed")
        proc = subprocess.run(
            [npm, "ci", "--no-audit", "--no-fund"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert proc.returncode == 0, proc.stderr
    return True


def run(scenario, tmp_path):
    name = f"_protocol_harness_{uuid.uuid4().hex[:8]}.mjs"
    script = ROOT / name
    scenario_file = tmp_path / f"{name}.json"
    scenario_file.write_text(json.dumps(scenario), encoding="utf-8")
    script.write_text(HARNESS, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", str(script), str(scenario_file)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
            encoding="utf-8",
        )
    finally:
        script.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


CID = "11111111-2222-3333-4444-555555555555"
CS = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

TOPIC = {
    "candidate_id": CID,
    "short_id": CID[:8],
    "title": "Nobody opens the report",
    "status": "proposed",
    "decision": "this_week",
    "in_this_week": True,
    "put_away": False,
    "brief": {"version": 2, "values": {"big_idea": "Check the result.", "takeaway": "Open it."}},
    "script": None,
    "research": None,
}
FOUND = {"status": 200, "data": {"status": "found", "topic": TOPIC, "candidates": []}}

VOICE_TOOLS = [
    "tce_week",
    "tce_topic",
    "tce_edit",
    "tce_decide",
    "tce_put_away",
    "tce_restore_idea",
    "tce_choose_hook",
    "tce_reorder_week",
    "tce_undo",
    "tce_write_script",
    "tce_more_hooks",
    "tce_research",
    "tce_jobs",
]

OLDER_TOOLS = [
    "tce_briefing",
    "tce_health",
    "tce_ideas",
    "tce_script",
    "tce_approve",
    "tce_choose_opening",
    "tce_schedule",
    "tce_evidence",
    "tce_news",
    "tce_news_check",
    "tce_news_feeds",
    "tce_produce_now",
    "tce_request",
    "tce_runs",
    "tce_run",
    "tce_resume_run",
]


def step(tool, **args):
    return {"tool": tool, "args": args}


def heard(result):
    """The words inside exactly what the model was handed for this result."""
    seen = result["seen"]
    return json.loads(seen)["said"] if seen.startswith("{") else seen


# ------------------------------------------------------------------ every tool loads


def test_every_family_loads_on_the_real_sdk(sdk_installed, tmp_path):
    out = run({"steps": []}, tmp_path)
    names = sorted(t["name"] for t in out["tools"])
    assert names == sorted(VOICE_TOOLS + OLDER_TOOLS)
    assert "failed to load" not in out["stderr"]
    assert f"{len(VOICE_TOOLS) + len(OLDER_TOOLS)} tools." in out["stderr"]
    edit = next(t for t in out["tools"] if t["name"] == "tce_edit")
    schema = edit["inputSchema"]
    assert sorted(schema["required"]) == ["part", "text", "topic"]
    assert "point 3" in schema["properties"]["part"]["description"]
    approve = next(t for t in out["tools"] if t["name"] == "tce_approve")
    assert approve["inputSchema"]["properties"]["decision"]["enum"] == ["approve", "reject"]


def test_the_voice_seat_gets_its_13_tools_and_a_call_reaches_the_api(sdk_installed, tmp_path):
    out = run(
        {
            "families": "voice",
            "steps": [step("tce_topic", topic="report")],
            "responses": {"GET /editorial/voice/topic": FOUND},
        },
        tmp_path,
    )
    assert sorted(t["name"] for t in out["tools"]) == sorted(VOICE_TOOLS)
    assert out["sent"][0]["key"] == "GET /editorial/voice/topic?q=report"
    assert out["sent"][0]["auth"] == "Bearer test-key"
    assert "Nobody opens the report (id 11111111)" in heard(out["results"][0])


# ------------------------------------------------------------------ what the model hears


def test_the_model_hears_why_a_call_went_nowhere(sdk_installed, tmp_path):
    out = run(
        {
            "families": "voice",
            "unreachable": True,
            "steps": [
                step("tce_week"),
                step("tce_decide", topic="report", decision="sideways"),
                step("tce_undo"),
                step("tce_jobs"),
            ],
        },
        tmp_path,
    )
    unreachable, bad_decision, undo, jobs = (heard(r) for r in out["results"])
    assert "could not reach TCE" in unreachable and "Nothing was read" in unreachable
    assert '"sideways" is not a decision' in bad_decision
    assert "undo" in undo.lower() and "could not" in undo.lower()
    assert "Nothing was started in this call" in jobs


def test_the_model_hears_the_research_summary(sdk_installed, tmp_path):
    rid = "77777777-0000-0000-0000-000000000000"
    out = run(
        {
            "families": "voice",
            "steps": [step("tce_research", topic="report"), step("tce_jobs")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/candidates/": {
                    "status": 202,
                    "data": {"research_id": rid, "state": "running", "already_running": False},
                },
                "GET /editorial/research/": {
                    "data": {
                        "state": "done",
                        "summary": "2 pieces of your own evidence, and no web search.",
                    }
                },
            },
        },
        tmp_path,
    )
    started, jobs = (heard(r) for r in out["results"])
    assert 'Started research on "Nobody opens the report"' in started
    assert "2 pieces of your own evidence, and no web search." in jobs


# ------------------------------------------------------------------ a restart mid-call


def test_a_restart_mid_call_keeps_the_last_change_and_the_jobs(sdk_installed, tmp_path):
    out = run(
        {
            "families": "voice",
            "call_id": "call-restart-1",
            "state_dir": str(tmp_path / "calls"),
            "steps": [
                step("tce_edit", topic="report", part="takeaway", text="Open the result."),
                step("tce_research", topic="report"),
                {"restart": True},
                step("tce_jobs"),
                step("tce_undo"),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/voice/change": {
                    "data": {
                        "change_set_id": CS,
                        "short_id": CS[:8],
                        "said": ['The takeaway now says "Open the result."'],
                        "changes": [],
                        "warnings": [],
                    }
                },
                "POST /editorial/candidates/": {
                    "status": 202,
                    "data": {"research_id": "r1", "state": "running", "already_running": False},
                },
                "GET /editorial/research/": {"data": {"state": "running"}},
                "POST /editorial/change-sets/": {"data": {"said": 'Undone: "Takeaway".'}},
            },
        },
        tmp_path,
    )
    jobs, undo = (heard(r) for r in out["results"][2:])
    assert 'Research for "Nobody opens the report" is still going' in jobs
    assert "Undone" in undo
    assert out["sent"][-1]["key"] == f"POST /editorial/change-sets/{CS}/undo"
