"""The voice agent's tools, driven with a fake engine through Node.

Each scenario runs a SEQUENCE of tool calls in one Node process, because "undo
the last thing I changed" and "is the script ready yet" only mean something
across calls. The fake records every request, so the tests can check what the
tools sent (attribution included), not only what they said.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "mcp-server"

HARNESS = r"""
import { register as registerVoice, parsePart } from './tools/voice.mjs';
import { register as registerVideo } from './tools/video.mjs';
import { reply, failure, shortId, authHeaders, identityFromEnv, familyFilter } from './tools.mjs';

// Both files are the "voice" family: the call seat loads them together.
const register = (server, call, helpers) => {
  registerVoice(server, call, helpers);
  registerVideo(server, call, helpers);
};

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
SID = CID[:8]
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
            "tce_new_idea",
            "tce_find_ideas",
            "tce_recordings",
            "tce_video_posts",
            "tce_publish",
            "tce_video_moment",
            "tce_video_note",
            "tce_video_notes",
            "tce_video_make",
            "tce_video_undo_version",
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


def test_the_week_says_a_filmed_topic_is_filmed_not_script_ready():
    """28-Sep review: Today tags a topic he filmed "Filmed" and leaves it out of
    "scripts ready", but the call read it as "script ready" and dropped `filmed`
    from what the model sees, so the call counted one more script to film than
    the screen in his hand."""
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
                                    "title": "Filmed on Sunday",
                                    "script_state": "ready",
                                    "filmed": True,
                                    "rank": 1,
                                },
                                {
                                    "candidate_id": "22222222-0000-0000-0000-000000000000",
                                    "title": "Next to film",
                                    "script_state": "ready",
                                    "filmed": False,
                                    "rank": 2,
                                },
                            ],
                            "reserve": [
                                {
                                    "candidate_id": "33333333-0000-0000-0000-000000000000",
                                    "title": "Spare, filmed too",
                                    "script_state": "none",
                                    "filmed": True,
                                },
                            ],
                        },
                        "attention": {"waiting": 0, "pending_reviews": 0, "scripts_ready": 1},
                        "next_action": {
                            "label": "Start recording",
                            "detail": "Next to film is first.",
                        },
                    },
                },
                "GET /editorial/topics": {"ok": True, "status": 200, "data": {"topics": []}},
            },
        }
    )
    text = out["texts"][0]
    assert "1. Filmed on Sunday - filmed already (id 11111111)" in text
    assert "2. Next to film - script ready (id 22222222)" in text
    assert text.count("script ready") == 1, "the same count as Today's scripts ready"
    assert "- Spare, filmed too - filmed already (id 33333333)" in text
    data = json.loads(out["seen"][0])["data"]
    assert [row["filmed"] for row in data["week"]] == [True, False]
    assert [row["filmed"] for row in data["reserve"]] == [True]


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


def test_a_close_but_unsure_match_is_read_back_as_a_question_with_its_id():
    out = run(
        {
            "steps": [step("tce_topic", topic="pricing fennel")],
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
            },
        }
    )
    text = out["texts"][0]
    assert "More than one" not in text
    assert '"How I set my pricing" (id cccc3333)' in text and "Ask him if that is the one" in text


WRITES = {
    "tce_edit": {"part": "takeaway", "text": "Charge more."},
    "tce_decide": {"decision": "approve"},
    "tce_put_away": {},
    "tce_restore_idea": {},
    "tce_choose_hook": {"option": "2", "expect": "Nobody checks."},
    "tce_reorder_week": {"move": "first"},
    "tce_write_script": {"replace": True},
    "tce_more_hooks": {},
    "tce_research": {},
}

# What the verifier heard steer a write to the wrong title, and a few more.
NOT_AN_ID = ["the first one", "זה שדיברנו עליו", "הראשון", "the one about the book", "report"]


@pytest.mark.parametrize("tool", sorted(WRITES))
def test_every_write_tool_takes_an_id_and_never_words(tool):
    out = run(
        {
            "steps": [step(tool, topic=words, **WRITES[tool]) for words in NOT_AN_ID],
            "responses": {"GET /editorial/voice/topic": FOUND},
        }
    )
    assert out["sent"] == [], "words never reach a lookup, let alone a write"
    for text in out["texts"]:
        assert "tce_topic" in text and "read its title back to him" in text, text
        assert "Nothing was changed" in text
    desc = out["descs"][tool]
    assert "Find the topic with tce_topic, read its title back to him, then pass its id." in desc


def test_a_write_looks_its_topic_up_by_id_alone():
    out = run(
        {
            "steps": [
                step("tce_topic", topic="report"),
                step("tce_decide", topic=SID, decision="later"),
                step("tce_put_away", topic=f"id {SID}"),
                step("tce_write_script", topic=CID),
                step("tce_research", topic=f"({SID})"),
            ],
            "responses": {"GET /editorial/voice/topic": FOUND},
        }
    )
    finds = [s["key"] for s in out["sent"] if s["key"].startswith("GET /editorial/voice/topic")]
    assert finds[0] == "GET /editorial/voice/topic?q=report"
    assert finds[1:] == [
        f"GET /editorial/voice/topic?id={SID}",
        f"GET /editorial/voice/topic?id={SID}",
        f"GET /editorial/voice/topic?id={CID}",
        f"GET /editorial/voice/topic?id={SID}",
    ]


def test_an_id_that_names_no_topic_says_so_and_writes_nothing():
    out = run(
        {
            "steps": [step("tce_decide", topic="deadbeef", decision="approve")],
            "responses": {
                "GET /editorial/voice/topic": {
                    "ok": False,
                    "status": 404,
                    "data": {
                        "detail": {
                            "code": "unknown_topic",
                            "message": 'No topic has the id "deadbeef". Nothing was changed.',
                        }
                    },
                }
            },
        }
    )
    assert 'No topic has the id "deadbeef"' in out["texts"][0]
    assert "tce_topic" in out["texts"][0]
    assert [s["key"] for s in out["sent"]] == ["GET /editorial/voice/topic?id=deadbeef"]


def test_every_write_reply_names_the_topic_it_changed():
    out = run(
        {
            "steps": [
                step("tce_edit", topic=SID, part="point 3", text="Sharper.", expect="Three."),
                step("tce_choose_hook", topic=SID, option="2", expect="Nobody checks."),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/voice/change": change_ok(
                    ['Point 3 now says "Sharper." (it said "Three.").'],
                    changes=[{"field": "script_phrases.0", "after": "Nobody checks."}],
                ),
            },
        }
    )
    for text in out["texts"]:
        assert '"Nobody opens the report"' in text, text


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
                step("tce_edit", topic=SID, part="point 3", text="Sharper.", expect="Three.")
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
    assert text.startswith('Done on "Nobody opens the report": Point 3 now says "Sharper."')
    assert "change aaaaaaaa" in text
    body = out["sent"][1]["body"]
    assert body["target"] == "script" and body["by"] == "voice"
    assert body["operations"] == [
        {"op": "set_field", "field": "bullets.2", "after": "Sharper.", "expect": "Three."}
    ]


def test_an_edit_that_lost_a_race_reads_back_the_new_text():
    out = run(
        {
            "steps": [step("tce_edit", topic=SID, part="the opening", text="New.", expect="Old.")],
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
    out = run({"steps": [step("tce_edit", topic=SID, part="the moon", text="x")], "responses": {}})
    assert "I do not know which part" in out["texts"][0]
    assert out["sent"] == []


def test_decide_approve_means_this_week_and_is_attributed():
    out = run(
        {
            "steps": [step("tce_decide", topic=SID, decision="approve")],
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


def test_put_away_then_undo_brings_it_back_by_its_change_id():
    away = "cccccccc-0000-0000-0000-000000000000"
    out = run(
        {
            "steps": [step("tce_put_away", topic=SID), step("tce_undo")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/topics/" + CID + "/decide": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "decision": "away",
                        "previous_decision": "this_week",
                        "changed": True,
                        "change_id": away,
                    },
                },
                "POST /editorial/topics/" + CID + "/undo-decision": {
                    "ok": True,
                    "status": 200,
                    "data": {"said": '"Nobody opens the report" is back in this week\'s list.'},
                },
            },
        }
    )
    assert out["texts"][0].startswith(
        'Put away: "Nobody opens the report". It can be brought back.'
    )
    assert out["texts"][1] == 'Undone. "Nobody opens the report" is back in this week\'s list.'
    assert out["sent"][-1]["key"] == f"POST /editorial/topics/{CID}/undo-decision"
    assert out["sent"][-1]["body"] == {"change_id": away, "by": "voice"}


def test_an_idea_the_engine_withdrew_that_is_still_chosen_and_listed_is_not_already_away():
    """RP11: withdrawn, but still chosen for this week and on its list. The read says it is
    in this week, and a put-away is sent, not answered "already put away"."""
    withdrawn_listed = {
        **TOPIC,
        "status": "withdrawn",
        "put_away": True,
        "in_this_week": True,
        "decision": "this_week",
    }
    away = "cccccccc-0000-0000-0000-000000000000"
    out = run(
        {
            "steps": [step("tce_topic", topic=SID), step("tce_put_away", topic=SID)],
            "responses": {
                "GET /editorial/voice/topic": {
                    "ok": True,
                    "status": 200,
                    "data": {"status": "found", "topic": withdrawn_listed},
                },
                "POST /editorial/topics/" + CID + "/decide": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "decision": "away",
                        "previous_decision": "this_week",
                        "changed": True,
                        "change_id": away,
                        "removed_from_week": {"slot": "primary", "rank": 2},
                    },
                },
            },
        }
    )
    assert "In this week." in out["texts"][0]
    assert "Put away." not in out["texts"][0]
    assert "already" not in out["texts"][1]
    assert out["texts"][1].startswith('Put away: "Nobody opens the report".')
    assert f"(change {away[:8]})" in out["texts"][1]
    assert out["sent"][-1]["key"] == f"POST /editorial/topics/{CID}/decide"
    assert out["sent"][-1]["body"] == {"decision": "away", "by": "voice"}


def test_restore_idea_says_where_it_went():
    out = run(
        {
            "steps": [step("tce_restore_idea", topic=SID)],
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
            "steps": [step("tce_choose_hook", topic=SID, option="2", expect="Nobody checks.")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/voice/change": change_ok(
                    ["A different opening was chosen."],
                    changes=[{"field": "script_phrases.0", "after": "Nobody checks."}],
                ),
            },
        }
    )
    assert out["texts"][0].startswith(
        'Done. The opening of "Nobody opens the report" is now option 2: "Nobody checks."'
    )
    body = out["sent"][1]["body"]
    assert body["target"] == "script" and body["operations"] == [
        {"op": "choose_hook", "after": "2", "expect": "Nobody checks."}
    ]
    assert "expect" in out["descs"]["tce_choose_hook"]


def test_an_opening_he_did_not_hear_reads_the_options_as_they_are_now():
    out = run(
        {
            "steps": [step("tce_choose_hook", topic=SID, option="2", expect="Old two.")],
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
            "steps": [step("tce_reorder_week", topic=SID, move="First")],
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
    out = run({"steps": [step("tce_reorder_week", topic=SID, move="sideways")], "responses": {}})
    assert '"sideways" is not a move' in out["texts"][0] and out["sent"] == []


# ------------------------------------------------------------------ undo


def test_undo_with_no_id_takes_back_the_last_change_of_this_call():
    out = run(
        {
            "steps": [
                step("tce_edit", topic=SID, part="takeaway", text="Open the result."),
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
CHANGE = "dddddddd-0000-0000-0000-000000000000"
LATER = "12121212-1111-0000-0000-000000000000"


def decided(decision, previous, change_id=CHANGE, *, added=False, removed=None, changed=True):
    return {
        "ok": True,
        "status": 200,
        "data": {
            "decision": decision,
            "previous_decision": previous,
            "changed": changed,
            "added_to_week": added,
            "removed_from_week": removed,
            "change_id": change_id,
            "placed": {"slot": "primary", "rank": 1} if decision == "this_week" else None,
        },
    }


def approved(previous, added=True, change_id=CHANGE):
    return decided("this_week", previous, change_id, added=added)


UNDONE = {"ok": True, "status": 200, "data": {"said": '"Nobody opens the report" is back.'}}


def test_undoing_a_decision_sends_its_own_change_id():
    out = run(
        {
            "steps": [step("tce_decide", topic=SID, decision="approve"), step("tce_undo")],
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
    assert f"change {CHANGE[:8]}" in out["texts"][0]
    sent = [s for s in out["sent"] if s["key"] == UNDO_DECISION]
    # The server holds what the decision did (the week included); the call sends
    # only which write it means.
    assert sent and sent[0]["body"] == {"change_id": CHANGE, "by": "voice"}
    assert not [s for s in out["sent"][2:] if s["key"] == DECIDE], "one route does both"
    assert "off this week's list" in out["texts"][1]


def test_approving_twice_then_undo_takes_back_the_approval_that_did_it():
    out = run(
        {
            "steps": [
                step("tce_decide", topic=SID, decision="approve"),
                step("tce_decide", topic=SID, decision="this_week"),
                step("tce_undo"),
                step("tce_undo"),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                DECIDE: [
                    approved("undecided"),
                    decided("this_week", "this_week", None, changed=False),
                ],
                UNDO_DECISION: UNDONE,
            },
        }
    )
    assert "already" in out["texts"][1] and "nothing" in out["texts"][1].lower()
    assert "change" not in out["texts"][1].replace("changed", "")
    undos = [s for s in out["sent"] if s["key"] == UNDO_DECISION]
    assert [u["body"]["change_id"] for u in undos] == [CHANGE], "the no-op left nothing to undo"
    assert out["texts"][3].startswith("Nothing has been changed in this call")


def test_undo_by_id_reaches_that_decision_and_not_a_later_one_on_the_same_topic():
    out = run(
        {
            "steps": [
                step("tce_decide", topic=SID, decision="approve"),
                step("tce_decide", topic=SID, decision="later"),
                step("tce_undo", change_id=CHANGE[:8]),
            ],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                DECIDE: [approved("undecided"), decided("later", "this_week", LATER)],
                UNDO_DECISION: UNDONE,
            },
        }
    )
    undos = [s for s in out["sent"] if s["key"] == UNDO_DECISION]
    assert [u["body"]["change_id"] for u in undos] == [CHANGE]


def test_undo_by_the_id_of_a_decision_from_an_earlier_call_finds_it_in_the_log():
    out = run(
        {
            "steps": [step("tce_undo", change_id=CHANGE[:8])],
            "responses": {
                "GET /editorial/voice/activity": {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "items": [
                            {
                                "kind": "decision",
                                "id": CHANGE,
                                "candidate_id": CID,
                                "title": "Nobody opens the report",
                                "decision": "this_week",
                            }
                        ]
                    },
                },
                UNDO_DECISION: UNDONE,
            },
        }
    )
    assert out["sent"][-1] == {"key": UNDO_DECISION, "body": {"change_id": CHANGE, "by": "voice"}}
    assert out["texts"][0] == 'Undone. "Nobody opens the report" is back.'


def test_a_refused_undo_lets_the_next_undo_move_on():
    out = run(
        {
            "steps": [
                step("tce_edit", topic=SID, part="takeaway", text="Open the result."),
                step("tce_decide", topic=SID, decision="approve"),
                step("tce_undo"),
                step("tce_undo"),
                step("tce_undo", change_id=CHANGE[:8]),
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
                step("tce_write_script", topic=SID, replace=True),
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
            "steps": [step("tce_write_script", topic=SID, replace=True), step("tce_jobs")],
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
            "steps": [step("tce_more_hooks", topic=SID), step("tce_jobs")],
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
            "steps": [step("tce_research", topic=SID), step("tce_jobs")],
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
                step("tce_decide", topic=SID, decision="sideways"),
                step("tce_reorder_week", topic=SID, move="sideways"),
                step("tce_put_away", topic=SID),
                step("tce_more_hooks", topic=SID),
                step("tce_research", topic=SID),
                step("tce_jobs"),
            ],
            "responses": {
                "GET /editorial/voice/topic": [
                    {
                        "ok": True,
                        "status": 200,
                        # A put-away idea: away, and off this week's list.
                        "data": {
                            "status": "found",
                            "topic": {
                                **TOPIC,
                                "put_away": True,
                                "in_this_week": False,
                                "decision": "away",
                            },
                        },
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
                step("tce_edit", topic=SID, part="takeaway", text="Open the result."),
                step("tce_write_script", topic=SID, replace=True),
            ],
            "responses": responses,
        },
        env=env,
    )
    assert first["texts"][0].startswith('Done on "Nobody opens the report"')
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
                step("tce_reorder_week", topic=SID, move="last"),
                step("tce_reorder_week", topic=SID, move="7"),
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
                step("tce_write_script", topic=SID, replace=True),
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
            "steps": [step("tce_more_hooks", topic=SID), step("tce_jobs", new_only=True)],
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
            "steps": [step("tce_write_script", topic=SID)],
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
            "steps": [step("tce_write_script", topic=SID)],
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
                step("tce_write_script", topic=SID, replace=True),
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
    # With the version the call was told it replaces, so the server can say
    # whether that is still what a missing record means.
    assert undone and undone[0]["body"] == {"rewrite_id": RW, "replaced_version": 3, "by": "voice"}
    assert out["texts"][1] == 'The script of "Nobody opens the report" is back.'


def test_a_rewrite_is_undone_by_its_id_and_the_next_undo_goes_further_back():
    out = run(
        {
            "steps": [
                step("tce_edit", topic=SID, part="takeaway", text="Open the result."),
                step("tce_write_script", topic=SID, replace=True),
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
                step("tce_write_script", topic=SID, replace=True),
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


def test_a_rewrite_the_script_moved_on_from_offers_the_version_and_puts_it_back():
    out = run(
        {
            "steps": [
                step("tce_write_script", topic=SID, replace=True),
                step("tce_undo"),
                step("tce_undo", change_id=RW[:8], restore_version=4),
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
                            "code": "replaced_since",
                            "message": (
                                'The script of "Nobody opens the report" is now version 5. '
                                "Nothing was undone."
                            ),
                            "current_version": 5,
                            "previous_version": 4,
                            "asked_version": 3,
                        }
                    },
                },
                RESTORE: {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "restored": True,
                        "change_set_id": CS,
                        "short_id": CS[:8],
                        "said": 'Script version 4 of "Nobody opens the report" is back.',
                    },
                },
                "POST /editorial/change-sets/": {
                    "ok": True,
                    "status": 200,
                    "data": {"said": "Undone: the put-back."},
                },
            },
        }
    )
    assert "now version 5" in out["texts"][1]
    assert "restore_version 4" in out["texts"][1] and RW[:8] in out["texts"][1]
    restores = [s for s in out["sent"] if s["key"] == RESTORE]
    assert restores and restores[0]["body"] == {"version": 4, "by": "voice"}
    assert out["texts"][2] == 'Script version 4 of "Nobody opens the report" is back.'
    # Putting it back is a change of this call like any other: undo takes it back.
    assert out["sent"][-1]["key"] == f"POST /editorial/change-sets/{CS}/undo"


def test_more_openings_while_a_script_is_written_are_refused_in_words():
    out = run(
        {
            "steps": [step("tce_more_hooks", topic=SID), step("tce_jobs")],
            "responses": {
                "GET /editorial/voice/topic": FOUND,
                "POST /editorial/packets/": {
                    "ok": False,
                    "status": 409,
                    "data": {
                        "detail": {
                            "code": "still_writing",
                            "message": (
                                'A new script for "Nobody opens the report" is being written. '
                                "Nothing was asked for."
                            ),
                        }
                    },
                },
            },
        }
    )
    assert "is being written" in out["texts"][0] and "Nothing was asked for" in out["texts"][0]
    assert out["texts"][1] == "Nothing was started in this call.", "a refusal is not a job"


# ------------------------------------------------------------------ the real API behind it

BRIDGE = r"""
import { createInterface } from 'node:readline';
import { register as registerVoice } from './tools/voice.mjs';
import { register as registerVideo } from './tools/video.mjs';
import { reply, failure, shortId } from './tools.mjs';

const register = (server, call, helpers) => {
  registerVoice(server, call, helpers);
  registerVideo(server, call, helpers);
};

const rl = createInterface({ input: process.stdin });
const lines = [];
let waiter = null;
rl.on('line', (l) => {
  if (waiter) { const w = waiter; waiter = null; w(l); } else lines.push(l);
});
const next = () => (lines.length
  ? Promise.resolve(lines.shift())
  : new Promise((r) => { waiter = r; }));
const send = (o) => process.stdout.write(`${JSON.stringify(o)}\n`);
const tools = {};
register(
  { tool: (name, d, s, fn) => { tools[name] = fn; } },
  async (method, path, body) => {
    send({ type: 'req', method, path, body: body ?? null });
    return JSON.parse(await next());
  },
  { reply, failure, shortId },
);
send({ type: 'ready' });
for (;;) {
  const cmd = JSON.parse(await next());
  if (cmd.type === 'quit') break;
  const out = await tools[cmd.tool](cmd.args || {});
  send({ type: 'result', text: out.content[0].text, data: out.structuredContent ?? null });
}
process.exit(0);
"""


class Live:
    """The real voice tools in Node, every request answered by the real API."""

    def __init__(self, http, proc):
        self.http = http
        self.proc = proc

    async def tool(self, name, **args):
        self.proc.stdin.write(
            (json.dumps({"type": "step", "tool": name, "args": args}) + "\n").encode()
        )
        await self.proc.stdin.drain()
        while True:
            line = await asyncio.wait_for(self.proc.stdout.readline(), 60)
            if not line:
                raise RuntimeError((await self.proc.stderr.read()).decode(errors="replace"))
            msg = json.loads(line)
            if msg["type"] == "result":
                return msg["text"], (msg["data"] or {}).get("data") or {}
            r = await self.http.request(msg["method"], "/api/v1" + msg["path"], json=msg["body"])
            try:
                data = r.json() if r.content else {}
            except ValueError:
                data = {"error": "not json", "body": r.text[:400]}
            answer = {"ok": r.is_success, "status": r.status_code, "data": data}
            self.proc.stdin.write((json.dumps(answer) + "\n").encode())
            await self.proc.stdin.drain()


@pytest.fixture
async def live(editorial_sessionmaker, monkeypatch):
    if shutil.which("node") is None:  # pragma: no cover
        pytest.skip("node is not installed")
    import httpx
    from fastapi import FastAPI
    from pydantic import SecretStr

    from tce.api.routers import editorial as editorial_router
    from tce.api.routers import editorial_voice as voice_router
    from tce.api.routers import editorial_workspace as workspace_router
    from tce.editorial import voice_agent
    from tce.settings import settings

    key = "synthetic-test-key"
    ws = uuid.uuid4()
    monkeypatch.setattr(settings, "private_access_key", SecretStr(key))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(voice_agent, "make_searcher", lambda: None)
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(voice_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: (
        editorial_sessionmaker
    )
    script = ROOT / f"_voice_bridge_{uuid.uuid4().hex[:8]}.mjs"
    script.write_text(BRIDGE, encoding="utf-8")
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("TCE_VOICE_CALL_ID", "KMBOT_VOICE_SESSION", "TCE_VOICE_STATE_DIR")
    }
    proc = await asyncio.create_subprocess_exec(
        "node",
        str(script),
        cwd=str(ROOT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        limit=2**24,
    )
    try:
        ready = json.loads(await asyncio.wait_for(proc.stdout.readline(), 60))
        assert ready["type"] == "ready", ready
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {key}", "X-Workspace-Id": str(ws)},
        ) as http:
            world = Live(http, proc)
            world.ws = ws
            world.sm = editorial_sessionmaker
            yield world
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        script.unlink(missing_ok=True)


async def live_topic(world, title):
    from tests.unit.test_editorial_voice_agent import add_candidate

    return str(await add_candidate(world.sm, world.ws, title))


async def live_week(world):
    body = (await world.http.get("/api/v1/editorial/weeks/current/lineup")).json()
    return [row["candidate_id"] for row in body["primary"] + body["reserve"]]


async def live_decision(world, cid):
    from sqlalchemy import select

    from tce.models.editorial_workspace import TopicDecision

    async with world.sm() as s:
        row = (
            await s.execute(
                select(TopicDecision).where(TopicDecision.candidate_id == uuid.UUID(cid))
            )
        ).scalar_one_or_none()
    return row.decision if row is not None else None


async def test_live_approving_twice_then_one_undo_takes_it_out_of_the_week(live):
    cid = await live_topic(live, "Invoices nobody opens")
    await live.tool("tce_decide", topic=cid[:8], decision="approve")
    again, _ = await live.tool("tce_decide", topic=cid[:8], decision="approve")
    assert "already" in again
    undone, _ = await live.tool("tce_undo")
    assert cid not in await live_week(live), undone
    assert await live_decision(live, cid) is None
    assert "Invoices nobody opens" in undone


async def test_live_undo_by_the_approvals_id_reaches_the_approval(live):
    cid = await live_topic(live, "Invoices nobody opens")
    _, approve = await live.tool("tce_decide", topic=cid[:8], decision="approve")
    await live.tool("tce_decide", topic=cid[:8], decision="later")

    # The approval by its id while the later stands: refused, nothing goes INTO the week.
    early, _ = await live.tool("tce_undo", change_id=approve["change_id"][:8])
    assert "Nothing was changed" in early
    assert cid not in await live_week(live) and await live_decision(live, cid) == "later"

    await live.tool("tce_undo")  # the later: back in the week
    assert cid in await live_week(live) and await live_decision(live, cid) == "this_week"
    back, _ = await live.tool("tce_undo", change_id=approve["change_id"][:8])
    assert cid not in await live_week(live), back
    assert await live_decision(live, cid) is None


async def test_live_a_voice_approval_he_changed_himself_is_not_undone(live):
    cid = await live_topic(live, "Invoices nobody opens")
    await live.tool("tce_decide", topic=cid[:8], decision="approve")
    for decision in ("later", "this_week"):  # on his phone
        r = await live.http.post(
            f"/api/v1/editorial/topics/{cid}/decide", json={"decision": decision, "by": "ziv"}
        )
        assert r.status_code == 200, r.text
    said, _ = await live.tool("tce_undo")
    assert "himself" in said
    assert cid in await live_week(live) and await live_decision(live, cid) == "this_week"


async def test_live_undo_after_the_week_rolled_over_takes_it_off_the_week_it_was_added_to(
    live, monkeypatch
):
    from datetime import timedelta

    from tce.editorial import common as common_service
    from tce.editorial import lineup as lineup_service

    cid = await live_topic(live, "Invoices nobody opens")
    first = common_service.current_week_start()
    monkeypatch.setattr(lineup_service, "current_week_start", lambda today=None: first)
    await live.tool("tce_decide", topic=cid[:8], decision="approve")
    assert cid in await live_week(live)
    monkeypatch.setattr(
        lineup_service, "current_week_start", lambda today=None: first + timedelta(days=7)
    )
    said, _ = await live.tool("tce_undo")
    monkeypatch.setattr(lineup_service, "current_week_start", lambda today=None: first)
    assert cid not in await live_week(live), said
    assert "week of" in said


async def live_superseded(world, title):
    """An undecided idea the weekly selection run replaced: withdrawn, no 'away'."""
    from tests.unit.test_editorial_voice_agent import add_candidate

    return str(
        await add_candidate(
            world.sm,
            world.ws,
            title,
            status="withdrawn",
            editor_notes="superseded by selection run 1234",
        )
    )


async def live_status(world, cid):
    from tce.models.editorial import TopicCandidate

    async with world.sm() as s:
        return (await s.get(TopicCandidate, uuid.UUID(cid))).status


async def live_set_status(world, cid, status):
    """What the engine does on its own (a selection re-run, a stale news idea, Archive)."""
    from tce.models.editorial import TopicCandidate

    async with world.sm() as s:
        (await s.get(TopicCandidate, uuid.UUID(cid))).status = status
        await s.commit()


async def test_live_restoring_a_superseded_idea_is_undone_by_its_id(live):
    cid = await live_superseded(live, "Invoices nobody opens")
    said, data = await live.tool("tce_restore_idea", topic=cid[:8])
    assert data.get("change_id"), said
    assert f"(change {data['change_id'][:8]})" in said
    assert await live_status(live, cid) == "proposed"

    undone, _ = await live.tool("tce_undo", change_id=data["change_id"][:8])
    assert await live_status(live, cid) == "withdrawn", undone
    assert "Invoices nobody opens" in undone and "put away again" in undone


async def test_live_restoring_a_superseded_idea_then_plain_undo_withdraws_it(live):
    cid = await live_superseded(live, "Invoices nobody opens")
    await live.tool("tce_restore_idea", topic=cid[:8])
    assert await live_status(live, cid) == "proposed"

    undone, _ = await live.tool("tce_undo")
    assert "Nothing has been changed" not in undone
    assert await live_status(live, cid) == "withdrawn", undone
    assert "put away again" in undone


async def test_live_plain_undo_after_a_restore_takes_back_the_restore_not_an_earlier_approval(
    live,
):
    approved = await live_topic(live, "Receptionist at night")
    await live.tool("tce_decide", topic=approved[:8], decision="approve")
    assert approved in await live_week(live)
    cid = await live_superseded(live, "Invoices nobody opens")
    await live.tool("tce_restore_idea", topic=cid[:8])

    undone, _ = await live.tool("tce_undo")
    assert await live_status(live, cid) == "withdrawn", undone
    assert "Invoices nobody opens" in undone
    assert approved in await live_week(live), "the approval stands"
    assert await live_decision(live, approved) == "this_week"


async def test_live_later_approve_undo_undo_keeps_the_place_in_the_week(live):
    ids = [
        await live_topic(live, title)
        for title in ("Receptionist at night", "Invoices nobody opens", "Funnel leaks")
    ]
    for cid in ids:
        await live.tool("tce_decide", topic=cid[:8], decision="approve")
    assert await live_week(live) == ids
    await live.tool("tce_decide", topic=ids[1][:8], decision="later")
    await live.tool("tce_decide", topic=ids[1][:8], decision="approve")
    await live.tool("tce_undo")
    assert await live_week(live) == [ids[0], ids[2]]
    said, _ = await live.tool("tce_undo")
    assert await live_week(live) == ids, said
    assert "place 2" in said


async def live_stale_later(world, title):
    """Saved for later on his phone, then withdrawn by a re-run of the week's selection."""
    from tce.models.editorial import TopicCandidate

    cid = await live_topic(world, title)
    r = await world.http.post(
        f"/api/v1/editorial/topics/{cid}/decide", json={"decision": "later", "by": "ziv"}
    )
    assert r.status_code == 200, r.text
    async with world.sm() as s:
        (await s.get(TopicCandidate, uuid.UUID(cid))).status = "withdrawn"
        await s.commit()
    return cid


async def test_live_later_on_a_stale_later_idea_says_it_came_back_and_plain_undo_takes_that_back(
    live,
):
    """D1: an earlier approval in the call stands; the plain undo takes back the D1 change."""
    approved = await live_topic(live, "Receptionist at night")
    await live.tool("tce_decide", topic=approved[:8], decision="approve")
    assert approved in await live_week(live)
    cid = await live_stale_later(live, "Invoices nobody opens")

    said, data = await live.tool("tce_decide", topic=cid[:8], decision="later")
    assert data.get("change_id"), said
    assert "Nothing was changed" not in said
    assert "back" in said and "saved for later" in said
    assert f"(change {data['change_id'][:8]})" in said
    assert await live_status(live, cid) == "proposed"

    undone, _ = await live.tool("tce_undo")
    assert await live_status(live, cid) == "withdrawn", undone
    assert await live_decision(live, cid) == "later"
    assert "Invoices nobody opens" in undone
    assert approved in await live_week(live), "the approval stands"
    assert await live_decision(live, approved) == "this_week"


async def test_live_discuss_on_a_stale_later_idea_then_plain_undo_is_later_and_withdrawn(live):
    """D5."""
    cid = await live_stale_later(live, "Invoices nobody opens")
    said, data = await live.tool("tce_decide", topic=cid[:8], decision="discuss")
    assert data.get("change_id"), said
    assert await live_status(live, cid) == "proposed"

    undone, _ = await live.tool("tce_undo")
    assert await live_status(live, cid) == "withdrawn", undone
    assert await live_decision(live, cid) == "later"


async def test_live_approve_on_a_superseded_idea_then_plain_undo_withdraws_it(live):
    """D3 (and D2 with later) through the real voice call."""
    for decision in ("approve", "later"):
        cid = await live_superseded(live, f"Invoices nobody opens {decision}")
        said, data = await live.tool("tce_decide", topic=cid[:8], decision=decision)
        assert data.get("change_id"), said
        assert await live_status(live, cid) == "proposed"

        undone, _ = await live.tool("tce_undo")
        assert await live_status(live, cid) == "withdrawn", undone
        assert await live_decision(live, cid) is None
        assert cid not in await live_week(live)


async def test_live_away_on_a_superseded_idea_is_already_put_away(live):
    """D4: nothing written, so the plain undo after it has nothing of this idea to undo."""
    approved = await live_topic(live, "Receptionist at night")
    await live.tool("tce_decide", topic=approved[:8], decision="approve")
    cid = await live_superseded(live, "Invoices nobody opens")

    said, data = await live.tool("tce_decide", topic=cid[:8], decision="away")
    assert "already put away" in said
    assert not data.get("change_id")
    assert await live_status(live, cid) == "withdrawn"
    assert await live_decision(live, cid) is None

    undone, _ = await live.tool("tce_undo")
    assert await live_status(live, cid) == "withdrawn", undone
    assert approved not in await live_week(live), "the plain undo reached the approval"


@pytest.mark.parametrize(
    ("tool", "extra"), [("tce_put_away", {}), ("tce_decide", {"decision": "away"})]
)
async def test_live_away_on_a_withdrawn_idea_still_in_the_week_then_undo_puts_it_back(
    live, tool, extra
):
    """RP11 through the real voice call: chosen for this week at place 2, withdrawn by the
    engine (it stays on the list), then put away by voice. It comes off the list with a
    change id, and the plain undo puts it back at place 2, withdrawn and chosen as before."""
    ids = [
        await live_topic(live, title)
        for title in ("Receptionist at night", "Invoices nobody opens", "Funnel leaks")
    ]
    for chosen in ids:  # on his phone
        r = await live.http.post(
            f"/api/v1/editorial/topics/{chosen}/decide",
            json={"decision": "this_week", "by": "ziv"},
        )
        assert r.status_code == 200, r.text
    cid = ids[1]
    await live_set_status(live, cid, "withdrawn")
    assert await live_week(live) == ids, "withdrawn, and still on this week's list"

    read, _ = await live.tool("tce_topic", topic=cid[:8])
    assert "In this week." in read and "Put away." not in read

    said, data = await live.tool(tool, topic=cid[:8], **extra)
    assert data.get("change_id"), said
    assert "already" not in said
    assert f"(change {data['change_id'][:8]})" in said
    assert await live_week(live) == [ids[0], ids[2]]
    assert await live_status(live, cid) == "withdrawn"
    assert await live_decision(live, cid) == "away"

    undone, _ = await live.tool("tce_undo")
    assert await live_week(live) == ids, undone
    assert await live_status(live, cid) == "withdrawn"
    assert await live_decision(live, cid) == "this_week"
    assert "place 2" in undone
    assert "brought back" not in undone


async def test_live_words_find_candidates_to_read_back_and_only_an_id_writes(live):
    first = await live_topic(live, "Your first client is the hardest")
    talked = await live_topic(live, "מה שדיברנו עליו בפגישה")
    for words in ("the first one", "זה שדיברנו עליו", "הראשון"):
        said, _ = await live.tool("tce_decide", topic=words, decision="approve")
        assert "tce_topic" in said and "Nothing was changed" in said
        read, data = await live.tool("tce_topic", topic=words)
        assert data.get("status") in ("none", "ambiguous"), (words, read)
    assert await live_decision(live, first) is None and await live_decision(live, talked) is None

    read, data = await live.tool("tce_topic", topic="first client")
    assert data["candidate_id"] == first and f"(id {first[:8]})" in read
    said, _ = await live.tool("tce_decide", topic=first[:8], decision="approve")
    assert '"Your first client is the hardest"' in said
    assert await live_decision(live, first) == "this_week"


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


# ------------------------------------------------------------------ new ideas

RUN = "12121212-3434-5656-7878-909090909090"


def test_a_new_idea_is_read_back_first_and_nothing_is_saved():
    out = run({
        "steps": [step("tce_new_idea", said="a video about selling outcomes not hours",
                       idea="Coaches should price the outcome, not the hours")],
        "responses": {},
    })
    assert out["sent"] == []
    assert out["texts"][0].startswith('Read this back to him and ask if it is right: "Coaches should price')  # noqa: E501
    assert "Nothing is saved until" in out["texts"][0]


def test_a_confirmed_idea_is_saved_through_the_gates_and_its_script_is_followed():
    out = run({
        "steps": [
            step("tce_new_idea", said="a video about selling outcomes not hours",
                 idea="Coaches should price the outcome, not the hours", confirmed=True),
            step("tce_jobs"),
            step("tce_jobs"),
        ],
        "responses": {
            "POST /editorial/spoken-idea": {"ok": True, "status": 202, "data": {"run_id": RUN}},
            f"GET /editorial/idea-runs/{RUN}": {"ok": True, "status": 200, "data": {
                "state": "done", "said": 'is saved as "Price the outcome"; its script is being written now',  # noqa: E501
                "result": {"saved": True, "candidate_id": CID, "title": "Price the outcome",
                           "script_started": True},
            }},
            f"GET /editorial/candidates/{CID}/packet-status": [
                {"ok": True, "status": 200, "data": {"job": {"state": "running", "current_activity": "Writing"}}},  # noqa: E501
                {"ok": True, "status": 200, "data": {"job": {"state": "done", "result": {}}}},
            ],
        },
    })
    post = [s for s in out["sent"] if s["key"] == "POST /editorial/spoken-idea"][0]["body"]
    assert post["said"] == "a video about selling outcomes not hours"
    assert post["write_script"] is True and post["by"] == "voice"
    assert out["texts"][0].startswith('Checking "Coaches should price the outcome, not the hours"')
    assert 'Your idea for "Coaches should price the outcome, not the hours" is saved as "Price the outcome"' in out["texts"][1]  # noqa: E501
    assert 'The script for "Price the outcome" is still going' in out["texts"][1]
    assert 'The script for "Price the outcome" is ready.' in out["texts"][2]


def test_a_refused_idea_says_which_check_it_failed():
    out = run({
        "steps": [
            step("tce_new_idea", said="funding news", idea="Funding news", confirmed=True),
            step("tce_jobs"),
        ],
        "responses": {
            "POST /editorial/spoken-idea": {"ok": True, "status": 202, "data": {"run_id": RUN}},
            f"GET /editorial/idea-runs/{RUN}": {"ok": True, "status": 200, "data": {
                "state": "done",
                "said": "was not saved. It did not pass the owner relevance check: not for coaches",
                "result": {"saved": False},
            }},
        },
    })
    assert "did not pass the owner relevance check" in out["texts"][1]
    assert not any("packet-status" in s["key"] for s in out["sent"])


def test_find_ideas_starts_research_and_reports_what_it_found():
    out = run({
        "steps": [step("tce_find_ideas", topic="pricing for coaches"), step("tce_find_ideas"),
                  step("tce_jobs")],
        "responses": {
            "POST /editorial/idea-research": {"ok": True, "status": 202, "data": {"run_id": RUN}},
            f"GET /editorial/idea-runs/{RUN}": {"ok": True, "status": 200, "data": {
                "state": "done", "said": 'looked at 6 pages: New on your list: "X".', "result": {},
            }},
        },
    })
    bodies = [s["body"] for s in out["sent"] if s["key"] == "POST /editorial/idea-research"]
    assert bodies == [
        {"topic": "pricing for coaches", "by": "voice", "count": 3, "type": "any", "days": 21},
        {"topic": None, "by": "voice", "count": 3, "type": "any", "days": 21},
    ]
    assert 'about "pricing for coaches"' in out["texts"][0]
    assert "what you have been working on lately" in out["texts"][1]
    assert 'Looking for ideas for "pricing for coaches" looked at 6 pages' in out["texts"][2]


def test_find_ideas_takes_how_many_and_what_type():
    """27-Sep: "research new topics, decide how many, choose a specific type of videos"."""
    out = run({
        "steps": [step("tce_find_ideas", count=5, type="coaching", days=14)],
        "responses": {
            "POST /editorial/idea-research": {"ok": True, "status": 202, "data": {"run_id": RUN}},
        },
    })
    bodies = [s["body"] for s in out["sent"] if s["key"] == "POST /editorial/idea-research"]
    assert bodies == [{"topic": None, "by": "voice", "count": 5, "type": "coaching", "days": 14}]
    assert "last 14 days" in out["texts"][0]
    assert "5 new coaching topics" in out["texts"][0]
    assert "notification" in out["texts"][0].lower() or "topics page" in out["texts"][0].lower()


def test_an_idea_run_lost_to_a_restart_says_so():
    out = run({
        "steps": [step("tce_find_ideas", topic="x"), step("tce_jobs")],
        "responses": {
            "POST /editorial/idea-research": {"ok": True, "status": 202, "data": {"run_id": RUN}},
            f"GET /editorial/idea-runs/{RUN}": {"ok": False, "status": 404, "data": {"detail": "gone"}},  # noqa: E501
        },
    })
    assert "stopped when the server restarted" in out["texts"][1]


def test_the_call_seat_allows_exactly_the_tools_the_voice_family_registers():
    """deploy/voice-seat/tce.json is what the release copies into the call's seat.
    A tool missing there cannot be called on a call; one extra names nothing."""
    seat = json.loads((ROOT.parent / "deploy" / "voice-seat" / "tce.json").read_text())
    out = run({"steps": [], "responses": {}})
    assert sorted(t.split("__")[-1] for t in seat["allowedTools"]) == out["names"]
    assert len(seat["allowedTools"]) == len(set(seat["allowedTools"]))
    # KM BOT refuses a seat that allows more than 64 tools (validateSeat), and then
    # every TCE call fails, not just the new tools.
    assert len(seat["allowedTools"]) < 64


# ------------------------------------------- recorded videos, posts, publishing
#
# 28-Sep call: how many videos he recorded today, where each stands, the posts
# once editing is done, and approving one to go out. Publishing really posts,
# so it reads back the exact post and platform and needs his yes, and refuses
# when the words changed after the read-back.

EDITED = "11111111-2222-4333-8444-555555555555"
EDITING = "99999999-2222-4333-8444-555555555555"
OLD = "77777777-2222-4333-8444-555555555555"


def _library(today_iso):
    return {"ok": True, "status": 200, "data": {"items": [
        {"upload_id": EDITED, "title": "Charge what you are worth", "recorded_at": today_iso, "status": "edited",
         "state_sentence": "Ready."},
        {"upload_id": EDITING, "title": "The first ten seconds", "recorded_at": today_iso, "status": "rendering",
         "state_sentence": "Rendering the cut."},
        {"upload_id": OLD, "title": "Last week's talk", "recorded_at": "2020-01-01T10:00:00", "status": "edited"},
    ]}}


def _posts(caption="Stop discounting. Here is why."):
    return {"ok": True, "status": 200, "data": {"upload_id": EDITED, "platforms": [
        {"platform": "instagram", "label": "Instagram", "status": "draft", "copy": {"caption": caption}},
        {"platform": "facebook", "label": "Facebook", "status": "none", "copy": {}},
        {"platform": "youtube", "label": "YouTube", "status": "draft",
         "copy": {"title": "Charge more", "description": "Why discounts cost you."}},
        {"platform": "linkedin", "label": "LinkedIn", "status": "posted", "copy": {"message": "Out already."}},
    ]}}


def _now_utc_naive():
    # The server sends naive UTC; "today" is his day in Israel.
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


QUEUE = {"ok": True, "status": 200, "data": {"ideas": [
    {"title": "Pricing for coaches", "active_session_status": "recording", "active_session_id": "abcdef12-0000"},
    {"title": "Not started", "active_session_status": None},
]}}


def test_recordings_counts_today_says_where_each_stands_and_who_is_still_recording():
    out = run({"steps": [step("tce_recordings"), step("tce_recordings", when="all")],
               "responses": {"GET /production/library": _library(_now_utc_naive()),
                             "GET /production/recording-queue": QUEUE}})
    today, every = out["texts"]
    assert today.startswith("You recorded 2 videos today."), today
    assert "Charge what you are worth: editing done." in today
    assert "The first ten seconds: in editing." in today
    assert "Last week's talk" not in today
    assert "Still recording: Pricing for coaches." in today
    assert every.startswith("There are 3 recordings in your library."), every
    assert EDITED not in today, "ids are for tools, never read out"


def test_the_day_is_israel_not_utc():
    # 22:30 UTC on 27-Sep is already 28-Sep in Israel (UTC+3).
    harness = ROOT / f"_voice_day_{uuid.uuid4().hex[:8]}.mjs"
    harness.write_text(
        "import { localDay } from './tools/voice.mjs';\n"
        "console.log(JSON.stringify([localDay('2026-09-27T22:30:00'), localDay('2026-09-27T20:59:00Z')]));\n"
    )
    try:
        got = subprocess.run(["node", str(harness)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    finally:
        harness.unlink(missing_ok=True)
    assert json.loads(got.stdout) == ["2026-09-28", "2026-09-27"], got.stdout + got.stderr


def test_video_posts_reads_each_written_post_and_waits_for_the_edit():
    out = run({"steps": [step("tce_video_posts", video=EDITED[:8]), step("tce_video_posts", video=EDITING[:8]),
                         step("tce_video_posts", video="the pricing one")],
               "responses": {"GET /production/library": _library(_now_utc_naive()),
                             "GET /production/uploads/": _posts()}})
    posts, not_yet, words = out["texts"]
    assert "Instagram, a draft: Stop discounting. Here is why." in posts
    assert "YouTube, a draft: Charge more. Why discounts cost you." in posts
    assert "LinkedIn, posted" in posts and "Facebook" not in posts
    assert "in editing" in not_yet and "not written yet" in not_yet
    assert "not an id" in words


def test_publish_reads_back_first_and_posts_only_after_a_yes_with_the_same_words():
    base = {"GET /production/library": _library(_now_utc_naive()), "GET /production/uploads/": _posts()}
    first = run({"steps": [step("tce_publish", video=EDITED[:8], platform="instagram")], "responses": base})
    said = first["texts"][0]
    assert 'Publish the Instagram post for "Charge what you are worth" now' in said
    assert "Stop discounting. Here is why." in said
    assert not any(s["key"].startswith("POST") for s in first["sent"]), "nothing goes out on the read-back"
    code = json.loads(first["seen"][0])["data"]["check"]

    yes = run({"steps": [step("tce_publish", video=EDITED[:8], platform="instagram", confirmed=True, check=code)],
               "responses": {**base, "POST /production/uploads/": {"ok": True, "status": 202, "data": {"ok": True}}}})
    posts = [s for s in yes["sent"] if s["key"].startswith("POST")]
    assert posts == [{"key": f"POST /production/uploads/{EDITED}/publishing/publish", "body": {"platforms": ["instagram"]}}]
    assert "Publishing the Instagram post" in yes["texts"][0]


def test_publish_refuses_changed_words_a_missing_check_and_anything_not_a_draft():
    changed = {"GET /production/library": _library(_now_utc_naive()),
               "GET /production/uploads/": _posts(caption="Different words now.")}
    first = run({"steps": [step("tce_publish", video=EDITED[:8], platform="instagram")],
                 "responses": {"GET /production/library": _library(_now_utc_naive()), "GET /production/uploads/": _posts()}})
    code = json.loads(first["seen"][0])["data"]["check"]
    out = run({"steps": [
        step("tce_publish", video=EDITED[:8], platform="instagram", confirmed=True, check=code),
        step("tce_publish", video=EDITED[:8], platform="instagram", confirmed=True),
        step("tce_publish", video=EDITED[:8], platform="linkedin", confirmed=True, check=code),
        step("tce_publish", video=EDITED[:8], platform="facebook"),
        step("tce_publish", video=EDITING[:8], platform="instagram", confirmed=True, check=code),
        step("tce_publish", video="the pricing one", platform="instagram", confirmed=True, check=code),
        step("tce_publish", video=EDITED[:8], platform="tiktok", confirmed=True, check=code),
    ], "responses": changed})
    t = out["texts"]
    assert "not the one you read back" in t[0] and "Different words now." in t[0]
    assert "not the one you read back" in t[1]
    assert "already posted" in t[2]
    assert "no Facebook post written" in t[3]
    assert "once editing is done" in t[4]
    assert "not an id" in t[5]
    assert "Which platform" in t[6]
    assert not any(s["key"].startswith("POST") for s in out["sent"]), "none of these publishes anything"



# ------------------------------------------- talk to the editor: the video tools
#
# Design of 30-Sep, section 4 (step 7). He pauses the edit, holds a button and
# says what is wrong; his notes sheet pins the paused second and saves his words.
# The call brain reads the moment, saves a one-line reading and says it back.
# Nothing renders until he says make it, and that has a read-back and a check
# code, like a publish. A call never opens a sitting and never pins a note.

VID = "abcdef12-2222-4333-8444-555555555555"
SITTING = "5e5e5e5e-1111-4222-8333-444444444444"
MADE = "6f6f6f6f-1111-4222-8333-444444444444"
NOTE1 = "a0a0a0a0-1111-4222-8333-444444444444"
NOTE2 = "b0b0b0b0-1111-4222-8333-444444444444"
TITLE = "Charge what you are worth"
FIND = f"GET /production/recordings/{VID}/talk"
MOMENT = f"GET /production/talk/{SITTING}/moment"
VIDEO_TOOLS = [
    "tce_video_moment",
    "tce_video_note",
    "tce_video_notes",
    "tce_video_make",
    "tce_video_undo_version",
]


def _note(
    nid,
    where="at 0:38",
    state="held",
    request="cut the second basically",
    understood=None,
    result=None,
):
    return {
        "id": nid,
        "upload_id": VID,
        "session_id": SITTING,
        "scope": "moment",
        "where": where,
        "start_s": 38.25,
        "end_s": None,
        "source_s": 40.1,
        "section_ref": None,
        "request": request,
        "understood": understood,
        "created_by": "ziv",
        "state": state,
        "result": result,
        "created_at": "2026-10-01T08:00:00",
        "resolved_at": None,
    }


def _sitting(state="open", notes=(), result=None, video_step=None, sid=SITTING):
    notes = list(notes)
    return {
        "session_id": sid,
        "upload_id": VID,
        "state": state,
        "render_ref": "r1",
        "file_url": f"/api/v1/production/uploads/{VID}/edited?v=r1",
        "edit_length_s": 120.0,
        "last_seen": None,
        "submitted_at": None,
        "finished_at": None,
        "summary": None,
        "result": result,
        "notes": notes,
        "waiting": sum(1 for n in notes if n["state"] in ("listening", "held")),
        "video_status": "edited",
        "video_step": video_step,
        "can_undo": False,
    }


def _found(live=None, made=None):
    return {
        "ok": True,
        "status": 200,
        "data": {"upload_id": VID, "title": TITLE, "status": "edited", "live": live, "made": made},
    }


def _moment(note=None, heard="cut the second basically", waiting=None, in_edit=True):
    note = note or _note(NOTE1)
    return {
        "ok": True,
        "status": 200,
        "data": {
            "session_id": SITTING,
            "video": VID,
            "state": "open",
            "note": note,
            "heard": heard,
            "waited_for_words": False,
            "at": {"edit_s": 38.25, "source_s": 40.1, "clock": "0:38", "in_edit": in_edit},
            "window": {"from_edit_s": 30.25, "to_edit_s": 46.25},
            "transcript": (
                "[0:36 in the edit] 70:so 71:basically ~~72:basically~~ /cut 0.4s/ "
                "73:what 74:I 75:do"
            ),
            "words": [{"index": 70, "text": "so", "source_s": 37.0, "edit_s": 36.1, "cut": False}],
            "marks": [
                {"index": 75, "text": "do", "mark": "your phone cut the end of this word short"}
            ],
            "waiting": waiting
            if waiting is not None
            else [{"id": note["id"], "where": note["where"], "heard": heard}],
            "earlier": [],
            "rules": "Standing rules: keep the pauses short.",
        },
    }


def _refused(code, message, status=409, **extra):
    return {
        "ok": False,
        "status": status,
        "data": {"detail": {"code": code, "message": message, **extra}},
    }


def test_the_moment_reads_his_note_with_the_words_around_it_and_the_rules_once():
    out = run(
        {
            "steps": [
                step("tce_video_moment", video=f"video:{VID}"),
                step("tce_video_moment", video=VID, note=NOTE1[:8]),
            ],
            "responses": {FIND: _found(live=_sitting(notes=[_note(NOTE1)])), MOMENT: _moment()},
        }
    )
    first, _second = out["texts"]
    keys = [s["key"] for s in out["sent"]]
    assert keys == [FIND, f"{MOMENT}?rules=1", FIND, f"{MOMENT}?note={NOTE1}"], (
        "rules ride on the first moment only"
    )
    assert first.startswith(f'Note at 0:38 on "{TITLE}" (note id {NOTE1}).'), first
    assert 'He said: "cut the second basically".' in first
    assert "~~72:basically~~ /cut 0.4s/" in first
    assert 'Word 75 "do": your phone cut the end of this word short' in first
    assert f"tce_video_note (note {NOTE1})" in first and "Do not ask him first" in first
    data = json.loads(out["seen"][0])["data"]
    assert data["rules"] == "Standing rules: keep the pauses short." and data["note"]["id"] == NOTE1
    assert "words" not in data, "the numbered transcript already carries them"
    assert not any(k.startswith(("POST", "PATCH")) for k in keys), (
        "reading a moment changes nothing"
    )


def test_the_moment_says_which_other_notes_wait_and_when_the_new_version_cut_the_second():
    waiting = [
        {"id": NOTE1, "where": "at 0:38", "heard": "cut the second basically"},
        {"id": NOTE2, "where": "at 1:09", "heard": "trim the pause"},
    ]
    out = run(
        {
            "steps": [step("tce_video_moment", video=VID)],
            "responses": {
                FIND: _found(live=_sitting(notes=[_note(NOTE1)])),
                MOMENT: _moment(waiting=waiting, in_edit=False, heard=None),
            },
        }
    )
    said = out["texts"][0]
    assert "His words for this note are not saved yet" in said
    assert "cut this moment" in said
    assert f'Also waiting for your reading: at 1:09 (note id {NOTE2}): "trim the pause".' in said


def test_the_moment_never_opens_a_sitting_and_says_when_there_is_nothing_to_read():
    making = _sitting(
        state="rendering",
        notes=[_note(NOTE1)],
        result={"status": "Applying your notes"},
        video_step="Burning in your captions: 40%",
    )
    no_note = _refused(
        "no_moment",
        "There is no note waiting in this sitting, and no second was given.",
        status=404,
    )
    none = run({"steps": [step("tce_video_moment", video=VID)], "responses": {FIND: _found()}})
    assert "No notes are open" in none["texts"][0] and "notes sheet" in none["texts"][0]
    busy = run(
        {"steps": [step("tce_video_moment", video=VID)], "responses": {FIND: _found(live=making)}}
    )
    assert (
        "being made into a new version right now (Burning in your captions: 40%)"
        in busy["texts"][0]
    )
    empty = run(
        {
            "steps": [
                step("tce_video_moment", video=VID),
                step("tce_video_moment", video="the pricing one"),
            ],
            "responses": {FIND: _found(live=_sitting()), MOMENT: no_note},
        }
    )
    assert "No note is waiting" in empty["texts"][0]
    assert "not an id" in empty["texts"][1]
    for out in (none, busy, empty):
        assert all(s["key"].startswith("GET") for s in out["sent"]), (
            "a call never opens a sitting or pins"
        )


def test_a_note_is_saved_by_its_id_and_said_back_naming_the_time_and_never_renders():
    saved = {
        "ok": True,
        "status": 200,
        "data": _note(NOTE1, understood="you want the second basically gone"),
    }
    reading = "At 0:38 you want the second basically gone."
    out = run(
        {
            "steps": [
                step("tce_video_moment", video=VID),
                step("tce_video_note", note=NOTE1, understood=reading),
                # Live hands the same words over twice (it re-reads its last lines):
                # the same note again.
                step("tce_video_note", note=NOTE1, understood=reading),
            ],
            "responses": {
                FIND: _found(live=_sitting(notes=[_note(NOTE1)])),
                MOMENT: _moment(),
                f"PATCH /production/talk/{SITTING}/notes/{NOTE1}": saved,
            },
        }
    )
    _, said, again = out["texts"]
    assert (
        said
        == "At 0:38: you want the second basically gone. "
        "Saved; nothing changes until you say make it."
    )
    assert again == said
    patches = [s for s in out["sent"] if s["key"].startswith("PATCH")]
    assert (
        patches
        == [
            {
                "key": f"PATCH /production/talk/{SITTING}/notes/{NOTE1}",
                "body": {"understood": "you want the second basically gone"},
            }
        ]
        * 2
    )
    assert not any(s["key"].startswith("POST") for s in out["sent"]), (
        "a note never pins, submits or renders"
    )


def test_a_note_this_process_never_read_is_found_through_its_video():
    both = _sitting(notes=[_note(NOTE1), _note(NOTE2, where="at 1:09", request="trim the pause")])
    out = run(
        {
            "steps": [
                step("tce_video_note", note=NOTE2, understood="trim the pause"),
                step("tce_video_note", note=NOTE2[:8], understood="trim the pause", video=VID),
            ],
            "responses": {
                FIND: _found(live=both),
                f"PATCH /production/talk/{SITTING}/notes/{NOTE2}": {
                    "ok": True,
                    "status": 200,
                    "data": _note(NOTE2, where="at 1:09", understood="trim the pause"),
                },
            },
        }
    )
    assert "Which video?" in out["texts"][0]
    assert (
        out["texts"][1] == "At 1:09: trim the pause. Saved; nothing changes until you say make it."
    )
    assert [s["key"] for s in out["sent"]] == [
        FIND,
        f"PATCH /production/talk/{SITTING}/notes/{NOTE2}",
    ]


def test_scratch_that_takes_the_note_back_and_a_late_reading_saves_nothing():
    taken = _refused("not_waiting", "That note was taken back.")
    out = run(
        {
            "steps": [
                step("tce_video_note", note=NOTE1, drop=True, video=VID),
                step("tce_video_note", note=NOTE1, drop=True),
                step("tce_video_note", note=NOTE1, understood="cut it"),
                step("tce_video_note", note=NOTE1),
            ],
            "responses": {
                FIND: _found(live=_sitting(notes=[_note(NOTE1)])),
                f"PATCH /production/talk/{SITTING}/notes/{NOTE1}": [
                    {"ok": True, "status": 200, "data": _note(NOTE1, state="rejected")},
                    taken,
                    taken,
                ],
            },
        }
    )
    t = out["texts"]
    assert t[0] == "Took back the note at 0:38. Nothing changes until you say make it."
    assert t[1] == "That note was already taken back. Nothing else changed."
    assert t[2].startswith("That note was taken back.") and "Nothing was saved" in t[2]
    assert "in one line" in t[3]
    assert [s["body"] for s in out["sent"] if s["key"].startswith("PATCH")] == [
        {"drop": True},
        {"drop": True},
        {"understood": "cut it"},
    ]


def test_make_reads_every_note_back_and_submits_only_with_its_check_then_jobs_follows_it():
    notes = [
        _note(NOTE1, understood="you want the second basically gone"),
        _note(NOTE2, where="at 1:09", understood="trim the pause"),
    ]
    read_back = (
        "2 notes: at 0:38: you want the second basically gone; at 1:09: trim the pause. "
        "One re-render."
    )
    preview = {
        "ok": True,
        "status": 200,
        "data": {
            "session_id": SITTING,
            "read_back": read_back,
            "check": "c0ffee123456",
            "count": 2,
            "notes": notes,
            "left_out": [],
        },
    }
    thinking = _sitting(
        state="thinking",
        notes=notes,
        result={"status": "Reading your 2 notes on the subscription", "notes": [NOTE1, NOTE2]},
    )
    settled = [
        {**notes[0], "state": "done", "result": {"reply": "Cut the second basically."}},
        {
            **notes[1],
            "state": "needs_you",
            "result": {"question": "Which pause, the one before or after 'service'?"},
        },
    ]
    done = _sitting(
        state="needs_you",
        notes=settled,
        result={
            "status": "New version made from your 2 notes. 1 of them needs you.",
            "notes": [NOTE1, NOTE2],
        },
    )
    out = run(
        {
            "steps": [
                step("tce_video_make", video=VID),
                step("tce_video_make", video=VID, confirmed=True),
                step("tce_video_make", video=VID, confirmed=True, check="c0ffee123456"),
                step("tce_jobs"),
                step("tce_jobs", new_only=True),
                step("tce_jobs", new_only=True),
            ],
            "responses": {
                FIND: _found(live=_sitting(notes=notes)),
                f"GET /production/talk/{SITTING}/submit": preview,
                f"POST /production/talk/{SITTING}/submit": {
                    "ok": True,
                    "status": 200,
                    "data": {**thinking, "read_back": read_back},
                },
                f"GET /production/talk/{SITTING}": [
                    {"ok": True, "status": 200, "data": thinking},
                    {"ok": True, "status": 200, "data": done},
                ],
            },
        }
    )
    t = out["texts"]
    assert t[0] == (
        f'Read this back to him about "{TITLE}" and ask for a clear yes: "{read_back}" '
        "Nothing is made "
        "until you call tce_video_make again with confirmed true and check c0ffee123456."
    )
    assert "no check code" in t[1]
    assert t[2].startswith(f'Making the new version of "{TITLE}" from 2 notes now'), t[2]
    # The submit itself; the hold that asked for each step is taken back first (its own test).
    posts = [s for s in out["sent"] if s["key"].startswith("POST") and not s["key"].endswith("/command")]
    assert posts == [
        {
            "key": f"POST /production/talk/{SITTING}/submit",
            "body": {"check": "c0ffee123456", "by": "voice"},
        }
    ]
    assert (
        t[3]
        == f'The new version for "{TITLE}" is still being made '
        "(Reading your 2 notes on the subscription)."
    )
    assert t[4].startswith(
        f'The new version for "{TITLE}" is done: '
        "New version made from your 2 notes. 1 of them needs you."
    ), t[4]
    assert "What was done: at 0:38: Cut the second basically." in t[4]
    assert t[4].endswith(
        "1 note needs him: at 1:09: Which pause, the one before or after 'service'?"
    ), t[4]
    assert t[5] == "Nothing new has finished yet."


def test_make_refuses_a_yes_to_notes_that_changed_and_says_what_else_is_editing():
    changed = _refused(
        "changed",
        "The notes changed since the read-back.",
        check="beef00000000",
        read_back="3 notes: at 0:38: cut it; at 1:09: trim; at 1:30: louder. One re-render.",
    )
    busy = _refused(
        "busy", "An editing request you typed is being made right now (Reading your request)."
    )
    out = run(
        {
            "steps": [
                step("tce_video_make", video=VID, confirmed=True, check="c0ffee123456"),
                step("tce_video_make", video=VID),
            ],
            "responses": {
                FIND: _found(live=_sitting(notes=[_note(NOTE1)])),
                f"POST /production/talk/{SITTING}/submit": changed,
                f"GET /production/talk/{SITTING}/submit": busy,
            },
        }
    )
    t = out["texts"]
    assert (
        "changed since you read them back" in t[0]
        and "at 1:30: louder" in t[0]
        and "beef00000000" in t[0]
    )
    assert json.loads(out["seen"][0])["data"]["made"] is False
    assert (
        t[1]
        == "An editing request you typed is being made right now (Reading your request). "
        "Nothing was made."
    )


def test_a_hold_that_carried_an_instruction_is_taken_back_by_the_tool_that_carries_it_out():
    """1-Oct final review: every hold on the sheet is pinned, so "that's all, make it", the
    yes, "no, I meant...", "scratch that" and "go back" each became a note. The tool that
    acts on one takes its hold back first (by his words), and a yes is said with the
    read-back's as_of, so a yes hold never changes the check."""
    as_of = "2026-10-01T08:00:05.123456"
    preview = {
        "ok": True,
        "status": 200,
        "data": {
            "session_id": SITTING,
            "read_back": "1 note: at 0:38: you want the second basically gone. One re-render.",
            "check": "c0ffee123456",
            "count": 1,
            "notes": [],
            "left_out": [],
            "as_of": as_of,
        },
    }
    notes = [_note(NOTE1, understood="you want the second basically gone")]
    thinking = _sitting(state="thinking", notes=notes, result={"notes": [NOTE1]})
    taken = {"ok": True, "status": 200, "data": {"taken": _note(NOTE2, state="rejected")}}
    out = run(
        {
            "steps": [
                step("tce_video_moment", video=VID, said="Trim the pause here."),
                step("tce_video_note", note=NOTE1, understood="the first basically", correcting=True,
                     said="no, I meant the first one", video=VID),
                step("tce_video_note", note=NOTE1, understood="cut it", video=VID),
                step("tce_video_make", video=VID, said="that's all, make it"),
                step("tce_video_make", video=VID, confirmed=True, check="c0ffee123456", said="yes"),
                step("tce_video_note", note=NOTE1, drop=True, said="scratch that", video=VID),
            ],
            "responses": {
                FIND: _found(live=_sitting(notes=notes)),
                MOMENT: _moment(),
                f"PATCH /production/talk/{SITTING}/notes/{NOTE1}": {"ok": True, "status": 200, "data": notes[0]},
                f"POST /production/talk/{SITTING}/command": taken,
                f"GET /production/talk/{SITTING}/submit": preview,
                f"POST /production/talk/{SITTING}/submit": {"ok": True, "status": 200, "data": thinking},
            },
        }
    )
    keys = [s["key"] for s in out["sent"]]
    assert f"{MOMENT}?said=Trim%20the%20pause%20here.&rules=1" in keys
    commands = [s["body"] for s in out["sent"] if s["key"].endswith("/command")]
    assert commands == [
        {"said": "no, I meant the first one", "keep": NOTE1},
        {"said": "that's all, make it"},
        {"said": "yes"},
        {"said": "scratch that", "keep": NOTE1},
    ], "a plain save takes nothing back"
    # Each hold is taken back before the read-back and before the yes is sent.
    sent = out["sent"]

    def at(match):
        return next(i for i, s in enumerate(sent) if match(s))

    def command(said):
        return at(lambda s: s["key"].endswith("/command") and s["body"].get("said") == said)

    assert command("that's all, make it") < at(lambda s: s["key"] == f"GET /production/talk/{SITTING}/submit")
    assert command("yes") < at(lambda s: s["key"] == f"POST /production/talk/{SITTING}/submit")
    submit = next(s for s in out["sent"] if s["key"] == f"POST /production/talk/{SITTING}/submit")
    assert submit["body"] == {"check": "c0ffee123456", "by": "voice", "as_of": as_of}
    assert out["texts"][4].startswith(f'Making the new version of "{TITLE}" from 1 note now')

    # Going back: his "go back" hold, in the notes he has open now, is taken back too.
    made = _sitting(state="done", sid=MADE, result={"status": "New version made from your 1 note."})
    back = run(
        {
            "steps": [step("tce_video_undo_version", video=VID, said="go back to the version before")],
            "responses": {
                FIND: _found(live=_sitting(), made=made),
                f"GET /production/talk/{MADE}/undo": {
                    "ok": True, "status": 200,
                    "data": {"session_id": MADE, "possible": True, "code": None, "reason": None,
                             "read_back": "Put back the version from before your 1 note. One re-render."},
                },
            },
        }
    )
    assert [s for s in back["sent"] if s["key"].endswith("/command")] == [
        {"key": f"POST /production/talk/{SITTING}/command", "body": {"said": "go back to the version before"}}
    ]


def test_a_moment_for_words_no_hold_has_says_it_may_be_an_instruction():
    out = run(
        {
            "steps": [step("tce_video_moment", video=VID, said="yes")],
            "responses": {
                FIND: _found(live=_sitting(notes=[_note(NOTE1)])),
                MOMENT: _refused("no_moment", "No hold of his waiting for a reading has those words.",
                                 status=404, said=True),
            },
        }
    )
    assert "use the tool for it" in out["texts"][0] and "Nothing was done" in out["texts"][0]


def test_going_back_reads_back_first_and_goes_back_only_on_that_read_back():
    made = _sitting(
        state="done", sid=MADE, result={"status": "New version made from your 2 notes."}
    )
    rb = "Put back the version from before your 2 notes (cut basically). One re-render."
    preview = {
        "ok": True,
        "status": 200,
        "data": {
            "session_id": MADE,
            "possible": True,
            "code": None,
            "reason": None,
            "read_back": rb,
        },
    }
    base = {FIND: _found(live=_sitting(), made=made), f"GET /production/talk/{MADE}/undo": preview}
    first = run({"steps": [step("tce_video_undo_version", video=VID)], "responses": base})
    assert f'"{rb}"' in first["texts"][0] and f'about "{TITLE}"' in first["texts"][0]
    # Only his "go back" hold is taken back (it is not a note); the video is untouched.
    assert [s["key"] for s in first["sent"] if s["key"].startswith("POST")] == [
        f"POST /production/talk/{SITTING}/command"
    ], "nothing changes on the read-back"
    code = json.loads(first["seen"][0])["data"]["check"]

    going = {
        **made,
        "result": {
            **made["result"],
            "undo": {"state": "rendering", "status": "Putting back the version"},
        },
    }
    back = {
        **made,
        "result": {
            **made["result"],
            "undo": {"state": "done", "status": "The version from before your notes is back."},
        },
    }
    yes = run(
        {
            "steps": [
                step("tce_video_undo_version", video=VID, confirmed=True, check="000000000000"),
                step("tce_video_undo_version", video=VID, confirmed=True, check=code),
                step("tce_jobs"),
                step("tce_jobs"),
            ],
            "responses": {
                **base,
                f"POST /production/talk/{MADE}/undo": {"ok": True, "status": 200, "data": going},
                f"GET /production/talk/{MADE}": [
                    {"ok": True, "status": 200, "data": going},
                    {"ok": True, "status": 200, "data": back},
                ],
            },
        }
    )
    t = yes["texts"]
    assert "not the read-back he heard" in t[0] and code in t[0]
    assert t[1].startswith(f'Putting back the version of "{TITLE}" from before his notes now')
    assert [s["key"] for s in yes["sent"] if s["key"].startswith("POST") and "/command" not in s["key"]] == [
        f"POST /production/talk/{MADE}/undo"
    ]
    assert "is still going (Putting back the version)" in t[2]
    assert t[3] == (
        f'Going back to the version before the notes for "{TITLE}" is done: '
        "The version from before your notes is back."
    )


UNDO_CHANGED = (
    "The video was changed again after these notes, so going back would undo that too. "
    "Nothing was changed."
)


def test_going_back_says_why_not_when_it_cannot_and_changes_nothing():
    made = _sitting(state="done", sid=MADE)
    refusal = {
        "ok": True,
        "status": 200,
        "data": {
            "session_id": MADE,
            "possible": False,
            "code": "changed",
            "reason": UNDO_CHANGED,
            "read_back": UNDO_CHANGED,
        },
    }
    out = run(
        {
            "steps": [
                step("tce_video_undo_version", video=VID, confirmed=True, check="x"),
                step("tce_video_undo_version", video=VID),
            ],
            "responses": {
                FIND: [_found(made=made), _found()],
                f"GET /production/talk/{MADE}/undo": refusal,
            },
        }
    )
    assert out["texts"][0] == (
        "The video was changed again after these notes, so going back would undo that too. "
        "Nothing was changed."
    )
    assert "nothing to go back from" in out["texts"][1]
    assert not any(s["key"].startswith("POST") for s in out["sent"])


def test_the_notes_say_where_each_stands_and_a_short_id_is_found_in_the_library():
    notes = [
        _note(NOTE1, understood="you want the second basically gone"),
        _note(NOTE2, where="at 1:09", state="listening", request=""),
        _note(
            "c0c0c0c0-1111-4222-8333-444444444444",
            where="at 1:30",
            state="rejected",
            request="louder",
        ),
        # His "yes" on a hold: an instruction taken back, never a note he took back.
        _note(
            "d0d0d0d0-1111-4222-8333-444444444444",
            where="at 1:31",
            state="rejected",
            request="yes",
            result={"command": "yes", "taken": "This hold was an instruction to the editor, not a note."},
        ),
    ]
    lib = {
        "ok": True,
        "status": 200,
        "data": {"items": [{"upload_id": VID, "title": TITLE, "status": "edited"}]},
    }
    out = run(
        {
            "steps": [step("tce_video_notes", video=VID[:8])],
            "responses": {"GET /production/library": lib, FIND: _found(live=_sitting(notes=notes))},
        }
    )
    assert out["texts"][0].splitlines() == [
        f'2 notes on "{TITLE}"; nothing changes until he says make it.',
        "at 0:38: you want the second basically gone (saved, waiting for make it)",
        "at 1:09: no words yet (his words are on their way)",
        "1 note was taken back.",
    ]
    assert [s["key"] for s in out["sent"]] == ["GET /production/library?filter=all", FIND]


# ------------------------------------------- the call seat that carries them

KMBOT = ROOT.parents[1] / "kmbot-talk"
SEAT_FILE = ROOT.parent / "deploy" / "voice-seat" / "tce.json"
INSTALLER = ROOT.parent / "scripts" / "install-voice-seat.sh"
# KM BOT's pattern for a call's ?context= (bin/kmbot-voice-seats.mjs CONTEXT_RE). Pinned
# for a checkout with no KM BOT beside it; the next test holds it equal to the real one.
CONTEXT_RE = r"^([a-z][a-z0-9_]{0,23})(?::([0-9a-f-]{6,40}))?$"
# The tce seat's contexts on the box, read on 1-Oct. The installer now owns them, so
# the repo must carry every one of them or a deploy would change a call it never meant to.
BOX_CONTEXTS = {
    "default": "He opened a call about his content. Ask what he wants to work on.",
    "week": (
        "He opened the call from his week. "
        "Start with tce_week and tell him briefly what needs a decision."
    ),
    "topic": (
        "He opened the call on one topic, id {id}. "
        "Start with tce_topic for that id and tell him where it stands."
    ),
}


def test_the_seat_has_a_video_context_for_any_upload_and_keeps_the_ones_on_the_box():
    seat = json.loads(SEAT_FILE.read_text(encoding="utf-8"))
    contexts = seat["contexts"]
    assert {k: contexts[k] for k in BOX_CONTEXTS} == BOX_CONTEXTS
    video = contexts["video"]
    assert "{id}" in video and "tce_video_moment" in video and "never answer it yourself" in video
    upload = str(uuid.uuid4())
    m = re.match(CONTEXT_RE, f"video:{upload}")
    assert m and m.group(1) == "video" and m.group(2) == upload
    for kind, text in contexts.items():
        assert kind == "default" or re.match(r"^[a-z][a-z0-9_]{0,23}$", kind)
        assert text.strip() and len(text) <= 2000
        assert "\u2014" not in text and "\u2013" not in text and "--" not in text
    assert all(f"mcp__tce__{name}" in seat["allowedTools"] for name in VIDEO_TOOLS)


SEAT_CHECK = r"""
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const [, , mod, seatFile, upload] = process.argv;
const m = await import(pathToFileURL(mod).href);
const repo = JSON.parse(readFileSync(seatFile, 'utf8'));
const errors = [];
const seat = m.validateSeat({
  id: 'tce', label: 'TCE', model: 'claude-opus-5-5', voice: 'gpt-live-1',
  brief: '/etc/kmbot/seats/tce-brief.md',
  mcpServers: { tce: {
    command: 'node', args: ['/home/ziv/team-content-engine/mcp-server/index.mjs'],
    env: { TCE_API_BASE: 'http://127.0.0.1:8200', TCE_MCP_FAMILIES: 'voice' },
  } },
  allowedTools: repo.allowedTools, contexts: repo.contexts,
}, errors);
console.log(JSON.stringify({
  errors, ok: Boolean(seat), re: String(m.CONTEXT_RE),
  video: seat && m.resolveContext(seat, `video:${upload}`),
  bare: seat && m.resolveContext(seat, 'video'),
  public: seat && m.publicSeat(seat),
}));
"""


def _kmbot(path):
    if shutil.which("node") is None:  # pragma: no cover
        pytest.skip("node is not installed")
    target = KMBOT / path
    if not target.exists():
        pytest.skip(f"KM BOT (kmbot-talk) is not beside this checkout: no {target}")
    return target


def test_km_bots_own_seat_check_takes_the_seat_and_opens_a_call_on_a_video():
    mod = _kmbot("bin/kmbot-voice-seats.mjs")
    upload = str(uuid.uuid4())
    script = ROOT / f"_seat_check_{uuid.uuid4().hex[:8]}.mjs"
    script.write_text(SEAT_CHECK, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", str(script), str(mod), str(SEAT_FILE), upload],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
        )
    finally:
        script.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["errors"] == [] and out["ok"], out["errors"]
    assert out["re"] == f"/{CONTEXT_RE}/", (
        "the pinned copy of KM BOT's context pattern is out of date"
    )
    assert out["video"]["ok"] and out["video"]["kind"] == "video" and upload in out["video"]["text"]
    assert out["bare"]["ok"] is False, "a video call needs the video's id"
    # Scenario F's preflight reads exactly this: the seat lists a "video" context.
    assert "video" in out["public"]["contexts"]


def test_scenario_f_in_km_bot_calls_only_tools_and_routes_this_repo_has():
    note_js = _kmbot("tools/voice-e2e/video-note.mjs")
    probe = ROOT / f"_f_probe_{uuid.uuid4().hex[:8]}.mjs"
    probe.write_text(
        "import { pathToFileURL } from 'node:url';\n"
        "const f = await import(pathToFileURL(process.argv[2]).href);\n"
        "console.log(JSON.stringify(\n"
        "  { video: f.VIDEO_TOOLS, allowed: f.F_ALLOWED_TOOLS, seat: f.TCE_SEAT }));\n",
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(
            ["node", str(probe), str(note_js)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
        )
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    f = json.loads(proc.stdout.strip().splitlines()[-1])
    seat = json.loads(SEAT_FILE.read_text(encoding="utf-8"))
    assert f["seat"] == "tce"
    assert set(f["video"]) <= set(seat["allowedTools"]), "F's preflight needs these on the seat"
    names = run({"steps": [], "responses": {}})["names"]
    assert {t for t in f["allowed"] if t != "ask_brain"} <= set(names)

    # Every TCE route F calls exists here, with that method.
    from tce.api.routers import editorial_workspace as workspace_router

    have = {
        (method, re.sub(r"\{[^}]+\}", "{}", route.path))
        for route in workspace_router.production_router.routes
        for method in route.methods
    }
    source = note_js.read_text(encoding="utf-8")
    calls = {
        (method, re.sub(r"\$\{[^}]+\}", "{}", path))
        for method, path in re.findall(
            r"tce\(\s*\"(GET|POST|PATCH)\",\s*[`\"](/production/[^`\"?]+)", source
        )
    }
    assert calls, "found no TCE calls in scenario F"
    assert calls <= have, sorted(calls - have)


# ------------------------------------------- the seat installer
#
# install-voice-seat.sh runs on every deploy. Its Python block decides what goes into
# /etc/kmbot/voice-seats.json; it runs here unchanged against copies shaped like the box.


def _installer_block() -> str:
    text = INSTALLER.read_text(encoding="utf-8")
    start = text.index("<<'PY'\n") + len("<<'PY'\n")
    return text[start : text.index("\nPY\n", start)]


# The call handle of KM BOT's web/voice-client.js, before and after K1 (the call's own
# mute and quiet, and startMuted), as far as the installer reads it.
OLD_CLIENT = """
    var greetFirst = true;
    return {
      send: function (text) { return sendText(text); },
      stop: function () { return stopCall(); },
      hush: function () { return hushNow(); },
    };
"""
K1_CLIENT = """
    var micMuted = Boolean(opts.startMuted);
    return {
      send: function (text) { return sendText(text); },
      mute: function (on) { return setMute(on === undefined ? true : Boolean(on)); },
      quiet: function (on) { return setQuiet(on === undefined ? true : Boolean(on)); },
    };
"""


def _client_file(tmp_path, text: str):
    path = tmp_path / f"voice-client-{uuid.uuid4().hex[:6]}.js"
    path.write_text(text, encoding="utf-8")
    return path


def _box_seats(**changes):
    repo = json.loads(SEAT_FILE.read_text(encoding="utf-8"))
    tce = {
        "id": "tce",
        "label": "TCE",
        "model": "claude-opus-5-5",
        "voice": "gpt-live-1",
        "brief": "/etc/kmbot/seats/tce-brief.md",
        "mcpServers": {
            "tce": {
                "command": "node",
                "args": ["/home/ziv/team-content-engine/mcp-server/index.mjs"],
                "env": {
                    "TCE_API_BASE": "http://127.0.0.1:8200",
                    "TCE_MCP_FAMILIES": "voice",
                    "TCE_PRIVATE_KEY": {"file": "/srv/tce/.env", "key": "TCE_PRIVATE_ACCESS_KEY"},
                },
            }
        },
        # The 18 tools and 3 contexts the box had on 1-Oct.
        "allowedTools": [t for t in repo["allowedTools"] if t.split("__")[-1] not in VIDEO_TOOLS],
        "contexts": dict(BOX_CONTEXTS),
    }
    tce.update(changes)
    other = {
        "id": "studio",
        "label": "Studio",
        "model": "claude-opus-5-5",
        "brief": "/etc/kmbot/seats/studio.md",
        "mcpServers": {"studio": {"command": "node"}},
        "allowedTools": ["mcp__studio__look"],
    }
    return {"seats": [other, tce]}


def _install(tmp_path, box, repo=None, name="candidate.json", client=None):
    seats = tmp_path / "voice-seats.json"
    seats.write_text(json.dumps(box, indent=2), encoding="utf-8")
    repo_file = tmp_path / "tce.json"
    repo_file.write_text(
        json.dumps(repo or json.loads(SEAT_FILE.read_text(encoding="utf-8"))), encoding="utf-8"
    )
    script = tmp_path / "seat_sync.py"
    script.write_text(_installer_block(), encoding="utf-8")
    out = tmp_path / name
    # The box's KM BOT voice client, as the installer passes it (K1_CLIENT by default).
    client = client or _client_file(tmp_path, K1_CLIENT)
    proc = subprocess.run(
        [sys.executable, str(script), str(seats), str(repo_file), str(out), str(client)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc, out


def test_the_installer_syncs_tools_and_contexts_and_keeps_what_only_the_box_has(tmp_path):
    box = _box_seats(contexts={**BOX_CONTEXTS, "legacy": "Something only this box has."})
    proc, out = _install(tmp_path, box)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    after = json.loads(out.read_text(encoding="utf-8"))
    repo = json.loads(SEAT_FILE.read_text(encoding="utf-8"))
    tce = next(s for s in after["seats"] if s["id"] == "tce")
    assert tce["allowedTools"] == repo["allowedTools"]
    assert tce["contexts"] == {**repo["contexts"], "legacy": "Something only this box has."}
    assert (
        tce["mcpServers"] == box["seats"][1]["mcpServers"]
        and tce["brief"] == box["seats"][1]["brief"]
    )
    assert after["seats"][0] == box["seats"][0], "another app's seat is never touched"
    assert (
        "added ['video']" in proc.stdout
        and "kept as they are on this box ['legacy']" in proc.stdout
    )
    assert "tools 18 -> 23" in proc.stdout

    # Run again on what it wrote: nothing to do, and nothing written.
    again, second = _install(tmp_path, after, name="second.json")
    assert again.returncode == 3, again.stdout + again.stderr
    assert "already current" in again.stdout and not second.exists()


@pytest.mark.parametrize(
    ("change", "why"),
    [
        (lambda r: r["contexts"].update({"Video": "x"}), "not a short lowercase word"),
        (lambda r: r["contexts"].update({"video": "x" * 2001}), "at most 2000 characters"),
        (lambda r: r["contexts"].update({"week": "   "}), "at most 2000 characters"),
        (
            lambda r: r["allowedTools"].append("mcp__other__tce_week"),
            "a server the live seat does not define",
        ),
        (lambda r: r["allowedTools"].append("Bash"), "not an mcp__<server>__<tool> name"),
        (lambda r: r["allowedTools"].extend(f"mcp__tce__t{n}" for n in range(60)), "at most 64"),
    ],
)
def test_the_installer_writes_nothing_the_voice_service_would_refuse(tmp_path, change, why):
    """A seat KM BOT refuses is dropped from the file whole: every TCE call would fail."""
    repo = json.loads(SEAT_FILE.read_text(encoding="utf-8"))
    change(repo)
    proc, out = _install(tmp_path, _box_seats(), repo=repo)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "REFUSED, nothing written" in proc.stdout and why in proc.stdout
    assert not out.exists()


def test_the_installer_holds_the_video_context_until_km_bots_voice_client_can_mute_the_call(tmp_path):
    """1-Oct final review: a TCE deploy before KM BOT's K1 put the video context on the
    box, and the notes sheet then opened an unmuted call that greeted over the video and
    threw on every hold. The context waits for a client with the call's mute and quiet."""
    old = _client_file(tmp_path, OLD_CLIENT)
    proc, out = _install(tmp_path, _box_seats(), client=old)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    tce = next(s for s in json.loads(out.read_text(encoding="utf-8"))["seats"] if s["id"] == "tce")
    assert "video" not in tce["contexts"] and tce["contexts"] == BOX_CONTEXTS
    assert all(f"mcp__tce__{name}" in tce["allowedTools"] for name in VIDEO_TOOLS)
    assert "the video context waits" in proc.stdout and "KM BOT K1" in proc.stdout

    missing, out2 = _install(tmp_path, _box_seats(), client=tmp_path / "no-such-client.js", name="c2.json")
    assert "video" not in json.loads(out2.read_text(encoding="utf-8"))["seats"][1]["contexts"]
    assert "the video context waits" in missing.stdout

    k1, out3 = _install(tmp_path, _box_seats(), client=_client_file(tmp_path, K1_CLIENT), name="c3.json")
    assert "video" in json.loads(out3.read_text(encoding="utf-8"))["seats"][1]["contexts"]
    assert "waits" not in k1.stdout

    # The real client on KM BOT's talk-to-editor branch has it; the box's main before K1 does not.
    real = KMBOT / "web" / "voice-client.js"
    if real.exists():
        mine, out4 = _install(tmp_path, _box_seats(), client=real, name="c4.json")
        assert "video" in json.loads(out4.read_text(encoding="utf-8"))["seats"][1]["contexts"], mine.stdout
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'VOICE_CLIENT_JS=/opt/kmbot/web/voice-client.js' in text
    assert '"$cand" "$VOICE_CLIENT_JS" <<\'PY\'' in text


def test_the_installer_refuses_a_seat_file_with_no_tce_seat(tmp_path):
    box = _box_seats()
    box["seats"] = box["seats"][:1]
    proc, out = _install(tmp_path, box)
    assert proc.returncode == 2 and "no tce seat" in proc.stdout and not out.exists()


def test_the_installers_last_check_is_km_bots_own_module(tmp_path):
    """Before the new file replaces the live one, the voice service's own loader reads it."""
    mod = _kmbot("bin/kmbot-voice-seats.mjs")
    text = INSTALLER.read_text(encoding="utf-8")
    check = text[
        text.index("NODE_CHECK='") + len("NODE_CHECK='") : text.index(
            "\n'\n", text.index("NODE_CHECK='")
        )
    ]
    proc, good = _install(tmp_path, _box_seats())
    assert proc.returncode == 0, proc.stdout
    bad = tmp_path / "bad.json"
    broken = json.loads(good.read_text(encoding="utf-8"))
    broken["seats"][1]["contexts"]["Video"] = "x"
    bad.write_text(json.dumps(broken), encoding="utf-8")

    def verdict(path):
        return subprocess.run(
            ["node", "--input-type=module", "-e", check, str(mod), str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
        )

    ok, refused, missing = verdict(good), verdict(bad), verdict(tmp_path / "nope.json")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "23 tools" in ok.stdout and "video" in ok.stdout
    assert refused.returncode == 2 and "would leave out the tce seat" in refused.stdout
    assert missing.returncode == 2, "a file it cannot read never goes live"


# ------------------------------------------- a scripted call on the real routes
#
# The sheet opens the sitting, pins the paused second and saves his words; the brain's
# tools then read the moment, save the reading, read every note back and make it, all
# answered by the real TCE routes on the test database. Nothing renders: the batch is
# replaced by a recorder, as the batch has its own tests.


@pytest.fixture
async def video_call(editorial_sessionmaker, monkeypatch, tmp_path):
    if shutil.which("node") is None:  # pragma: no cover
        pytest.skip("node is not installed")
    import httpx
    from fastapi import FastAPI
    from pydantic import SecretStr

    from tce.api.routers import editorial as editorial_router
    from tce.api.routers import editorial_workspace as workspace_router
    from tce.api.routers import production as prod
    from tce.db.session import get_db
    from tce.settings import settings
    from tests.unit.test_talk_to_editor import KEY, render_once, seed

    sm = editorial_sessionmaker
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(prod, "session_factory", lambda: sm)

    async def fake_render_edit(src, keep, out, **_kw):
        Path(out).write_bytes(b"edited")
        return Path(out)

    async def fake_size(_src):
        return (1080, 1920)

    monkeypatch.setattr(prod.media, "render_edit", fake_render_edit)
    monkeypatch.setattr(prod.media, "probe_video_size", fake_size)
    monkeypatch.setattr(prod.wordbox, "usable", lambda *_a, **_k: False)
    started: list[uuid.UUID] = []
    monkeypatch.setattr(prod, "start_talk_session", lambda sid, ws_: started.append(sid))

    ws, uid = await seed(sm, tmp_path)
    row = await render_once(sm, ws, uid)
    assert row.status == "edited" and row.render_ref

    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(workspace_router.production_router, prefix="/api/v1")
    app.include_router(prod.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sm

    async def _db():
        async with sm() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    script = ROOT / f"_voice_bridge_{uuid.uuid4().hex[:8]}.mjs"
    script.write_text(BRIDGE, encoding="utf-8")
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("TCE_VOICE_CALL_ID", "KMBOT_VOICE_SESSION", "TCE_VOICE_STATE_DIR")
    }
    proc = await asyncio.create_subprocess_exec(
        "node",
        str(script),
        cwd=str(ROOT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        limit=2**24,
    )
    try:
        ready = json.loads(await asyncio.wait_for(proc.stdout.readline(), 60))
        assert ready["type"] == "ready", ready
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)},
        ) as http:
            world = Live(http, proc)
            world.sm, world.ws, world.uid, world.row, world.started = sm, ws, uid, row, started
            yield world
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        script.unlink(missing_ok=True)


async def _sittings(world):
    from sqlalchemy import select

    from tce.models.editorial_workspace import EditingRequest, EditSession

    async with world.sm() as s:
        sittings = list(
            (
                await s.execute(select(EditSession).where(EditSession.upload_id == world.uid))
            ).scalars()
        )
        notes = list(
            (
                await s.execute(select(EditingRequest).where(EditingRequest.upload_id == world.uid))
            ).scalars()
        )
    return sittings, notes


async def test_live_a_scripted_note_call_pins_reads_saves_reads_back_and_makes_it_once(video_call):
    from tce.production import autoedit

    world = video_call
    uid = str(world.uid)

    # Before his sheet is open, the brain finds nothing, and opens nothing.
    nothing, _ = await world.tool("tce_video_moment", video=uid)
    assert "No notes are open" in nothing
    assert await _sittings(world) == ([], [])

    # The sheet: open the sitting, pin the paused second, save his words.
    opened = (await world.http.post(f"/api/v1/production/recordings/{uid}/talk")).json()
    sid = opened["session_id"]
    pin = await world.http.post(
        f"/api/v1/production/talk/{sid}/notes",
        json={"edit_s": 2.0, "render_ref": world.row.render_ref, "by": "voice"},
    )
    assert pin.status_code == 200, pin.text
    nid = pin.json()["note_id"]
    heard = "the pause after smart drags on, tighten it"
    assert (
        await world.http.patch(f"/api/v1/production/talk/{sid}/notes/{nid}", json={"heard": heard})
    ).status_code == 200

    # The brain: the moment (with his rules), the reading, said back naming the time.
    moment, data = await world.tool("tce_video_moment", video=f"video:{uid}")
    assert moment.startswith('Note at 0:02 on "Call them after the service"'), moment
    assert f'He said: "{heard}".' in moment and "in the edit]" in moment
    assert data["note"]["id"] == nid and data["rules"] == autoedit.editor_skill()
    reading = "At 0:02 you want the pause after smart shorter."
    said, _ = await world.tool("tce_video_note", note=nid, understood=reading)
    assert (
        said
        == "At 0:02: you want the pause after smart shorter. "
        "Saved; nothing changes until you say make it."
    )
    # Live hands the same words over twice: the same note, never a second one.
    again, _ = await world.tool("tce_video_note", note=nid, understood=reading)
    assert again == said
    sittings, notes = await _sittings(world)
    assert len(sittings) == 1 and [(n.id, n.state, n.request, n.understood) for n in notes] == [
        (uuid.UUID(nid), "held", heard, "you want the pause after smart shorter")
    ]
    assert world.started == [], "a note never renders"

    # "That's all, make it": the read-back and its check code, then his yes.
    listed, _ = await world.tool("tce_video_notes", video=uid)
    assert "at 0:02: you want the pause after smart shorter (saved, waiting for make it)" in listed
    back, rb = await world.tool("tce_video_make", video=uid)
    assert '"1 note: at 0:02: you want the pause after smart shorter. One re-render."' in back
    assert world.started == [] and rb["made"] is False
    wrong, _ = await world.tool("tce_video_make", video=uid, confirmed=True, check="000000000000")
    assert "changed since you read them back" in wrong and world.started == []
    made, _ = await world.tool("tce_video_make", video=uid, confirmed=True, check=rb["check"])
    assert made.startswith(
        'Making the new version of "Call them after the service" from 1 note now'
    ), made
    assert world.started == [uuid.UUID(sid)], "one job, started once"
    sittings, _ = await _sittings(world)
    assert sittings[0].state == "thinking" and sittings[0].result["by"] == "voice"
    assert sittings[0].result["notes"] == [nid]

    jobs, _ = await world.tool("tce_jobs")
    assert jobs == (
        'The new version for "Call them after the service" is still being made '
        "(Reading your 1 note on the subscription)."
    )
    # New notes wait until it is made.
    busy, _ = await world.tool("tce_video_moment", video=uid)
    assert "being made into a new version right now" in busy


async def test_live_every_hold_is_pinned_and_his_spoken_instructions_make_one_version_of_his_notes(video_call):
    """1-Oct final review, scripted the way the sheet really works: EVERY hold is pinned
    and saved, including "no, I meant...", "scratch that", "that's all, make it" and the
    yes. Before, the yes changed the check code each time (Make never started), the
    correction hold took the next note's reading, and "make it" went to the batch."""
    world = video_call
    uid = str(world.uid)
    opened = (await world.http.post(f"/api/v1/production/recordings/{uid}/talk")).json()
    sid = opened["session_id"]

    async def hold(edit_s: float, words: str) -> str:
        # The sheet: the pin at the press, his words saved when the voice flushes them,
        # which is when Live hands them to the brain (before the brain's turn).
        pin = await world.http.post(
            f"/api/v1/production/talk/{sid}/notes",
            json={"edit_s": edit_s, "render_ref": world.row.render_ref, "by": "voice"},
        )
        assert pin.status_code == 200, pin.text
        nid = pin.json()["note_id"]
        saved = await world.http.patch(f"/api/v1/production/talk/{sid}/notes/{nid}", json={"heard": words})
        assert saved.status_code == 200, saved.text
        return nid

    first_words = "the pause after smart drags on, tighten it"
    first = await hold(2.0, first_words)
    m, data = await world.tool("tce_video_moment", video=uid, said=first_words)
    assert data["note"]["id"] == first, m
    await world.tool("tce_video_note", note=first, understood="you want the pause after smart shorter")

    correction = await hold(2.1, "no, I meant the pause before smart")
    fixed, _ = await world.tool(
        "tce_video_note", note=first, understood="you want the pause before smart shorter",
        correcting=True, said="no, I meant the pause before smart",
    )
    assert fixed.startswith("At 0:02: you want the pause before smart shorter."), fixed

    # The next note is read at its own second, never at the correction's.
    last_words = "cut the last two words"
    last = await hold(5.0, last_words)
    m, data = await world.tool("tce_video_moment", video=uid, said=last_words)
    assert data["note"]["id"] == last and data["at"]["clock"] == "0:05", m
    await world.tool("tce_video_note", note=last, understood="you want the last two words cut")
    scratch = await hold(5.1, "scratch that")
    await world.tool("tce_video_note", note=last, drop=True, said="scratch that")

    make_it = await hold(5.2, "That's all, make it.")
    back, rb = await world.tool("tce_video_make", video=uid, said="that's all, make it")
    assert '"1 note: at 0:02: you want the pause before smart shorter. One re-render."' in back, back
    yes = await hold(5.2, "Yes.")
    made, _ = await world.tool("tce_video_make", video=uid, confirmed=True, check=rb["check"], said="yes")
    assert made.startswith('Making the new version of "Call them after the service" from 1 note now'), made
    assert world.started == [uuid.UUID(sid)], "one job, started on the first yes"

    sittings, notes = await _sittings(world)
    assert sittings[0].state == "thinking" and sittings[0].result["notes"] == [first]
    state = {str(n.id): n.state for n in notes}
    assert state == {
        first: "held", correction: "rejected", last: "rejected", scratch: "rejected",
        make_it: "rejected", yes: "rejected",
    }, state
    instructions = {str(n.id) for n in notes if (n.result or {}).get("command")}
    assert instructions == {correction, scratch, make_it, yes}
