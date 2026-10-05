"""A lane workspace's own script writer (5-Oct, Matan, phase 5).

The owner's packet prompt (Ziv, English, coaching, "his own first-person experience")
never runs for a lane workspace; its scripts are walk-and-talk lines in his voice, a
behind_scenes script is questions around HIS memory with a [הסיפור שלך כאן] slot, and no
lane explains a method. Owner workspaces write packets exactly as before. Synthetic data.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

import tce.llm
from tce.editorial import lane_packets, packets
from tce.llm import LLMResult
from tce.models.editorial import EvidenceSource, RecordingPacket, TopicCandidate
from tce.settings import settings

MATAN = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
MOMENT = "22222222-2222-2222-2222-222222222222"
SLOT = "[הסיפור שלך כאן]"


@pytest.fixture
def lanes(monkeypatch):
    monkeypatch.setattr(settings, "workspace_lane_profiles", f"{MATAN}:performer", raising=False)
    monkeypatch.setattr(settings, "workspace_languages", f"{MATAN}:he", raising=False)


def behind_scenes(**over) -> dict:
    phrases = [
        "מה עובר על מנטליסט רגע לפני שהוא עולה לבמה?",
        "כולם רואים את הרגע שבו הקהל צועק.",
        "אף אחד לא רואה את החמש דקות שלפני.",
        "מה הרגשת בפעם הראשונה שהקהל לא הגיב?",
        SLOT,
        "ומה למדת מזה על קהל ישראלי?",
        "אולי זה בדיוק מה שהופך מופע לחוויה.",
    ]
    data = {
        "bullets": [
            "הרגע לפני העלייה לבמה",
            "מה הקהל רואה",
            "מה הקהל לא רואה",
            "הסיפור שלך",
            "מה למדת",
        ],
        "script_phrases": phrases,
        "facebook_post": "מה עובר על מנטליסט חמש דקות לפני שהוא עולה לבמה?",
        "interviewer_prompt": "ספר על הפעם הראשונה שהקהל לא הגיב: מה הרגשת?",
        "hook_options": [
            {"id": "h1", "text": phrases[0], "question": "מה קורה מאחורי הקלעים?", "payoff_phrase_id": "p005",
             "moment_ids": [MOMENT], "rationale": "שאלה פשוטה"},
            {"id": "h2", "text": "הרגע הכי מפחיד במופע הוא לא על הבמה.", "question": "איפה?",
             "payoff_phrase_id": "p003", "moment_ids": [MOMENT], "rationale": "טענה"},
            {"id": "h3", "text": "כל מנטליסט מכיר את השקט הזה.", "question": "איזה שקט?",
             "payoff_phrase_id": "p004", "moment_ids": [MOMENT], "rationale": "סקרנות"},
        ],
        "selected_hook_id": "h1",
        "beats": [
            {"id": f"b{i + 1:02d}", "label": b, "bullet_index": i, "start_phrase_id": s, "end_phrase_id": e}
            for i, (b, s, e) in enumerate(
                zip(
                    ["הרגע", "רואים", "לא רואים", "הסיפור", "למדת"],
                    ["p001", "p002", "p003", "p004", "p006"],
                    ["p001", "p002", "p003", "p005", "p007"],
                    strict=True,
                )
            )
        ],
        "self_check": {"one_idea": True, "no_invented_memory": True},
    }
    data.update(over)
    if "script_phrases" in over:
        data["hook_options"][0]["text"] = data["script_phrases"][0]
    return data


async def make_lane_candidate(session, ws, kind="story_seed"):
    src = EvidenceSource(
        workspace_id=ws, source_kind=kind, external_id=str(uuid.uuid4()), version_hash="c" * 64,
        payload_private={},
    )
    session.add(src)
    await session.flush()
    c = TopicCandidate(
        workspace_id=ws, week_start=datetime(2026, 10, 5), moment_ids=[MOMENT],
        title="הרגע לפני הבמה", lesson="מה קורה רגע לפני", audience="event_owners",
        public_angle="מאחורי הקלעים", gates={}, status="selected",
        citations_private=[{"moment_id": MOMENT, "source_id": str(src.id), "source_kind": kind,
                            "excerpt_private": "seed: a moment before going on stage"}],
    )
    session.add(c)
    await session.commit()
    return c


@pytest.fixture
def fake_llm(monkeypatch):
    state = {"output": behind_scenes(), "calls": []}

    async def fake_complete(req, *, wait_timeout_s=None, requeue_failed=False):
        state["calls"].append(req)
        return LLMResult(job_id=uuid.uuid4(), text="", structured=copy.deepcopy(state["output"]),
                         model="claude-opus-5-5")

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    return state


# ---------------------------------------------------------------- the writer


async def test_a_lane_workspace_is_written_by_its_own_writer_never_the_owners(
    editorial_sessionmaker, fake_llm, lanes
):
    async with editorial_sessionmaker() as s:
        c = await make_lane_candidate(s, MATAN)
    out = await packets.build_packet(editorial_sessionmaker, MATAN, c.id)
    assert out.status in ("ready", "issues"), out.errors
    req = fake_llm["calls"][0]
    assert req.system != packets.SYSTEM_PROMPT and "Ziv" not in req.system
    assert "behind_scenes" in req.system and SLOT in req.system
    assert req.prompt_version == lane_packets.PROMPT_VERSION and req.workspace_id == MATAN
    assert req.messages[0]["content"].startswith("PACKET REQUEST: ")
    p = out.packet
    assert SLOT in p["script_phrases"] and p["linkedin_post"] == ""
    assert p["prompt_version"] == lane_packets.PROMPT_VERSION
    # The language line is added when the job is stored (localize_request).
    from tce.llm.provider import HEBREW_STYLE, localize_request

    assert HEBREW_STYLE in localize_request(req).system


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("פעם אחת בחתונה הופעתי מול אלף איש.", "narrates an event"),
        ("אני זוכר את הכלה שבכתה.", "narrates an event"),
    ],
)
async def test_a_behind_scenes_script_never_invents_his_memory(
    editorial_sessionmaker, fake_llm, lanes, line, why
):
    phrases = behind_scenes()["script_phrases"]
    phrases[2] = line
    fake_llm["output"] = behind_scenes(script_phrases=phrases)
    async with editorial_sessionmaker() as s:
        c = await make_lane_candidate(s, MATAN)
    out = await packets.build_packet(editorial_sessionmaker, MATAN, c.id)
    assert out.status == "failed" and any(why in e for e in out.errors), out.errors
    async with editorial_sessionmaker() as s:
        assert (await s.execute(select(RecordingPacket))).scalars().first() is None


async def test_a_behind_scenes_script_keeps_one_slot_for_his_story(editorial_sessionmaker, fake_llm, lanes):
    phrases = [p for p in behind_scenes()["script_phrases"] if p != SLOT] + ["וזה הכל להיום."]
    fake_llm["output"] = behind_scenes(script_phrases=phrases)
    async with editorial_sessionmaker() as s:
        c = await make_lane_candidate(s, MATAN)
    out = await packets.build_packet(editorial_sessionmaker, MATAN, c.id)
    assert out.status == "failed" and any("exactly one line" in e for e in out.errors), out.errors


def test_lane_rules_in_code():
    clean = behind_scenes()
    clean["linkedin_post"] = ""
    assert lane_packets.lane_errors(clean, "behind_scenes") == []
    method = copy.deepcopy(clean)
    method["script_phrases"][1] = "הסוד הוא שהוא ראה את הקלף מראש."
    assert any("how an effect is done" in e for e in lane_packets.lane_errors(method, "magic_clip"))
    two = copy.deepcopy(clean)
    two["script_phrases"][1] = "זה מטורף. ואז כולם צחקו."
    assert any("more than one sentence" in e for e in lane_packets.lane_errors(two, "magic_clip"))
    money = copy.deepcopy(clean)
    money["facebook_post"] = "המחיר של מופע כזה הוא 5000 ₪"
    assert any("money" in e for e in lane_packets.lane_errors(money, "trend_reaction"))
    ask = copy.deepcopy(clean)
    ask["facebook_post"] = "כתבו לי בתגובות מה דעתכם"
    assert any("call to action" in e for e in lane_packets.lane_errors(ask, "trend_reaction"))
    # "What I would change" is his reaction, not an invented event (magic_clip).
    would = copy.deepcopy(clean)
    would["script_phrases"][1] = "הייתי משנה את הסוף לקהל ישראלי."
    assert lane_packets.lane_errors(would, "magic_clip") == []


def test_each_lane_has_its_own_brief_and_the_magic_lane_never_explains():
    p = None
    assert "NEVER explain, hint at or guess how it is done" in lane_packets.system_prompt("magic_clip", p)
    assert "his reaction".lower() in lane_packets.system_prompt("trend_reaction", p).lower()
    for lane in ("trend_reaction", "magic_clip", "behind_scenes"):
        text = lane_packets.system_prompt(lane, p)
        assert "Ziv" not in text and "one spoken sentence per line" in text


async def test_owner_openings_tools_are_refused_for_a_lane_workspace(editorial_sessionmaker, lanes):
    out = await packets.more_hook_options(editorial_sessionmaker, MATAN, uuid.uuid4())
    assert out.status == "invalid" and "own script writer" in (out.detail or "")
    out = await packets.voice_pass(editorial_sessionmaker, MATAN, uuid.uuid4())
    assert out.status == "invalid" and "own script writer" in (out.detail or "")


async def test_choosing_another_opening_works_on_a_lane_script(editorial_sessionmaker, fake_llm, lanes):
    async with editorial_sessionmaker() as s:
        c = await make_lane_candidate(s, MATAN)
    out = await packets.build_packet(editorial_sessionmaker, MATAN, c.id)
    async with editorial_sessionmaker() as s:
        clone = await packets.choose_hook(s, MATAN, uuid.UUID(out.packet["id"]), "h2")
        await s.commit()
    assert clone.script_phrases[0] == "הרגע הכי מפחיד במופע הוא לא על הבמה." and clone.linkedin_post == ""


async def test_a_lane_workspace_never_resumes_an_owner_writer_job(editorial_sessionmaker, fake_llm, lanes):
    from tce.models.llm_job import LLMJob

    async with editorial_sessionmaker() as s:
        c = await make_lane_candidate(s, MATAN)
        job = LLMJob(
            job_type=packets.JOB_TYPE, agent_name=packets.AGENT_NAME, workspace_id=MATAN, run_id=c.id,
            status="succeeded", idempotency_key="k", input_hash="h", prompt_version=packets.PROMPT_VERSION,
            policy_model="claude-opus-5-5", request_json={"messages": [{"role": "user", "content": "PACKET REQUEST: x"}]},
        )
        s.add(job)
        await s.commit()
        job_id = job.id
    out = await packets.build_packet(editorial_sessionmaker, MATAN, c.id, resume_job_id=job_id)
    assert out.status == "failed" and "owner's writer" in (out.detail or "") and not fake_llm["calls"]


# ---------------------------------------------------------------- owners, as before


async def test_owner_packets_are_written_exactly_as_before(editorial_sessionmaker, monkeypatch, lanes):
    from tests.unit.test_editorial_packets import good_output, make_candidate

    calls: list = []

    async def fake_complete(req, *, wait_timeout_s=None, requeue_failed=False):
        calls.append(req)
        return LLMResult(job_id=uuid.uuid4(), text="", structured=good_output(), model="claude-opus-5-5")

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        c = await make_candidate(s, ws)
    out = await packets.build_packet(editorial_sessionmaker, ws, c.id)
    assert out.status == "ready"
    req = calls[0]
    assert req.system == packets.SYSTEM_PROMPT and req.output_schema == packets.OUTPUT_SCHEMA
    assert (req.agent_name, req.prompt_version) == (packets.AGENT_NAME, packets.PROMPT_VERSION)
    assert out.packet["prompt_version"] == packets.PROMPT_VERSION and out.packet["linkedin_post"]
    with pytest.raises(packets.PacketValidationError, match="linkedin_post is required"):
        bad = good_output()
        bad["linkedin_post"] = ""
        packets.validate_packet_output(bad)


# Review 5-Oct: Hebrew glues one-letter prefixes (ו ש כ ב ה ל מ) onto the word, so
# "כשהופעתי" and "והסוד" slipped past checks that only matched the bare word.
@pytest.mark.parametrize(
    "lane,line",
    [
        ("trend_reaction", "כשהופעתי בחתונה בהרצליה כולם צחקו."),
        ("trend_reaction", "ופעם אחת זה קרה באמצע הריקוד."),
        ("trend_reaction", "באירוע שהופעתי בו כולם עמדו."),
        ("magic_clip", "והסוד הוא שהקלף כבר בכיס."),
        ("magic_clip", "הטריק הוא שהקלף כבר בכיס שלו."),
        ("magic_clip", "יש לו גימיק בתוך הארנק."),
        ("behind_scenes", "כשהייתי בחתונה ההיא כולם שתקו?"),
        ("behind_scenes", "וראיתי את הכלה בוכה?"),
    ],
)
def test_hebrew_prefixes_never_hide_an_event_or_a_method(lane, line):
    clean = behind_scenes()
    clean["linkedin_post"] = ""
    clean["script_phrases"][1] = line
    assert lane_packets.lane_errors(clean, lane), line


@pytest.mark.parametrize(
    "lane,line",
    [
        ("magic_clip", "הייתי משנה את הסוף לקהל ישראלי."),
        ("magic_clip", "איך הוא עשה את זה בכלל?"),
        ("trend_reaction", "זה היה עובד בבר מצווה בישראל."),
    ],
)
def test_his_reactions_stay_legal(lane, line):
    clean = behind_scenes()
    clean["linkedin_post"] = ""
    clean["script_phrases"][1] = line
    assert lane_packets.lane_errors(clean, lane) == []


def test_a_post_with_a_prefixed_method_word_gets_a_note():
    from tce.production import publishing

    flagged = publishing.copy_problems({"instagram": {"caption": "והסוד הוא שהקלף בכיס"}})
    assert "instagram" in flagged
