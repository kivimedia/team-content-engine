"""Story Strategist - frames one piece from an evidence-backed idea (PRD Section 9.5).

Evidence-backed TopicCandidates (from Ziv's calls and his team's work) are the primary
source. An operator-assigned topic still wins. Trends are optional context and only a
verification constraint when the piece makes a news claim. No weekday angle and no
giveaway/guide CTA is forced; the call to action is a strategy session.

Output shape is unchanged: {"story_brief": {...}}.
"""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

# Legacy angle vocabulary, offered as optional suggestions only.
DEFAULT_CADENCE = {
    0: {"angle": "big_shift_explainer", "label": "Monday"},
    1: {"angle": "tactical_workflow_guide", "label": "Tuesday"},
    2: {"angle": "contrarian_diagnosis", "label": "Wednesday"},
    3: {"angle": "case_study_build_story", "label": "Thursday"},
    4: {"angle": "second_order_implication", "label": "Friday"},
}

SYSTEM_PROMPT = """\
You are the Story Strategist for Ziv Raviv's coaching content. You decide how to frame \
one piece: the single lesson, who it is for, and the angle.

You must output a StoryBrief as JSON with these fields:
- brief_id: a descriptive identifier
- topic: one sentence describing the piece
- audience: who this targets (coaches first, event-industry small business owners second) \
and what they currently believe
- angle_type: a short free label for the angle you chose
- desired_belief_shift: FROM -> TO format
- template_id: which template to use (name, not UUID), or "" when none fits
- house_voice_weights: adjusted weights for this specific post
- thesis: the single core lesson (1-2 sentences)
- evidence_requirements: claims that still need verification (array of strings; empty \
when the cited evidence already supports every claim)
- cta_goal: "strategy_session"
- visual_job: cinematic_symbolic / proof_diagram / emotional_alternate
- platform_notes: any platform-specific adjustments
- candidate_id: the evidence-backed idea this brief is built on, or null
- public_safety_notes: redaction and uncertainty notes carried from the idea, or ""

RULES:
- Evidence-backed ideas come first; keep their lesson and public angle.
- One lesson per piece. Keep coaching lessons that do not mention AI.
- The call to action is booking a strategy session. No giveaway, guide or comment keyword.
- Never prices or revenue figures; no client or customer names or words.
- Claims discipline: built, tested, deployed, used and measured are different; never state \
an outcome the evidence does not measure. No invented statistics.
- Trends are optional context. A news claim goes into evidence_requirements for verification.
- The thesis must be specific enough that a writer can build from it.
- Never repeat a topic covered in the last 10 posts.
"""


def build_story_prompt_parts(
    context: dict[str, Any],
    *,
    strategy_text: str = "",
    evidence_candidates: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Pure prompt builder (unit-tested): no DB, no LLM."""
    trend_brief = context.get("trend_brief") or {}
    day_of_week = context.get("day_of_week", 0)
    templates = context.get("templates", [])
    recent_posts = context.get("recent_posts", [])
    weekly_theme = context.get("weekly_theme", "")
    operator_overrides = context.get("operator_overrides", {})
    user_topic = context.get("topic", "")
    template_hint = context.get("template_hint", "")
    suggested = DEFAULT_CADENCE.get(day_of_week, DEFAULT_CADENCE[0])

    parts: list[str] = []
    assigned = context.get("topic_candidate")
    if user_topic:
        parts.append(
            "OPERATOR-ASSIGNED TOPIC (NON-NEGOTIABLE):\n"
            "Build the StoryBrief around this topic. Do not pick a different one.\n\n"
            f"TOPIC:\n{user_topic}"
        )
        if template_hint:
            parts.append(
                f"TEMPLATE HINT: The operator suggests the '{template_hint}' template pattern."
            )
    if assigned:
        parts.append(
            "ASSIGNED EVIDENCE-BACKED IDEA (build the brief on this):\n"
            + json.dumps(assigned, indent=2)
        )
    if evidence_candidates and not assigned:
        parts.append(
            "EVIDENCE-BACKED IDEAS (primary pool unless an operator topic is set):\n"
            + json.dumps(evidence_candidates, indent=2)
        )

    parts.append(
        f"Optional angle suggestion: {suggested['angle']} (use only if it fits the lesson)."
    )
    if weekly_theme:
        parts.append(f"Weekly theme: {weekly_theme}")

    if trend_brief.get("trends"):
        parts.append(
            "OPTIONAL TREND CONTEXT (framing only; any news claim must be listed in "
            "evidence_requirements for verification):\n"
            f"{json.dumps(trend_brief['trends'][:5], indent=2)}"
        )

    if templates:
        template_names = [
            t.get("template_name", t.get("template_family", "unknown")) for t in templates[:10]
        ]
        parts.append(f"Available templates: {', '.join(template_names)}")

    if recent_posts:
        parts.append(f"Recent posts (avoid repetition): {json.dumps(recent_posts[-10:], indent=2)}")

    if operator_overrides:
        parts.append(f"Operator overrides: {json.dumps(operator_overrides)}")

    creator_profile = context.get("creator_profile") or {}
    if creator_profile:
        creator_name = creator_profile.get("creator_name", "the reference creator")
        disallowed = creator_profile.get("disallowed_clone_markers") or []
        top_patterns = creator_profile.get("top_patterns") or []
        hook_prefs = [
            p.split(":", 1)[1].replace("_", " ") for p in top_patterns if p.startswith("hook:")
        ]
        creator_parts = [
            f"\nCREATOR DELIVERY REFERENCE ({creator_name}) - delivery only (hooks, pacing); "
            "it never decides identity, positioning or topic:"
        ]
        if disallowed:
            creator_parts.append(
                "Delivery patterns to avoid:\n"
                + "\n".join(f"- {d.replace('_', ' ')}" for d in disallowed)
            )
        if hook_prefs:
            creator_parts.append(
                "Opening patterns that work for this reference:\n"
                + "\n".join(f"- {h}" for h in hook_prefs)
            )
        parts.append("\n".join(creator_parts))

    if strategy_text:
        parts.append(
            "BUSINESS STRATEGY (effective for this workspace; read before framing):\n\n"
            + strategy_text
        )
    else:
        parts.append(
            "STRATEGY: coaches first, event-industry small business owners second. Offer: "
            "Super Coaching (Ziv's human team and AI team become the client's). Call to "
            "action: book a strategy session. No prices."
        )

    creator_insp = context.get("creator_inspiration")
    if creator_insp:
        parts.append(
            "DELIVERY INSPIRATION: structure may borrow from "
            f"{creator_insp.get('creator_name', 'a creator')} "
            f"(hook_type={creator_insp.get('hook_type', '?')}, "
            f"body_structure={creator_insp.get('body_structure', '?')}, "
            f"story_arc={creator_insp.get('story_arc', '?')}). The topic and lesson still "
            "come from the evidence and strategy."
        )

    parts.append("Frame the best piece and produce a StoryBrief as JSON.")
    return parts


@register_agent
class StoryStrategist(AgentBase):
    name = "story_strategist"
    default_model = "claude-opus-4-8"  # Most consequential decision - worth premium

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Frame one piece and produce a StoryBrief."""
        trend_brief = context.get("trend_brief") or {}
        day_of_week = context.get("day_of_week", 0)
        suggested = DEFAULT_CADENCE.get(day_of_week, DEFAULT_CADENCE[0])
        ws_id = context.get("workspace_id")

        evidence_candidates: list[dict[str, Any]] = []
        if not context.get("topic") and not context.get("topic_candidate"):
            from tce.editorial.planning import load_week_candidates

            evidence_candidates = await load_week_candidates(
                self.db, ws_id, context.get("week_start")
            )

        from tce.services.strategy_loader import load_effective_strategy, load_strategy

        if self.db is not None and ws_id:
            strategy_text = (await load_effective_strategy(self.db, ws_id)).text
        else:
            strategy_text = load_strategy()
        if strategy_text:
            self._report("Loaded strategy for framing")

        prompt_parts = build_story_prompt_parts(
            context, strategy_text=strategy_text, evidence_candidates=evidence_candidates
        )

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.6,
        )

        self._report("Parsing story brief...")
        text = self._extract_text(response)
        try:
            story_brief = self._parse_json_response(text)
        except json.JSONDecodeError:
            self._report("JSON parse failed, attempting LLM repair...")
            try:
                repair = await self._call_llm(
                    messages=[
                        {"role": "user", "content": "\n\n".join(prompt_parts)},
                        {"role": "assistant", "content": text},
                        {
                            "role": "user",
                            "content": (
                                "Your previous response was not valid JSON. "
                                "Please output ONLY a valid JSON object "
                                "with the StoryBrief fields. "
                                "No markdown, no commentary - just the JSON object."
                            ),
                        },
                    ],
                    system=SYSTEM_PROMPT,
                    max_tokens=4096,
                    temperature=0.3,
                )
                story_brief = self._parse_json_response(self._extract_text(repair))
                self._report("Repair succeeded")
            except (json.JSONDecodeError, Exception):
                base = context.get("topic_candidate") or (
                    evidence_candidates[0] if evidence_candidates else None
                )
                if base:
                    story_brief = {
                        "topic": base.get("title", ""),
                        "thesis": base.get("lesson", ""),
                        "audience": base.get("audience", "coaches"),
                        "angle_type": suggested["angle"],
                        "evidence_requirements": [],
                        "candidate_id": base.get("candidate_id"),
                        "public_safety_notes": base.get("public_safety_notes") or "",
                    }
                else:
                    top_trend = (trend_brief.get("trends") or [{}])[0]
                    story_brief = {
                        "topic": context.get("topic") or top_trend.get("headline", ""),
                        "angle_type": suggested["angle"],
                        "thesis": "",
                        "audience": "coaches",
                        "evidence_requirements": [top_trend["headline"]]
                        if top_trend.get("headline")
                        else [],
                    }
                story_brief["cta_goal"] = "strategy_session"
                story_brief["_parsing_failed"] = True
                self._report("Using evidence-based fallback brief")

        story_brief.setdefault("cta_goal", "strategy_session")

        self._report("Selected story:")
        self._report(f"  Topic: {story_brief.get('topic', 'N/A')}")
        self._report(f"  Angle: {story_brief.get('angle_type', 'N/A')}")
        self._report(f"  Thesis: {story_brief.get('thesis', 'N/A')}")
        self._report(f"  Audience: {story_brief.get('audience', 'N/A')}")
        if story_brief.get("desired_belief_shift"):
            self._report(f"  Belief shift: {story_brief['desired_belief_shift']}")
        if story_brief.get("template_id"):
            self._report(f"  Template: {story_brief['template_id']}")
        if story_brief.get("visual_job"):
            self._report(f"  Visual direction: {story_brief['visual_job']}")

        return {"story_brief": story_brief}
