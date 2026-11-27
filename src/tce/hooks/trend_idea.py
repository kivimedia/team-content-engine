"""After his yes on a trend, TCE works out how he would do it (T-26074, part 3).

Ziv, 27-Nov-2026: "I see a trend I say yes, it goes into the list of big ideas. The next
time I talk with TCE, it tells me something like, oh, I noticed you wanted to do this
trend, so after research, I came up with an idea about how we would do it ... I want you
to research and come up with ideas based on my pillars and based on other videos we did."

So a yes starts one background job. The writer gets the trend (what it is, its steps),
his pillars and the titles of his recent topics, and answers with ONE concrete idea: the
pillar and the topic it fits best, the idea in his words, how each step of the trend
would go, and what he has to confirm before it can be written (a list of books he read,
the three tools he really uses). It invents no facts about him: anything it would need
from him goes in "confirm". The idea is kept on his yes in hooks.json ("idea": writing,
ready, failed) and read out at the start of his next TCE talk (tce_week). Nothing is put
on a video and no script is written here.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from sqlalchemy import select

from tce import llm as _llm
from tce.editorial.common import open_session
from tce.hooks import format_library, library
from tce.hooks.formats import BY_ID, Format
from tce.llm import LLMRequest

logger = structlog.get_logger()

JOB_TYPE = "trend_idea"  # batch lane: nobody waits on it, he hears it on his next call
AGENT = "trend_idea_writer"
PROMPT_VERSION = "trend_idea.v1"
TOPICS_READ = 40
CONFIRM_MAX = 25
TEXT_MAX = 400

SYSTEM = """\
You plan ONE short talking video for a creator, in a trending format he said yes to.
He will hear your idea read out on a call and say yes, change it, or no.

- Pick the pillar of his that the format fits best, and the topic: one of his recent
  topics when one fits, else a new topic inside that pillar. Say in one sentence why.
- Make it concrete: what the video is, in one or two sentences, and one short line per
  step of the format saying what goes there.
- Never invent facts about him: no clients, numbers, results, books, tools or stories
  he has not given. Anything the idea needs from him goes in "confirm" as a short list
  of items for him to confirm or replace (for example the books he really read).
- Plain spoken English, no hype, no long dashes, no emojis.

Return only JSON matching the schema."""


def schema(fmt: Format) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["pillar", "topic", "existing_topic", "why", "idea", "steps", "confirm"],
        "properties": {
            "pillar": {"type": "string"},
            "topic": {"type": "string"},
            "existing_topic": {"type": "boolean"},
            "why": {"type": "string"},
            "idea": {"type": "string"},
            "steps": {
                "type": "array",
                "minItems": len(fmt.steps),
                "maxItems": len(fmt.steps),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["step", "line"],
                    "properties": {
                        "step": {"type": "string", "enum": [s.id for s in fmt.steps]},
                        "line": {"type": "string"},
                    },
                },
            },
            "confirm": {"type": "array", "maxItems": CONFIRM_MAX, "items": {"type": "string"}},
        },
    }


def pillars_for(ws: uuid.UUID) -> list[str]:
    """His pillars: a profiled workspace's own lanes, else the owner's three."""
    from tce.editorial import lane_profile
    from tce.editorial.lineup import LANE_LABELS

    profile = lane_profile.profile_for(ws)
    if profile is not None:
        return [lane.label for lane in profile.lanes]
    return [LANE_LABELS[k] for k in ("build", "coaching", "ai_news")]


async def recent_topics(sm: Any, ws: uuid.UUID) -> list[str]:
    """The titles of his newest topics, the closest thing to "the videos we did"."""
    from tce.models.editorial import TopicCandidate

    try:
        async with open_session(sm) as db:
            rows = await db.execute(
                select(TopicCandidate.title)
                .where(TopicCandidate.workspace_id == ws)
                .order_by(TopicCandidate.created_at.desc())
                .limit(TOPICS_READ * 2)
            )
            titles = [str(t).strip() for (t,) in rows.all() if str(t or "").strip()]
    except Exception as exc:  # noqa: BLE001 - the idea can still be written from the pillars
        logger.info("hooks.trend_idea_topics_unread", error=type(exc).__name__)
        return []
    seen: list[str] = []
    for title in titles:
        if title not in seen:
            seen.append(title)
    return seen[:TOPICS_READ]


def build_prompt(fmt: Format, pillars: list[str], topics: list[str]) -> str:
    steps = [{"step": s.id, "what_this_part_does": s.does} for s in fmt.steps]
    example = fmt.real[0] if fmt.real else None
    return "\n\n".join([
        "THE TREND HE SAID YES TO:\n" + json.dumps({
            "name": fmt.name, "what_it_is": fmt.what, "why_people_watch_it": fmt.why,
            **({"a_real_example": example.watch} if example else {}),
        }, indent=1),
        "ITS STEPS (one line each in your answer, in this order):\n" + json.dumps(steps, indent=1),
        "HIS PILLARS:\n" + "\n".join(f"- {p}" for p in pillars),
        "HIS RECENT TOPICS (newest first):\n" + ("\n".join(f"- {t}" for t in topics) or "(none yet)"),
    ])


def _tidy(text: Any, limit: int = TEXT_MAX) -> str:
    return " ".join(str(text or "").replace("—", "-").replace("–", "-").split())[:limit]


def clean(fmt: Format, answer: Any) -> dict[str, Any] | None:
    """The writer's idea, checked and trimmed, or None when it gave nothing usable."""
    if not isinstance(answer, dict):
        return None
    raw = answer.get("steps")
    rows: list[Any] = raw if isinstance(raw, list) else []
    by_step = {str(r.get("step")): _tidy(r.get("line"), 220) for r in rows if isinstance(r, dict)}
    steps = [{"step": s.id, "label": s.label, "line": by_step.get(s.id, "")} for s in fmt.steps]
    idea, topic = _tidy(answer.get("idea")), _tidy(answer.get("topic"), 200)
    if not idea or not topic or any(not s["line"] for s in steps):
        return None
    confirm = [_tidy(c, 160) for c in (answer.get("confirm") or []) if _tidy(c, 160)][:CONFIRM_MAX]
    return {
        "pillar": _tidy(answer.get("pillar"), 80),
        "topic": topic,
        "existing_topic": bool(answer.get("existing_topic")),
        "why": _tidy(answer.get("why")),
        "idea": idea,
        "steps": steps,
        "confirm": confirm,
    }


async def save(ws: uuid.UUID, format_id: str, idea: dict[str, Any]) -> bool:
    """Keep the idea on his yes, only while it is still a yes (a no or an undo meanwhile wins)."""
    async with library._LOCK:
        data = library.read_store(ws)
        found = data.get("format_wants")
        wants: dict[str, Any] = found if isinstance(found, dict) else {}
        entry = wants.get(format_id)
        if not isinstance(entry, dict) or entry.get("choice") != "want":
            return False
        entry["idea"] = {**idea, "at": library._now()}
        data["format_wants"] = wants
        library.write_store(ws, data)
        return True


async def think(sm: Any, ws: uuid.UUID, format_id: str) -> dict[str, Any]:
    """Work out the idea for one trend he said yes to, and keep it on his yes."""
    fmt = BY_ID.get(format_id)
    if fmt is None:
        return {"state": "failed", "detail": "That trend is not in the studio."}

    async def say(state: str, detail: str, **extra: Any) -> dict[str, Any]:
        idea = {"state": state, "detail": detail, **extra}
        await save(ws, format_id, idea)
        return idea

    await say("writing", f"TCE is working out how you would do {fmt.name}, from your pillars and recent topics.")
    pillars = pillars_for(ws)
    topics = await recent_topics(sm, ws)
    request = LLMRequest(
        job_type=JOB_TYPE,
        agent_name=AGENT,
        messages=[{"role": "user", "content": build_prompt(fmt, pillars, topics)}],
        system=SYSTEM,
        output_schema=schema(fmt),
        max_tokens=1200,
        prompt_version=PROMPT_VERSION,
        workspace_id=ws,
        idempotency_key=f"trend-idea:{ws}:{format_id}:{uuid.uuid4()}",
    )
    try:
        result = await _llm.complete(request)
    except Exception as exc:  # busy, parked or failed: the yes stays, the call can ask again
        logger.info("hooks.trend_idea_unavailable", format=format_id, error=type(exc).__name__)
        return await say("failed", f"TCE could not work out the idea yet ({type(exc).__name__}).")
    answer = result.structured if isinstance(result.structured, dict) else None
    if answer is None:
        try:
            answer = json.loads(result.text)
        except (TypeError, ValueError):
            answer = None
    cleaned = clean(fmt, answer)
    if cleaned is None:
        return await say("failed", "TCE's idea did not fit the trend. It can try again.")
    return await say("ready", "TCE's idea for this trend, for you to say yes to, change or drop.", **cleaned)


def ready_ideas(ws: uuid.UUID) -> list[dict[str, Any]]:
    """Every trend he said yes to with where its idea stands, for his next call."""
    wants = library.read_store(ws).get("format_wants") or {}
    out = []
    for item in format_library.wanted(ws):
        idea = (wants.get(item["id"]) or {}).get("idea") or {}
        out.append({"trend": item["name"], "trend_id": item["id"], "said_yes_at": item.get("at"),
                    "idea_state": idea.get("state") or "none", **({"idea": idea} if idea.get("state") == "ready" else {})})
    return out
