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
    default_model = "claude-opus-4-20250514"  # Most consequential decision — worth premium

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Select today's angle and produce a StoryBrief."""
        trend_brief = context.get("trend_brief", {})
        day_of_week = context.get("day_of_week", 0)  # 0=Monday
        templates = context.get("templates", [])
        recent_posts = context.get("recent_posts", [])
        weekly_theme = context.get("weekly_theme", "")
        operator_overrides = context.get("operator_overrides", {})

        cadence = DEFAULT_CADENCE.get(day_of_week, DEFAULT_CADENCE[0])

        prompt_parts = [
            f"Today is {cadence['label']}.",
            f"Today's cadence slot: {cadence['angle']}",
        ]

        if weekly_theme:
            prompt_parts.append(f"Weekly theme: {weekly_theme}")

        if trend_brief.get("trends"):
            prompt_parts.append(
                "TREND BRIEF (ranked candidates):\n"
                f"{json.dumps(trend_brief['trends'][:10], indent=2)}"
            )

        if templates:
            template_names = [t.get("template_name", t.get("template_family", "unknown"))
                            for t in templates[:10]]
            prompt_parts.append(f"Available templates: {', '.join(template_names)}")

        if recent_posts:
            prompt_parts.append(
                f"Recent posts (avoid repetition): {json.dumps(recent_posts[-10:], indent=2)}"
            )

        if operator_overrides:
            prompt_parts.append(f"Operator overrides: {json.dumps(operator_overrides)}")

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
                        {"role": "user", "content": (
                            "Your previous response was not valid JSON. "
                            "Please output ONLY a valid JSON object with the StoryBrief fields. "
                            "No markdown, no commentary - just the JSON object."
                        )},
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
                    "thesis": top_trend.get("angles", [""])[0] if top_trend.get("angles") else "Analyze the latest shift in AI and what it means for business",
                    "audience": "Business leaders and AI-curious professionals",
                    "evidence_requirements": [top_trend.get("headline", "")] if top_trend else [],
                    "_parsing_failed": True,
                }
                self._report("Using top trend as fallback")

        self._report(f"Selected story:")
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
