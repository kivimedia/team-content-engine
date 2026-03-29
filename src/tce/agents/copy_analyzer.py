"""Copy Analyzer — extracts story_brief from user-provided copy and matches to best template."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent
from tce.models.pattern_template import PatternTemplate

SYSTEM_PROMPT = """\
You are the Copy Analyzer for Team Content Engine. Your job is to:
1. Read raw copy the user has written
2. Extract a synthetic story_brief (the same shape downstream agents expect)
3. Analyze the copy structure (hook type, body structure, gaps)
4. Match to the best PatternTemplate from the provided list

You always respond in valid JSON only, no markdown fences.
"""

USER_PROMPT_TEMPLATE = """\
Here is the user's raw copy:
---
{raw_copy}
---

{notes_section}

Here are the top-performing PatternTemplates (sorted by median_score desc):
{templates_json}

Analyze the copy and return a single JSON object:
{{
  "story_brief": {{
    "topic": "main topic of the copy",
    "thesis": "core argument or insight",
    "audience": "who this is written for",
    "angle_type": "one of: contrarian_insight, founder_journey, data_storytelling, industry_trends, how_we_built_it, client_transformation, myth_busting, behind_the_scenes, lessons_learned, future_prediction",
    "visual_job": "what an image should convey (emotion, scene, metaphor)",
    "platform_notes": "any platform-specific observations"
  }},
  "copy_analysis": {{
    "hook_type": "question | bold_claim | story_opener | statistic | pattern_interrupt",
    "body_structure": "list | narrative | problem_solution | before_after | case_study",
    "estimated_word_count": 0,
    "strengths": ["what works well"],
    "gaps": ["what could be improved"],
    "tone": "conversational | authoritative | provocative | empathetic | educational"
  }},
  "matched_template": {{
    "template_name": "name of the best matching template",
    "template_family": "family of the matched template",
    "match_reason": "why this template fits",
    "hook_formula": "the template's hook formula to apply",
    "body_formula": "the template's body formula to apply"
  }}
}}

Pick the template that best matches the copy's structure and intent.
If no template is a strong match, pick the closest one and note the gaps.
"""


@register_agent
class CopyAnalyzer(AgentBase):
    """Analyzes user-provided copy and matches it to the best PatternTemplate."""

    name = "copy_analyzer"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        raw_copy = context.get("raw_copy", "")
        notes = context.get("notes", "")

        if not raw_copy:
            self._report("No raw_copy provided in context - nothing to analyze.")
            return {"error": "No raw_copy provided"}

        self._report(f"Analyzing copy ({len(raw_copy.split())} words)...")

        # Query top PatternTemplates from DB
        templates = []
        try:
            result = await self.db.execute(
                select(PatternTemplate)
                .where(PatternTemplate.status.in_(["validated", "provisional"]))
                .order_by(PatternTemplate.median_score.desc().nulls_last())
                .limit(10)
            )
            rows = result.scalars().all()
            templates = [
                {
                    "template_name": t.template_name,
                    "template_family": t.template_family,
                    "best_for": t.best_for,
                    "hook_formula": t.hook_formula,
                    "body_formula": t.body_formula,
                    "median_score": t.median_score,
                    "platform_fit": t.platform_fit,
                }
                for t in rows
            ]
            self._report(f"Found {len(templates)} templates to match against.")
        except Exception as exc:
            self._report(f"Could not load templates: {exc} - will analyze without template matching.")

        notes_section = f"User notes:\n{notes}" if notes else ""
        templates_json = json.dumps(templates, indent=2) if templates else "[]"

        prompt = USER_PROMPT_TEMPLATE.format(
            raw_copy=raw_copy,
            notes_section=notes_section,
            templates_json=templates_json,
        )

        response = await self._call_llm(
            messages=[{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT,
        )

        text = self._extract_text(response)
        result = self._parse_json_response(text)
        if not result:
            self._report("Failed to parse LLM response as JSON.")
            return {"error": "Failed to parse copy analysis"}

        story_brief = result.get("story_brief", {})
        copy_analysis = result.get("copy_analysis", {})
        matched = result.get("matched_template", {})

        self._report(f"Topic: {story_brief.get('topic', 'unknown')}")
        self._report(f"Angle: {story_brief.get('angle_type', 'unknown')}")
        self._report(f"Hook type: {copy_analysis.get('hook_type', 'unknown')}")
        self._report(f"Body structure: {copy_analysis.get('body_structure', 'unknown')}")
        self._report(f"Matched template: {matched.get('template_name', 'none')}")
        if copy_analysis.get("gaps"):
            self._report(f"Gaps found: {', '.join(copy_analysis['gaps'][:3])}")

        return {
            "story_brief": story_brief,
            "copy_analysis": copy_analysis,
            "matched_template": matched,
            "raw_copy": raw_copy,
        }
