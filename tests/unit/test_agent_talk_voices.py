"""An agent talk is a two-person conversation (3-Oct): the agent's lines are content.

The edit of a filmed voice call must never cut the agent's lines as retakes, asides or
junk, while his own talk to the dogs and the dead air still go. These tests line the
recogniser's words up with the call's transcript, then run the review's validation,
the rules and the whole automatic edit (with a fake subscription answer) on a talk.
Synthetic data only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from tce.api.routers import production as prod
from tce.llm import LLMUnavailable
from tce.llm.provider import LLMResult
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.production import agent_talks, autoedit
from tce.production.retakes import plan_edit

# (speaker, line, start second). Each word lasts 0.4 s, one every 0.5 s; between the
# lines, the dead air of a call (one waits while the other thinks).
TALK = [
    ("host", "Let us go through the open sessions.", 0.0),
    ("agent", "Sure. Two are waiting for you. The first one wants to continue to phase three.", 6.0),
    ("host", "Hey, Maple Rain, boy!", 15.0),
    ("host", "Continue to phase three.", 18.0),
    ("agent", "Continue to phase three. Done, I typed it in.", 21.0),
    ("host", "Great, next one.", 27.0),
]


def heard() -> tuple[list[dict], set[int]]:
    """The recogniser's words for TALK, and which of them are the agent's."""
    words: list[dict] = []
    agent: set[int] = set()
    for who, line, start in TALK:
        for k, w in enumerate(line.split()):
            if who == "agent":
                agent.add(len(words))
            words.append({"text": w, "start_s": start + k * 0.5, "end_s": start + k * 0.5 + 0.4,
                          "precision": "word"})
    return words, agent


def call(offset_ms: int = 0, *, dogs: bool = True) -> list[dict]:
    """The call's own transcript: who and when on the call's clock. The call's speech
    recogniser writes his lines a little differently from the recording's."""
    lines = []
    for who, line, start in TALK:
        if who == "host" and "Maple" in line and not dogs:
            continue
        text = line.replace("Let us", "Let's") if who == "host" else line
        lines.append({"who": "ziv" if who == "host" else "agent", "text": text,
                      "t_ms": int(start * 1000) + offset_ms})
    return lines


def text_of(words, indices) -> str:
    return " ".join(words[i]["text"] for i in sorted(indices))


# ---------------------------------------------------------------------------
# Telling the voices apart


@pytest.mark.parametrize("offset_ms", [0, 30_000, -2_500])
def test_the_agents_words_are_found_whatever_the_calls_clock(offset_ms):
    words, agent = heard()
    voices = agent_talks.voices(words, call(offset_ms), "atlas")
    assert voices.known and voices.agent == "Atlas"
    assert voices.agent_words == frozenset(agent), text_of(words, voices.agent_words ^ agent)
    # The call's clock against the recording's, from the words they share.
    assert voices.offset_s == pytest.approx(-offset_ms / 1000, abs=0.6)


def test_a_line_the_call_never_wrote_takes_the_voice_around_it():
    # His talk to the dogs is not in the call's transcript: its words sit between his own
    # lines, so they are his (and the rules may still cut them as an aside).
    words, agent = heard()
    voices = agent_talks.voices(words, call(dogs=False), "atlas")
    maple = next(i for i, w in enumerate(words) if w["text"].startswith("Maple"))
    assert voices.labels[maple] == agent_talks.HOST
    assert voices.agent_words == frozenset(agent)


def test_without_a_call_transcript_every_word_is_kept():
    words, _agent = heard()
    for transcript in (None, [], [{"who": "nobody", "text": "x"}], [{"who": "agent", "text": "zzz qqq"}]):
        voices = agent_talks.voices(words, transcript, "atlas")
        assert voices.known is False
        assert voices.agent_words == frozenset(range(len(words)))


# ---------------------------------------------------------------------------
# The review: what it reads, and what of its answer is used


def test_the_review_reads_who_says_each_line_and_the_conversation_rules():
    words, _agent = heard()
    voices = agent_talks.voices(words, call(), "atlas")
    prompt, system = prod._review_request(words, "Topic: Talk with Atlas, 3 Oct", voices)
    lines = prompt.splitlines()
    assert any(line.startswith("[0:00] HOST: 0:Let") for line in lines), prompt
    assert any(line.startswith("[0:06] ATLAS: 7:Sure.") for line in lines), prompt
    # A line never holds both voices.
    for line in lines:
        assert not ("HOST:" in line and "ATLAS:" in line)
    assert "THIS VIDEO IS A CONVERSATION" in system and "ATLAS is Atlas" in system
    assert "never remove them, as a retake, a false start, an aside or junk" in system
    # A walk's review is unchanged by any of this.
    walk_prompt, walk_system = prod._review_request(words, "Topic: A walk")
    assert "HOST:" not in walk_prompt and "CONVERSATION" not in walk_system
    assert prod._review_key(uuid.uuid4(), prompt, system) != prod._review_key(uuid.uuid4(), walk_prompt, walk_system)


def _span(words, phrase: str, start_at: int = 0) -> tuple[int, int]:
    toks = phrase.split()
    for i in range(start_at, len(words) - len(toks) + 1):
        if [w["text"] for w in words[i : i + len(toks)]] == toks:
            return i, i + len(toks) - 1
    raise AssertionError(phrase)


def test_no_removal_takes_the_agents_words():
    words, agent = heard()
    dogs = _span(words, "Hey, Maple Rain, boy!")
    his = _span(words, "Continue to phase three.")
    theirs = _span(words, "Continue to phase three.", his[1] + 1)
    great = _span(words, "Great, next one.")
    removals = [
        {"first": dogs[0], "last": dogs[1], "heard": "Hey, Maple Rain, boy!", "kind": "aside",
         "kept_from": -1, "why": "the dogs"},
        # The review took the agent's answer for a retake of his line.
        {"first": theirs[0], "last": theirs[1], "heard": "Continue to phase three.", "kind": "retake",
         "kept_from": his[0], "why": "said twice"},
        # A junk span that runs from the agent's last words into his.
        {"first": great[0] - 2, "last": great[0], "heard": "it in. Great,", "kind": "junk",
         "kept_from": -1, "why": "?"},
    ]
    # And it took his line for a take of the agent's answer.
    removals.append({"first": his[0], "last": his[1], "heard": "Continue to phase three.", "kind": "retake",
                     "kept_from": theirs[0], "why": "said twice"})
    valid, notes = autoedit.validate_removals(words, removals, protected=agent, protected_name="Atlas")
    texts = [v["text"] for v in valid]
    assert texts == ["Hey, Maple Rain, boy!", "Great,"], texts
    assert any("those are Atlas's words" in n for n in notes)
    assert any("kept Atlas's words inside" in n for n in notes)
    assert any("Atlas's answer, not his line said again" in n for n in notes)
    # Without the protection the same answer would cut the agent's answer and his line.
    unguarded, _ = autoedit.validate_removals(words, removals)
    assert [v["text"] for v in unguarded].count("Continue to phase three.") == 2


# ---------------------------------------------------------------------------
# The rules (no review): one of his turns at a time


def test_the_rules_never_take_the_agents_answer_for_his_retake():
    words, agent = heard()
    names = ["Maple", "Rain"]
    # The bug this guards: without the voices, his line is cut as a retake of the agent's.
    plain = plan_edit(words, [], aside_names=names)
    assert plain["kept_text"].count("Continue to phase three.") == 1
    plan = plan_edit(words, [], aside_names=names, protected=agent)
    kept = plan["kept_text"]
    assert kept.count("Continue to phase three.") == 2  # his line and the agent's answer
    assert "Sure. Two are waiting for you." in kept and "Done, I typed it in." in kept
    assert "Maple" not in kept  # his talk to the dogs still goes
    assert {r["reason"] for r in plan["removed"]} == {"aside"}
    # Dead air between the turns is not kept: the 2.6 s before the agent answers is cut.
    first_end = words[_span(words, "Let us go through the open sessions.")[1]]["end_s"]
    assert not any(s < first_end + 1.0 < e for s, e in plan["keep"])
    assert any(d["reason"] == "pause" and d["start"] < first_end + 1.0 < d["end"] for d in plan["dropped"])
    # His own request can still cut the agent's words.
    theirs = _span(words, "Done, I typed it in.")
    cut = plan_edit(words, [], aside_names=names, protected=agent,
                    overrides={"cut": [[words[theirs[0]]["start_s"], words[theirs[1]]["end_s"]]]})
    assert "Done, I typed it in." not in cut["kept_text"]


def test_segment_timings_in_a_talk_keep_every_line():
    rows = [{"text": line, "start_s": float(start), "end_s": float(start) + 3.0} for _w, line, start in TALK]
    rows[4]["text"] = rows[3]["text"]  # the agent says his line back
    plan = plan_edit(rows, [], protected={4})
    assert all(u["kept"] for u in plan["units"])


# ---------------------------------------------------------------------------
# The whole automatic edit of a talk, with a fake subscription answer


@pytest.fixture
def wired(monkeypatch, editorial_sessionmaker):
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    monkeypatch.setattr(prod.settings, "production_auto_edit", True)
    asked: list[tuple[str, str, str]] = []
    answers: dict[str, object] = {}

    async def fake_ask(kind, prompt, system, schema, ws, key, **_opts):
        asked.append((kind, prompt, system))
        answer = answers.get(kind)
        if answer is None:
            raise LLMUnavailable("no_worker", "no worker in tests")
        return LLMResult(job_id=uuid.uuid4(), text="", structured=answer, model="claude-opus-5-5")

    async def fake_render(upload_id, ws, attempt, mode):
        async with editorial_sessionmaker() as s:
            row = await prod._load(s, upload_id, ws)
            row.status, row.edited_path = "edited", "/tmp/edited.mp4"
            await s.commit()

    monkeypatch.setattr(prod, "_ask", fake_ask)
    monkeypatch.setattr(prod, "_run_render", fake_render)
    monkeypatch.setattr(prod, "start_draft_posts", lambda *a, **k: None)
    return {"sm": editorial_sessionmaker, "asked": asked, "answers": answers}


async def seed_talk(sm, transcript) -> tuple[uuid.UUID, uuid.UUID]:
    ws = uuid.uuid4()
    words, _agent = heard()
    async with sm() as s:
        cand = TopicCandidate(workspace_id=ws, week_start=datetime(2026, 9, 28), moment_ids=[],
                              title="Talk with Atlas, 3 Oct", lesson="", audience="both",
                              public_angle="", gates={}, status="recorded", origin="agent_talk")
        s.add(cand)
        await s.flush()
        up = RecordingUpload(workspace_id=ws, candidate_id=cand.id, original_filename="agent-talk.webm",
                             storage_path="/tmp/agent-talk.webm", sha256=uuid.uuid4().hex * 2,
                             status="transcribed", transcript=words, duration_s=30.0,
                             source="agent_talk", agent_name="Atlas", call_transcript=transcript)
        s.add(up)
        await s.commit()
        return ws, up.id


async def test_a_talk_edits_itself_keeping_the_agents_lines(wired):
    words, agent = heard()
    ws, uid = await seed_talk(wired["sm"], call())
    dogs = _span(words, "Hey, Maple Rain, boy!")
    his = _span(words, "Continue to phase three.")
    theirs = _span(words, "Continue to phase three.", his[1] + 1)
    wired["answers"][autoedit.REVIEW_JOB] = {
        "removals": [
            {"first": dogs[0], "last": dogs[1], "heard": "Hey, Maple Rain, boy!", "kind": "aside",
             "kept_from": -1, "why": "the dogs"},
            {"first": his[0], "last": his[1], "heard": "Continue to phase three.", "kind": "retake",
             "kept_from": theirs[0], "why": "said twice"},
            {"first": theirs[0], "last": theirs[1], "heard": "Continue to phase three.", "kind": "retake",
             "kept_from": his[0], "why": "said twice"},
        ],
        "corrections": [],
    }
    await prod.auto_edit(uid, ws)
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    plan = row.edit_plan
    assert row.status == "edited" and plan["decided_by"] == "editor_review"
    kept = plan["kept_text"]
    assert "Maple" not in kept  # his aside to the dogs is cut
    assert "Sure. Two are waiting for you." in kept and "Done, I typed it in." in kept
    # Both of the review's attempts on the exchange were refused, and said so: the agent's
    # answer is not a retake, and his line answered by it is not one either.
    assert kept.count("Continue to phase three.") == 2
    notes = plan["review"]["notes"]
    assert any("those are Atlas's words" in n for n in notes), notes
    assert any("Atlas's answer, not his line said again" in n for n in notes), notes
    assert [r["reason"] for r in plan["removed"]] == ["aside"]
    assert plan["voices"]["agent"] == "Atlas" and plan["voices"]["agent_words"] == len(agent)
    assert plan["voices"]["known"] is True
    kind, prompt, system = wired["asked"][0]
    assert kind == autoedit.REVIEW_JOB and "ATLAS:" in prompt and "THIS VIDEO IS A CONVERSATION" in system


async def test_a_talk_with_no_worker_goes_out_on_the_rules_and_keeps_both_voices(wired):
    ws, uid = await seed_talk(wired["sm"], call())
    await prod.auto_edit(uid, ws)  # no answer registered: the rules decide
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    kept = row.edit_plan["kept_text"]
    assert row.status == "edited" and row.edit_plan["decided_by"] == "rules"
    assert kept.count("Continue to phase three.") == 2 and "Maple" not in kept


async def test_a_talk_whose_call_sent_no_transcript_cuts_nothing_but_pauses(wired):
    ws, uid = await seed_talk(wired["sm"], [])
    await prod.auto_edit(uid, ws)
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    words, _agent = heard()
    assert row.edit_plan["kept_text"] == " ".join(w["text"] for w in words)
    assert row.edit_plan["voices"]["known"] is False
