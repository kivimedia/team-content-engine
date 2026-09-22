"""Conversation: the assistant may discuss anything and change nothing.

The plan's "Conversation" acceptance tests. The failure they prevent is the one
that makes a thinking-partner unusable - it edits your topic because you were
thinking out loud - so the sharpest test here is that discuss mode produces no
mutation even when the model tries to hand one over.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from tce.editorial import briefs, conversation
from tce.editorial.conversation import ConversationError
from tce.llm import LLMResult, LLMUnavailable
from tce.models.editorial import TopicCandidate
from tce.models.editorial_workspace import EditorialChangeSet

WEEK = datetime(2026, 9, 21)


def gates() -> dict:
    return {
        k: {"pass": True, "reason": "y"}
        for k in (
            "small_service_business",
            "coach_or_event_owner_relevance",
            "concrete_supported_substance",
            "connects_to_ziv_work",
        )
    }


async def make_topic(session, ws, title="Your AI should know I will from I did"):
    row = TopicCandidate(
        workspace_id=ws,
        week_start=WEEK,
        moment_ids=[str(uuid.uuid4())],
        title=title,
        lesson="A report that mixes intention with completion is not a report.",
        audience="coaches",
        reasons_to_care=["they manage agents the same way"],
        public_angle="Manage an agent like a person.",
        gates=gates(),
        citations_private=[
            {
                "moment_id": str(uuid.uuid4()),
                "source_kind": "fathom_meeting",
                "title": "A call",
                "url_private": "https://fathom.video/share/SECRET-TOKEN",
            }
        ],
        status="proposed",
        origin="selector",
        freshness_role="evergreen",
    )
    session.add(row)
    await session.flush()
    await briefs.ensure_brief(session, ws, row)
    await session.commit()
    return row


def fake_llm(monkeypatch, payload, *, captured=None):
    """Stand in for the desktop worker. Records the prompt it was given."""

    async def _complete(request, **kwargs):
        if captured is not None:
            captured["prompt"] = request.messages[0]["content"]
            captured["system"] = request.system
        return LLMResult(
            job_id=uuid.uuid4(),
            text="",
            structured=payload,
            model="claude-opus-5",
            receipt={},
            input_tokens=10,
            output_tokens=10,
        )

    monkeypatch.setattr(conversation._llm, "complete", _complete)


async def change_sets(session, ws):
    from sqlalchemy import select

    result = await session.execute(
        select(EditorialChangeSet).where(EditorialChangeSet.workspace_id == ws)
    )
    return list(result.scalars().all())


# ------------------------------------------------------------------ threads


async def test_one_thread_per_object_however_often_it_is_opened(editorial_session):
    ws = uuid.uuid4()
    topic = await make_topic(editorial_session, ws)

    first = await conversation.ensure_thread(
        editorial_session, ws, context_type="topic", context_id=topic.id
    )
    second = await conversation.ensure_thread(
        editorial_session, ws, context_type="topic", context_id=topic.id
    )
    await editorial_session.commit()

    assert first.id == second.id


async def test_a_turn_is_stored_before_the_model_is_called(editorial_session):
    """A crash between the tap and the worker must leave "still thinking", not nothing."""
    ws = uuid.uuid4()
    topic = await make_topic(editorial_session, ws)
    thread = await conversation.ensure_thread(
        editorial_session, ws, context_type="topic", context_id=topic.id
    )

    editor, assistant = await conversation.post_message(
        editorial_session, ws, thread, text="Is this actually about AI?", mode="discuss"
    )
    await editorial_session.commit()

    assert editor.status == "complete"
    assert assistant.status == "queued"
    assert assistant.text == ""
    assert "PC worker" in assistant.status_detail
    messages = await conversation.list_messages(editorial_session, ws, thread.id)
    assert [m.seq for m in messages] == [1, 2]


async def test_an_empty_message_is_refused(editorial_session):
    ws = uuid.uuid4()
    topic = await make_topic(editorial_session, ws)
    thread = await conversation.ensure_thread(
        editorial_session, ws, context_type="topic", context_id=topic.id
    )
    with pytest.raises(ConversationError) as caught:
        await conversation.post_message(editorial_session, ws, thread, text="   ", mode="discuss")
    assert caught.value.code == "empty"


# -------------------------------------------------------------- the contract


async def test_discussing_produces_no_proposal_even_if_the_model_returns_one(
    editorial_sessionmaker, monkeypatch
):
    """The single most important test in this file.

    A model that helpfully hands back an edit during a "what do you think"
    conversation must not be able to create a proposal. If it can, every sentence
    he types becomes risky and he stops thinking out loud in front of it.
    """
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        topic = await make_topic(s, ws)
        thread = await conversation.ensure_thread(
            s, ws, context_type="topic", context_id=topic.id
        )
        _, assistant = await conversation.post_message(
            s, ws, thread, text="I wonder if the point is really about management", mode="discuss"
        )
        await s.commit()
        thread_id, message_id = thread.id, assistant.id

    fake_llm(
        monkeypatch,
        {
            "reply": "It is about management, yes.",
            "proposal": {
                "summary": "Rewrite the point",
                "operations": [{"field": "big_idea", "after": "It is about management."}],
            },
        },
    )
    await conversation.run_turn(editorial_sessionmaker, ws, thread_id, message_id)

    async with editorial_sessionmaker() as s:
        messages = await conversation.list_messages(s, ws, thread_id)
        reply = messages[-1]
        assert reply.status == "complete"
        assert reply.text == "It is about management, yes."
        assert reply.change_set_id is None
        assert await change_sets(s, ws) == []
        current = await briefs.latest_version(s, ws, topic.id)
        assert current.version == 1


async def test_propose_mode_creates_a_proposal_that_is_still_inert(
    editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        topic = await make_topic(s, ws)
        thread = await conversation.ensure_thread(
            s, ws, context_type="topic", context_id=topic.id
        )
        _, assistant = await conversation.post_message(
            s, ws, thread, text="Make the point about management", mode="propose"
        )
        await s.commit()
        thread_id, message_id, topic_id = thread.id, assistant.id, topic.id

    fake_llm(
        monkeypatch,
        {
            "reply": "Here is what I would change.",
            "proposal": {
                "summary": "Make the point about management",
                "rationale": "The AI angle is the example, not the lesson.",
                "operations": [
                    {
                        "field": "big_idea",
                        "after": "Manage an agent the way you manage a person.",
                        "rationale": "Says the actual lesson.",
                    }
                ],
            },
        },
    )
    await conversation.run_turn(editorial_sessionmaker, ws, thread_id, message_id)

    async with editorial_sessionmaker() as s:
        messages = await conversation.list_messages(s, ws, thread_id)
        reply = messages[-1]
        assert reply.change_set_id is not None
        sets = await change_sets(s, ws)
        assert len(sets) == 1
        assert sets[0].state == "proposed"
        assert sets[0].origin == "conversation"
        # Proposed is not applied. The topic has not moved.
        current = await briefs.latest_version(s, ws, topic_id)
        assert current.version == 1


async def test_a_proposal_naming_a_field_that_does_not_exist_is_caught(
    editorial_sessionmaker, monkeypatch
):
    """The model gets no private door: it goes through the same validation."""
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        topic = await make_topic(s, ws)
        thread = await conversation.ensure_thread(
            s, ws, context_type="topic", context_id=topic.id
        )
        _, assistant = await conversation.post_message(
            s, ws, thread, text="change the gates", mode="propose"
        )
        await s.commit()
        thread_id, message_id = thread.id, assistant.id

    fake_llm(
        monkeypatch,
        {
            "reply": "Doing that.",
            "proposal": {
                "summary": "Edit the gates",
                "operations": [{"field": "gates", "after": "all pass"}],
            },
        },
    )
    await conversation.run_turn(editorial_sessionmaker, ws, thread_id, message_id)

    async with editorial_sessionmaker() as s:
        sets = await change_sets(s, ws)
        assert len(sets) == 1
        assert sets[0].state == "invalid"
        assert sets[0].validation["ok"] is False


async def test_no_worker_leaves_the_turn_queued_and_says_so(
    editorial_sessionmaker, monkeypatch
):
    """Waiting for capacity is not a failure. The worker will get to it."""
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        topic = await make_topic(s, ws)
        thread = await conversation.ensure_thread(
            s, ws, context_type="topic", context_id=topic.id
        )
        _, assistant = await conversation.post_message(
            s, ws, thread, text="what do you think", mode="discuss"
        )
        await s.commit()
        thread_id, message_id = thread.id, assistant.id

    async def _unavailable(request, **kwargs):
        raise LLMUnavailable("waiting_capacity", "no capacity", job_id=uuid.uuid4())

    monkeypatch.setattr(conversation._llm, "complete", _unavailable)
    await conversation.run_turn(editorial_sessionmaker, ws, thread_id, message_id)

    async with editorial_sessionmaker() as s:
        reply = (await conversation.list_messages(s, ws, thread_id))[-1]
        assert reply.status == "queued"
        assert "capacity" in reply.status_detail.lower()


# ------------------------------------------------------------------ privacy


async def test_the_model_never_sees_a_private_share_url(
    editorial_sessionmaker, monkeypatch
):
    """A tokenized Fathom link is a credential, and a prompt is somewhere it can leak."""
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        topic = await make_topic(s, ws)
        thread = await conversation.ensure_thread(
            s, ws, context_type="topic", context_id=topic.id
        )
        _, assistant = await conversation.post_message(
            s, ws, thread, text="what is this resting on", mode="discuss"
        )
        await s.commit()
        thread_id, message_id = thread.id, assistant.id

    captured: dict = {}
    fake_llm(monkeypatch, {"reply": "On one of your calls.", "proposal": None},
             captured=captured)
    await conversation.run_turn(editorial_sessionmaker, ws, thread_id, message_id)

    assert "SECRET-TOKEN" not in captured["prompt"]
    assert "fathom.video/share" not in captured["prompt"]


async def test_the_prompt_tells_a_discuss_turn_it_may_not_propose(
    editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        topic = await make_topic(s, ws)
        thread = await conversation.ensure_thread(
            s, ws, context_type="topic", context_id=topic.id
        )
        _, assistant = await conversation.post_message(
            s, ws, thread, text="thoughts?", mode="discuss"
        )
        await s.commit()
        thread_id, message_id = thread.id, assistant.id

    captured: dict = {}
    fake_llm(monkeypatch, {"reply": "ok", "proposal": None}, captured=captured)
    await conversation.run_turn(editorial_sessionmaker, ws, thread_id, message_id)

    assert "MODE: Discuss" in captured["prompt"]
    assert "proposal: null" in captured["prompt"]
    # And the brief fields are offered by their exact keys, so it cannot invent one.
    assert "why_this_is_yours" in captured["prompt"]
