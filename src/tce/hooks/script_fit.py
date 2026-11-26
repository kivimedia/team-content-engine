"""The script opens on the hook (T-25711).

When a hook from the library is put on one of the week's videos (by TCE or by him),
the script writer writes one new opening for that hook (a number said out loud for
Big number, a before and an after for Split screen) and the whole script is rewritten
to follow it, through the same path as choosing an opening on the recording screen
(T-24293). The opening it replaces stays on the list, so he can switch back exactly.

Nothing changes under a take set that is already being recorded: the opening is
frozen there, and the line on the hook says so. Every outcome is written on the pick
in plain words, so the hook library and the recording screen can say what happened.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select

from tce.editorial.common import open_session
from tce.editorial.packets import choose_hook_with_script, more_hook_options
from tce.hooks import library
from tce.hooks.catalog import BY_ID
from tce.models.editorial import RecordingPacket

logger = structlog.get_logger()


async def _current_packet(sm: Any, ws: uuid.UUID, candidate_id: str) -> RecordingPacket | None:
    try:
        cid = uuid.UUID(str(candidate_id))
    except ValueError:
        return None
    async with open_session(sm) as db:
        return (
            await db.execute(
                select(RecordingPacket)
                .where(
                    RecordingPacket.workspace_id == ws,
                    RecordingPacket.candidate_id == cid,
                    RecordingPacket.status != "superseded",
                )
                .order_by(RecordingPacket.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


def _words(detail: str | None) -> str:
    text = (detail or "").strip().rstrip(".")
    return text[:1].upper() + text[1:] if text else "The writer did not answer"


async def fit_script(sm: Any, ws: uuid.UUID, week: str, candidate_id: str, hook_id: str) -> dict[str, Any]:
    """Write an opening for this hook on this video and make the script follow it.

    Returns the state written on the pick: {"state": fitted|kept|none, "detail": ...}.
    """
    hook = BY_ID.get(hook_id)
    if hook is None:
        return {"state": "none", "detail": "That hook is not in the library."}

    async def say(state: str, detail: str, **extra: Any) -> dict[str, Any]:
        await library.set_script(ws, week, hook_id, candidate_id, state, detail, **extra)
        return {"state": state, "detail": detail, **extra}

    packet = await _current_packet(sm, ws, candidate_id)
    if packet is None:
        return await say("none", "This video has no script yet, so there is no opening to fit.")
    await say("writing", f"Writing an opening for {hook.name} and the script to follow it.")
    try:
        more = await more_hook_options(sm, ws, packet.id, wanted=1, visual_hook=hook)
    except Exception as exc:  # the pick stays; only the script is unchanged
        logger.exception("hooks.fit_script_failed", hook=hook_id, candidate=str(candidate_id))
        return await say("kept", f"The script kept its opening: the writer stopped ({type(exc).__name__}). Pick the hook again to retry.")
    if more.status != "ok" or not more.packet:
        return await say("kept", f"The script kept its opening: {_words(more.detail)}.")
    before = {str(h.get("id")) for h in (packet.hook_options or [])}
    fresh = [h for h in more.packet.get("hook_options", []) if str(h.get("id")) not in before]
    if not fresh:
        return await say("kept", "The script kept its opening: no new opening came back for this hook.")
    opening = fresh[-1]
    try:
        chosen = await choose_hook_with_script(sm, ws, more.packet["id"], str(opening["id"]))
    except Exception as exc:
        logger.exception("hooks.fit_script_choose_failed", hook=hook_id, candidate=str(candidate_id))
        chosen = None
        reason = type(exc).__name__
    else:
        reason = _words(chosen.detail)
    if chosen is not None and chosen.status == "ok":
        return await say(
            "fitted",
            f"The script now opens with “{opening.get('text', '')}”, written for {hook.name}, and the rest follows it.",
            opening=str(opening.get("text") or ""),
        )
    return await say(
        "kept",
        f"An opening for {hook.name} is ready to choose on the recording screen (“{opening.get('text', '')}”); "
        f"the script kept its opening: {reason}.",
        opening=str(opening.get("text") or ""),
    )
