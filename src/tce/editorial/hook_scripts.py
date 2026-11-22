"""Each opening's own whole script (T-24293, 22-Nov-2026).

Choosing an opening used to swap only the first spoken line: the points, the
beats and every line after it stayed as they were written for the first
opening, so line two often did not follow from the one he picked. His words:
"the script entirely needs to be rewritten based on that hook."

So every opening carries the whole script written for it, under the option's
"script" key: {bullets, script_phrases, beats, payoff_phrase_id}. One writer job
writes the scripts of every opening that has none, in one call, as soon as a
script or new openings are saved, so a pick is normally instant. A pick that
finds no script for its opening writes it on the spot, with a plain progress
line on the page, and never switches the opening until the whole script is
there.

The scripts belong to one wording of the idea. They are valid while the
opening in use still carries, as its own script, exactly the script the
version holds now. An edit to the script breaks that match, so the other
openings' scripts (written from the words before the edit) are not used: they
are written again from the edited words before a pick can use them.

The posts are not rewritten: they adapt the lesson for text and do not quote
the spoken opening, and they were already checked and possibly edited.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from typing import Any

SCRIPT_KEY = "script"
JOB_TYPE = "recording_packet_hook_scripts"
AGENT_NAME = "recording_hook_script_writer"
PROMPT_VERSION = "recording_hook_scripts.v1"

REWRITE_TASK = """\
THE TASK NOW. This overrides the output shape described above.

The script below was written for one opening. Write the WHOLE script again for
each of the other openings listed, so that it follows from that opening to its
last line:

- script_phrases[0] is the opening's text, copied exactly.
- Every line after it is written to follow from that opening: line two picks up
  what the opening just said, the middle answers the belief or question the
  opening raises, and the last lines land the same lesson and stop. Rewrite
  freely; do not just keep the old lines.
- Same idea, same lesson, same evidence, same language, same voice and every
  rule above. Nothing the evidence does not support.
- bullets: 5 to 7 short walking points for THIS version of the script.
- beats: one beat per bullet, phrase IDs p001, p002 and so on over THIS
  script, ordered inclusive ranges, bullet_index 0, 1, 2 in order.
- payoff_phrase_id: the phrase ID in THIS script that pays the opening off.
- Do not write posts. Write one entry per opening listed, with its hook_id.

Return only JSON matching the schema."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["scripts"],
    "properties": {
        "scripts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "hook_id",
                    "bullets",
                    "script_phrases",
                    "beats",
                    "payoff_phrase_id",
                ],
                "properties": {
                    "hook_id": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 5,
                        "maxItems": 7,
                    },
                    "script_phrases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 6,
                    },
                    "beats": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "id",
                                "label",
                                "bullet_index",
                                "start_phrase_id",
                                "end_phrase_id",
                            ],
                            "properties": {
                                "id": {"type": "string"},
                                "label": {"type": "string"},
                                "bullet_index": {"type": "integer"},
                                "start_phrase_id": {"type": "string"},
                                "end_phrase_id": {"type": "string"},
                            },
                        },
                    },
                    "payoff_phrase_id": {"type": "string"},
                },
            },
        }
    },
}


class HookScriptNeeded(ValueError):
    """The chosen opening has no whole script written for the current words yet."""


# ---------------------------------------------------------------------------
# Pure helpers: what a version holds, and whether an opening's script fits it
# ---------------------------------------------------------------------------


def _field(source: Any, name: str) -> Any:
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def _clean_beats(beats: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for beat in beats or []:
        if not isinstance(beat, dict):
            continue
        out.append(
            {
                "id": str(beat.get("id") or ""),
                "label": str(beat.get("label") or ""),
                "bullet_index": beat.get("bullet_index"),
                "start_phrase_id": str(beat.get("start_phrase_id") or ""),
                "end_phrase_id": str(beat.get("end_phrase_id") or ""),
            }
        )
    return out


def script_of(source: Any) -> dict[str, Any]:
    """The words a version (or a stored script) holds: points, lines and beats."""
    return {
        "bullets": [str(b) for b in (_field(source, "bullets") or [])],
        "script_phrases": [str(p) for p in (_field(source, "script_phrases") or [])],
        "beats": _clean_beats(_field(source, "beats")),
    }


def same_script(a: Any, b: Any) -> bool:
    return script_of(a) == script_of(b)


def script_sig(source: Any) -> str:
    raw = json.dumps(script_of(source), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _option(options: list[dict[str, Any]], hook_id: str | None) -> dict[str, Any] | None:
    return next((o for o in options if str(o.get("id")) == str(hook_id)), None)


def scripts_fit(options: list[dict[str, Any]], selected_id: str | None, current: Any) -> bool:
    """True when the stored scripts were written from the words this version holds.

    The opening in use keeps the script it was recorded with; when the version
    still holds exactly that, nothing was edited since the scripts were written.
    """
    selected = _option(options, selected_id)
    stored = selected.get(SCRIPT_KEY) if selected else None
    return isinstance(stored, dict) and same_script(stored, current)


def ready_script(
    options: list[dict[str, Any]], selected_id: str | None, current: Any, hook_id: str
) -> dict[str, Any] | None:
    """The whole script for `hook_id` that may be used now, or None."""
    target = _option(options, hook_id)
    if target is None:
        return None
    if str(hook_id) == str(selected_id):
        return {**script_of(current), "payoff_phrase_id": target.get("payoff_phrase_id")}
    if not scripts_fit(options, selected_id, current):
        return None
    stored = target.get(SCRIPT_KEY)
    if not isinstance(stored, dict):
        return None
    phrases = list(stored.get("script_phrases") or [])
    if not phrases or phrases[0].strip() != str(target.get("text") or "").strip():
        return None
    return {**script_of(stored), "payoff_phrase_id": stored.get("payoff_phrase_id")}


def missing_hooks(
    options: list[dict[str, Any]], selected_id: str | None, current: Any
) -> list[str]:
    """Openings that need their whole script written for the words held now."""
    fit = scripts_fit(options, selected_id, current)
    out: list[str] = []
    for option in options:
        hook_id = str(option.get("id") or "")
        if not hook_id or hook_id == str(selected_id):
            continue
        if fit and ready_script(options, selected_id, current, hook_id) is not None:
            continue
        out.append(hook_id)
    return out


def _payoff_in(script: dict[str, Any], wanted: Any) -> str:
    count = len(script.get("script_phrases") or [])
    ids = {f"p{n:03d}" for n in range(1, count + 1)}
    wanted = str(wanted or "")
    if wanted in ids:
        return wanted
    return f"p{count:03d}" if count else wanted


def switch_options(
    options: list[dict[str, Any]],
    selected_id: str | None,
    current: Any,
    hook_id: str,
    target: dict[str, Any],
) -> list[dict[str, Any]]:
    """The openings list for the version that uses `target` for `hook_id`.

    The opening being left keeps the script it had, so switching back is
    instant and gives back exactly those words. Each opening's payoff line is
    the one in its own script; on the version's list it must also name a line
    of the script now in use, so it is kept inside it.
    """
    fit = scripts_fit(options, selected_id, current)
    out: list[dict[str, Any]] = []
    for option in options:
        item = copy.deepcopy(option)
        oid = str(item.get("id") or "")
        if oid == str(selected_id):
            item[SCRIPT_KEY] = {
                **script_of(current),
                "payoff_phrase_id": item.get("payoff_phrase_id"),
            }
        elif not fit:
            # Written from words that are no longer there: never offered again.
            item.pop(SCRIPT_KEY, None)
        if oid == str(hook_id):
            item[SCRIPT_KEY] = {**script_of(target), "payoff_phrase_id": target.get("payoff_phrase_id")}
            item["payoff_phrase_id"] = _payoff_in(target, target.get("payoff_phrase_id"))
        else:
            item["payoff_phrase_id"] = _payoff_in(target, item.get("payoff_phrase_id"))
        out.append(item)
    return out


def keep_scripts(raw: list[dict[str, Any]], clean: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validation keeps only an opening's own fields; put each stored script back."""
    by_id = {str(o.get("id")): o for o in raw if isinstance(o, dict)}
    out = []
    for option in clean:
        stored = (by_id.get(str(option.get("id"))) or {}).get(SCRIPT_KEY)
        out.append({**option, SCRIPT_KEY: stored} if isinstance(stored, dict) else dict(option))
    return out


# ---------------------------------------------------------------------------
# The writer job
# ---------------------------------------------------------------------------


def build_prompt(packet: Any, cand: Any, hook_ids: list[str]) -> str:
    options = list(_field(packet, "hook_options") or [])
    selected = _option(options, _field(packet, "selected_hook_id"))
    phrases = [
        {"phrase_id": f"p{n + 1:03d}", "text": text}
        for n, text in enumerate(_field(packet, "script_phrases") or [])
    ]
    wanted = [
        {
            "hook_id": str(o.get("id")),
            "text": o.get("text"),
            "question": o.get("question"),
            "rationale": o.get("rationale"),
        }
        for o in options
        if str(o.get("id")) in set(hook_ids)
    ]
    evidence = [
        {
            "moment_id": str(c.get("moment_id") or ""),
            "claim_type": c.get("claim_type"),
            "excerpt_private": (c.get("excerpt_private") or "")[:400],
        }
        for c in (_field(cand, "citations_private") or [])
    ]
    return "\n\n".join(
        [
            f"WRITE THE WHOLE SCRIPT FOR {len(wanted)} OPENING(S).",
            "THE IDEA:\n"
            + json.dumps(
                {"title": _field(cand, "title"), "lesson": _field(cand, "lesson")},
                indent=1,
                ensure_ascii=False,
            ),
            "THE SCRIPT AS WRITTEN FOR THE OPENING IN USE"
            + (f' ("{selected.get("text")}")' if selected else "")
            + ":\n"
            + json.dumps(
                {
                    "bullets": list(_field(packet, "bullets") or []),
                    "script_phrases": phrases,
                    "beats": list(_field(packet, "beats") or []),
                },
                indent=1,
                ensure_ascii=False,
            ),
            "THE OPENINGS TO WRITE A WHOLE SCRIPT FOR:\n"
            + json.dumps(wanted, indent=1, ensure_ascii=False),
            "EVIDENCE (the only support for any claim):\n"
            + json.dumps(evidence, indent=1, ensure_ascii=False),
        ]
    )


def request_key(ws: uuid.UUID, system: str, prompt: str) -> str:
    """Same words asked for twice is one job: a pick reuses what the early write did."""
    digest = hashlib.sha256((system + "\n\x00\n" + prompt).encode("utf-8")).hexdigest()[:32]
    return f"hook-scripts:{ws}:{digest}"


def parse_scripts(payload: Any) -> list[dict[str, Any]]:
    data = payload if isinstance(payload, dict) else None
    if data is None:
        try:
            data = json.loads(payload or "")
        except (TypeError, ValueError):
            return []
    items = (data or {}).get("scripts")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
