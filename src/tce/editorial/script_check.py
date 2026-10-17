"""The script check (T-13569): a written script is scored against his own lines before he sees it.

One subscription job reads the finished script next to the stretches of his own speech
the writer was shown, names up to three phrases that do not sound like him ("this
opening sounds like a coach, not like you") and gives one rewrite per named slip, in
his register. The rewrites replace those phrases in place, so phrase ids, openings and
beats keep pointing at the same lines. It runs once, never loops, and never blocks a
script: if the job is unavailable, answers badly, or a rewrite would fail the packet
rules, the script goes through as written with the slips noted for him to see.

Off with TCE_SCRIPT_SLIP_CHECK=0.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

from tce import llm as _llm
from tce.llm import LLMRequest, LLMUnavailable

JOB_TYPE = "recording_script_slips"
AGENT_NAME = "recording_slip_checker"
PROMPT_VERSION = "recording_script_slips.v1"
MAX_SLIPS = 3

SYSTEM = """\
You are the last reader of Ziv Raviv's recording scripts before he sees them. You know
how he really talks from the stretches of his own speech you are given. Find up to three
phrases in the script that do NOT sound like him, and name each slip in plain words the
way an editor who knows him would: "this opening sounds like a coach, not like you",
"he would never say 'unlock'", "a list where he would tell it as a story".

Never name p001: the opening is judged by a separate pass and must stay as written.

Slips to look for: coach or guru register, motivational filler, the curiosity gap
("here is why", "what nobody tells you", any question that withholds the answer),
corporate or marketing words he avoids, tidy three-part lists, an example that is not
his, a phrase longer than he would say in one breath.

For each slip give a rewrite of that ONE phrase in his register: same job in the
script, same meaning, never quoting his samples, no invented facts, no call to action,
no question marks unless the original had one, no dashes. If the script already sounds
like him, return no slips. Do not flag a phrase just to flag something.

Return only JSON matching the schema."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["slips"],
    "properties": {
        "slips": {
            "type": "array",
            "maxItems": MAX_SLIPS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["phrase_id", "slip", "rewrite"],
                "properties": {
                    "phrase_id": {"type": "string"},
                    "slip": {"type": "string"},
                    "rewrite": {"type": "string"},
                },
            },
        },
    },
}

_DASH = re.compile("[—–]|--")


def enabled() -> bool:
    return os.environ.get("TCE_SCRIPT_SLIP_CHECK", "1").strip() != "0"


def phrase_id(index: int) -> str:
    return f"p{index:03d}"


def build_prompt(voice_spec: str, voice_block: str, title: str, phrases: list[str]) -> str:
    script = [{"id": phrase_id(i), "text": t} for i, t in enumerate(phrases, start=1)]
    parts = ["HIS VOICE (the rules):\n" + (voice_spec or "(none)")]
    if voice_block:
        parts.append(voice_block)
    parts.append("THE IDEA:\n" + title)
    parts.append("THE SCRIPT AS WRITTEN:\n" + json.dumps(script, indent=1))
    return "\n\n".join(parts)


def usable_slips(payload: Any, phrases: list[str]) -> list[dict[str, Any]]:
    """The slips that name a real phrase, once each, with a rewrite that is a plain phrase."""
    if not isinstance(payload, dict) or not isinstance(payload.get("slips"), list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in payload["slips"][:MAX_SLIPS]:
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("phrase_id") or "")
        m = re.fullmatch(r"p(\d{3})", pid)
        index = int(m.group(1)) if m else 0
        slip = str(raw.get("slip") or "").strip()
        rewrite = str(raw.get("rewrite") or "").strip()
        if not (2 <= index <= len(phrases)) or index in seen or not slip or not rewrite:
            continue
        if _DASH.search(rewrite) or _DASH.search(slip) or "\n" in rewrite:
            continue
        if rewrite == phrases[index - 1].strip():
            continue
        seen.add(index)
        out.append(
            {
                "phrase_id": pid,
                "index": index,
                "was": phrases[index - 1],
                "slip": slip,
                "rewrite": rewrite,
            }
        )
    return out


def apply_rewrites(phrases: list[str], slips: list[dict[str, Any]]) -> list[str]:
    new = list(phrases)
    for s in slips:
        new[s["index"] - 1] = s["rewrite"]
    return new


async def check_script(
    *, ws: Any, candidate_id: Any, title: str, phrases: list[str], voice_spec: str, voice_block: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the check once. Returns (usable slips, a report for the packet). Never raises."""
    if not enabled():
        return [], {"status": "off"}
    try:
        nonce = str(uuid.uuid4())
        request = LLMRequest(
            job_type=JOB_TYPE,
            agent_name=AGENT_NAME,
            messages=[
                {
                    "role": "user",
                    "content": f"SCRIPT CHECK: {nonce}\n\n"
                    + build_prompt(voice_spec, voice_block, title, phrases),
                }
            ],
            system=SYSTEM,
            output_schema=SCHEMA,
            max_tokens=2000,
            prompt_version=PROMPT_VERSION,
            workspace_id=ws,
            run_id=candidate_id,
            idempotency_key=f"script-slips:{ws}:{nonce}",
        )
        llm = await _llm.complete(request)
        payload = llm.structured
        if payload is None:
            payload = json.loads(llm.text)
        slips = usable_slips(payload, phrases)
        return slips, {
            "status": "checked",
            "slips": len(slips),
            "job_id": str(llm.job_id) if llm.job_id else None,
        }
    except LLMUnavailable as exc:
        return [], {"status": "unavailable", "detail": str(exc.detail or exc.status)[:200]}
    except Exception as exc:  # a check must never stop a script reaching him
        return [], {"status": "error", "detail": f"{type(exc).__name__}: {exc}"[:200]}
