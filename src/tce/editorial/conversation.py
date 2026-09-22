"""Contextual editorial conversation.

The assistant may discuss anything. It may change nothing. The only path from
something it said to something stored is a change set a human accepted, which is
the contract `changes.py` already enforces and which the topic room has been
exercising by hand since day one.

Three modes, and the difference between them is the whole design:

    discuss   conversation only. No proposal is produced, whatever he says.
    propose   the reply may carry a change set. It is still inert.
    review    not a model call at all - the client showing an existing proposal.

Nothing is applied from exploratory speech. "I wonder if the point is really
about X" must never rewrite the point, because if it can, every sentence becomes
risky to say and he stops thinking out loud in front of it.

Latency is a design constraint, not an accident. Every model call is a row in
`llm_jobs` leased by the desktop worker at roughly one Opus job a minute, so a
turn cannot be awaited inside a request. The editor's message is stored
immediately, the assistant's is stored as `queued` with its job id, and the page
polls. That queued row is also what lets a refresh restore a pending turn instead
of losing it.

Privacy: the model receives the object's public-safe editorial representation and
bounded excerpts that already passed the safety pass. It does not receive
`payload_private`, `url_private`, or anything else that would be a credential if
it came back out in a proposal.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial import briefs
from tce.editorial import changes as change_service
from tce.editorial import lineup as lineup_service
from tce.llm import LLMRequest, LLMUnavailable
from tce.llm import provider as _llm
from tce.models.editorial import RecordingPacket, TopicCandidate
from tce.models.editorial_workspace import (
    BRIEF_FIELDS,
    EditorialMessage,
    EditorialThread,
)

JOB_TYPE = "editorial_conversation"
AGENT_NAME = "editorial_conversation"
PROMPT_VERSION = "editorial_conversation.v1"

# What the page says while the worker has not picked it up yet. Named, not a
# spinner: he is entitled to know it is queued behind his own desktop.
QUEUED_SENTENCE = (
    "Thinking about this. It runs on your PC worker, so it usually takes a minute."
)

SYSTEM = """You are Ziv's editorial assistant inside TCE.

Ziv is a business coach who records short talking-head videos for coaches and
service-business owners. You help him think about a topic before he spends a
recording slot on it.

How you talk:
- Like a sharp editor who has read his week, not like a chatbot. No preamble, no
  "great question", no summarising back what he just said.
- Short. Two or three sentences unless he asked for more.
- Take a position. "I would cut the second half" beats "you could consider".
- Never use the word "delve", never use em dashes.

What you may and may not do:
- You can discuss, disagree, ask one clarifying question, or say the idea is weak.
- You NEVER change anything. If a change is wanted you propose it, and a human
  accepts or rejects it. In discuss mode you propose nothing at all, even if he
  seems to be asking for an edit; say what you would change and let him switch to
  Propose changes.
- Only propose changes to fields listed in the context you were given. Never
  invent a field.
- Never put a client's name, a customer's words, an email, a phone number, money
  figures, or a link into a proposal.

Return JSON only."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply"],
    "properties": {
        "reply": {
            "type": "string",
            "description": "What you say to Ziv. Plain text, no markdown headings.",
        },
        "proposal": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["summary", "operations"],
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One plain sentence for the review sheet header.",
                },
                "rationale": {"type": ["string", "null"]},
                "operations": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["field", "after"],
                        "properties": {
                            "field": {"type": "string"},
                            "after": {"type": "string"},
                            "rationale": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    },
}


class ConversationError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


async def ensure_thread(
    db: AsyncSession,
    ws: uuid.UUID,
    *,
    context_type: str,
    context_id: uuid.UUID,
    label: str | None = None,
) -> EditorialThread:
    """One thread per object. The room's context_id is the workspace itself."""
    result = await db.execute(
        select(EditorialThread).where(
            EditorialThread.workspace_id == ws,
            EditorialThread.context_type == context_type,
            EditorialThread.context_id == context_id,
        )
    )
    found = result.scalar_one_or_none()
    if found is not None:
        if label and found.context_label != label:
            found.context_label = label
            await db.flush()
        return found

    row = EditorialThread(
        workspace_id=ws,
        context_type=context_type,
        context_id=context_id,
        context_label=label,
        status="open",
        last_mode="discuss",
        message_count=0,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        again = await db.execute(
            select(EditorialThread).where(
                EditorialThread.workspace_id == ws,
                EditorialThread.context_type == context_type,
                EditorialThread.context_id == context_id,
            )
        )
        existing = again.scalar_one_or_none()
        if existing is None:  # pragma: no cover
            raise
        return existing
    return row


async def get_thread(
    db: AsyncSession, ws: uuid.UUID, thread_id: uuid.UUID
) -> EditorialThread:
    result = await db.execute(
        select(EditorialThread).where(
            EditorialThread.workspace_id == ws, EditorialThread.id == thread_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ConversationError("not_found", "that conversation is not here", status=404)
    return row


async def list_messages(
    db: AsyncSession, ws: uuid.UUID, thread_id: uuid.UUID, *, after: int = 0
) -> list[EditorialMessage]:
    result = await db.execute(
        select(EditorialMessage)
        .where(
            EditorialMessage.workspace_id == ws,
            EditorialMessage.thread_id == thread_id,
            EditorialMessage.seq > after,
        )
        .order_by(EditorialMessage.seq.asc())
    )
    return list(result.scalars().all())


async def _next_seq(db: AsyncSession, ws: uuid.UUID, thread_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.max(EditorialMessage.seq)).where(
            EditorialMessage.workspace_id == ws, EditorialMessage.thread_id == thread_id
        )
    )
    return int(result.scalar_one() or 0) + 1


# ---------------------------------------------------------------------------
# Context the model is allowed to see
# ---------------------------------------------------------------------------


async def build_context(
    db: AsyncSession, ws: uuid.UUID, thread: EditorialThread
) -> tuple[str, str | None, uuid.UUID | None, int | None]:
    """Return (prompt block, target_type, target_id, base_version).

    The target is what a proposal from this thread would be written against. A
    room thread has none, which is why the room can talk about the week but can
    only ever hand him back a suggestion in prose.
    """
    if thread.context_type == "topic":
        return await _topic_context(db, ws, thread.context_id)
    if thread.context_type == "packet":
        return await _packet_context(db, ws, thread.context_id)
    if thread.context_type == "week":
        return await _week_context(db, ws), None, None, None
    return await _room_context(db, ws), None, None, None


async def _topic_context(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> tuple[str, str, uuid.UUID, int]:
    result = await db.execute(
        select(TopicCandidate).where(
            TopicCandidate.workspace_id == ws, TopicCandidate.id == candidate_id
        )
    )
    candidate = result.scalar_one_or_none()
    if candidate is None:
        raise ConversationError("not_found", "that topic is not here", status=404)
    brief = await briefs.ensure_brief(db, ws, candidate)

    lines = [
        "You are looking at ONE TOPIC he has not recorded yet.",
        f"Title: {candidate.title}",
        "",
        "Its brief, block by block. These are the only fields you may propose "
        "changes to, by their exact key:",
    ]
    stored = brief.brief or {}
    for field in BRIEF_FIELDS:
        value = (stored.get(field) or "").strip()
        lines.append(f"- {field}: {value if value else '(nothing written yet)'}")
    return "\n".join(lines), "candidate_brief", candidate.id, brief.version


async def _packet_context(
    db: AsyncSession, ws: uuid.UUID, packet_id: uuid.UUID
) -> tuple[str, str, uuid.UUID, int]:
    result = await db.execute(
        select(RecordingPacket).where(
            RecordingPacket.workspace_id == ws, RecordingPacket.id == packet_id
        )
    )
    packet = result.scalar_one_or_none()
    if packet is None:
        raise ConversationError("not_found", "that script is not here", status=404)

    lines = [
        "You are looking at ONE SCRIPT, the one he will read to camera.",
        "",
        "Talking points (field key `bullets`, one line each; to change line 3 use "
        "the key `bullets.2`, counting from zero):",
    ]
    for index, bullet in enumerate(packet.bullets or []):
        lines.append(f"  [{index}] {bullet}")
    lines.append("")
    lines.append(
        "The spoken script (field key `script_phrases`, same indexing rule, "
        "`script_phrases.0` is the first line):"
    )
    for index, phrase in enumerate(packet.script_phrases or []):
        lines.append(f"  [{index}] {phrase}")
    lines.append("")
    lines.append("You may also propose changes to `facebook_post` and `linkedin_post`.")
    lines.append(
        "He reads these out loud while walking, so short spoken sentences beat "
        "written ones."
    )
    return "\n".join(lines), "packet", packet.id, packet.version


async def _week_context(db: AsyncSession, ws: uuid.UUID) -> str:
    week_start = lineup_service.week_start_for(None)
    row = await lineup_service.get_lineup(db, ws, week_start)
    if row is None:
        return "He has not chosen anything for this week yet."
    payload = await lineup_service.lineup_to_json(db, ws, row)
    lines = ["This is his recording list for the week.", ""]
    for item in payload["primary"]:
        lines.append(f"{item['rank']}. {item['title']} ({item['lane_label']})")
    if payload["reserve"]:
        lines.append("")
        lines.append("In reserve:")
        for item in payload["reserve"]:
            lines.append(f"- {item['title']} ({item['lane_label']})")
    lines.append("")
    lines.append(
        "You cannot reorder this yourself. If the order is wrong, say which one "
        "you would record first and why."
    )
    return "\n".join(lines)


async def _room_context(db: AsyncSession, ws: uuid.UUID) -> str:
    """The editorial room: the week plus what is still waiting, in outline."""
    week = await _week_context(db, ws)
    waiting = await db.execute(
        select(TopicCandidate.title)
        .where(
            TopicCandidate.workspace_id == ws,
            TopicCandidate.status == "proposed",
        )
        .order_by(TopicCandidate.rank.asc())
        .limit(15)
    )
    titles = [t[0] for t in waiting.all()]
    lines = [week, "", "Ideas still waiting for a decision:"]
    lines += [f"- {t}" for t in titles] or ["- (none)"]
    lines.append("")
    lines.append(
        "This is a planning conversation across topics. You cannot change "
        "anything from here; give him your view."
    )
    return "\n".join(lines)


def build_prompt(
    context_block: str, history: list[EditorialMessage], instruction: str, mode: str
) -> str:
    lines = [context_block, ""]
    recent = [m for m in history if m.status == "complete"][-10:]
    if recent:
        lines.append("The conversation so far:")
        for message in recent:
            who = "Ziv" if message.role == "editor" else "You"
            lines.append(f"{who}: {message.text.strip()}")
        lines.append("")
    if mode == "propose":
        lines.append(
            "MODE: Propose changes. If a concrete edit follows from what he said, "
            "return it in `proposal` using the exact field keys above. If nothing "
            "concrete follows, return `proposal: null` and say why."
        )
    else:
        lines.append(
            "MODE: Discuss. Return `proposal: null` no matter what he asks. If he "
            "wants an edit made, tell him to switch to Propose changes."
        )
    lines.append("")
    lines.append(f"Ziv says: {instruction.strip()}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------


async def post_message(
    db: AsyncSession,
    ws: uuid.UUID,
    thread: EditorialThread,
    *,
    text: str,
    mode: str,
) -> tuple[EditorialMessage, EditorialMessage]:
    """Store his message and a queued placeholder for the reply.

    Both rows exist before any model call is made, so a crash between here and
    the worker leaves a visible "still thinking" rather than a lost turn.
    """
    if not text.strip():
        raise ConversationError("empty", "say something first", status=400)
    if mode not in ("discuss", "propose"):
        raise ConversationError("bad_mode", f"unknown mode {mode}", status=400)

    seq = await _next_seq(db, ws, thread.id)
    editor = EditorialMessage(
        workspace_id=ws,
        thread_id=thread.id,
        seq=seq,
        role="editor",
        mode=mode,
        text=text.strip(),
        status="complete",
    )
    assistant = EditorialMessage(
        workspace_id=ws,
        thread_id=thread.id,
        seq=seq + 1,
        role="assistant",
        mode=mode,
        text="",
        status="queued",
        status_detail=QUEUED_SENTENCE,
    )
    db.add(editor)
    db.add(assistant)
    thread.last_mode = mode
    thread.message_count = seq + 1
    thread.last_message_at = datetime.now(UTC).replace(tzinfo=None)
    await db.flush()
    return editor, assistant


async def run_turn(
    sessionmaker: Any, ws: uuid.UUID, thread_id: uuid.UUID, message_id: uuid.UUID
) -> None:
    """Fill in a queued assistant message. Runs as a background task.

    Every failure lands in the message row rather than a log: an assistant turn
    that silently never arrives is indistinguishable from one still thinking.
    """
    from tce.editorial.common import open_session

    async with open_session(sessionmaker) as db:
        thread = await get_thread(db, ws, thread_id)
        result = await db.execute(
            select(EditorialMessage).where(
                EditorialMessage.workspace_id == ws, EditorialMessage.id == message_id
            )
        )
        assistant = result.scalar_one_or_none()
        if assistant is None or assistant.status != "queued":
            return
        history = await list_messages(db, ws, thread_id)
        instruction = next(
            (m.text for m in reversed(history) if m.role == "editor"), ""
        )
        try:
            context_block, target_type, target_id, base_version = await build_context(
                db, ws, thread
            )
        except ConversationError as error:
            assistant.status = "failed"
            assistant.status_detail = error.message
            await db.commit()
            return
        prompt = build_prompt(context_block, history, instruction, assistant.mode)
        await db.commit()

    request = LLMRequest(
        job_type=JOB_TYPE,
        agent_name=AGENT_NAME,
        messages=[{"role": "user", "content": prompt}],
        system=SYSTEM,
        output_schema=SCHEMA,
        max_tokens=1200,
        prompt_version=PROMPT_VERSION,
        workspace_id=ws,
        run_id=thread_id,
        idempotency_key=f"conversation:{ws}:{message_id}",
    )
    try:
        llm = await _llm.complete(request, sessionmaker=sessionmaker)
    except LLMUnavailable as exc:
        async with open_session(sessionmaker) as db:
            result = await db.execute(
                select(EditorialMessage).where(
                    EditorialMessage.workspace_id == ws, EditorialMessage.id == message_id
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                # waiting_capacity is not a failure: the worker will get to it.
                row.status = "queued" if exc.status == "waiting_capacity" else "failed"
                row.status_detail = _unavailable_sentence(exc)
                row.job_id = exc.job_id
            await db.commit()
        return
    except Exception as error:  # pragma: no cover - defensive
        async with open_session(sessionmaker) as db:
            result = await db.execute(
                select(EditorialMessage).where(
                    EditorialMessage.workspace_id == ws, EditorialMessage.id == message_id
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                row.status = "failed"
                row.status_detail = f"Could not finish that turn: {error}"
            await db.commit()
        return

    payload = llm.structured if isinstance(llm.structured, dict) else {}
    reply = str(payload.get("reply") or llm.text or "").strip()
    proposal = payload.get("proposal")

    async with open_session(sessionmaker) as db:
        result = await db.execute(
            select(EditorialMessage).where(
                EditorialMessage.workspace_id == ws, EditorialMessage.id == message_id
            )
        )
        row = result.scalar_one_or_none()
        if row is None:  # pragma: no cover
            return
        row.text = reply or "I do not have anything useful to add there."
        row.status = "complete"
        row.status_detail = None
        row.job_id = llm.job_id
        row.model_receipt = {"model": llm.model, "prompt_version": PROMPT_VERSION}

        # Discuss mode never produces a proposal, whatever the model returned.
        if row.mode == "propose" and isinstance(proposal, dict) and target_type:
            change_set = await _proposal_to_change_set(
                db,
                ws,
                thread_id=thread_id,
                target_type=target_type,
                target_id=target_id,
                base_version=base_version,
                proposal=proposal,
                message_id=message_id,
            )
            if change_set is not None:
                row.change_set_id = change_set.id
        await db.commit()


def _unavailable_sentence(exc: LLMUnavailable) -> str:
    if exc.status == "waiting_capacity":
        return "Waiting for capacity on your subscription. It will finish on its own."
    if exc.status == "no_worker":
        return "No PC worker is running. This starts when it checks in."
    return f"Could not reach the worker ({exc.status})."


async def _proposal_to_change_set(
    db: AsyncSession,
    ws: uuid.UUID,
    *,
    thread_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID | None,
    base_version: int | None,
    proposal: dict[str, Any],
    message_id: uuid.UUID,
) -> Any:
    """Turn the model's suggestion into a proposal the normal review path owns.

    It goes through `changes.propose`, so an invented field, an unchanged value
    or an unsafe line is caught by the same validation a hand-typed edit gets.
    The model does not get a private door.
    """
    raw_ops = proposal.get("operations")
    if not isinstance(raw_ops, list) or not raw_ops or target_id is None:
        return None
    operations = [
        change_service.OperationInput(
            op="set_field",
            field=str(op.get("field") or ""),
            after=op.get("after"),
            rationale=(op.get("rationale") or None),
        )
        for op in raw_ops
        if isinstance(op, dict)
    ]
    if not operations:
        return None
    try:
        return await change_service.propose(
            db,
            ws,
            target_type=target_type,
            target_id=target_id,
            base_version=base_version,
            operations=operations,
            summary=str(proposal.get("summary") or "A change from our conversation"),
            rationale=proposal.get("rationale") or None,
            origin="conversation",
            thread_id=thread_id,
            idempotency_key=f"conversation-proposal:{message_id}",
        )
    except change_service.ChangeError:
        # A refused proposal is not a failed turn. He still gets the reply.
        return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def message_to_json(row: EditorialMessage) -> dict[str, Any]:
    return {
        "seq": row.seq,
        "role": row.role,
        "mode": row.mode,
        "text": row.text,
        "status": row.status,
        "status_detail": row.status_detail,
        "change_set_id": str(row.change_set_id) if row.change_set_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def thread_to_json(thread: EditorialThread, messages: list[EditorialMessage]) -> dict[str, Any]:
    return {
        "thread_id": str(thread.id),
        "context_type": thread.context_type,
        "context_id": str(thread.context_id),
        "context_label": thread.context_label,
        "last_mode": thread.last_mode,
        "messages": [message_to_json(m) for m in messages],
        "pending": any(m.status == "queued" for m in messages),
    }
