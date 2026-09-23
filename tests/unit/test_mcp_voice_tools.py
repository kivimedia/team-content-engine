"""The voice agent's tools, driven with a fake engine through Node.

Each scenario runs a SEQUENCE of tool calls in one Node process, because "undo
the last thing I changed" and "is the script ready yet" only mean something
across calls. The fake records every request, so the tests can check what the
tools sent (attribution included), not only what they said.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "mcp-server"

HARNESS = r"""
import { register, parsePart } from './tools/voice.mjs';
import { reply, failure, shortId, authHeaders, identityFromEnv, familyFilter } from './tools.mjs';

const scenario = JSON.parse(process.argv[2]);
if (scenario.unit) {
  const out = {
    parts: (scenario.parts || []).map((p) => parsePart(p)),
    bearer: authHeaders({ key: 'k1', workspaceId: 'ws1' }),
    basic: authHeaders({ user: 'ziv', password: 'pw' }),
    envBearer: identityFromEnv({
      TCE_PRIVATE_KEY: 'k1', TCE_WORKSPACE_ID: 'ws1', TCE_BASIC_USER: 'u', TCE_BASIC_PASS: 'p',
    }),
    envBasic: identityFromEnv({ TCE_BASIC_USER: 'u', TCE_BASIC_PASS: 'p' }),
    envNone: identityFromEnv({}),
    families: familyFilter({ TCE_MCP_FAMILIES: 'voice, ideas' }),
    noFamilies: familyFilter({}),
  };
  console.log(JSON.stringify(out));
  process.exit(0);
}
const tools = {};
const sent = [];
const counters = {};
register({ tool: (name, d, s, fn) => { tools[name] = fn; } },
  async (method, path, body) => {
    const key = `${method} ${path}`;
    sent.push({ key, body: body ?? null });
    const hits = Object.keys(scenario.responses).filter((k) => key.startsWith(k));
    hits.sort((a, b) => b.length - a.length);
    if (!hits.length) return { ok: false, status: 404, data: { detail: 'no fake for ' + key } };
    const value = scenario.responses[hits[0]];
    if (Array.isArray(value)) {
      const n = counters[hits[0]] = (counters[hits[0]] ?? -1) + 1;
      return value[Math.min(n, value.length - 1)];
    }
    return value;
  },
  { reply, failure, shortId });
const texts = [];
for (const step of scenario.steps) {
  const out = await tools[step.tool](step.args || {});
  texts.push(out.content[0].text);
}
console.log(JSON.stringify({ texts, sent, names: Object.keys(tools).sort() }));
"""


def run(scenario):
    if shutil.which("node") is None:  # pragma: no cover
        pytest.skip("node is not installed")
    script = ROOT / "_voice_harness.mjs"
    script.write_text(HARNESS, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", str(script), json.dumps(scenario)],
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
    "script": {
        "packet_id": "99999999-8888-7777-6666-555555555555",
        "version": 3,
        "status": "ready",
        "opening": "Your AI said done.",
        "points": ["One.", "Two.", "Three."],
        "script_phrases": ["Your AI said done.", "Line two."],
        "hooks": [
            {"n": 1, "id": "h1", "text": "Your AI said done.", "chosen": True},
            {"n": 2, "id": "h2", "text": "Nobody checks.", "chosen": False},
        ],
    },
    "research": None,
}

FOUND = {"ok": True, "status": 200, "data": {"status": "found", "topic": TOPIC, "candidates": []}}


def change_ok(said, short="aaaaaaaa", changes=None):
    return {
        "ok": True,
        "status": 200,
        "data": {
            "change_set_id": CS,
            "short_id": short,
            "said": said,
            "changes": changes or [],
            "warnings": [],
            "version": 4,
        },
    }


def step(tool, **args):
    return {"tool": tool, "args": args}


# ------------------------------------------------------------------ plumbing


def test_the_voice_family_registers_every_tool():
    out = run({"steps": [], "responses": {}})
    assert out["names"] == sorted(
        [
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
    )


def test_parts_he_names_map_to_fields_and_the_vps_key_is_a_bearer():
    out = run(
        {
            "unit": True,
            "parts": [
                "point 3",
                "Line 5",
                "the opening",
                "Big idea",
                "your angle",
                "facebook post",
                "call to action",
                "the moon",
            ],
        }
    )
    fields = [p["field"] if p else None for p in out["parts"]]
    assert fields == [
        "bullets.2",
        "script_phrases.4",
        "script_phrases.0",
        "big_idea",
        "distinctive_perspective",
        "facebook_post",
        "cta",
        None,
    ]
    assert out["parts"][0]["target"] == "script" and out["parts"][3]["target"] == "brief"
    assert out["bearer"] == {"Authorization": "Bearer k1", "X-Workspace-Id": "ws1"}
    assert out["basic"]["Authorization"].startswith("Basic ")
    assert out["envBearer"]["mode"] == "bearer", "the private key wins on the VPS"
    assert out["envBasic"]["mode"] == "basic"
    assert out["envNone"]["ok"] is False
    assert out["families"] == ["voice", "ideas"] and out["noFamilies"] is None


# ------------------------------------------------------------------ reading


def test_the_week_says_the_order_the_script_states_and_what_needs_deciding():
    out = run(
        {
            "steps": [step("tce_week")],
            "responses": {
                "GET /editorial/today": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "week": {
                            "primary": [
                                {
                                    "candidate_id": CID,
                                    "title": "First topic",
                                    "script_state": "ready",
                                    "rank": 1,
                                },
                                {
                                    "candidate_id": "22222222-0000-0000-0000-000000000000",
                                    "title": "Second topic",
                                    "script_state": "none",
                                    "rank": 2,
                                },
                            ],
                            "reserve": [],
                        },
                        "attention": {"waiting": 2, "pending_reviews": 0},
                        "next_action": {
                            "label": "Start recording",
                            "detail": "First topic is first.",
                        },
                    },
                },
                "GET /editorial/topics": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "topics": [
                            {
                                "candidate_id": "33333333-0000-0000-0000-000000000000",
                                "title": "Undecided A",
                                "decision": None,
                            },
                            {
                                "candidate_id": "44444444-0000-0000-0000-000000000000",
                                "title": "Undecided B",
                                "decision": None,
                            },
                        ]
                    },
                },
            },
        }
    )
    text = out["texts"][0]
    assert "1. First topic - script ready (id 11111111)" in text
    assert "2. Second topic - no script yet" in text
    assert "2 ideas need a decision" in text and "- Undecided A (id 33333333)" in text
    assert "Next: Start recording." in text


def test_a_topic_reads_its_opening_points_and_numbered_options():
    out = run(
        {
            "steps": [step("tce_topic", topic="report")],
            "responses": {"GET /editorial/voice/topic": FOUND},
        }
    )
    text = out["texts"][0]
    assert text.startswith("Nobody opens the report (id 11111111)")
    assert 'Opening: "Your AI said done."' in text
    assert "  3. Three." in text
    assert "  2. Nobody checks." in text and "(in use)" in text
    assert out["sent"][0]["key"] == "GET /editorial/voice/topic?q=report"


def test_ambiguous_words_ask_which_one():
    out = run(
        {
            "steps": [step("tce_topic", topic="follow up")],
            "responses": {
                "GET /editorial/voice/topic": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "status": "ambiguous",
                        "topic": None,
                        "candidates": [
                            {"title": "Follow up fast", "short_id": "aaaa1111"},
                            {"title": "Follow up after", "short_id": "bbbb2222"},
                        ],
                    },
                }
            },
        }
    )
    text = out["texts"][0]
    assert "More than one topic matches" in text and "2. Follow up after (id bbbb2222)" in text


def test_no_match_says_so():
    out = run(
        {
            "steps": [step("tce_topic", topic="zebra")],
            "responses": {
                "GET /editorial/voice/topic": {
                    "ok": True,
                    "status": 200,
                    "data": {"status": "none", "candidates": []},
                }
            },
        }
    )
    assert out["texts"][0].startswith('No topic matches "zebra"')


# ------------------------------------------------------------------ writing


def test_an_edit_applies_at_once_as_voice_and_names_the_change():
    out = run(
        {
            "steps": [
                step("tce_edit", topic="report", part="point 3", text="Sharper.", expect="Three.")
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/voice/change": change_ok(
                    ['Point 3 now says "Sharper." (it said "Three.").']
                ),
            },
        }
    )
    text = out["texts"][0]
    assert text.startswith('Done. Point 3 now says "Sharper."')
    assert "change aaaaaaaa" in text
    body = out["sent"][1]["body"]
    assert body["target"] == "script" and body["by"] == "voice"
    assert body["operations"] == [
        {"op": "set_field", "field": "bullets.2", "after": "Sharper.", "expect": "Three."}
    ]


def test_an_edit_that_lost_a_race_reads_back_the_new_text():
    out = run(
        {
            "steps": [
                step("tce_edit", topic="report", part="the opening", text="New.", expect="Old.")
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/voice/change": {
                    "ok": False,
                    "status": 409,
                    "data": {
                        "detail": {
                            "code": "changed",
                            "message": (
                                "The opening line was changed since you read it. "
                                "Nothing was written."
                            ),
                            "current": "Someone else's opening.",
                        }
                    },
                },
            },
        }
    )
    text = out["texts"][0]
    assert "Nothing was written." in text
    assert 'It now says: "Someone else\'s opening."' in text


def test_an_unknown_part_lists_what_can_be_changed_and_calls_nothing():
    out = run(
        {"steps": [step("tce_edit", topic="report", part="the moon", text="x")], "responses": {}}
    )
    assert "I do not know which part" in out["texts"][0]
    assert out["sent"] == []


def test_decide_approve_means_this_week_and_is_attributed():
    out = run(
        {
            "steps": [step("tce_decide", topic="report", decision="approve")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/topics/": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "decision": "this_week",
                        "previous_decision": None,
                        "placed": {"slot": "primary", "rank": 2},
                    },
                },
            },
        }
    )
    assert out["texts"][0] == '"Nobody opens the report" is in this week\'s list, place 2.'
    assert out["sent"][1]["body"] == {"decision": "this_week", "by": "voice"}


def test_put_away_then_undo_brings_it_back():
    out = run(
        {
            "steps": [step("tce_put_away", topic="report"), step("tce_undo")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/topics/" + CID + "/decide": {
                    "ok": True,
                    "status": 200,
                    "data": {"decision": "away", "previous_decision": "this_week"},
                },
                "POST /editorial/topics/" + CID + "/restore": {
                    "ok": True,
                    "status": 200,
                    "data": {"restored": True, "said": "back"},
                },
            },
        }
    )
    assert out["texts"][0] == 'Put away: "Nobody opens the report". It can be brought back.'
    assert out["texts"][1] == 'Undone. "Nobody opens the report" is back where it was.'
    assert out["sent"][-1]["key"] == f"POST /editorial/topics/{CID}/restore"


def test_restore_idea_says_where_it_went():
    out = run(
        {
            "steps": [step("tce_restore_idea", topic="report")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/topics/": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "restored": True,
                        "said": '"Nobody opens the report" is back in saved for later.',
                    },
                },
            },
        }
    )
    assert out["texts"][0] == '"Nobody opens the report" is back in saved for later.'


def test_choose_hook_sends_the_option_number_to_the_script():
    out = run(
        {
            "steps": [step("tce_choose_hook", topic="report", option="2")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/voice/change": change_ok(
                    ["A different opening was chosen."],
                    changes=[{"field": "script_phrases.0", "after": "Nobody checks."}],
                ),
            },
        }
    )
    assert out["texts"][0].startswith('Done. The opening is now option 2: "Nobody checks."')
    body = out["sent"][1]["body"]
    assert body["target"] == "script" and body["operations"] == [
        {"op": "choose_hook", "after": "2"}
    ]


def test_reorder_week_turns_words_into_a_move():
    out = run(
        {
            "steps": [step("tce_reorder_week", topic="report", move="First")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/voice/change": change_ok(
                    ["Nobody opens the report moved to first in the week."]
                ),
            },
        }
    )
    assert "moved to first" in out["texts"][0]
    op = out["sent"][1]["body"]["operations"][0]
    assert op == {"op": "move_topic", "after": {"action": "first", "candidate_id": CID}}


def test_a_bad_move_is_refused_without_calling_anything():
    out = run(
        {"steps": [step("tce_reorder_week", topic="report", move="sideways")], "responses": {}}
    )
    assert '"sideways" is not a move' in out["texts"][0] and out["sent"] == []


# ------------------------------------------------------------------ undo


def test_undo_with_no_id_takes_back_the_last_change_of_this_call():
    out = run(
        {
            "steps": [
                step("tce_edit", topic="report", part="takeaway", text="Open the result."),
                step("tce_undo"),
                step("tce_undo"),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/voice/change": change_ok(["The takeaway now says ..."]),
                "POST /editorial/change-sets/": {
                    "ok": True,
                    "status": 200,
                    "data": {"said": 'Undone: "Takeaway".', "already": False},
                },
            },
        }
    )
    assert out["texts"][1] == 'Undone: "Takeaway".'
    assert out["sent"][2]["key"] == f"POST /editorial/change-sets/{CS}/undo"
    assert out["sent"][2]["body"] == {"by": "voice"}
    assert out["texts"][2].startswith("Nothing has been changed in this call")


def test_undo_by_short_id_finds_a_change_from_earlier_today():
    out = run(
        {
            "steps": [step("tce_undo", change_id="aaaaaaaa")],
            "responses": {
                "GET /editorial/voice/activity": {
                    "ok": True,
                    "status": 200,
                    "data": {"items": [{"kind": "change", "id": CS, "title": "x"}]},
                },
                "POST /editorial/change-sets/": {
                    "ok": True,
                    "status": 200,
                    "data": {"said": "Undone: x."},
                },
            },
        }
    )
    assert out["texts"][0] == "Undone: x."
    assert out["sent"][-1]["key"] == f"POST /editorial/change-sets/{CS}/undo"


def test_undo_refused_because_it_changed_again_reads_the_current_text():
    out = run(
        {
            "steps": [step("tce_undo", change_id=CS)],
            "responses": {
                "POST /editorial/change-sets/": {
                    "ok": False,
                    "status": 409,
                    "data": {
                        "detail": {
                            "code": "changed",
                            "message": "Point 1 was changed again after that. Nothing was written.",
                            "current": "Three.",
                        }
                    },
                }
            },
        }
    )
    assert 'It now says: "Three."' in out["texts"][0]


# ------------------------------------------------------------------ jobs


def test_a_script_starts_and_jobs_announces_it_once_when_ready():
    running = {
        "ok": True,
        "status": 200,
        "data": {"job": {"state": "running", "current_activity": "Queued packet"}},
    }
    done = {"ok": True, "status": 200, "data": {"job": {"state": "done"}}}
    out = run(
        {
            "steps": [
                step("tce_write_script", topic="report"),
                step("tce_jobs"),
                step("tce_jobs", new_only=True),
                step("tce_jobs", new_only=True),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/candidates/": {
                    "ok": True,
                    "status": 200,
                    "data": {"status": "running"},
                },
                "GET /editorial/candidates/": [running, done, done],
            },
        }
    )
    assert out["texts"][0].startswith('Started the script for "Nobody opens the report"')
    assert "is still going (Queued packet)" in out["texts"][1]
    assert out["texts"][2] == 'The script for "Nobody opens the report" is ready.'
    assert out["texts"][3] == "Nothing new has finished yet."


def test_a_script_already_being_written_is_still_tracked():
    out = run(
        {
            "steps": [step("tce_write_script", topic="report"), step("tce_jobs")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/candidates/": {
                    "ok": False,
                    "status": 409,
                    "data": {"detail": "packet already being written"},
                },
                "GET /editorial/candidates/": {
                    "ok": True,
                    "status": 200,
                    "data": {"job": {"state": "done"}},
                },
            },
        }
    )
    assert "already being written" in out["texts"][0]
    assert "is ready" in out["texts"][1]


def test_more_hooks_uses_the_current_script():
    out = run(
        {
            "steps": [step("tce_more_hooks", topic="report"), step("tce_jobs")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/packets/": {
                    "ok": True,
                    "status": 202,
                    "data": {"status": "running"},
                },
                "GET /editorial/packets/": {"ok": True, "status": 200, "data": {"state": "done"}},
            },
        }
    )
    assert (
        out["sent"][1]["key"]
        == "POST /editorial/packets/99999999-8888-7777-6666-555555555555/more-hooks"
    )
    assert out["texts"][1] == 'More openings for "Nobody opens the report" are ready.'


def test_research_starts_and_its_summary_is_read_when_done():
    rid = "77777777-0000-0000-0000-000000000000"
    out = run(
        {
            "steps": [step("tce_research", topic="report"), step("tce_jobs")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/candidates/": {
                    "ok": True,
                    "status": 202,
                    "data": {"research_id": rid, "state": "running", "already_running": False},
                },
                "GET /editorial/research/": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "state": "done",
                        "summary": (
                            "Research on it is ready: 2 pieces of your own evidence, "
                            "and no web search."
                        ),
                    },
                },
            },
        }
    )
    assert out["texts"][0].startswith('Started research on "Nobody opens the report"')
    assert out["sent"][1]["body"] == {"by": "voice"}
    assert "2 pieces of your own evidence" in out["texts"][1]


def test_jobs_with_nothing_started_says_so():
    out = run({"steps": [step("tce_jobs")], "responses": {}})
    assert out["texts"][0] == "Nothing was started in this call."
