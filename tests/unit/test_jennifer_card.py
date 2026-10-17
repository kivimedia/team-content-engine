"""Jennifer's character rides in the call brief and repeats every 10th video tool result (T-13569)."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = (ROOT / "deploy/voice-seat/jennifer-core.txt").read_text(encoding="utf-8").strip()

HARNESS = r"""
import { bump, withCard, wrapHandler, EVERY } from './card.mjs';
const env = { TCE_VOICE_CALL_ID: 'card-test', TCE_VOICE_STATE_DIR: process.argv[1] };
const h = wrapHandler(async () => ({ content: [{ type: 'text', text: 'Saved.' }], structuredContent: { said: 'Saved.', data: {} } }), env);
const outs = [];
for (let i = 0; i < 21; i++) outs.push(await h());
const none = await wrapHandler(async () => ({ content: [{ type: 'text', text: 'x' }] }), {})();
const bad = withCard(null, 10, 'core');
console.log(JSON.stringify({ every: EVERY, texts: outs.map((o) => o.content[0].text), said: outs[9].structuredContent.said, none: none.content[0].text, bad }));
"""


def _run():
    with tempfile.TemporaryDirectory() as d:
        out = subprocess.run(["node", "--input-type=module", "-e", HARNESS, d],
                             cwd=ROOT / "mcp-server", capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)


def test_core_text_is_on_the_10th_and_20th_result_only():
    r = _run()
    assert r["every"] == 10
    with_core = [i + 1 for i, t in enumerate(r["texts"]) if CORE in t]
    assert with_core == [10, 20]
    assert r["texts"][0] == "Saved."


def test_the_spoken_copy_carries_it_too_and_no_call_id_means_no_count():
    r = _run()
    assert CORE in r["said"]
    assert r["none"] == "x"
    assert r["bad"] is None


def test_the_core_keeps_the_notes_rule_on_top():
    assert "stay quiet" in CORE and "outranks" in CORE
    assert "—" not in CORE and " -- " not in CORE


def test_the_call_brief_opens_with_the_same_character():
    brief = (ROOT / "deploy/voice-seat/tce-brief.md").read_text(encoding="utf-8")
    assert CORE in brief
    assert "never add an opinion" in brief  # her existing rule is untouched
    assert "Honestly? The opening's slow." in brief
