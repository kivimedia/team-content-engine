"""The agent says "um, sorry, my dog" too (3-Oct review of the two-voice edit).

DECIDED 6 and contract C4: in an agent talk the agent's lines are content, never cut as
asides, retakes or junk, while his own talk to the dogs still goes. The hard case is an
agent line that LOOKS like an aside: it starts with a filler and an apology, names his
dog, and repeats his call to her ("I heard Maple, come here"). Every place that can cut
a word is tried with that line: the rules (no review), the review's answer, Jennifer's
leftover-asides check, and the whole automatic edit. Synthetic data only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from tce.api.routers import production as prod
from tce.llm import LLMUnavailable
from tce.llm.provider import LLMResult
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.production import agent_talks, autoedit, qc
from tce.production.retakes import plan_edit

NAMES = ["Maple", "Rain"]
AGENT_LINE = "Um, sorry, my dog question first. I heard Maple, come here. Is Maple your dog?"
HIS_ASIDE = "Maple, come here!"
# (speaker, line, start second); a word is 0.4 s long, one every 0.5 s.
TALK = [
    ("host", "Tell me why the build failed.", 0.0),
    ("agent", AGENT_LINE, 5.0),
    ("host", HIS_ASIDE, 14.0),
    ("host", "Yes, she is. Now the build.", 17.0),
    ("agent", "Sorry, um, the voice tests failed.", 21.0),
    ("host", "Good, fix them.", 26.0),
]


def heard() -> tuple[list[dict], set[int]]:
    words: list[dict] = []
    agent: set[int] = set()
    for who, line, start in TALK:
        for k, w in enumerate(line.split()):
            if who == "agent":
                agent.add(len(words))
            words.append({"text": w, "start_s": start + k * 0.5, "end_s": start + k * 0.5 + 0.4,
                          "precision": "word"})
    return words, agent


def call(*, with_aside: bool = True) -> list[dict]:
    """The call's own transcript. His call to the dog may or may not be in it."""
    return [
        {"who": "ziv" if who == "host" else "agent", "text": line, "t_ms": int(start * 1000) + 40_000}
        for who, line, start in TALK
        if with_aside or line != HIS_ASIDE
    ]


def span(words, phrase: str, start_at: int = 0) -> tuple[int, int]:
    toks = phrase.split()
    for i in range(start_at, len(words) - len(toks) + 1):
        if [w["text"] for w in words[i : i + len(toks)]] == toks:
            return i, i + len(toks) - 1
    raise AssertionError(phrase)


def kept_text(plan) -> str:
    return plan["kept_text"]


@pytest.mark.parametrize("with_aside", [True, False])
def test_the_voices_put_the_agents_dog_words_with_the_agent_and_his_call_with_him(with_aside):
    words, agent = heard()
    voices = agent_talks.voices(words, call(with_aside=with_aside), "atlas")
    assert voices.known
    assert voices.agent_words == frozenset(agent)
    a, b = span(words, HIS_ASIDE)
    assert all(voices.labels[i] == agent_talks.HOST for i in range(a, b + 1))


def test_without_the_protection_the_rules_would_cut_the_agents_line():
    """The guard is real: the same words, read as one voice, lose the agent's dog line."""
    words, _agent = heard()
    plan = plan_edit(words, [], aside_names=NAMES)
    assert "I heard Maple, come here." not in kept_text(plan)
    assert "Um," not in kept_text(plan)


@pytest.mark.parametrize("with_aside", [True, False])
def test_the_rules_keep_every_word_of_the_agents_line_and_cut_his_call_to_the_dog(with_aside):
    words, _agent = heard()
    voices = agent_talks.voices(words, call(with_aside=with_aside), "atlas")
    plan = plan_edit(words, [], aside_names=NAMES, protected=voices.agent_words)
    kept = kept_text(plan)
    # The agent's line, filler and apology and the dog's name included, all of it.
    assert AGENT_LINE in kept, kept
    assert "Sorry, um, the voice tests failed." in kept
    # His own call to the dog is gone; his lines around it stay.
    assert HIS_ASIDE not in kept and "Yes, she is. Now the build." in kept
    removed = {r["text"]: r["reason"] for r in plan["removed"]}
    assert removed.get(HIS_ASIDE) == "aside", plan["removed"]
    agent_cut = [d for d in plan["dropped"] if d["reason"] != "pause" and "Um" in d["text"]]
    assert agent_cut == []


def test_the_reviews_answer_can_never_take_the_agents_line_but_takes_his_call():
    words, agent = heard()
    voices = agent_talks.voices(words, call(), "atlas")
    um = span(words, "Um, sorry, my dog question first.")
    calls = span(words, "I heard Maple, come here.")
    his = span(words, HIS_ASIDE)
    second_um = span(words, "Sorry, um,")
    removals = [
        {"first": um[0], "last": um[1], "heard": "Um, sorry, my dog question first.", "kind": "false_start",
         "kept_from": -1, "why": "a false start"},
        {"first": calls[0], "last": calls[1], "heard": "I heard Maple, come here.", "kind": "aside",
         "kept_from": -1, "why": "talk to the dog"},
        {"first": second_um[0], "last": second_um[1], "heard": "Sorry, um,", "kind": "junk",
         "kept_from": -1, "why": "filler"},
        {"first": his[0], "last": his[1], "heard": HIS_ASIDE, "kind": "aside", "kept_from": -1,
         "why": "talk to the dog"},
    ]
    valid, notes = autoedit.validate_removals(words, removals, protected=voices.agent_words, protected_name="Atlas")
    assert [v["text"] for v in valid] == [HIS_ASIDE]
    assert sum("those are Atlas's words" in n for n in notes) == 3
    plan = plan_edit(words, [], aside_names=NAMES, removals=valid, protected=voices.agent_words)
    assert AGENT_LINE in plan["kept_text"] and HIS_ASIDE not in plan["kept_text"]
    assert set(agent) <= {w["index"] for w in plan["words"]}


def test_jennifers_check_never_cuts_the_agents_dog_line_but_cuts_his():
    words, _agent = heard()
    voices = agent_talks.voices(words, call(), "atlas")
    keep = [[0.0, 30.0]]  # an edit that kept everything, to see what her check would take out
    kept = qc.kept_on_edit(
        [{"index": i, "text": w["text"], "start": w["start_s"], "end": w["end_s"]} for i, w in enumerate(words)],
        keep,
    )
    calls = span(words, "I heard Maple, come here.")
    his = span(words, HIS_ASIDE)
    answer = {"asides": [
        {"first": calls[0], "last": calls[1], "heard": "I heard Maple, come here.", "why": "talk to the dog"},
        {"first": his[0], "last": his[1], "heard": HIS_ASIDE, "why": "talk to the dog"},
    ]}
    found = qc.check_asides(kept, answer, protected=voices.agent_words)
    assert [p["detail"].split('"')[1] for p in found["problems"]] == [HIS_ASIDE]
    [cut] = found["problems"][0]["fix"]["cut"]
    assert cut == [words[his[0]]["start_s"], words[his[1]]["end_s"]]
    # The reading is told who speaks each line and that the agent's lines are content.
    prompt = qc.asides_prompt(kept, "Topic: Talk with Atlas", voices.speaker_names())
    assert "ATLAS: " in prompt and "HOST: " in prompt


# ---------------------------------------------------------------------------
# The whole automatic edit, with a review that tries to cut the agent's dog line


@pytest.fixture
def wired(monkeypatch, editorial_sessionmaker):
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    monkeypatch.setattr(prod.settings, "production_auto_edit", True)
    answers: dict[str, object] = {}

    async def fake_ask(kind, prompt, system, schema, ws, key, **_opts):
        answer = answers.get(kind)
        if answer is None:
            raise LLMUnavailable("no_worker", "no worker in tests")
        return LLMResult(job_id=uuid.uuid4(), text="", structured=answer, model="claude-opus-5-5")

    async def fake_render(upload_id, ws, attempt, mode):
        async with editorial_sessionmaker() as s:
            row = await prod._load(s, upload_id, ws)
            row.status, row.edited_path = "edited", "/work/projects/alpha-service/edited.mp4"
            await s.commit()

    monkeypatch.setattr(prod, "_ask", fake_ask)
    monkeypatch.setattr(prod, "_run_render", fake_render)
    monkeypatch.setattr(prod, "start_draft_posts", lambda *a, **k: None)
    return {"sm": editorial_sessionmaker, "answers": answers}


async def seed(sm) -> tuple[uuid.UUID, uuid.UUID]:
    ws = uuid.uuid4()
    words, _agent = heard()
    async with sm() as s:
        cand = TopicCandidate(workspace_id=ws, week_start=datetime(2026, 9, 28), moment_ids=[],
                              title="Talk with Atlas, 3 Oct", lesson="", audience="both",
                              public_angle="", gates={}, status="recorded", origin="agent_talk")
        s.add(cand)
        await s.flush()
        up = RecordingUpload(workspace_id=ws, candidate_id=cand.id, original_filename="agent-talk.webm",
                             storage_path="/work/projects/alpha-service/agent-talk.webm",
                             sha256=uuid.uuid4().hex * 2, status="transcribed", transcript=words,
                             duration_s=30.0, source="agent_talk", agent_name="Atlas", call_transcript=call())
        s.add(up)
        await s.commit()
        return ws, up.id


@pytest.mark.parametrize("reviewed", [True, False])
async def test_a_talk_whose_agent_says_um_sorry_my_dog_keeps_it_and_loses_his_call(wired, reviewed):
    words, agent = heard()
    ws, uid = await seed(wired["sm"])
    if reviewed:
        um = span(words, "Um, sorry, my dog question first.")
        calls = span(words, "I heard Maple, come here.")
        his = span(words, HIS_ASIDE)
        wired["answers"][autoedit.REVIEW_JOB] = {
            "removals": [
                {"first": um[0], "last": calls[1], "heard": "Um, sorry, my dog question first. I heard Maple, come here.",
                 "kind": "aside", "kept_from": -1, "why": "talk to the dog"},
                {"first": his[0], "last": his[1], "heard": HIS_ASIDE, "kind": "aside", "kept_from": -1,
                 "why": "talk to the dog"},
            ],
            "corrections": [],
        }
    await prod.auto_edit(uid, ws)
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    plan = row.edit_plan
    assert row.status == "edited"
    assert plan["decided_by"] == ("editor_review" if reviewed else "rules")
    assert AGENT_LINE in plan["kept_text"] and "Sorry, um, the voice tests failed." in plan["kept_text"]
    assert HIS_ASIDE not in plan["kept_text"]
    # Every one of the agent's words is a kept word of the plan.
    assert set(agent) <= {w["index"] for w in plan["words"]}
    if reviewed:
        assert any("those are Atlas's words" in n for n in plan["review"]["notes"])
