"""What the voice agent is allowed to do, and how each thing is said back.

The voice agent is an Opus brain on a live call. It hears Ziv, reads a change
back to him, and then applies it at once (his decision, 23-Sep). That is only
safe because three things hold, and this module is where they hold:

  1. Every write is attributed. Change sets carry origin `voice`, decisions carry
     decided_by `voice`, so the workspace lists exactly what the call changed.
  2. Every write is undoable by id. `undo_change_set` builds the inverse of an
     applied change set as a NEW change set, never an edit in place, and refuses
     (with the text as it is now) when something changed after it.
  3. A stale read is caught. The brain passes the text it read back, and must
     when it replaces text that exists; if the script says something else by
     the time it applies, nothing is written and the fresh text comes back so it
     can read that instead.

The research job lives here too, because it is the agent's one long errand that
is not a script: it gathers what TCE already holds about an idea, adds a web
search when one is configured, and says plainly when it is not.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial import briefs
from tce.editorial import changes as change_service
from tce.editorial import inbox as inbox_service
from tce.editorial import lineup as lineup_service
from tce.editorial.common import open_session, packet_to_json
from tce.models.editorial import (
    EvidenceMoment,
    EvidenceSource,
    RecordingPacket,
    TopicCandidate,
)
from tce.models.editorial_workspace import (
    ACTORS,
    EditorialChangeSet,
    IdeaResearch,
    TopicDecision,
)
from tce.models.recording_session import RecordingSession

logger = structlog.get_logger()

# Mirrors packets.RECORDING_IN_PROGRESS_STATUSES; imported lazily there to keep
# this module light, so it is restated here and pinned by a test.
TAKE_IN_PROGRESS = ("recording", "finalizing")

BRIEF_LABELS = {
    "topic": "The topic",
    "audience": "Who it is for",
    "big_idea": "The big idea",
    "why_now": "Why now",
    "why_this_is_yours": "Why this is yours",
    "distinctive_perspective": "Your angle",
    "evidence": "The evidence",
    "claims_to_avoid": "Claims to avoid",
    "takeaway": "The takeaway",
    "cta": "The call to action",
}

PACKET_LABELS = {
    "facebook_post": "The Facebook post",
    "linkedin_post": "The LinkedIn post",
    "interviewer_prompt": "The interviewer prompt",
    "selected_hook_id": "The chosen opening",
}


class VoiceError(Exception):
    """Something the agent asked for cannot be done. Carries the spoken reason."""

    def __init__(self, code: str, message: str, *, status: int = 409, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def check_actor(by: str | None) -> str:
    actor = by or "ziv"
    if actor not in ACTORS:
        raise VoiceError("bad_actor", f"unknown actor {actor}", status=400)
    return actor


def _clip(text: Any, limit: int = 140) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def _same(a: Any, b: Any) -> bool:
    """Compare two texts the way a listener would: spacing and case do not count."""
    norm = lambda v: " ".join(str(v or "").split()).casefold()  # noqa: E731
    return norm(a) == norm(b)


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------


def field_label(target_type: str, field: str | None) -> str:
    """ "bullets.2" -> "Point 3". The words he would use for the part that changed."""
    path = field or ""
    if target_type == "candidate_brief":
        return BRIEF_LABELS.get(path, path.replace("_", " "))
    name, _, index = path.partition(".")
    if name in ("bullets", "script_phrases") and index.isdigit():
        n = int(index)
        if name == "bullets":
            return f"Point {n + 1}"
        return "The opening line" if n == 0 else f"Script line {n + 1}"
    if name == "bullets":
        return "The points"
    if name == "script_phrases":
        return "The script"
    return PACKET_LABELS.get(path, path.replace("_", " "))


def describe_operation(target_type: str, op: dict[str, Any], titles: dict[str, str]) -> str:
    """One plain sentence for one applied operation."""
    kind = op.get("op")
    if kind in ("set_field", "replace_text"):
        label = field_label(target_type, op.get("field"))
        before = op.get("before")
        after = op.get("after")
        if before in (None, ""):
            return f'{label} now says "{_clip(after)}" (it was empty).'
        return f'{label} now says "{_clip(after)}" (it said "{_clip(before)}").'
    if kind == "choose_hook":
        return "A different opening was chosen."
    if kind == "move_topic":
        move = op.get("after") or {}
        title = titles.get(str(move.get("candidate_id")), "A topic")
        action = move.get("action") or "rank"
        return {
            "first": f"{title} moved to first in the week.",
            "up": f"{title} moved up one place in the week.",
            "down": f"{title} moved down one place in the week.",
            "remove": f"{title} was taken out of the week.",
            "slot": f"{title} moved to the {move.get('slot', 'other')} list.",
        }.get(action, f"{title} moved to place {move.get('rank')} in the week.")
    if kind == "reorder_week":
        return "The week went back to its earlier order."
    if kind == "restore_version":
        return "An earlier wording was restored."
    return f"{kind} was applied."


# ---------------------------------------------------------------------------
# Finding a topic by what he calls it
# ---------------------------------------------------------------------------

_ID_LIKE = re.compile(r"^[0-9a-f-]{4,36}$")


def _tokens(text: str) -> list[str]:
    # \w is Unicode-aware, so a Hebrew title is matched on its own words rather
    # than normalised away to nothing.
    return [t for t in re.findall(r"\w+", (text or "").casefold()) if len(t) >= 2]


def _score(needle: str, title: str) -> float:
    words = _tokens(needle)
    if not words:
        return 0.0
    haystack = " ".join(_tokens(title))
    phrase = " ".join(words)
    if phrase and phrase in haystack:
        return 1.0 + min(len(phrase) / max(len(haystack), 1), 1.0) * 0.5
    have = set(_tokens(title))
    return sum(1 for w in words if w in have) / len(words)


async def _week_ids(db: AsyncSession, ws: uuid.UUID) -> set[str]:
    lineup = await lineup_service.get_lineup(db, ws, lineup_service.week_start_for(None))
    if lineup is None:
        return set()
    return {str(i.candidate_id) for i in await lineup_service.list_items(db, ws, lineup.id)}


async def find_topics(db: AsyncSession, ws: uuid.UUID, query: str) -> dict[str, Any]:
    """Resolve an id, a short id or a title fragment to one topic, or say which ones.

    Put-away ideas are included on purpose: "bring back the one about invoices"
    has to find an idea that is no longer in any list.
    """
    q = (query or "").strip()
    if not q:
        raise VoiceError("empty", "say which topic", status=400)
    result = await db.execute(
        select(TopicCandidate).where(
            TopicCandidate.workspace_id == ws,
            TopicCandidate.origin.notin_(inbox_service.HIDDEN_ORIGINS),
            TopicCandidate.status != "rejected",
        )
    )
    rows = list(result.scalars().all())

    if _ID_LIKE.match(q.lower()):
        hits = [c for c in rows if str(c.id).startswith(q.lower())]
        if len(hits) == 1:
            return {"status": "found", "candidate": hits[0], "candidates": []}

    in_week = await _week_ids(db, ws)
    scored: list[tuple[float, TopicCandidate]] = []
    for c in rows:
        score = _score(q, c.title)
        if score < 0.5:
            continue
        # Ties go to what he is working on, then to what is still live.
        if str(c.id) in in_week:
            score += 0.02
        if c.status != "withdrawn":
            score += 0.01
        scored.append((score, c))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    if not scored:
        return {"status": "none", "candidate": None, "candidates": []}
    top = scored[0][0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    clear = len(scored) == 1 or (top >= 1.0 and second < 1.0) or (top - second) >= 0.34
    if clear:
        return {"status": "found", "candidate": scored[0][1], "candidates": []}
    return {
        "status": "ambiguous",
        "candidate": None,
        "candidates": [c for _, c in scored[:5]],
    }


def candidate_brief_json(c: TopicCandidate) -> dict[str, Any]:
    return {
        "candidate_id": str(c.id),
        "short_id": str(c.id)[:8],
        "title": c.title,
        "status": c.status,
    }


# ---------------------------------------------------------------------------
# Reading one topic
# ---------------------------------------------------------------------------


async def current_packet(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> RecordingPacket | None:
    result = await db.execute(
        select(RecordingPacket)
        .where(
            RecordingPacket.workspace_id == ws,
            RecordingPacket.candidate_id == candidate_id,
        )
        .order_by(RecordingPacket.version.desc())
    )
    return next((p for p in result.scalars().all() if p.status != "superseded"), None)


async def take_in_progress(db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID) -> int | None:
    row = (
        await db.execute(
            select(RecordingSession.packet_version).where(
                RecordingSession.workspace_id == ws,
                RecordingSession.candidate_id == candidate_id,
                RecordingSession.status.in_(TAKE_IN_PROGRESS),
            )
        )
    ).first()
    return None if row is None else int(row[0] or 0)


def script_json(packet: RecordingPacket | None) -> dict[str, Any] | None:
    if packet is None:
        return None
    data = packet_to_json(packet)
    hooks = []
    for n, h in enumerate(data["hook_options"], start=1):
        hooks.append(
            {
                "n": n,
                "id": h.get("id"),
                "text": h.get("text"),
                "chosen": h.get("id") == data["selected_hook_id"],
            }
        )
    phrases = data["script_phrases"]
    return {
        "packet_id": data["id"],
        "version": data["version"],
        "status": data["status"],
        "opening": phrases[0] if phrases else None,
        "points": data["bullets"],
        "script_phrases": phrases,
        "hooks": hooks,
        "google_doc_url": data["google_doc_url"],
    }


async def latest_research(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID
) -> IdeaResearch | None:
    result = await db.execute(
        select(IdeaResearch)
        .where(IdeaResearch.workspace_id == ws, IdeaResearch.candidate_id == candidate_id)
        .order_by(IdeaResearch.created_at.desc())
    )
    return result.scalars().first()


async def topic_detail(
    db: AsyncSession, ws: uuid.UUID, candidate: TopicCandidate
) -> dict[str, Any]:
    brief = await briefs.ensure_brief(db, ws, candidate)
    decision = await inbox_service.get_decision(db, ws, candidate.id)
    packet = await current_packet(db, ws, candidate.id)
    research = await latest_research(db, ws, candidate.id)
    in_week = str(candidate.id) in await _week_ids(db, ws)
    return {
        **candidate_brief_json(candidate),
        "decision": decision.decision if decision else None,
        "in_this_week": in_week,
        "put_away": candidate.status == "withdrawn",
        "brief": {
            "version": brief.version,
            "values": dict(brief.brief or {}),
            "labels": BRIEF_LABELS,
        },
        "script": script_json(packet),
        "research": research_to_json(research) if research else None,
    }


# ---------------------------------------------------------------------------
# Changing: propose and apply in one step
# ---------------------------------------------------------------------------


def _resolve_hook(packet: RecordingPacket, wanted: Any) -> dict[str, Any]:
    options = list(packet.hook_options or [])
    if not options:
        raise VoiceError(
            "no_hooks", "this script has no opening options to choose from", status=409
        )
    text = str(wanted or "").strip()
    if text.isdigit():
        n = int(text)
        if 1 <= n <= len(options):
            return options[n - 1]
    found = next((o for o in options if str(o.get("id")) == text), None)
    if found is None:
        raise VoiceError(
            "unknown_hook",
            f"there is no opening {text}; this script has {len(options)} options",
            status=404,
        )
    return found


async def _fresh(
    db: AsyncSession, ws: uuid.UUID, target_type: str, target_id: uuid.UUID, fields: list[str]
) -> dict[str, Any]:
    """The current text of the fields a failed change was about."""
    try:
        state = await change_service.load_target(db, ws, target_type, target_id)
    except change_service.ChangeError:
        return {}
    out: dict[str, Any] = {"version": state.version}
    for f in fields:
        _, value = change_service._resolve_path(state.values, f)
        out[f] = value
    return out


async def apply_change(
    db: AsyncSession,
    ws: uuid.UUID,
    *,
    candidate_id: uuid.UUID,
    target: str,
    operations: list[dict[str, Any]],
    summary: str,
    by: str = "voice",
) -> dict[str, Any]:
    """Propose and apply at once, attributed to the caller.

    `target` is what he talks about: "brief", "script" or "week". Each operation
    is {op, field, after, expect}. `expect` is the text the agent read back as
    the current one; if the stored text is different by now, nothing is written.

    The read-back is not optional. Replacing text that exists without saying
    what was read is refused with the text as it is now, because the version the
    brain read may be minutes old (a script rewritten in the background, a tap on
    the phone). For choose_hook, `expect` is the opening he heard: the options
    are renumbered when a script is rewritten, so "option 2" alone can name a
    text he never heard.
    """
    actor = check_actor(by)
    candidate = await inbox_service.get_candidate(db, ws, candidate_id)
    if not operations:
        raise VoiceError("empty", "no change was asked for", status=400)

    ops_in: list[change_service.OperationInput] = []
    expectations: list[tuple[str, Any]] = []

    if target == "brief":
        target_type, target_id = "candidate_brief", candidate.id
    elif target == "script":
        packet = await current_packet(db, ws, candidate.id)
        if packet is None:
            raise VoiceError(
                "no_script",
                f'"{candidate.title}" has no script yet. Ask for one first.',
                status=404,
            )
        taking = await take_in_progress(db, ws, candidate.id)
        if taking is not None:
            raise VoiceError(
                "recording",
                "A take is being recorded on this script right now, so it stays as it is "
                "until that recording is finished.",
                status=409,
            )
        target_type, target_id = "packet", packet.id
    elif target == "week":
        lineup = await lineup_service.ensure_lineup(db, ws, lineup_service.week_start_for(None))
        target_type, target_id = "lineup", lineup.id
    else:
        raise VoiceError("bad_target", f"unknown target {target}", status=400)

    for raw in operations:
        op = str(raw.get("op") or "set_field")
        if op == "choose_hook":
            if target_type != "packet":
                raise VoiceError("bad_target", "an opening belongs to the script", status=400)
            hook = _resolve_hook(packet, raw.get("after"))
            heard = raw.get("expect")
            if heard is not None and not _same(hook.get("text"), heard):
                raise VoiceError(
                    "changed",
                    "The opening options changed since you read them. Nothing was written. "
                    "Read him the options as they are now.",
                    status=409,
                    current=[
                        {"n": n, "text": o.get("text")}
                        for n, o in enumerate(packet.hook_options or [], start=1)
                    ],
                    version=packet.version,
                )
            ops_in.append(change_service.OperationInput(op="choose_hook", after=str(hook["id"])))
            phrases = list(packet.script_phrases or [])
            hook_text = str(hook.get("text") or "").strip()
            if phrases and hook_text and phrases[0] != hook_text:
                ops_in.append(
                    change_service.OperationInput(
                        op="set_field", field="script_phrases.0", after=hook_text
                    )
                )
            continue
        if op == "move_topic":
            move = dict(raw.get("after") or {})
            move.setdefault("candidate_id", str(candidate.id))
            ops_in.append(change_service.OperationInput(op="move_topic", after=move))
            continue
        field = str(raw.get("field") or "")
        ops_in.append(change_service.OperationInput(op=op, field=field, after=raw.get("after")))
        if raw.get("expect") is not None or op in ("set_field", "replace_text"):
            expectations.append((field, raw.get("expect")))

    state = await change_service.load_target(db, ws, target_type, target_id)
    for field, expected in expectations:
        exists, value = change_service._resolve_path(state.values, field)
        if expected is None:
            if exists and str(value or "").strip():
                raise VoiceError(
                    "expect_required",
                    f"{field_label(target_type, field)} already says something, and the "
                    "change did not say what you read him. Nothing was written.",
                    status=409,
                    field=field,
                    current=value,
                    version=state.version,
                )
            continue
        if exists and not _same(value, expected):
            raise VoiceError(
                "changed",
                f"{field_label(target_type, field)} was changed since you read it. "
                "Nothing was written.",
                status=409,
                field=field,
                current=value,
                version=state.version,
            )

    change_set = await change_service.propose(
        db,
        ws,
        target_type=target_type,
        target_id=target_id,
        base_version=state.version,
        operations=ops_in,
        summary=summary or "Changed by voice",
        origin="voice",
    )
    issues = (change_set.validation or {}).get("issues") or []
    if change_set.state == "invalid":
        blocking = next(
            (i for i in issues if i["code"] in ("unknown_op", "unknown_field", "bad_value")),
            issues[0] if issues else {"message": "that cannot be changed"},
        )
        raise VoiceError("invalid", blocking["message"], status=400)

    try:
        result = await change_service.apply(db, ws, change_set.id, decided_by=actor)
    except (change_service.ChangeError, lineup_service.LineupError) as error:
        if change_set.state == "proposed":
            # It failed while applying (a topic not in the week, a recorded one),
            # not on a version conflict, which already marked it superseded. Close
            # it, or it waits forever as a change "for a yes or no" that nobody
            # asked for. reject() also resets the operations apply() had marked.
            await change_service.reject(db, ws, change_set.id, decided_by=actor)
        fresh = await _fresh(db, ws, target_type, target_id, [o.field for o in ops_in if o.field])
        raise VoiceError(error.code, error.message, status=error.status, current=fresh) from error

    ops = await change_service.load_operations(db, ws, change_set.id)
    titles = {str(candidate.id): candidate.title}
    rendered = [change_service.operation_to_json(o) for o in ops]
    return {
        "change_set_id": str(change_set.id),
        "short_id": str(change_set.id)[:8],
        "target_type": target_type,
        "candidate_id": str(candidate.id),
        "title": candidate.title,
        "version": result["version"],
        "said": [describe_operation(target_type, o, titles) for o in rendered],
        "changes": [
            {
                "field": o["field"],
                "label": field_label(target_type, o["field"]) if o["field"] else o["op"],
                "before": o["before"],
                "after": o["after"],
            }
            for o in rendered
        ],
        # Not blocking, but worth saying out loud before he records it.
        "warnings": [i["message"] for i in issues if i["code"] == "safety"],
    }


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


def _undo_key(change_set_id: uuid.UUID) -> str:
    return f"undo:{change_set_id}"


async def _undone_by(
    db: AsyncSession, ws: uuid.UUID, change_set_ids: list[uuid.UUID]
) -> dict[str, str]:
    """{original change set id: the applied change set that undid it}."""
    if not change_set_ids:
        return {}
    keys = {_undo_key(i) for i in change_set_ids}
    result = await db.execute(
        select(EditorialChangeSet).where(
            EditorialChangeSet.workspace_id == ws,
            EditorialChangeSet.state == "applied",
            EditorialChangeSet.idempotency_key.like("undo:%"),
        )
    )
    out: dict[str, str] = {}
    for row in result.scalars().all():
        base = ":".join((row.idempotency_key or "").split(":")[:2])
        if base in keys:
            out[base.removeprefix("undo:")] = str(row.id)
    return out


async def _packet_for_change(
    db: AsyncSession, ws: uuid.UUID, change_set: EditorialChangeSet
) -> RecordingPacket:
    row = (
        await db.execute(
            select(RecordingPacket).where(
                RecordingPacket.workspace_id == ws, RecordingPacket.id == change_set.target_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise VoiceError("not_found", "that script is no longer here", status=404)
    return row


async def _check_week_is_back(
    db: AsyncSession, ws: uuid.UUID, lineup_id: uuid.UUID, before_order: list[Any]
) -> None:
    """Say "Undone" only when every topic of the earlier order is in the week again.

    A topic taken out and then put away or rejected is not brought back into the
    week behind his back; the undo is refused instead, and the caller rolls back.
    """
    now = await change_service.load_target(db, ws, "lineup", lineup_id)
    present = {str(e.get("candidate_id")) for e in now.values.get("order") or []}
    missing = [
        str(e.get("candidate_id"))
        for e in before_order
        if isinstance(e, dict) and str(e.get("candidate_id")) not in present
    ]
    if not missing:
        return
    ids: list[uuid.UUID] = []
    for value in missing:
        try:
            ids.append(uuid.UUID(value))
        except ValueError:
            continue
    titles = {
        str(c.id): c.title
        for c in (
            await db.execute(
                select(TopicCandidate).where(
                    TopicCandidate.workspace_id == ws, TopicCandidate.id.in_(ids)
                )
            )
        )
        .scalars()
        .all()
    }
    named = ", ".join(f'"{titles.get(m, "a topic")}"' for m in missing)
    raise VoiceError(
        "not_restored",
        f"{named} cannot go back in the week, because it was put away or dropped since. "
        "Nothing was written.",
        status=409,
        missing=missing,
    )


async def undo_change_set(
    db: AsyncSession, ws: uuid.UUID, change_set_id: uuid.UUID, *, by: str = "voice"
) -> dict[str, Any]:
    """Write the inverse of an applied change set as a new, applied change set.

    Refuses rather than overwrites: if the part it changed has been changed again
    since, the current text comes back and nothing is written.
    """
    actor = check_actor(by)
    try:
        original = await change_service.get_change_set(db, ws, change_set_id)
    except change_service.ChangeError as error:
        raise VoiceError(error.code, error.message, status=error.status) from error
    if original.state != "applied":
        raise VoiceError(
            "not_applied",
            f"That change was never applied (it is {original.state}), so there is nothing to undo.",
            status=409,
        )
    already = (await _undone_by(db, ws, [original.id])).get(str(original.id))
    if already:
        return {
            "change_set_id": already,
            "undid": str(original.id),
            "already": True,
            "said": f'"{original.summary}" was already undone.',
        }

    ops = [
        o for o in await change_service.load_operations(db, ws, original.id) if o.state == "applied"
    ]
    if not ops:
        raise VoiceError("empty", "that change has nothing to undo", status=409)

    inverse: list[change_service.OperationInput] = []
    target_type = original.target_type
    changed_since = lambda label, now: VoiceError(  # noqa: E731
        "changed",
        f"{label} was changed again after that, so undoing it would lose the newer "
        "change. Nothing was written.",
        status=409,
        current=now,
    )

    if target_type == "candidate_brief":
        target_id = original.target_id
        state = await change_service.load_target(db, ws, target_type, target_id)
        values = dict(state.values)
        for op in ops:
            before = (op.before or {}).get("value")
            after = (op.after or {}).get("value")
            if op.op in ("set_field", "replace_text"):
                if not _same(values.get(op.field or ""), after):
                    raise changed_since(
                        field_label(target_type, op.field), values.get(op.field or "")
                    )
                if before is None:
                    values.pop(op.field or "", None)
                else:
                    values[op.field or ""] = before
            elif op.op == "restore_version":
                if state.version != original.applied_version:
                    raise changed_since("The brief", state.values)
                earlier = await briefs.get_version(db, ws, target_id, original.base_version)
                values = dict(earlier.brief or {}) if earlier else values
        inverse.append(
            change_service.OperationInput(
                op="restore_version", after=values, rationale="Undo a change made by voice."
            )
        )
    elif target_type == "packet":
        applied_packet = await _packet_for_change(db, ws, original)
        packet = await current_packet(db, ws, applied_packet.candidate_id)
        if packet is None:
            raise VoiceError("not_found", "that script is no longer here", status=404)
        if await take_in_progress(db, ws, packet.candidate_id) is not None:
            raise VoiceError(
                "recording",
                "A take is being recorded on this script right now, so it cannot change until "
                "that recording is finished.",
                status=409,
            )
        target_id = packet.id
        state = await change_service.load_target(db, ws, target_type, target_id)
        for op in ops:
            before = (op.before or {}).get("value")
            after = (op.after or {}).get("value")
            if op.op in ("set_field", "replace_text"):
                exists, now = change_service._resolve_path(state.values, op.field or "")
                if not exists or not _same(now, after):
                    raise changed_since(field_label(target_type, op.field), now)
                inverse.append(
                    change_service.OperationInput(
                        op="set_field", field=op.field, after="" if before is None else before
                    )
                )
            elif op.op == "choose_hook":
                if state.values.get("selected_hook_id") != after:
                    raise changed_since("The chosen opening", state.values.get("selected_hook_id"))
                if before:
                    inverse.append(change_service.OperationInput(op="choose_hook", after=before))
    elif target_type == "lineup":
        target_id = original.target_id
        state = await change_service.load_target(db, ws, target_type, target_id)
        if state.version != original.applied_version:
            raise changed_since("The week", state.values.get("order"))
        before_order = next(
            (
                (o.before or {}).get("value")
                for o in ops
                if isinstance((o.before or {}).get("value"), list)
            ),
            None,
        )
        if before_order is None:
            raise VoiceError(
                "no_before",
                "the order before that move was not recorded, so it cannot be undone",
                status=409,
            )
        inverse.append(change_service.OperationInput(op="reorder_week", after=before_order))
    else:
        raise VoiceError("unsupported", f"cannot undo a {target_type} change", status=400)

    if not inverse:
        raise VoiceError("empty", "there is nothing to put back", status=409)

    undo_set = await change_service.propose(
        db,
        ws,
        target_type=target_type,
        target_id=target_id,
        base_version=state.version,
        operations=inverse,
        summary=f"Undo: {original.summary}",
        rationale=f"Undoes change {str(original.id)[:8]}.",
        origin="undo",
        idempotency_key=f"{_undo_key(original.id)}:{uuid.uuid4().hex[:8]}",
    )
    if undo_set.state == "invalid":
        issues = (undo_set.validation or {}).get("issues") or []
        raise VoiceError(
            "invalid", issues[0]["message"] if issues else "that cannot be undone", status=409
        )
    result = await change_service.apply(db, ws, undo_set.id, decided_by=actor)
    if target_type == "lineup":
        await _check_week_is_back(db, ws, target_id, inverse[0].after)
    return {
        "change_set_id": str(undo_set.id),
        "undid": str(original.id),
        "already": False,
        "version": result["version"],
        "said": f'Undone: "{original.summary}".',
    }


# ---------------------------------------------------------------------------
# Putting an idea away and bringing it back
# ---------------------------------------------------------------------------


# The word the decide route takes, and answers with as `previous_decision`, for
# "no decision". Undoing a first decision is then one more decide call, like
# undoing any other: decide the previous one.
UNDECIDED = "undecided"


async def clear_decision(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID, *, by: str = "voice"
) -> TopicDecision | None:
    """Take a decision back to undecided. The row, and the note on it, stay.

    Deleting the row was how "undecided" used to be written, and it took the
    note he wrote while deciding with it. `previous_decision` keeps what it was.
    """
    actor = check_actor(by)
    candidate = await inbox_service.get_candidate(db, ws, candidate_id)
    row = await inbox_service.get_decision(db, ws, candidate_id)
    if row is not None and row.decision is not None:
        row.previous_decision = row.decision
        row.decision = None
        row.decided_by = actor
        row.decided_at = _now()
    if candidate.status == "withdrawn":
        candidate.status = "proposed"
    await db.flush()
    return row


async def restore_topic(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID, *, by: str = "voice"
) -> dict[str, Any]:
    """Bring a put-away idea back to where it was before it was put away.

    Where it was includes its place in this week's list, when putting it away
    took it off that list.
    """
    actor = check_actor(by)
    candidate = await inbox_service.get_candidate(db, ws, candidate_id)
    decision = await inbox_service.get_decision(db, ws, candidate_id)
    back_to: str | None = None
    placed: dict[str, Any] | None = None
    if decision is not None and decision.decision == "away":
        previous = decision.previous_decision
        if previous and previous != "away":
            decision = await inbox_service.decide(
                db, ws, candidate_id, decision=previous, decided_by=actor
            )
            back_to = previous
        else:
            # It was never decided before it went away: back to undecided,
            # keeping the row and the note on it.
            decision = await clear_decision(db, ws, candidate_id, by=actor)
        week = await lineup_service.follow_decision(db, ws, candidate, decision, by=actor)
        placed = week["placed"]
    elif candidate.status != "withdrawn":
        return {
            "candidate_id": str(candidate.id),
            "title": candidate.title,
            "restored": False,
            "said": f'"{candidate.title}" is not put away.',
        }
    if candidate.status == "withdrawn":
        candidate.status = "proposed"
    await db.flush()
    in_week = "back in this week's list"
    if placed is not None:
        in_week += ", in reserve" if placed["slot"] == "reserve" else f", place {placed['rank']}"
    where = {
        "this_week": in_week,
        "discuss": "back, marked to think about",
        "later": "back in saved for later",
    }.get(back_to or "", "back with the ideas waiting for a decision")
    return {
        "candidate_id": str(candidate.id),
        "title": candidate.title,
        "restored": True,
        "decision": back_to,
        "placed": placed,
        "said": f'"{candidate.title}" is {where}.',
    }


# ---------------------------------------------------------------------------
# What the voice agent changed
# ---------------------------------------------------------------------------


async def activity(db: AsyncSession, ws: uuid.UUID, *, hours: int = 24) -> dict[str, Any]:
    """Everything the voice agent wrote in the window, newest first, in plain words."""
    since = _now() - timedelta(hours=hours)
    result = await db.execute(
        select(EditorialChangeSet).where(
            EditorialChangeSet.workspace_id == ws,
            EditorialChangeSet.state == "applied",
            EditorialChangeSet.created_at >= since,
        )
    )
    sets = [
        cs
        for cs in result.scalars().all()
        if cs.origin == "voice" or (cs.origin == "undo" and cs.decided_by == "voice")
    ]
    undone = await _undone_by(db, ws, [cs.id for cs in sets])

    decisions = list(
        (
            await db.execute(
                select(TopicDecision).where(
                    TopicDecision.workspace_id == ws,
                    TopicDecision.decided_by == "voice",
                    TopicDecision.decided_at >= since,
                )
            )
        )
        .scalars()
        .all()
    )

    # Titles for every topic mentioned, in one query.
    packet_ids = [cs.target_id for cs in sets if cs.target_type == "packet"]
    packet_to_candidate: dict[str, uuid.UUID] = {}
    if packet_ids:
        rows = await db.execute(
            select(RecordingPacket.id, RecordingPacket.candidate_id).where(
                RecordingPacket.workspace_id == ws, RecordingPacket.id.in_(packet_ids)
            )
        )
        packet_to_candidate = {str(pid): cid for pid, cid in rows}
    ops_by: dict[str, list[dict[str, Any]]] = {}
    wanted: set[uuid.UUID] = {d.candidate_id for d in decisions}
    for cs in sets:
        ops = [
            change_service.operation_to_json(o)
            for o in await change_service.load_operations(db, ws, cs.id)
        ]
        ops = [o for o in ops if o["state"] == "applied"]
        ops_by[str(cs.id)] = ops
        if cs.target_type == "candidate_brief":
            wanted.add(cs.target_id)
        elif cs.target_type == "packet" and str(cs.target_id) in packet_to_candidate:
            wanted.add(packet_to_candidate[str(cs.target_id)])
        for o in ops:
            if o["op"] == "move_topic" and isinstance(o["after"], dict):
                try:
                    wanted.add(uuid.UUID(str(o["after"].get("candidate_id"))))
                except ValueError:
                    pass
    titles: dict[str, str] = {}
    statuses: dict[str, str] = {}
    if wanted:
        rows = await db.execute(
            select(TopicCandidate).where(
                TopicCandidate.workspace_id == ws, TopicCandidate.id.in_(list(wanted))
            )
        )
        for c in rows.scalars().all():
            titles[str(c.id)] = c.title
            statuses[str(c.id)] = c.status

    items: list[dict[str, Any]] = []
    for cs in sets:
        if cs.target_type == "candidate_brief":
            cid = str(cs.target_id)
        elif cs.target_type == "packet":
            cid = str(packet_to_candidate.get(str(cs.target_id)) or "") or None
        else:
            cid = None
        ops = ops_by[str(cs.id)]
        when = cs.applied_at or cs.created_at
        is_undo = cs.origin == "undo"
        items.append(
            {
                "kind": "change",
                "id": str(cs.id),
                "short_id": str(cs.id)[:8],
                "at": when.isoformat() if when else None,
                "summary": cs.summary,
                "target_type": cs.target_type,
                "candidate_id": cid,
                "title": titles.get(cid or "", "This week" if cs.target_type == "lineup" else ""),
                "lines": [describe_operation(cs.target_type, o, titles) for o in ops],
                "is_undo": is_undo,
                "undone": str(cs.id) in undone,
                "can_undo": str(cs.id) not in undone,
            }
        )
    for d in decisions:
        cid = str(d.candidate_id)
        title = titles.get(cid, "An idea")
        words = {
            "this_week": f'Put "{title}" in this week.',
            "discuss": f'Marked "{title}" to think about.',
            "later": f'Saved "{title}" for later.',
            "away": f'Put "{title}" away.',
            None: f'Put "{title}" back with the ideas waiting for a decision.',
        }.get(d.decision, f'Decided "{title}": {d.decision}.')
        items.append(
            {
                "kind": "decision",
                "id": str(d.id),
                "at": d.decided_at.isoformat() if d.decided_at else None,
                "candidate_id": cid,
                "title": title,
                "decision": d.decision,
                "lines": [words],
                "can_restore": d.decision == "away" and statuses.get(cid) == "withdrawn",
            }
        )
    items.sort(key=lambda i: i["at"] or "", reverse=True)
    return {"hours": hours, "items": items, "count": len(items)}


# ---------------------------------------------------------------------------
# Research, in the background
# ---------------------------------------------------------------------------


def make_searcher() -> Any:
    """The web search, or None. Replaced in tests; never called at import time."""
    from tce.services.web_search import WebSearchService

    return WebSearchService()


def research_to_json(row: IdeaResearch) -> dict[str, Any]:
    return {
        "research_id": str(row.id),
        "short_id": str(row.id)[:8],
        "candidate_id": str(row.candidate_id),
        "state": row.state,
        "requested_by": row.requested_by,
        "query": row.query,
        "web_status": row.web_status,
        "summary": row.summary,
        "detail": row.detail,
        "evidence": list(row.evidence or []),
        "web": list(row.web or []),
        "started_at": row.created_at.isoformat() if row.created_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


async def start_research(
    db: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID, *, by: str = "voice"
) -> tuple[IdeaResearch, bool]:
    """Start research, or return the one already running. (row, created)."""
    actor = check_actor(by)
    candidate = await inbox_service.get_candidate(db, ws, candidate_id)
    running = (
        (
            await db.execute(
                select(IdeaResearch).where(
                    IdeaResearch.workspace_id == ws,
                    IdeaResearch.candidate_id == candidate.id,
                    IdeaResearch.state == "running",
                )
            )
        )
        .scalars()
        .first()
    )
    if running is not None:
        return running, False
    row = IdeaResearch(
        workspace_id=ws,
        candidate_id=candidate.id,
        state="running",
        requested_by=actor,
        query=candidate.title[:500],
        evidence=[],
        web=[],
        web_status="skipped",
    )
    db.add(row)
    await db.flush()
    return row, True


async def gather_evidence(
    db: AsyncSession, ws: uuid.UUID, candidate: TopicCandidate, *, limit: int = 12
) -> list[dict[str, Any]]:
    """His own calls and commits behind the idea, most specific first."""
    raw_ids = list(candidate.moment_ids or []) + [
        c.get("moment_id") for c in (candidate.citations_private or []) if isinstance(c, dict)
    ]
    ids: list[uuid.UUID] = []
    for value in raw_ids:
        try:
            parsed = uuid.UUID(str(value))
        except (TypeError, ValueError):
            continue
        if parsed not in ids:
            ids.append(parsed)
    found: list[dict[str, Any]] = []
    if ids:
        rows = await db.execute(
            select(EvidenceMoment, EvidenceSource)
            .join(EvidenceSource, EvidenceSource.id == EvidenceMoment.source_id)
            .where(EvidenceMoment.workspace_id == ws, EvidenceMoment.id.in_(ids))
        )
        for moment, source in rows.all():
            found.append(
                {
                    "moment_id": str(moment.id),
                    "source_kind": source.source_kind,
                    "title": source.title,
                    "occurred_at": source.occurred_at.isoformat() if source.occurred_at else None,
                    "excerpt": _clip(moment.excerpt_private, 300),
                    "lesson": _clip(moment.lesson_summary, 200),
                }
            )
    if not found:
        # The moments may have been pruned; the citations still say where it came from.
        for c in candidate.citations_private or []:
            if isinstance(c, dict):
                found.append(
                    {
                        "moment_id": c.get("moment_id"),
                        "source_kind": c.get("source_kind"),
                        "title": c.get("title"),
                        "occurred_at": None,
                        "excerpt": _clip(c.get("span"), 300),
                        "lesson": "",
                    }
                )
    return found[:limit]


def _summary(
    title: str, evidence: list[dict[str, Any]], web: list[dict[str, Any]], web_status: str
) -> str:
    calls = sum(
        1
        for e in evidence
        if "meeting" in str(e.get("source_kind") or "") or "call" in str(e.get("source_kind") or "")
    )
    commits = sum(
        1
        for e in evidence
        if "commit" in str(e.get("source_kind") or "")
        or "github" in str(e.get("source_kind") or "")
    )
    other = len(evidence) - calls - commits
    parts = []
    if calls:
        parts.append(f"{calls} from your calls")
    if commits:
        parts.append(f"{commits} from your commits")
    if other:
        parts.append(f"{other} other")
    own = (
        f"{len(evidence)} pieces of your own evidence ({', '.join(parts)})"
        if evidence
        else "none of your own evidence (TCE holds no calls or commits linked to it)"
    )
    web_words = {
        "searched": f"{len(web)} web results",
        "no_key": "no web search, because web search is not set up on TCE (no search key), "
        "so this is your own evidence only",
        "failed": "no web search, because the search failed this time, so this is your own "
        "evidence only",
        "skipped": "no web search",
    }[web_status]
    return f'Research on "{title}" is ready: {own}, and {web_words}.'


async def run_research(sm: Any, ws: uuid.UUID, research_id: uuid.UUID) -> None:
    """The background half. Never raises: a failure is written onto the row."""
    async with open_session(sm) as db:
        row = (
            await db.execute(
                select(IdeaResearch).where(
                    IdeaResearch.workspace_id == ws, IdeaResearch.id == research_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return
        try:
            candidate = await inbox_service.get_candidate(db, ws, row.candidate_id)
            evidence = await gather_evidence(db, ws, candidate)
            web: list[dict[str, Any]] = []
            searcher = make_searcher()
            if searcher is None or not getattr(searcher, "api_key", None):
                web_status = "no_key"
            else:
                try:
                    hits = await searcher.search(row.query or candidate.title, count=5)
                    web = [
                        {
                            "title": h.get("title"),
                            "url": h.get("url"),
                            "description": _clip(h.get("description"), 300),
                            "age": h.get("age"),
                        }
                        for h in hits or []
                    ]
                    web_status = "searched"
                except Exception as error:  # the web half must not sink the evidence half
                    logger.warning("voice.research_web_failed", error=type(error).__name__)
                    web_status = "failed"
            row.evidence = evidence
            row.web = web
            row.web_status = web_status
            row.summary = _summary(candidate.title, evidence, web, web_status)
            row.state = "done"
        except Exception as error:
            logger.exception("voice.research_failed", research_id=str(research_id))
            row.state = "failed"
            row.detail = f"{type(error).__name__}: {_clip(error, 300)}"
            row.summary = "The research stopped with an error. Nothing else was changed."
        row.finished_at = _now()
        await db.commit()
