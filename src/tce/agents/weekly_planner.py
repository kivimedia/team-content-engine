"""Weekly Planner - coordinates the week's content from evidence-backed ideas.

Primary pool: evidence-backed TopicCandidates for this workspace and week (produced by
the editorial selector from Ziv's calls and his team's work). Trends are optional
context: the trend scout runs only when no candidates exist or when the operator asks
for trends, and a trend is only a constraint when a topic makes a news claim that must
be verified.

The output JSON shape is unchanged (weekly_plan, trend_brief, weekly_theme, gift_theme,
weekly_keyword, guide_options) because KMHub/km-worker consume it via the pipeline API.
A guide and a comment keyword are no longer forced: guide_options may be empty and the
call to action is a strategy session.
"""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import get_agent_class, register_agent

# Legacy angle vocabulary. Kept as optional suggestions for backward compatibility;
# no weekday is forced to an angle any more.
CADENCE = {
    0: {"angle": "big_shift_explainer", "label": "Monday"},
    1: {"angle": "tactical_workflow_guide", "label": "Tuesday"},
    2: {"angle": "contrarian_diagnosis", "label": "Wednesday"},
    3: {"angle": "case_study_build_story", "label": "Thursday"},
    4: {"angle": "second_order_implication", "label": "Friday"},
}

STRATEGY_SESSION_CTA = {"type": "strategy_session", "text": "Book a strategy session"}

SYSTEM_PROMPT = """\
You are the Weekly Content Planner for Ziv Raviv's coaching content. You arrange the \
week's ideas into day slots so the team can produce them.

WHERE TOPICS COME FROM:
- EVIDENCE-BACKED IDEAS are the primary pool when provided. They come from Ziv's own \
calls and his team's work, already checked against the editorial gates. Use them first, \
keep their lesson and public angle, and carry their candidate_id into the option.
- Trend items, when provided, are optional context. Use a trend only when it genuinely \
helps an owner, and treat any news claim as something to verify before publishing.
- Without evidence-backed ideas, pick topics from the strategy and any trend context, \
still following every rule below.

RULES:
- Audience: coaches first, event-industry small business owners second.
- One lesson per topic. Keep coaching lessons that do not mention AI; do not turn the \
week into AI news commentary.
- The call to action is booking a strategy session. Do not invent a giveaway, guide or \
comment keyword unless the operator explicitly asks for one.
- Never prices, fees or revenue figures. No client or customer names, no customer words.
- Claims discipline: built, tested, deployed, used and measured are different. Never state \
an outcome the evidence does not measure. No invented statistics.
- No fixed weekday angles. angle_type is a short free label describing the angle you chose.
- Do NOT pad. Plan only as many days as there are strong ideas (three strong ideas is a \
good week). Give 1-3 options per day; never rephrase one idea three ways.
- No crisis or fear hooks, no forced company names.

HUMANITARIAN SENSITIVITY (non-negotiable):
- Avoid topics that trivialize or exploit human suffering; no fear hooks; never punish the \
audience; every topic passes the dignity test. If a topic touches job loss, acknowledge the \
human cost first.

WRITING STYLE FOR TOPICS AND THESES:
Write like a peer explaining the idea over coffee: first or second person, concrete, \
short sentences, plain words. If you cannot picture what the piece says, it is too vague.

WALKING VIDEO DAYS (optional, operator-specified):
Walking recordings are one person, one idea, phone in hand, read in short phrases. Prefer \
first-person lessons from something Ziv did or explained. Beats are flexible around the \
lesson. Mark those options content_format "walking_video"; other days "text".

OUTPUT: A JSON object with:
- weekly_theme: 1 sentence (conversational) or "" when the ideas do not share one
- guide_options: [] unless the operator explicitly asked for a guide (then up to 3 objects \
with title, subtitle, sections, rationale)
- cta_keyword: "" unless the operator explicitly asked for a comment keyword
- cta: {"type": "strategy_session", "text": "Book a strategy session"}
- days: array (only as many as there are strong ideas, max 5), each containing:
  - day_of_week: 0-4
  - day_label: "Monday" through "Friday"
  - angle_type: short free label
  - options: array of 1-3 topic options, each containing:
    - topic: 1 specific sentence
    - thesis: the core lesson in 1-2 plain sentences
    - audience: "coaches", "event-business owners" or both, described plainly
    - desired_belief_shift: FROM -> TO in plain language
    - evidence_requirements: array of claims to verify (empty when the evidence already \
supports every claim)
    - visual_job: cinematic_symbolic / proof_diagram / emotional_alternate
    - connection_to_gift: "" unless a guide was requested
    - platform_notes: any platform-specific adjustments
    - content_format: "text" or "walking_video"
    - cta_goal: "strategy_session"
    - candidate_id: the evidence-backed idea id, or null
    - public_safety_notes: carried from the idea, or ""
  The first option (index 0) is your best pick.
"""


def build_planner_prompt_parts(
    *,
    evidence_candidates: list[dict[str, Any]] | None = None,
    trends: list[dict[str, Any]] | None = None,
    trend_summary: str | None = None,
    strategy_text: str = "",
    portfolio_text: str = "",
    recent_posts: list[Any] | None = None,
    operator_overrides: dict[str, Any] | None = None,
    founder_voice: dict[str, Any] | None = None,
    creator_profiles: list[dict[str, Any]] | None = None,
    video_days: list[int] | None = None,
    sensitive_period: bool = False,
    humanitarian_context: str = "",
) -> list[str]:
    """Pure prompt builder (unit-tested): no DB, no LLM."""
    parts: list[str] = []

    if evidence_candidates:
        parts.append(
            "EVIDENCE-BACKED IDEAS (primary pool; selected ideas first, then proposed, by rank):\n"
            + json.dumps(evidence_candidates, indent=2)
        )
    else:
        parts.append(
            "EVIDENCE-BACKED IDEAS: none available for this week. Plan from the strategy; "
            "return fewer days rather than weak topics."
        )

    if trends:
        parts.append(
            "OPTIONAL TREND CONTEXT (use only when it helps an owner; any news claim must be "
            "verified before publishing):\n" + json.dumps(trends[:15], indent=2)
        )
        if trend_summary:
            parts.append(f"Trend landscape (optional context): {trend_summary}")

    if strategy_text:
        parts.append("BUSINESS STRATEGY (effective for this workspace):\n\n" + strategy_text)
    else:
        parts.append(
            "STRATEGY: content for coaches first and event-industry small business owners "
            "second. Offer: Super Coaching. Call to action: book a strategy session. No prices."
        )

    if portfolio_text:
        parts.append(
            "WORK PORTFOLIO (background proof material, not the offer; reference a build only "
            "when it carries the lesson, and describe it as built/tested/deployed/used exactly "
            "as far as the evidence goes):\n\n" + portfolio_text
        )

    if recent_posts:
        parts.append(
            f"RECENT POSTS (avoid repetition):\n{json.dumps(recent_posts[-10:], indent=2)}"
        )

    if operator_overrides:
        parts.append(f"OPERATOR OVERRIDES:\n{json.dumps(operator_overrides)}")

    parts.append(
        "ANGLE VOCABULARY (optional suggestions, not assignments): "
        + ", ".join(c["angle"] for c in CADENCE.values())
    )

    if founder_voice:
        fv_parts = []
        if founder_voice.get("recurring_themes"):
            fv_parts.append("Recurring themes: " + ", ".join(founder_voice["recurring_themes"]))
        if founder_voice.get("values_and_beliefs"):
            fv_parts.append("Core values: " + ", ".join(founder_voice["values_and_beliefs"]))
        if founder_voice.get("taboos"):
            fv_parts.append("NEVER write about: " + ", ".join(founder_voice["taboos"]))
        if founder_voice.get("tone_range"):
            fv_parts.append(f"Tone range: {json.dumps(founder_voice['tone_range'])}")
        if fv_parts:
            parts.append("FOUNDER VOICE (the human behind the brand):\n" + "\n".join(fv_parts))

    if creator_profiles:
        creator_lines = []
        for cp in creator_profiles:
            line = f"- {cp.get('name', '?')} ({cp.get('style', 'N/A')})"
            if cp.get("top_patterns"):
                line += f" | delivery patterns: {', '.join(cp['top_patterns'][:2])}"
            creator_lines.append(line)
        parts.append(
            "CREATOR REFERENCE (delivery only - hooks and pacing; never identity, positioning "
            "or topic choice):\n" + "\n".join(creator_lines)
        )

    if video_days:
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        valid = sorted({d for d in video_days if 0 <= d <= 4})
        if valid:
            parts.append(
                "WALKING VIDEO DAYS: "
                + ", ".join(f"Day {d} ({day_names[d]})" for d in valid)
                + ". If you plan those days, write their options as walking recordings: one "
                "first-person lesson, short phrases, flexible beats, roughly 60-120 seconds, "
                "ending with the strategy-session invitation. Mark them content_format "
                '"walking_video"; all other days "text".'
            )

    if sensitive_period or humanitarian_context:
        hum = ["HUMANITARIAN CONTEXT (read carefully before choosing topics):"]
        if sensitive_period:
            hum.append(
                "** SENSITIVE PERIOD ACTIVE ** - Extra caution required. "
                "Avoid humor about serious topics, war metaphors, fear-based hooks."
            )
        if humanitarian_context:
            hum.append(humanitarian_context)
        parts.append("\n".join(hum))

    parts.append(
        "Plan the week from the strongest ideas. Plan fewer days rather than padding. "
        "Every topic must pass the humanitarian dignity test."
    )
    return parts


def normalize_weekly_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Fill backward-compatible defaults without inventing a guide or keyword."""
    plan.setdefault("weekly_theme", "")
    plan.setdefault("guide_options", [])
    plan.setdefault("cta_keyword", "")
    plan.setdefault("cta", dict(STRATEGY_SESSION_CTA))
    plan.setdefault("days", [])
    for day in plan.get("days") or []:
        if not isinstance(day, dict):
            continue
        for opt in day.get("options") or []:
            if isinstance(opt, dict):
                opt.setdefault("cta_goal", "strategy_session")
    return plan


@register_agent
class WeeklyPlanner(AgentBase):
    name = "weekly_planner"
    default_model = "claude-opus-4-8"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Plan the week from evidence-backed ideas; trends are optional context."""
        from tce.editorial.planning import load_week_candidates

        ws_id = context.get("workspace_id")
        evidence_candidates = await load_week_candidates(self.db, ws_id, context.get("week_start"))
        if evidence_candidates:
            self._report(f"Phase 1: {len(evidence_candidates)} evidence-backed ideas for this week")

        trend_brief: dict[str, Any] = {}
        trends: list[dict[str, Any]] = []
        if context.get("_skip_trend_scout") and context.get("trend_brief"):
            trend_brief = context["trend_brief"]
            trends = trend_brief.get("trends", [])
            self._report(f"Using shared trend brief as optional context ({len(trends)} items)")
        elif not evidence_candidates or context.get("include_trends"):
            self._report("Scanning trends for optional context...")
            trend_scout_cls = get_agent_class("trend_scout")
            trend_scout = trend_scout_cls(
                db=self.db,
                settings=self.settings,
                cost_tracker=self.cost_tracker,
                prompt_manager=self.prompt_manager,
                run_id=self.run_id,
                progress_log=self._progress_log,
            )
            scout_context = {
                **context,
                "scan_type": "weekly",
                "focus_areas": context.get(
                    "focus_areas", ["coaching business", "small service business operations"]
                ),
            }
            scout_result = await trend_scout._execute(scout_context)
            trend_brief = scout_result.get("trend_brief", {})
            trends = trend_brief.get("trends", [])
            self._report(f"Found {len(trends)} optional trend items")
        else:
            self._report("Skipping trend scan: evidence-backed ideas are the pool this week")

        self._report("Phase 2: Arranging the week...")

        from tce.services.strategy_loader import (
            load_effective_strategy,
            load_portfolio_for_workspace,
        )

        strategy = await load_effective_strategy(self.db, ws_id)
        if strategy.text:
            self._report(
                "Loaded strategy: " + ", ".join(s.get("kind", "?") for s in strategy.sources)
            )
        portfolio_text = await load_portfolio_for_workspace(self.db, ws_id)

        video_days = context.get("video_day_weekdays")
        if not video_days:
            legacy = context.get("video_day_weekday")
            if legacy is not None and 0 <= legacy <= 4:
                video_days = [legacy]

        prompt_parts = build_planner_prompt_parts(
            evidence_candidates=evidence_candidates,
            trends=trends[:25],
            trend_summary=trend_brief.get("summary"),
            strategy_text=strategy.text,
            portfolio_text=portfolio_text,
            recent_posts=context.get("recent_posts", []),
            operator_overrides=context.get("operator_overrides", {}),
            founder_voice=context.get("founder_voice"),
            creator_profiles=context.get("creator_profiles"),
            video_days=video_days,
            sensitive_period=context.get("sensitive_period", False),
            humanitarian_context=context.get("humanitarian_context", ""),
        )

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
            temperature=0.75,
        )

        text = self._extract_text(response)
        try:
            weekly_plan = self._parse_json_response(text)
        except json.JSONDecodeError:
            self._report("JSON parse failed, attempting repair...")
            try:
                repair = await self._call_llm(
                    messages=[
                        {"role": "user", "content": "\n\n".join(prompt_parts)},
                        {"role": "assistant", "content": text},
                        {
                            "role": "user",
                            "content": (
                                "Your response was not valid JSON. Output ONLY the JSON object "
                                "with weekly_theme, guide_options, cta_keyword, cta and days "
                                "(each day has an options array). "
                                "No markdown, no commentary."
                            ),
                        },
                    ],
                    system=SYSTEM_PROMPT,
                    max_tokens=8192,
                    temperature=0.3,
                )
                weekly_plan = self._parse_json_response(self._extract_text(repair))
                self._report("Repair succeeded")
            except Exception:
                weekly_plan = {
                    "weekly_theme": "",
                    "gift_theme": "",
                    "cta_keyword": "",
                    "days": [],
                    "_parsing_failed": True,
                }
                self._report("Planning output unusable - returning an empty plan (no padding)")

        weekly_plan = normalize_weekly_plan(weekly_plan)
        theme = weekly_plan.get("weekly_theme", "")
        keyword = weekly_plan.get("cta_keyword", "")
        days = weekly_plan.get("days", [])

        # Backward compat: gift_theme from guide_options[0] when a guide was requested
        guide_options = weekly_plan.get("guide_options", [])
        if guide_options and isinstance(guide_options, list):
            gift = guide_options[0]
        else:
            gift = weekly_plan.get("gift_theme", "")

        self._report("\nWeekly Plan:")
        self._report(f"  Theme: {theme or '(none)'}")
        self._report("  CTA: strategy session" + (f" (keyword {keyword})" if keyword else ""))
        self._report(f"  Days planned: {len(days)}")
        for d in days:
            day_label = d.get("day_label", f"Day {d.get('day_of_week', '?')}")
            options = d.get("options", [])
            if not options and d.get("topic"):
                options = [d]
            self._report(
                f"\n  {day_label} ({d.get('angle_type', '-')}) - {len(options)} option(s):"
            )
            for oi, opt in enumerate(options):
                marker = " *" if oi == 0 else ""
                self._report(f"    [{oi}]{marker} {opt.get('topic', 'N/A')}")

        return {
            "weekly_plan": weekly_plan,
            "trend_brief": trend_brief,
            "weekly_theme": theme,
            "gift_theme": gift,
            "weekly_keyword": keyword,
            "guide_options": guide_options,
            "evidence_candidates": evidence_candidates,
        }
