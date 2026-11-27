"""TCE writes the format's script from the video's topic, for him to review (T-25834).

When a trend format is put on one of the week's videos, the writer gets the format's
steps (what each part does) and that video's topic and current script, and writes
one line per step: for good, better, best an opening that names the one thing, a
line that starts with Good, one with Better, one with Best, each with a one or two
word name for the point, and a closing line. It reshapes what the script already
says and invents nothing (no numbers, clients or results that are not in it).

The answer is saved on the pick as a draft ("ready"). He reads it on the hook
studio, can change any line, and accepts it ("approved"); the recording cards say
each line on its step. The video's own script and its takes are not touched.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import structlog

from tce import llm as _llm
from tce.hooks import format_library, script_fit
from tce.hooks.formats import BY_ID, Format
from tce.llm import LLMRequest

logger = structlog.get_logger()

JOB_TYPE = "format_script"
AGENT = "format_writer"
PROMPT_VERSION = "format_script.v1"
NAME_MAX = 24

SYSTEM = """\
You write the script of one short talking video in a trending format. The
speaker records it to a phone in one take, so every line is said out loud, in
plain spoken words, one breath each.

- Write exactly one line per step, for the steps given, in their order.
- Use only what the topic and its current script say. Never invent numbers,
  clients, results, tools or stories that are not in them.
- A step that names a word to start with starts its line with exactly that
  word, then the point, like "Good: you send a price list." Give that point a
  name of one or two words, as it would sit on a list.
- Every line is under 25 words. The opening line names the one thing and does
  not say the format's words yet. The close is one line, then stop.
- Same language as the current script. No hype, no long dashes, no emojis.

Return only JSON matching the schema."""


def schema(fmt: Format) -> dict[str, Any]:
    step_ids = [s.id for s in fmt.steps]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["steps"],
        "properties": {
            "steps": {
                "type": "array",
                "minItems": len(step_ids),
                "maxItems": len(step_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["step", "line", "name"],
                    "properties": {
                        "step": {"type": "string", "enum": step_ids},
                        "line": {"type": "string"},
                        "name": {"type": "string"},
                    },
                },
            }
        },
    }


def build_prompt(fmt: Format, topic: dict[str, Any], script_lines: list[str]) -> str:
    steps = [
        {
            "step": s.id,
            "what_this_line_does": s.does,
            **({"start_the_line_with": s.word.capitalize()} if s.word else {}),
        }
        for s in fmt.steps
    ]
    return "\n\n".join(
        [
            "THE FORMAT:\n" + json.dumps({"name": fmt.name, "what_it_is": fmt.what}, indent=1),
            "THE STEPS (one line each, in this order):\n" + json.dumps(steps, indent=1),
            "THE TOPIC:\n" + json.dumps(
                {
                    "title": topic.get("title") or "",
                    "big_idea": topic.get("big_idea") or "",
                    "why_it_is_this_week": topic.get("reason") or "",
                },
                indent=1,
            ),
            "ITS CURRENT SCRIPT (what is true and can be said; reshape it, add nothing):\n"
            + ("\n".join(f"- {line}" for line in script_lines if str(line).strip()) or "(no script yet: use only the topic)"),
        ]
    )


def _tidy(text: Any) -> str:
    return " ".join(str(text or "").replace("—", "-").replace("–", "-").split())


def clean(fmt: Format, answer: Any) -> tuple[dict[str, str], dict[str, str]] | None:
    """The writer's lines and point names by step, checked, or None when it gave no
    usable script. A beat line that does not start with its word gets it in front,
    so the edit can find the word in the take."""
    rows = answer.get("steps") if isinstance(answer, dict) else None
    if not isinstance(rows, list):
        return None
    by_step = {str(r.get("step")): r for r in rows if isinstance(r, dict)}
    lines: dict[str, str] = {}
    names: dict[str, str] = {}
    for step in fmt.steps:
        row = by_step.get(step.id)
        line = _tidy((row or {}).get("line"))
        if not line or len(line) > format_library.LINE_MAX:
            return None
        if step.word and not re.match(rf"^{re.escape(step.word)}\b", line, re.I):
            line = f"{step.word.capitalize()}: {line[:1].lower() + line[1:]}"
        lines[step.id] = line
        name = _tidy((row or {}).get("name")).strip(".:")
        if step.word and name:
            names[step.id] = name[:NAME_MAX]
    return lines, names


async def _topic_script(sm: Any, ws: uuid.UUID, candidate_id: str) -> list[str]:
    try:
        packet = await script_fit._current_packet(sm, ws, candidate_id)
    except Exception:  # noqa: BLE001 - no packet means the topic alone is the source
        logger.info("hooks.format_script_no_packet", candidate=str(candidate_id))
        return []
    if packet is None:
        return []
    return [str(p) for p in (packet.script_phrases or []) if str(p).strip()]


async def fill(sm: Any, ws: uuid.UUID, week: str, format_id: str, candidate_id: str, topic: dict[str, Any]) -> dict[str, Any]:
    """Write the format's script for this video and save it on the pick for review."""
    fmt = BY_ID.get(format_id)
    if fmt is None:
        return {"state": "failed", "detail": "That format is not in the studio."}

    async def say(state: str, detail: str, **extra: Any) -> dict[str, Any]:
        script = {"state": state, "detail": detail, **extra}
        await format_library.set_script(ws, week, format_id, candidate_id, script)
        return script

    await say("writing", f"Writing the {fmt.name} script from this video's topic.")
    script_lines = await _topic_script(sm, ws, candidate_id)
    request = LLMRequest(
        job_type=JOB_TYPE,
        agent_name=AGENT,
        messages=[{"role": "user", "content": build_prompt(fmt, topic, script_lines)}],
        system=SYSTEM,
        output_schema=schema(fmt),
        max_tokens=900,
        prompt_version=PROMPT_VERSION,
        workspace_id=ws,
        idempotency_key=f"format-script:{ws}:{week}:{format_id}:{candidate_id}:{uuid.uuid4()}",
    )
    try:
        result = await _llm.complete(request)
    except Exception as exc:  # busy, parked or failed: the pick stays, he can ask again
        logger.info("hooks.format_script_unavailable", format=format_id, error=type(exc).__name__)
        return await say("failed", f"The writer did not answer ({type(exc).__name__}). Press Write it again.")
    answer = result.structured if isinstance(result.structured, dict) else None
    if answer is None:
        try:
            answer = json.loads(result.text)
        except (TypeError, ValueError):
            answer = None
    cleaned = clean(fmt, answer)
    if cleaned is None:
        return await say("failed", "The writer's script did not fit the format. Press Write it again.")
    lines, names = cleaned
    source = "its script" if script_lines else "its topic (it has no script yet)"
    return await say(
        "ready", f"Written from {source}. Read it, change any line, then accept it.", lines=lines, names=names,
    )
