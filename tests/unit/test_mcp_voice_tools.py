"""The voice agent's tools, driven with a fake engine through Node.

Each scenario runs a SEQUENCE of tool calls in one Node process, because "undo
the last thing I changed" and "is the script ready yet" only mean something
across calls. The fake records every request, so the tests can check what the
tools sent (attribution included), not only what they said.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
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
const descs = {};
const sent = [];
const counters = {};
register({ tool: (name, d, s, fn) => { tools[name] = fn; descs[name] = d; } },
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
const seen = [];
for (const step of scenario.steps) {
  const out = await tools[step.tool](step.args || {});
  texts.push(out.content[0].text);
  // What Claude Code hands the model: structuredContent alone when it is set.
  seen.push(out.structuredContent !== undefined
    ? JSON.stringify(out.structuredContent)
    : out.content.map((c) => c.text).join(' '));
}
console.log(JSON.stringify({ texts, seen, sent, descs, names: Object.keys(tools).sort() }));
"""


def run(scenario, env=None):
    if shutil.which("node") is None:  # pragma: no cover
        pytest.skip("node is not installed")
    script = ROOT / f"_voice_harness_{uuid.uuid4().hex[:8]}.mjs"
    script.write_text(HARNESS, encoding="utf-8")
    # A call id from the shell running the tests must not leak into them.
    base_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("TCE_VOICE_CALL_ID", "KMBOT_VOICE_SESSION", "TCE_VOICE_STATE_DIR")
    }
    try:
        proc = subprocess.run(
            ["node", str(script), json.dumps(scenario)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            encoding="utf-8",
            env={**base_env, **(env or {})},
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


def test_a_close_but_unsure_match_asks_before_any_write():
    out = run(
        {
            "steps": [
                step("tce_edit", topic="pricing fennel", part="takeaway", text="Charge more.")
            ],
            "responses": {
                "GET /editorial/voice/topic": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "status": "ambiguous",
                        "topic": None,
                        "candidates": [{"title": "How I set my pricing", "short_id": "cccc3333"}],
                    },
                },
                "POST /editorial/voice/change": change_ok(["The takeaway now says ..."]),
            },
        }
    )
    text = out["texts"][0]
    assert "More than one" not in text
    assert '"How I set my pricing" (id cccc3333)' in text and "Ask him if that is the one" in text
    assert [s["key"] for s in out["sent"]] == [
        "GET /editorial/voice/topic?q=pricing%20fennel&strict=1"
    ], "nothing is written to a topic he did not confirm"


def test_a_write_asks_for_a_sure_match_and_a_read_does_not():
    out = run(
        {
            "steps": [
                step("tce_topic", topic="report"),
                step("tce_decide", topic="report", decision="later"),
                step("tce_put_away", topic="report"),
                step("tce_write_script", topic="report"),
                step("tce_research", topic="report"),
            ],
            "responses": {"GET /editorial/voice/topic": FOUND},
        }
    )
    finds = [s["key"] for s in out["sent"] if s["key"].startswith("GET /editorial/voice/topic")]
    assert finds[0] == "GET /editorial/voice/topic?q=report"
    assert finds[1:] == ["GET /editorial/voice/topic?q=report&strict=1"] * 4


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


def test_choose_hook_sends_the_option_number_and_the_opening_he_heard():
    out = run(
        {
            "steps": [step("tce_choose_hook", topic="report", option="2", expect="Nobody checks.")],
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
        {"op": "choose_hook", "after": "2", "expect": "Nobody checks."}
    ]
    assert "expect" in out["descs"]["tce_choose_hook"]


def test_an_opening_he_did_not_hear_reads_the_options_as_they_are_now():
    out = run(
        {
            "steps": [step("tce_choose_hook", topic="report", option="2", expect="Old two.")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/voice/change": {
                    "ok": False,
                    "status": 409,
                    "data": {
                        "detail": {
                            "code": "changed",
                            "message": "The opening options changed since you read them.",
                            "current": [{"n": 1, "text": "New one."}, {"n": 2, "text": "New two."}],
                        }
                    },
                },
            },
        }
    )
    text = out["texts"][0]
    assert "changed since you read them" in text
    assert '1. "New one."' in text and '2. "New two."' in text


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


DECIDE = f"POST /editorial/topics/{CID}/decide"
UNDO_DECISION = f"POST /editorial/topics/{CID}/undo-decision"
DECISION_ID = "dddddddd-0000-0000-0000-000000000000"


def approved(previous, added=True):
    return {
        "ok": True,
        "status": 200,
        "data": {
            "decision": "this_week",
            "previous_decision": previous,
            "added_to_week": added,
            "decision_id": DECISION_ID,
            "placed": {"slot": "primary", "rank": 1},
        },
    }


def test_undoing_an_approval_says_what_it_added_to_the_week():
    out = run(
        {
            "steps": [step("tce_decide", topic="report", decision="approve"), step("tce_undo")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                DECIDE: approved("this_week"),
                UNDO_DECISION: {
                    "ok": True,
                    "status": 200,
                    "data": {"said": '"Nobody opens the report" is off this week\'s list again.'},
                },
            },
        }
    )
    sent = [s for s in out["sent"] if s["key"] == UNDO_DECISION]
    assert sent and sent[0]["body"] == {
        "previous": "this_week",
        "decision": "this_week",
        "added_to_week": True,
        "removed_from_week": False,
        "by": "voice",
    }
    assert not [s for s in out["sent"][2:] if s["key"] == DECIDE], "one route does both"
    assert "off this week's list" in out["texts"][1]


def test_undoing_a_later_says_the_week_lost_it_so_it_goes_back():
    out = run(
        {
            "steps": [step("tce_decide", topic="report", decision="later"), step("tce_undo")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                DECIDE: {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "decision": "later",
                        "previous_decision": "this_week",
                        "added_to_week": False,
                        "removed_from_week": {"slot": "primary", "rank": 2},
                    },
                },
                UNDO_DECISION: {"ok": True, "status": 200, "data": {"said": "back"}},
            },
        }
    )
    sent = [s for s in out["sent"] if s["key"] == UNDO_DECISION]
    assert sent[0]["body"]["removed_from_week"] is True
    assert sent[0]["body"]["previous"] == "this_week"


def test_a_refused_undo_lets_the_next_undo_move_on():
    out = run(
        {
            "steps": [
                step("tce_edit", topic="report", part="takeaway", text="Open the result."),
                step("tce_decide", topic="report", decision="approve"),
                step("tce_undo"),
                step("tce_undo"),
                step("tce_undo", change_id=DECISION_ID[:8]),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/voice/change": change_ok(["The takeaway now says ..."]),
                DECIDE: approved("undecided"),
                UNDO_DECISION: {
                    "ok": False,
                    "status": 409,
                    "data": {
                        "detail": {
                            "code": "changed",
                            "message": "It was decided again since. Nothing was changed.",
                        }
                    },
                },
                "POST /editorial/change-sets/": {
                    "ok": True,
                    "status": 200,
                    "data": {"said": 'Undone: "Takeaway".'},
                },
            },
        }
    )
    assert "Nothing was changed." in out["texts"][2]
    assert "next undo" in out["texts"][2]
    # The second plain undo goes to the edit before it, not the refused one again.
    assert out["texts"][3] == 'Undone: "Takeaway".'
    assert out["sent"][-2]["key"] == f"POST /editorial/change-sets/{CS}/undo"
    # The refused one is still reachable by its id.
    assert out["sent"][-1]["key"] == UNDO_DECISION


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
                step("tce_write_script", topic="report", replace=True),
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
            "steps": [step("tce_write_script", topic="report", replace=True), step("tce_jobs")],
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


# ------------------------------------------------------------------ what the model hears


def test_every_reply_the_model_sees_carries_the_spoken_words():
    """Claude Code gives the model structuredContent alone, so `said` must be in it."""
    out = run(
        {
            "steps": [
                step("tce_decide", topic="report", decision="sideways"),
                step("tce_reorder_week", topic="report", move="sideways"),
                step("tce_put_away", topic="report"),
                step("tce_more_hooks", topic="report"),
                step("tce_research", topic="report"),
                step("tce_jobs"),
            ],
            "responses": {
                "GET /editorial/voice/topic": [
                    {
                        "ok": True,
                        "status": 200,
                        "data": {"status": "found", "topic": {**TOPIC, "put_away": True}},
                    },
                    {
                        "ok": True,
                        "status": 200,
                        "data": {"status": "found", "topic": {**TOPIC, "script": None}},
                    },
                    FOUND,
                ],
                "POST /editorial/candidates/": {
                    "ok": True,
                    "status": 202,
                    "data": {"research_id": "r1", "state": "running", "already_running": False},
                },
                "GET /editorial/research/": {
                    "ok": True,
                    "status": 200,
                    "data": {"state": "done", "summary": "No web search: no search key is set."},
                },
            },
        }
    )
    seen = [json.loads(s) for s in out["seen"]]
    assert all(s["said"] == t for s, t in zip(seen, out["texts"], strict=True))
    assert '"sideways" is not a decision' in seen[0]["said"]
    assert '"sideways" is not a move' in seen[1]["said"]
    assert "already put away" in seen[2]["said"]
    assert "has no script yet" in seen[3]["said"]
    assert "No web search: no search key is set." in seen[5]["said"]


def test_a_failed_request_tells_the_model_nothing_was_changed():
    out = run(
        {
            "steps": [step("tce_week")],
            "responses": {
                "GET /editorial/today": {
                    "ok": False,
                    "status": 0,
                    "data": {
                        "error": "could not reach TCE",
                        "hint": (
                            "The request never got there: refused. "
                            "Nothing was read and nothing was changed."
                        ),
                    },
                }
            },
        }
    )
    seen = json.loads(out["seen"][0])
    assert "could not reach TCE" in seen["said"] and "nothing was changed" in seen["said"]
    assert seen["data"] == {"ok": False, "status": 0}


# ------------------------------------------------------------------ a restart mid-call


def test_undo_after_a_restart_names_the_last_voice_change_and_asks_first():
    """A fresh process with no record must not say nothing changed, nor undo blindly."""
    out = run(
        {
            "steps": [step("tce_undo")],
            "responses": {
                "GET /editorial/voice/activity": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "items": [
                            {
                                "kind": "change",
                                "id": "bbbbbbbb-0000-0000-0000-000000000000",
                                "short_id": "bbbbbbbb",
                                "title": "Old undo",
                                "lines": ["An undo."],
                                "is_undo": True,
                                "undone": False,
                                "can_undo": True,
                            },
                            {
                                "kind": "change",
                                "id": CS,
                                "short_id": CS[:8],
                                "title": "Nobody opens the report",
                                "lines": ['The takeaway now says "Open the result."'],
                                "is_undo": False,
                                "undone": False,
                                "can_undo": True,
                            },
                        ]
                    },
                }
            },
        }
    )
    text = out["texts"][0]
    assert "Nothing has been changed" not in text
    assert 'The takeaway now says "Open the result."' in text
    assert "Nobody opens the report" in text
    assert "aaaaaaaa" in text and "Is that the one" in text
    assert [s["key"] for s in out["sent"]] == ["GET /editorial/voice/activity?hours=1"]
    assert json.loads(out["seen"][0])["data"]["change_id"] == CS


def test_the_call_ledger_survives_a_new_process(tmp_path):
    env = {"TCE_VOICE_CALL_ID": "call/one", "TCE_VOICE_STATE_DIR": str(tmp_path)}
    responses = {
        "GET /editorial/voice/topic": FOUND,
        "POST /editorial/voice/change": change_ok(["The takeaway now says ..."]),
        "POST /editorial/candidates/": {"ok": True, "status": 200, "data": {"status": "running"}},
        "GET /editorial/candidates/": {
            "ok": True,
            "status": 200,
            "data": {"job": {"state": "done"}},
        },
        "POST /editorial/change-sets/": {"ok": True, "status": 200, "data": {"said": "Undone."}},
    }
    first = run(
        {
            "steps": [
                step("tce_edit", topic="report", part="takeaway", text="Open the result."),
                step("tce_write_script", topic="report", replace=True),
            ],
            "responses": responses,
        },
        env=env,
    )
    assert first["texts"][0].startswith("Done.")
    second = run(
        {"steps": [step("tce_jobs", new_only=True), step("tce_undo")], "responses": responses},
        env=env,
    )
    assert second["texts"][0] == 'The script for "Nobody opens the report" is ready.'
    assert second["texts"][1] == "Undone."
    assert second["sent"][-1]["key"] == f"POST /editorial/change-sets/{CS}/undo"
    # Another call's id starts with an empty ledger of its own.
    other = run(
        {"steps": [step("tce_jobs")], "responses": responses},
        env={**env, "TCE_VOICE_CALL_ID": "call-two"},
    )
    assert other["texts"][0] == "Nothing was started in this call."


# ------------------------------------------------------------------ the last place


WEEK4 = {
    "ok": True,
    "status": 200,
    "data": {
        "week": {
            "primary": [
                {"candidate_id": "a0000000-0000-0000-0000-000000000000", "title": "A", "rank": 1},
                {"candidate_id": CID, "title": "Nobody opens the report", "rank": 2},
                {"candidate_id": "c0000000-0000-0000-0000-000000000000", "title": "C", "rank": 3},
                {"candidate_id": "d0000000-0000-0000-0000-000000000000", "title": "D", "rank": 4},
            ],
            "reserve": [],
        }
    },
}


def test_move_to_last_names_the_real_last_place_not_99():
    out = run(
        {
            "steps": [
                step("tce_reorder_week", topic="report", move="last"),
                step("tce_reorder_week", topic="report", move="7"),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "GET /editorial/today": WEEK4,
                "POST /editorial/voice/change": change_ok(
                    ["Nobody opens the report moved to place 4 in the week."]
                ),
            },
        }
    )
    moves = [s["body"]["operations"][0]["after"] for s in out["sent"] if s["body"]]
    assert moves == [
        {"action": "rank", "rank": 4, "candidate_id": CID},
        {"action": "rank", "rank": 4, "candidate_id": CID},
    ]
    assert "99" not in out["texts"][0]
    assert "last place in the week (place 4)" in out["texts"][0]
    assert "place 4" in out["texts"][1] and "7" not in out["texts"][1]


# ------------------------------------------------------------------ stuck jobs


def test_an_interrupted_script_says_ask_again_not_still_going():
    out = run(
        {
            "steps": [
                step("tce_write_script", topic="report", replace=True),
                step("tce_jobs", new_only=True),
                step("tce_jobs"),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/candidates/": {"ok": True, "status": 200, "data": {}},
                "GET /editorial/candidates/": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "job": {
                            "state": "interrupted",
                            "current_activity": (
                                "Packet written but never saved (the request ended first)."
                            ),
                        }
                    },
                },
            },
        }
    )
    assert "stopped before it was saved" in out["texts"][1]
    assert "still going" not in out["texts"][1]
    assert "stopped before it was saved" in out["texts"][2]


def test_more_openings_lost_to_a_restart_say_ask_again():
    out = run(
        {
            "steps": [step("tce_more_hooks", topic="report"), step("tce_jobs", new_only=True)],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/packets/": {"ok": True, "status": 202, "data": {}},
                "GET /editorial/packets/": {
                    "ok": True,
                    "status": 200,
                    "data": {"state": "idle", "current_activity": "Nothing asked for yet"},
                },
            },
        }
    )
    assert "stopped when the server restarted" in out["texts"][1]
    assert "still being written" not in out["texts"][1]


# ------------------------------------------------------------------ a rewrite replaces


def test_write_script_tells_the_brain_a_rewrite_replaces_the_current_script():
    out = run({"steps": [], "responses": {}})
    desc = out["descs"]["tce_write_script"]
    assert "replaces the current script" in desc
    assert "replace" in out["descs"]["tce_write_script"] and "yes" in desc


PACKET = f"POST /editorial/candidates/{CID}/packet"
RESTORE = f"POST /editorial/candidates/{CID}/script/restore"
UNDO_REWRITE = f"POST /editorial/candidates/{CID}/script/undo-rewrite"
RW = "eeeeeeee-1111-2222-3333-444444444444"
REWRITE_STARTED = {
    "ok": True,
    "status": 200,
    "data": {"status": "running", "replaces_version": 3, "rewrite_id": RW},
}


def test_a_script_over_an_existing_one_is_read_back_and_nothing_starts():
    out = run(
        {
            "steps": [step("tce_write_script", topic="report")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                PACKET: {"ok": True, "status": 200, "data": {"status": "running"}},
            },
        }
    )
    text = out["texts"][0]
    assert '"Nobody opens the report" already has a script (version 3, ready)' in text
    assert "replace" in text
    assert not [s for s in out["sent"] if s["key"] == PACKET], "nothing may start before a yes"
    assert json.loads(out["seen"][0])["data"]["code"] == "has_script"


def test_a_script_the_server_says_exists_is_read_back_too():
    # He read the topic before the first script was saved: the tool thinks there is
    # none, the server knows better and refuses.
    fresh = json.loads(json.dumps(FOUND))
    fresh["data"]["topic"]["script"] = None
    out = run(
        {
            "steps": [step("tce_write_script", topic="report")],
            "responses": {
                "GET /editorial/voice/topic": fresh,
                PACKET: {
                    "ok": False,
                    "status": 409,
                    "data": {
                        "detail": {
                            "code": "has_script",
                            "message": "It already has a script.",
                            "version": 1,
                            "status": "ready",
                        }
                    },
                },
            },
        }
    )
    sent = [s for s in out["sent"] if s["key"] == PACKET]
    assert sent[0]["body"] == {"replace": False, "by": "voice"}
    assert "already has a script (version 1, ready)" in out["texts"][0]
    assert "replace" in out["texts"][0]
    assert "Started" not in out["texts"][0]


def test_a_rewrite_he_agreed_to_names_what_it_replaces_and_undo_puts_it_back():
    out = run(
        {
            "steps": [
                step("tce_write_script", topic="report", replace=True),
                step("tce_undo"),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                PACKET: REWRITE_STARTED,
                UNDO_REWRITE: {
                    "ok": True,
                    "status": 200,
                    "data": {"said": 'The script of "Nobody opens the report" is back.'},
                },
            },
        }
    )
    started = [s for s in out["sent"] if s["key"] == PACKET]
    assert started[0]["body"] == {"replace": True, "by": "voice"}
    assert "replaces version 3" in out["texts"][0] and f"change {RW[:8]}" in out["texts"][0]
    undone = [s for s in out["sent"] if s["key"] == UNDO_REWRITE]
    assert undone and undone[0]["body"] == {"rewrite_id": RW, "by": "voice"}
    assert out["texts"][1] == 'The script of "Nobody opens the report" is back.'


def test_a_rewrite_is_undone_by_its_id_and_the_next_undo_goes_further_back():
    out = run(
        {
            "steps": [
                step("tce_edit", topic="report", part="takeaway", text="Open the result."),
                step("tce_write_script", topic="report", replace=True),
                step("tce_undo", change_id=RW[:8]),
                step("tce_undo"),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/voice/change": change_ok(["The takeaway now says ..."]),
                PACKET: REWRITE_STARTED,
                UNDO_REWRITE: {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "said": "The earlier script is back.",
                        "change_set_id": "ffffffff-0000-0000-0000-000000000000",
                    },
                },
                "POST /editorial/change-sets/": {
                    "ok": True,
                    "status": 200,
                    "data": {"said": 'Undone: "Takeaway".'},
                },
            },
        }
    )
    assert out["texts"][2] == "The earlier script is back."
    assert [s["key"] for s in out["sent"] if s["key"] == UNDO_REWRITE] == [UNDO_REWRITE]
    # The second undo steps back to the edit; it does not take back the undo and
    # bring the new script back.
    assert out["sent"][-1]["key"] == f"POST /editorial/change-sets/{CS}/undo"
    assert out["texts"][3] == 'Undone: "Takeaway".'


def test_undoing_a_rewrite_that_is_still_being_written_says_so_and_stays_next():
    out = run(
        {
            "steps": [
                step("tce_write_script", topic="report", replace=True),
                step("tce_undo"),
                step("tce_undo"),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                PACKET: REWRITE_STARTED,
                UNDO_REWRITE: {
                    "ok": False,
                    "status": 409,
                    "data": {
                        "detail": {
                            "code": "still_writing",
                            "message": "The new script is still being written.",
                        }
                    },
                },
            },
        }
    )
    assert "still being written" in out["texts"][1]
    assert json.loads(out["seen"][1])["data"]["ok"] is False
    # "Not yet" is not "never": the rewrite is still the next thing undo takes.
    assert [s["key"] for s in out["sent"] if s["key"] == UNDO_REWRITE] == [UNDO_REWRITE] * 2


def test_a_failed_request_that_is_not_json_says_what_came_back():
    out = run(
        {
            "steps": [step("tce_week")],
            "responses": {
                "GET /editorial/today": {
                    "ok": False,
                    "status": 502,
                    "data": {
                        "error": "TCE did not answer with JSON",
                        "body": "<html><head><title>502 Bad Gateway</title></head>"
                        "<body><h1>502 Bad Gateway</h1><p>nginx</p></body></html>",
                    },
                }
            },
        }
    )
    text = out["texts"][0]
    assert "did not answer with JSON" in text
    assert "502 Bad Gateway" in text and "<" not in text
