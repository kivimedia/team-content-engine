"""Story Strategist — chooses the daily angle and best-fit template (PRD Section 9.5)."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

# Default 5-day cadence (PRD Section 9.5)
DEFAULT_CADENCE = {
    0: {"angle": "big_shift_explainer", "label": "Monday: big AI shift explained"},
    1: {"angle": "tactical_workflow_guide", "label": "Tuesday: practical workflow/tool post"},
    2: {"angle": "contrarian_diagnosis", "label": "Wednesday: contrarian belief-shift post"},
    3: {"angle": "case_study_build_story", "label": "Thursday: case study/build-with-AI post"},
    4: {
        "angle": "second_order_implication",
        "label": "Friday: strategic implication/future-of-work",
    },
}

SYSTEM_PROMPT = """\
You are the Story Strategist for Team Content Engine. Your job is the most \
consequential decision each day: choosing what to write about and how to frame it.

You must output a StoryBrief as JSON with these fields:
- brief_id: a descriptive identifier
- topic: one sentence describing the story
- audience: who this post targets and what they currently believe
- angle_type: from the cadence
- desired_belief_shift: FROM -> TO format
- template_id: which template to use (name, not UUID)
- house_voice_weights: adjusted weights for this specific post
- thesis: the single core argument (1-2 sentences)
- evidence_requirements: what the Research Agent must verify (array of strings)
- cta_goal: "weekly_guide_keyword" (default) or secondary CTA type
- visual_job: cinematic_symbolic / proof_diagram / emotional_alternate
- platform_notes: any platform-specific adjustments

RULES:
- The thesis must be specific enough that a writer can build an argument from it
- Never pick a topic that was covered in the last 10 posts
- The belief shift must be something the reader can verify after reading
"""


@register_agent
class StoryStrategist(AgentBase):
    name = "story_strategist"
    default_model = "claude-opus-4-7"  # Most consequential decision - worth premium

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Select today's angle and produce a StoryBrief."""
        trend_brief = context.get("trend_brief", {})
        day_of_week = context.get("day_of_week", 0)  # 0=Monday
        templates = context.get("templates", [])
        recent_posts = context.get("recent_posts", [])
        weekly_theme = context.get("weekly_theme", "")
        operator_overrides = context.get("operator_overrides", {})
        user_topic = context.get("topic", "")
        template_hint = context.get("template_hint", "")

        cadence = DEFAULT_CADENCE.get(day_of_week, DEFAULT_CADENCE[0])

        prompt_parts = []

        # When user provided a specific topic, override cadence framing
        if user_topic:
            prompt_parts.append(
                "OPERATOR-ASSIGNED TOPIC (NON-NEGOTIABLE):\n"
                f"The operator has assigned a specific topic for this post. "
                f"You MUST build your StoryBrief around this topic. "
                f"Do NOT pick a different topic from the trend brief.\n\n"
                f"TOPIC:\n{user_topic}"
            )
            if template_hint:
                prompt_parts.append(
                    f"TEMPLATE HINT: The operator suggests using the '{template_hint}' template pattern."
                )
            prompt_parts.append(
                f"Cadence reference (adapt if needed): {cadence['angle']}"
            )
        else:
            prompt_parts.append(f"Today is {cadence['label']}.")
            prompt_parts.append(f"Today's cadence slot: {cadence['angle']}")

        if weekly_theme:
            prompt_parts.append(f"Weekly theme: {weekly_theme}")

        if trend_brief.get("trends"):
            if user_topic:
                # When user topic is set, trends are supporting context only
                prompt_parts.append(
                    "SUPPORTING TREND CONTEXT (for evidence/framing only - "
                    "do NOT change the topic):\n"
                    f"{json.dumps(trend_brief['trends'][:5], indent=2)}"
                )
            else:
                prompt_parts.append(
                    "TREND BRIEF (ranked candidates):\n"
                    f"{json.dumps(trend_brief['trends'][:10], indent=2)}"
                )

        if templates:
            template_names = [
                t.get("template_name", t.get("template_family", "unknown")) for t in templates[:10]
            ]
            prompt_parts.append(f"Available templates: {', '.join(template_names)}")

        if recent_posts:
            prompt_parts.append(
                f"Recent posts (avoid repetition): {json.dumps(recent_posts[-10:], indent=2)}"
            )

        if operator_overrides:
            prompt_parts.append(f"Operator overrides: {json.dumps(operator_overrides)}")

        # Layer 3 of TJ grounding: when a creator_profile is in context, bake
        # in their failure patterns + angle preferences so the StoryBrief this
        # agent produces respects what works for that creator's audience.
        creator_profile = context.get("creator_profile") or {}
        if creator_profile:
            creator_name = creator_profile.get("creator_name", "the reference creator")
            disallowed = creator_profile.get("disallowed_clone_markers") or []
            angle_weights = creator_profile.get("angle_weights") or {}
            top_patterns = creator_profile.get("top_patterns") or []
            hook_prefs = [p.split(":", 1)[1].replace("_", " ")
                          for p in top_patterns if p.startswith("hook:")]
            creator_parts = [f"\nCREATOR STYLE ANCHOR ({creator_name}):"]
            if disallowed:
                creator_parts.append(
                    "HARD AVOID (these failure patterns scored 0 views in their bottom 10 posts):\n"
                    + "\n".join(f"- {d.replace('_', ' ')}" for d in disallowed)
                )
            if hook_prefs:
                creator_parts.append(
                    "PREFERRED HOOK FORMULAS (their top-performing opening patterns):\n"
                    + "\n".join(f"- {h}" for h in hook_prefs)
                )
            if angle_weights:
                weighted = sorted(angle_weights.items(), key=lambda kv: -kv[1])
                creator_parts.append(
                    "ANGLE FIT WEIGHTS for this creator (pick higher-weighted angles when the topic fits):\n"
                    + "\n".join(f"- {a}: {w:.1f}" for a, w in weighted)
                )
            creator_parts.append(
                "Use these as calibration, not a checklist. The goal is a brief that "
                "a writer can execute in this creator's voice without parroting them."
            )
            prompt_parts.append("\n".join(creator_parts))

        # Business strategy context — always loaded, not gated on niche flag
        from tce.services.strategy_loader import load_strategy
        strategy_context = load_strategy()
        if strategy_context:
            self._report("Loaded Super Coaching strategy doc for topic selection")
            prompt_parts.append(
                "BUSINESS STRATEGY — READ BEFORE CHOOSING ANY TOPIC:\n"
                "The following defines who this content is for, what makes a topic pass or fail, "
                "and what the content must make the viewer feel. Apply the topic filter, "
                "the 5 pillars, and the emotional trigger test to every topic you pick.\n\n"
                f"{strategy_context}\n\n"
                "CONTENT GOAL: Build authority as THE person who helps coaches add AI agent "
                "teams. Every piece should leave the viewer thinking 'I need to talk to this guy.'"
            )
        else:
            self._report("Strategy doc not found — using inline fallback context")
            prompt_parts.append(
                "NICHE CONTEXT - SUPER COACHING:\n"
                "This content is for coaches who want to add AI agent teams to their coaching business. "
                "Creator: Ziv Raviv (Kivi Media, 300+ clients, 'Super Coaching' trademarked).\n"
                "TARGET: Independent coaches earning $10K-30K/mo, burned by generic agency content.\n"
                "GOAL: Every piece makes a coach think 'I need to talk to Ziv Raviv.'"
            )

        # Creator inspiration context
        creator_insp = context.get("creator_inspiration")
        if creator_insp:
            cname = creator_insp.get("creator_name", "a creator")
            hook = creator_insp.get("hook_type", "?")
            body = creator_insp.get("body_structure", "?")
            arc = creator_insp.get("story_arc", "?")
            prompt_parts.append(
                f"CREATOR INSPIRATION: The operator wants this"
                f" post INSPIRED by {cname}'s style. "
                f"Pick a topic that would work well with their"
                f" style patterns: "
                f"hook_type={hook}, "
                f"body_structure={body}, "
                f"story_arc={arc}. "
                f"The post topic should be fresh but the"
                f" structural approach should align with"
                f" the creator's strengths."
            )

        prompt_parts.append("Select the best story and produce a StoryBrief as JSON.")

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
                # Use top trend as fallback instead of generic text
                top_trend = {}
                if trend_brief.get("trends"):
                    top_trend = trend_brief["trends"][0]
                story_brief = {
                    "topic": top_trend.get("headline", "AI industry update"),
                    "angle_type": cadence["angle"],
                    "thesis": top_trend.get("angles", [""])[0]
                    if top_trend.get("angles")
                    else "Analyze the latest shift in AI and what it means for business",
                    "audience": "Business leaders and AI-curious professionals",
                    "evidence_requirements": [top_trend.get("headline", "")] if top_trend else [],
                    "_parsing_failed": True,
                }
                self._report("Using top trend as fallback")

        self._report("Selected story:")
        self._report(f"  Topic: {story_brief.get('topic', 'N/A')}")
        self._report(f"  Angle: {story_brief.get('angle_type', 'N/A')}")
        self._report(f"  Thesis: {story_brief.get('thesis', 'N/A')}")
        self._report(f"  Audience: {story_brief.get('audience', 'N/A')}")
        belief_shift = story_brief.get("desired_belief_shift", "")
        if belief_shift:
            self._report(f"  Belief shift: {belief_shift}")
        template = story_brief.get("template_id", "")
        if template:
            self._report(f"  Template: {template}")
        visual = story_brief.get("visual_job", "")
        if visual:
            self._report(f"  Visual direction: {visual}")

        return {"story_brief": story_brief}
