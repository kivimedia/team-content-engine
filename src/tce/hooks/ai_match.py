"""The AI picks the video for a hook (T-25711).

Picking a hook puts it on a video at once with the word rule in catalog.py, so the
page never waits. Then, in the background, the writer reads this week's videos and
the hook and chooses the video it fits best, with one plain line saying why. If it
chooses another video, the pick moves there (unless he moved it himself meanwhile),
and the script is then fitted to the hook on the video it ended on.

A pick he placed himself is never moved. When the writer is busy or answers with
a video that is not on this week's list, the word rule's choice stays.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from tce import llm as _llm
from tce.hooks import library, script_fit
from tce.hooks.catalog import BY_ID, Hook
from tce.llm import LLMRequest

logger = structlog.get_logger()

MATCH_JOB_TYPE = "hook_video_match"
MATCH_AGENT = "hook_matcher"
MATCH_PROMPT_VERSION = "hook_match.v1"

MATCH_SYSTEM = """\
You choose which of this week's videos a visual opening (a hook) goes on. Ziv
records short talking videos; the hook is what the viewer sees in the first two
seconds, and it only works when the topic gives it something real to show.

- Choose exactly one video from the list, by its candidate_id copied verbatim.
- Prefer the video whose topic gives this hook the most to work with (what the
  first line must give it is stated). Prefer a video with no hook yet when two fit
  about equally.
- "why" is one plain sentence under 25 words that names what in that video makes
  the hook land. No hype, no long dashes, nothing invented about the video.

Return only JSON matching the schema."""

MATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidate_id", "why"],
    "properties": {"candidate_id": {"type": "string"}, "why": {"type": "string"}},
}


def build_prompt(hook: Hook, videos: list[dict[str, Any]], hooks_on: dict[str, list[str]]) -> str:
    listed = [
        {
            "candidate_id": v["candidate_id"],
            "title": v.get("title") or "",
            "big_idea": v.get("big_idea") or "",
            "why_it_is_this_week": v.get("reason") or "",
            "hooks_already_on_it": hooks_on.get(v["candidate_id"], []),
        }
        for v in videos
    ]
    return "\n\n".join(
        [
            "THE HOOK:\n" + json.dumps(
                {"name": hook.name, "what_the_viewer_sees": hook.what, "the_first_line_must_give_it": hook.script_need},
                indent=1,
            ),
            "THIS WEEK'S VIDEOS:\n" + json.dumps(listed, indent=1),
        ]
    )


def _clean_why(text: str) -> str:
    why = " ".join(str(text or "").replace("\u2014", "-").replace("\u2013", "-").split())
    if len(why) > 220:
        why = why[:217].rsplit(" ", 1)[0] + "..."
    if why and why[-1] not in ".!?":
        why += "."
    return why


async def ai_place(
    ws: uuid.UUID, week: str, hook: Hook, videos: list[dict[str, Any]], hooks_on: dict[str, list[str]]
) -> tuple[str, str] | None:
    """The writer's choice (candidate_id, why), or None when it gave none we can use."""
    if len(videos) < 2:
        return None
    request = LLMRequest(
        job_type=MATCH_JOB_TYPE,
        agent_name=MATCH_AGENT,
        messages=[{"role": "user", "content": build_prompt(hook, videos, hooks_on)}],
        system=MATCH_SYSTEM,
        output_schema=MATCH_SCHEMA,
        max_tokens=400,
        prompt_version=MATCH_PROMPT_VERSION,
        workspace_id=ws,
        idempotency_key=f"hook-match:{ws}:{week}:{hook.id}:{uuid.uuid4()}",
    )
    try:
        result = await _llm.complete(request)
    except Exception as exc:  # busy, parked or failed: the word rule's choice stays
        logger.info("hooks.ai_match_unavailable", hook=hook.id, error=type(exc).__name__)
        return None
    answer = result.structured if isinstance(result.structured, dict) else None
    if answer is None:
        try:
            answer = json.loads(result.text)
        except (TypeError, ValueError):
            return None
    chosen = str(answer.get("candidate_id") or "").strip()
    why = _clean_why(answer.get("why") or "")
    if chosen not in {v["candidate_id"] for v in videos} or not why:
        return None
    return chosen, why


async def match_and_fit(sm: Any, ws: uuid.UUID, week: str, hook_id: str, lineup: dict[str, Any]) -> None:
    """Background step after a pick TCE placed: AI choice of video, then the script."""
    hook = BY_ID.get(hook_id)
    if hook is None:
        return
    entry = next((p for p in library.read_store(ws)["weeks"].get(week, []) if p.get("hook_id") == hook_id), None)
    if entry is None or not entry.get("candidate_id"):
        return
    placed = entry["candidate_id"]
    if entry.get("chosen_by") == "tce":
        videos = library.week_videos(lineup)
        hooks_on: dict[str, list[str]] = {}
        for other in library.read_store(ws)["weeks"].get(week, []):
            other_hook = BY_ID.get(other.get("hook_id"))
            if other_hook is not None and other.get("hook_id") != hook_id and other.get("candidate_id"):
                hooks_on.setdefault(other["candidate_id"], []).append(other_hook.name)
        choice = await ai_place(ws, week, hook, videos, hooks_on)
        if choice is not None:
            chosen, why = choice
            if await library.repoint(ws, week, hook_id, placed, chosen, why):
                placed = chosen
    await script_fit.fit_script(sm, ws, week, placed, hook_id)
