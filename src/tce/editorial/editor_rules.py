"""Jennifer's rules: the rows behind "every note becomes a rule" (3-Oct).

A rule is one sentence she learned from a note on one video (production/rules.py
decides which notes are rules). Active rules go into the review of every next video
and into her leftover-asides check. He sees them on the rules page with the video each
came from and how many videos it was applied on, and Delete switches a rule off: the
row stays, so what she learned and from where is never lost.

Every read and write is filtered by the workspace.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import EditingRequest
from tce.models.jennifer import EditorRule
from tce.production import rules as rule_text

MAX_APPLIED_KEPT = 500  # video ids remembered per rule, so the same video counts once


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def active_rules(db: AsyncSession, ws: uuid.UUID) -> list[EditorRule]:
    """The rules in force, oldest first (the order they are numbered in a prompt)."""
    result = await db.execute(
        select(EditorRule)
        .where(EditorRule.workspace_id == ws, EditorRule.active.is_(True))
        .order_by(EditorRule.created_at.asc(), EditorRule.id.asc())
    )
    return list(result.scalars().all())


async def prompt_rules(db: AsyncSession, ws: uuid.UUID) -> list[list[str]]:
    """The active rules as [[id, text], ...], oldest first: what a job is given, and what
    a review that is still waiting keeps so its key does not move when a rule is added."""
    return [[str(r.id), r.text] for r in await active_rules(db, ws)]


def block(rules: list[list[str]] | None) -> tuple[str, list[str]]:
    """The prompt block for these rules and, for each Rn written, the rule's id."""
    rules = [r for r in rules or [] if len(r) == 2]
    text, used = rule_text.rules_block([r[1] for r in rules])
    return text, [rules[i][0] for i in used]


def in_block(rules: list[list[str]] | None) -> list[list[str]]:
    """The rules a prompt holds, oldest first: the newest that fit under the cap
    (rules.MAX_RULES_BLOCK_CHARS). Every prompt that lists her rules (the review, her
    check, the distilling job, her voice seat) lists these and no more, so a long list
    of rules can never blow up a prompt (3-Oct review)."""
    rules = [r for r in rules or [] if len(r) == 2]
    _text, used = rule_text.rules_block([r[1] for r in rules])
    return [rules[i] for i in used]


async def add_rule(
    db: AsyncSession,
    ws: uuid.UUID,
    text: str,
    *,
    upload_id: uuid.UUID | None,
    note_id: uuid.UUID | None,
) -> EditorRule:
    row = EditorRule(
        workspace_id=ws,
        text=text,
        source_upload_id=upload_id,
        source_note_id=note_id,
        active=True,
        times_applied=0,
        applied_uploads=[],
        # Set here, to the microsecond: rules made from one sitting keep their order.
        created_at=_now(),
    )
    db.add(row)
    await db.flush()
    return row


async def deactivate(db: AsyncSession, ws: uuid.UUID, rule_id: uuid.UUID) -> EditorRule | None:
    """Delete on the rules page: the rule stops being applied and the row stays."""
    row = (
        await db.execute(
            select(EditorRule).where(EditorRule.workspace_id == ws, EditorRule.id == rule_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.active:
        row.active = False
        row.deactivated_at = _now()
        await db.flush()
    return row


async def mark_applied(
    db: AsyncSession, ws: uuid.UUID, rule_ids: list[str], upload_id: uuid.UUID
) -> int:
    """A cut on this video named these rules. Each rule counts a video once, however
    many times that video is edited again. Returns how many counts moved."""
    moved = 0
    video = str(upload_id)
    for raw in dict.fromkeys(rule_ids):
        try:
            rid = uuid.UUID(str(raw))
        except ValueError:
            continue
        row = (
            await db.execute(
                select(EditorRule).where(EditorRule.workspace_id == ws, EditorRule.id == rid)
            )
        ).scalar_one_or_none()
        # A rule he deleted meanwhile is not counted: it is not applied any more.
        if row is None or not row.active or video in (row.applied_uploads or []):
            continue
        row.applied_uploads = [*(row.applied_uploads or []), video][-MAX_APPLIED_KEPT:]
        row.times_applied = int(row.times_applied or 0) + 1
        moved += 1
    if moved:
        await db.flush()
    return moved


async def list_rules(db: AsyncSession, ws: uuid.UUID) -> dict[str, Any]:
    """The rules page: every active rule, newest first, with the video it came from (and
    whether that video still has an edit to open), his note, and how often it applied.

    `in_use` False: the rule is older than the newest rules that fit in a prompt, so it
    is not applied right now; the page says so instead of letting it look applied."""
    oldest_first = await active_rules(db, ws)
    applied_now = {r[0] for r in in_block([[str(r.id), r.text] for r in oldest_first])}
    rows = list(reversed(oldest_first))
    upload_ids = [r.source_upload_id for r in rows if r.source_upload_id]
    note_ids = [r.source_note_id for r in rows if r.source_note_id]
    videos: dict[uuid.UUID, dict[str, Any]] = {}
    if upload_ids:
        found = await db.execute(
            select(RecordingUpload.id, RecordingUpload.edited_path, TopicCandidate.title)
            .join(TopicCandidate, TopicCandidate.id == RecordingUpload.candidate_id, isouter=True)
            .where(RecordingUpload.workspace_id == ws, RecordingUpload.id.in_(upload_ids))
        )
        for upload_id, edited, title in found.all():
            videos[upload_id] = {"title": title or "(untitled recording)", "has_edit": bool(edited)}
    notes: dict[uuid.UUID, str] = {}
    if note_ids:
        found = await db.execute(
            select(EditingRequest.id, EditingRequest.request, EditingRequest.understood).where(
                EditingRequest.workspace_id == ws, EditingRequest.id.in_(note_ids)
            )
        )
        for note_id, said, understood in found.all():
            notes[note_id] = (said or "").strip() or (understood or "").strip()
    items = []
    for r in rows:
        video = videos.get(r.source_upload_id) if r.source_upload_id else None
        items.append(
            {
                "id": str(r.id),
                "text": r.text,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "times_applied": int(r.times_applied or 0),
                "source_upload_id": str(r.source_upload_id) if r.source_upload_id and video else None,
                "source_title": video["title"] if video else None,
                "source_has_edit": bool(video and video["has_edit"]),
                "source_note": notes.get(r.source_note_id) if r.source_note_id else None,
                "in_use": str(r.id) in applied_now,
            }
        )
    return {"rules": items, "total": len(items), "in_use": len(applied_now)}
