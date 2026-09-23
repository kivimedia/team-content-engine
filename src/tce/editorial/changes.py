"""Proposed changes: the only path from an instruction to stored editorial content.

The contract, in one paragraph. An assistant, a quick action or an undo builds a
*proposal* against one object at one known version. The proposal is inert. A human
reviews it as a before/after and accepts it whole or operation by operation.
Accepting writes a NEW immutable version; it never edits the version that was
read. Rejecting keeps the proposal for audit. Undo is not a delete: it is another
proposal whose `after` values are the content of an earlier version.

Why so much ceremony for "change a sentence": the failure this prevents is the one
that makes an editorial tool untrustworthy - the assistant quietly rewriting a
topic because the owner was thinking aloud. If speech can mutate state, every
sentence becomes risky to say. Here it cannot.

Three target types share the contract:

  candidate_brief  version = CandidateBriefVersion.version
  packet           version = RecordingPacket.version
  lineup           version = WeeklyLineup.revision

`base_version` is checked at apply time, not only at propose time. Between the two
the object can move - another device, another tab, the packet writer finishing -
and a stale proposal must surface the newer state rather than overwrite it.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial import briefs
from tce.editorial.safety import scan_public_text
from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import (
    BRIEF_FIELDS,
    CHANGE_OPS,
    EditorialChangeOperation,
    EditorialChangeSet,
    WeeklyLineup,
    WeeklyLineupItem,
)

# Packet fields an editor may change from the script workshop. `bullets` and
# `script_phrases` accept an index suffix ("bullets.2") to change one line.
PACKET_LIST_FIELDS = ("bullets", "script_phrases")
PACKET_TEXT_FIELDS = ("facebook_post", "linkedin_post", "interviewer_prompt")
PACKET_FIELDS = (*PACKET_LIST_FIELDS, *PACKET_TEXT_FIELDS, "selected_hook_id", "beats")

# Fields that end up in front of an audience, so a proposed value is scanned
# before it can be accepted.
PACKET_PUBLIC_FIELDS = ("bullets", "script_phrases", "facebook_post", "linkedin_post")


class ChangeError(Exception):
    """A proposal cannot be built or applied. Carries an HTTP-shaped reason."""

    def __init__(self, code: str, message: str, *, status: int = 409, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


@dataclass
class OperationInput:
    """One requested operation, before it is captured against live state."""

    op: str
    # Shadows `dataclasses.field` inside this class body, hence the qualified
    # call below. Renaming the attribute would change the API's wire shape.
    field: str | None = None
    after: Any = None
    rationale: str | None = None
    depends_on: list[int] = dataclasses.field(default_factory=list)


@dataclass
class TargetState:
    """The live object a proposal is measured against."""

    version: int
    values: dict[str, Any]
    # Set when the object may not change at all, with the reason to show.
    frozen_reason: str | None = None


# ---------------------------------------------------------------------------
# Reading live state
# ---------------------------------------------------------------------------


def _resolve_path(values: dict[str, Any], path: str) -> tuple[bool, Any]:
    """Read `field` or `field.index`. Returns (exists, value)."""
    if "." not in path:
        return (path in values, values.get(path))
    name, _, raw_index = path.partition(".")
    holder = values.get(name)
    if not isinstance(holder, list):
        return (False, None)
    try:
        index = int(raw_index)
    except ValueError:
        return (False, None)
    if index < 0 or index >= len(holder):
        return (False, None)
    return (True, holder[index])


def _write_path(values: dict[str, Any], path: str, new_value: Any) -> None:
    """Write `field` or `field.index`, copying the list so the old version is untouched."""
    if "." not in path:
        values[path] = new_value
        return
    name, _, raw_index = path.partition(".")
    holder = list(values.get(name) or [])
    index = int(raw_index)
    if index >= len(holder):
        raise ChangeError(
            "unknown_field", f"{path} is no longer in this version", status=409
        )
    holder[index] = new_value
    values[name] = holder


async def load_target(
    db: AsyncSession, ws: uuid.UUID, target_type: str, target_id: uuid.UUID
) -> TargetState:
    if target_type == "candidate_brief":
        return await _load_brief_target(db, ws, target_id)
    if target_type == "packet":
        return await _load_packet_target(db, ws, target_id)
    if target_type == "lineup":
        return await _load_lineup_target(db, ws, target_id)
    raise ChangeError("unknown_target", f"unknown target type {target_type}", status=400)


async def _load_brief_target(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> TargetState:
    result = await db.execute(
        select(TopicCandidate).where(
            TopicCandidate.workspace_id == ws, TopicCandidate.id == candidate_id
        )
    )
    candidate = result.scalar_one_or_none()
    if candidate is None:
        raise ChangeError("not_found", "that topic is not here", status=404)
    current = await briefs.ensure_brief(db, ws, candidate)
    return TargetState(version=current.version, values=dict(current.brief or {}))


async def _load_packet_target(
    db: AsyncSession, ws: uuid.UUID, packet_id: uuid.UUID
) -> TargetState:
    result = await db.execute(
        select(RecordingPacket).where(
            RecordingPacket.workspace_id == ws, RecordingPacket.id == packet_id
        )
    )
    packet = result.scalar_one_or_none()
    if packet is None:
        raise ChangeError("not_found", "that script is not here", status=404)

    # A packet that has been recorded against is history. Changing it would make
    # the video and the script disagree, with nothing to say which was true.
    recorded = await db.execute(
        select(RecordingUpload.id)
        .where(
            RecordingUpload.workspace_id == ws,
            RecordingUpload.packet_id == packet.id,
        )
        .limit(1)
    )
    frozen = None
    if recorded.scalar_one_or_none() is not None:
        frozen = (
            "This script has already been recorded, so it stays as it was read. "
            "Ask for a new version of the script to change it for a re-record."
        )

    return TargetState(
        version=packet.version,
        values={
            "bullets": list(packet.bullets or []),
            "script_phrases": list(packet.script_phrases or []),
            "facebook_post": packet.facebook_post,
            "linkedin_post": packet.linkedin_post,
            "interviewer_prompt": packet.interviewer_prompt,
            "selected_hook_id": packet.selected_hook_id,
            "beats": list(packet.beats or []) if packet.beats else None,
        },
        frozen_reason=frozen,
    )


async def _load_lineup_target(
    db: AsyncSession, ws: uuid.UUID, lineup_id: uuid.UUID
) -> TargetState:
    result = await db.execute(
        select(WeeklyLineup).where(
            WeeklyLineup.workspace_id == ws, WeeklyLineup.id == lineup_id
        )
    )
    lineup = result.scalar_one_or_none()
    if lineup is None:
        raise ChangeError("not_found", "that week is not here", status=404)
    items = await db.execute(
        select(WeeklyLineupItem)
        .where(
            WeeklyLineupItem.workspace_id == ws,
            WeeklyLineupItem.lineup_id == lineup_id,
        )
        .order_by(WeeklyLineupItem.slot.asc(), WeeklyLineupItem.rank.asc())
    )
    order = [
        {"candidate_id": str(i.candidate_id), "slot": i.slot, "rank": i.rank}
        for i in items.scalars().all()
    ]
    return TargetState(version=lineup.revision, values={"order": order})


# ---------------------------------------------------------------------------
# Proposing
# ---------------------------------------------------------------------------


def _validate_operation(
    target_type: str, state: TargetState, op_in: OperationInput, seq: int
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Capture `before` and return any issues. Never raises for content problems."""
    issues: list[dict[str, Any]] = []

    def issue(code: str, message: str) -> None:
        issues.append({"code": code, "message": message, "op_seq": seq})

    if op_in.op not in CHANGE_OPS:
        issue("unknown_op", f"unknown operation {op_in.op}")
        return None, issues

    if op_in.op in ("set_field", "replace_text"):
        path = op_in.field or ""
        allowed = BRIEF_FIELDS if target_type == "candidate_brief" else PACKET_FIELDS
        root = path.partition(".")[0]
        if root not in allowed:
            issue("unknown_field", f"{path or '(none)'} is not editable here")
            return None, issues
        exists, before = _resolve_path(state.values, path)
        if "." in path and not exists:
            issue("unknown_field", f"{path} is not in this version")
            return None, issues
        if not isinstance(op_in.after, str):
            issue("bad_value", f"{path} needs text")
            return None, issues
        if before == op_in.after:
            issue("no_change", f"{path} already says this")
        return {"value": before}, issues

    if op_in.op == "choose_hook":
        if not isinstance(op_in.after, str) or not op_in.after:
            issue("bad_value", "an opening id is required")
            return None, issues
        return {"value": state.values.get("selected_hook_id")}, issues

    if op_in.op == "reorder_week":
        if not isinstance(op_in.after, list):
            issue("bad_value", "a new order is required")
            return None, issues
        return {"value": state.values.get("order")}, issues

    if op_in.op == "move_topic":
        if not isinstance(op_in.after, dict) or "candidate_id" not in op_in.after:
            issue("bad_value", "a topic and a destination are required")
            return None, issues
        # The whole order before the move, so the move can be undone exactly.
        return {"value": state.values.get("order")}, issues

    if op_in.op == "restore_version":
        if not isinstance(op_in.after, dict):
            issue("bad_value", "nothing to restore")
            return None, issues
        return {"value": None}, issues

    # request_edit is recorded against a recording, handled by the library service.
    return {"value": None}, issues


def _safety_issues(target_type: str, operations: list[OperationInput]) -> list[dict[str, Any]]:
    """Scan proposed text that would end up in front of an audience."""
    if target_type != "packet":
        return []
    fields: dict[str, Any] = {}
    for index, op_in in enumerate(operations, start=1):
        root = (op_in.field or "").partition(".")[0]
        if root in PACKET_PUBLIC_FIELDS and isinstance(op_in.after, str):
            fields[f"op{index}:{op_in.field}"] = op_in.after
    if not fields:
        return []
    report = scan_public_text(fields)
    return [
        {
            "code": "safety",
            "message": f"{issue['kind']} in {issue['field']}: {issue['match']}",
            "op_seq": int(str(issue["field"]).split(":")[0].removeprefix("op").split("[")[0] or 0),
        }
        for issue in report.get("issues", [])
    ]


async def propose(
    db: AsyncSession,
    ws: uuid.UUID,
    *,
    target_type: str,
    target_id: uuid.UUID,
    base_version: int | None,
    operations: list[OperationInput],
    summary: str,
    rationale: str | None = None,
    origin: str = "conversation",
    thread_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    job_id: uuid.UUID | None = None,
) -> EditorialChangeSet:
    """Build a proposal. Validation problems are recorded, not raised.

    A proposal with issues is still stored and still shown, because "here is what
    I would have changed and why it cannot be applied" is more useful than a
    generic failure. Only `invalid` sets refuse to apply.
    """
    if idempotency_key:
        existing = await db.execute(
            select(EditorialChangeSet).where(
                EditorialChangeSet.workspace_id == ws,
                EditorialChangeSet.idempotency_key == idempotency_key,
            )
        )
        found = existing.scalar_one_or_none()
        if found is not None:
            return found

    if not operations:
        raise ChangeError("empty", "a proposal needs at least one change", status=400)

    state = await load_target(db, ws, target_type, target_id)
    if state.frozen_reason:
        raise ChangeError("immutable", state.frozen_reason, status=409)

    base = state.version if base_version is None else base_version
    issues: list[dict[str, Any]] = []
    if base != state.version:
        issues.append(
            {
                "code": "stale_base",
                "message": (
                    f"This was written against version {base}; the current version "
                    f"is {state.version}."
                ),
                "op_seq": None,
            }
        )

    change_set = EditorialChangeSet(
        workspace_id=ws,
        thread_id=thread_id,
        target_type=target_type,
        target_id=target_id,
        base_version=base,
        summary=summary,
        rationale=rationale,
        state="proposed",
        origin=origin,
        idempotency_key=idempotency_key,
        job_id=job_id,
        validation={},
    )
    db.add(change_set)
    await db.flush()

    for seq, op_in in enumerate(operations, start=1):
        before, op_issues = _validate_operation(target_type, state, op_in, seq)
        issues.extend(op_issues)
        db.add(
            EditorialChangeOperation(
                workspace_id=ws,
                change_set_id=change_set.id,
                seq=seq,
                op=op_in.op,
                field=op_in.field,
                before=before,
                after={"value": op_in.after},
                rationale=op_in.rationale,
                state="proposed",
                depends_on=list(op_in.depends_on or []),
            )
        )

    issues.extend(_safety_issues(target_type, operations))
    blocking = {"unknown_op", "unknown_field", "bad_value"}
    change_set.validation = {
        "ok": not any(i["code"] in blocking for i in issues),
        "issues": issues,
    }
    if any(i["code"] in blocking for i in issues):
        change_set.state = "invalid"
    await db.flush()
    return change_set


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


async def load_operations(
    db: AsyncSession, ws: uuid.UUID, change_set_id: uuid.UUID
) -> list[EditorialChangeOperation]:
    result = await db.execute(
        select(EditorialChangeOperation)
        .where(
            EditorialChangeOperation.workspace_id == ws,
            EditorialChangeOperation.change_set_id == change_set_id,
        )
        .order_by(EditorialChangeOperation.seq.asc())
    )
    return list(result.scalars().all())


async def get_change_set(
    db: AsyncSession, ws: uuid.UUID, change_set_id: uuid.UUID
) -> EditorialChangeSet:
    result = await db.execute(
        select(EditorialChangeSet).where(
            EditorialChangeSet.workspace_id == ws, EditorialChangeSet.id == change_set_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ChangeError("not_found", "that proposal is not here", status=404)
    return row


def _closure(
    operations: list[EditorialChangeOperation], accepted: set[int]
) -> tuple[set[int], list[str]]:
    """Accepting an operation accepts what it depends on, or says why it cannot."""
    problems: list[str] = []
    resolved = set(accepted)
    known = {op.seq for op in operations}
    changed = True
    while changed:
        changed = False
        for op in operations:
            if op.seq not in resolved:
                continue
            for dep in op.depends_on or []:
                if dep not in known:
                    problems.append(f"change {op.seq} depends on {dep}, which is not in this set")
                    continue
                if dep not in resolved:
                    resolved.add(dep)
                    changed = True
    return resolved, problems


async def apply(
    db: AsyncSession,
    ws: uuid.UUID,
    change_set_id: uuid.UUID,
    *,
    accept_seqs: list[int] | None = None,
    decided_by: str | None = None,
) -> dict[str, Any]:
    """Accept a proposal, whole or in part, and write a new version.

    Returns the new version plus the operations that were applied and skipped.
    Raises `ChangeError("conflict")` carrying the newer state when the object has
    moved since the proposal was built - never an overwrite.
    """
    change_set = await get_change_set(db, ws, change_set_id)
    if change_set.state == "applied":
        # Re-applying is a no-op, not an error: a retried tap must not double-write.
        return {
            "change_set_id": str(change_set.id),
            "state": "applied",
            "version": change_set.applied_version,
            "applied": [],
            "skipped": [],
            "already": True,
        }
    if change_set.state != "proposed":
        raise ChangeError(
            "not_proposed", f"this proposal is {change_set.state}", status=409
        )

    state = await load_target(db, ws, change_set.target_type, change_set.target_id)
    if state.frozen_reason:
        raise ChangeError("immutable", state.frozen_reason, status=409)
    if state.version != change_set.base_version:
        change_set.state = "superseded"
        await db.flush()
        raise ChangeError(
            "conflict",
            (
                f"This was written against version {change_set.base_version} and the "
                f"current version is {state.version}. Nothing was changed."
            ),
            status=409,
            current_version=state.version,
            base_version=change_set.base_version,
        )

    operations = await load_operations(db, ws, change_set_id)
    if not operations:
        raise ChangeError("empty", "this proposal has no changes", status=409)

    requested = {op.seq for op in operations} if accept_seqs is None else set(accept_seqs)
    unknown = requested - {op.seq for op in operations}
    if unknown:
        raise ChangeError(
            "unknown_operation", f"no such change: {sorted(unknown)}", status=400
        )
    resolved, problems = _closure(operations, requested)
    if problems:
        raise ChangeError("dependency", "; ".join(problems), status=409)

    applied: list[int] = []
    skipped: list[int] = []
    values = dict(state.values)

    for op in operations:
        if op.seq not in resolved:
            op.state = "skipped"
            skipped.append(op.seq)
            continue
        after = (op.after or {}).get("value")
        if op.op in ("set_field", "replace_text"):
            _write_path(values, op.field or "", after)
        elif op.op == "choose_hook":
            values["selected_hook_id"] = after
        elif op.op == "reorder_week":
            values["order"] = after
        elif op.op == "move_topic":
            values.setdefault("moves", []).append(after)
        elif op.op == "restore_version":
            # REPLACE, not merge. Restoring version 1 over a version 2 that added
            # a block has to remove that block again; `update` would leave it
            # behind and call the result "version 1", which is a lie about what
            # the editor is looking at.
            if isinstance(after, dict):
                values = dict(after)
        op.state = "applied"
        applied.append(op.seq)

    if not applied:
        raise ChangeError("nothing_accepted", "no change was accepted", status=400)

    new_version = await _commit_values(
        db,
        ws,
        change_set,
        values,
        decided_by=decided_by,
    )

    now = datetime.now(UTC).replace(tzinfo=None)
    change_set.state = "applied"
    change_set.applied_version = new_version
    change_set.applied_at = now
    change_set.decided_by = decided_by
    change_set.decided_at = now
    await db.flush()

    return {
        "change_set_id": str(change_set.id),
        "state": "applied",
        "version": new_version,
        "applied": applied,
        "skipped": skipped,
        "already": False,
    }


async def _commit_values(
    db: AsyncSession,
    ws: uuid.UUID,
    change_set: EditorialChangeSet,
    values: dict[str, Any],
    *,
    decided_by: str | None,
) -> int:
    """Write the merged values as a new version of the target. Never in place."""
    if change_set.target_type == "candidate_brief":
        row = await briefs.write_version(
            db,
            ws,
            change_set.target_id,
            brief=values,
            parent_version=change_set.base_version,
            origin="undo" if change_set.origin == "undo" else "change_set",
            change_set_id=change_set.id,
            created_by=decided_by,
            note=change_set.summary or None,
        )
        return row.version

    if change_set.target_type == "packet":
        return await _write_packet_version(db, ws, change_set, values, decided_by=decided_by)

    if change_set.target_type == "lineup":
        return await _write_lineup_revision(db, ws, change_set, values, decided_by=decided_by)

    raise ChangeError("unknown_target", "unknown target type", status=400)


async def _write_packet_version(
    db: AsyncSession,
    ws: uuid.UUID,
    change_set: EditorialChangeSet,
    values: dict[str, Any],
    *,
    decided_by: str | None,
) -> int:
    result = await db.execute(
        select(RecordingPacket).where(
            RecordingPacket.workspace_id == ws, RecordingPacket.id == change_set.target_id
        )
    )
    packet = result.scalar_one_or_none()
    if packet is None:
        raise ChangeError("not_found", "that script is not here", status=404)

    highest = await db.execute(
        select(RecordingPacket.version)
        .where(
            RecordingPacket.workspace_id == ws,
            RecordingPacket.candidate_id == packet.candidate_id,
        )
        .order_by(RecordingPacket.version.desc())
        .limit(1)
    )
    next_version = (highest.scalar_one_or_none() or packet.version) + 1

    fresh = RecordingPacket(
        workspace_id=ws,
        candidate_id=packet.candidate_id,
        version=next_version,
        bullets=list(values.get("bullets") or []),
        script_phrases=list(values.get("script_phrases") or []),
        facebook_post=values.get("facebook_post"),
        linkedin_post=values.get("linkedin_post"),
        interviewer_prompt=values.get("interviewer_prompt"),
        hook_options=packet.hook_options,
        selected_hook_id=values.get("selected_hook_id"),
        beats=values.get("beats"),
        citations_private=packet.citations_private,
        public_safety=_rescan_packet(values),
        status=packet.status if packet.status != "exported" else "ready",
        prompt_version=packet.prompt_version,
    )
    db.add(fresh)
    # The version that was read stays readable; it is simply no longer current.
    packet.status = "superseded"
    await db.flush()
    change_set.target_id = fresh.id
    return next_version


def _rescan_packet(values: dict[str, Any]) -> dict[str, Any]:
    """Re-run the public scan on the merged packet, not only on the changed line.

    A safe sentence can be unsafe next to the one before it, and the stored
    verdict must describe the version that exists, not the edit that made it.
    """
    report = scan_public_text(
        {
            "bullets": list(values.get("bullets") or []),
            "script_phrases": list(values.get("script_phrases") or []),
            "facebook_post": values.get("facebook_post") or "",
            "linkedin_post": values.get("linkedin_post") or "",
        }
    )
    return {
        "checked": True,
        "status": report.get("status", "clean"),
        "issues": report.get("issues", []),
    }


async def _write_lineup_revision(
    db: AsyncSession,
    ws: uuid.UUID,
    change_set: EditorialChangeSet,
    values: dict[str, Any],
    *,
    decided_by: str | None,
) -> int:
    from tce.editorial import lineup as lineup_service

    result = await db.execute(
        select(WeeklyLineup).where(
            WeeklyLineup.workspace_id == ws, WeeklyLineup.id == change_set.target_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ChangeError("not_found", "that week is not here", status=404)

    order = values.get("order")
    if isinstance(order, list):
        # An undo puts back an order recorded before a topic was taken out, so it
        # has to put that topic back too. Every other order only rearranges.
        await lineup_service.apply_order(
            db,
            ws,
            row,
            order,
            create_missing=change_set.origin == "undo",
            added_by=decided_by,
        )
    for move in values.get("moves") or []:
        await lineup_service.apply_move(db, ws, row, move)

    row.revision += 1
    row.updated_by = decided_by
    await db.flush()
    return row.revision


# ---------------------------------------------------------------------------
# Rejecting and undoing
# ---------------------------------------------------------------------------


async def reject(
    db: AsyncSession,
    ws: uuid.UUID,
    change_set_id: uuid.UUID,
    *,
    decided_by: str | None = None,
) -> EditorialChangeSet:
    """Turn a proposal down. The row and its operations are kept, never deleted."""
    change_set = await get_change_set(db, ws, change_set_id)
    if change_set.state == "applied":
        raise ChangeError(
            "already_applied",
            "this was already applied. Undo it from the topic's history instead.",
            status=409,
        )
    if change_set.state == "rejected":
        return change_set
    now = datetime.now(UTC).replace(tzinfo=None)
    change_set.state = "rejected"
    change_set.decided_by = decided_by
    change_set.decided_at = now
    for op in await load_operations(db, ws, change_set_id):
        op.state = "rejected"
    await db.flush()
    return change_set


async def undo(
    db: AsyncSession,
    ws: uuid.UUID,
    *,
    target_type: str,
    target_id: uuid.UUID,
    to_version: int,
    decided_by: str | None = None,
) -> dict[str, Any]:
    """Restore known content as a NEW version.

    History stays append-only, so "undo the undo" is an ordinary operation and
    nothing an editor did is ever unreachable.
    """
    if target_type != "candidate_brief":
        raise ChangeError(
            "unsupported",
            "only a topic brief can be restored this way today",
            status=400,
        )

    wanted = await briefs.get_version(db, ws, target_id, to_version)
    if wanted is None:
        raise ChangeError("not_found", f"there is no version {to_version}", status=404)

    state = await load_target(db, ws, target_type, target_id)
    if state.version == to_version:
        raise ChangeError("no_change", "that is already the current version", status=409)

    operations = [
        OperationInput(
            op="restore_version",
            field=None,
            after=dict(wanted.brief or {}),
            rationale=f"Restore the wording of version {to_version}.",
        )
    ]
    change_set = await propose(
        db,
        ws,
        target_type=target_type,
        target_id=target_id,
        base_version=state.version,
        operations=operations,
        summary=f"Go back to version {to_version}",
        origin="undo",
    )
    return await apply(db, ws, change_set.id, decided_by=decided_by)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def operation_to_json(op: EditorialChangeOperation) -> dict[str, Any]:
    return {
        "seq": op.seq,
        "op": op.op,
        "field": op.field,
        "before": (op.before or {}).get("value"),
        "after": (op.after or {}).get("value"),
        "rationale": op.rationale,
        "state": op.state,
        "depends_on": op.depends_on or [],
    }


def change_set_to_json(
    change_set: EditorialChangeSet, operations: list[EditorialChangeOperation]
) -> dict[str, Any]:
    return {
        "id": str(change_set.id),
        "thread_id": str(change_set.thread_id) if change_set.thread_id else None,
        "target_type": change_set.target_type,
        "target_id": str(change_set.target_id),
        "base_version": change_set.base_version,
        "summary": change_set.summary,
        "rationale": change_set.rationale,
        "state": change_set.state,
        "origin": change_set.origin,
        "validation": change_set.validation or {},
        "applied_version": change_set.applied_version,
        "applied_at": change_set.applied_at.isoformat() if change_set.applied_at else None,
        "decided_by": change_set.decided_by,
        "created_at": change_set.created_at.isoformat() if change_set.created_at else None,
        "operations": [operation_to_json(op) for op in operations],
    }
