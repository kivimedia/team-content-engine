"""Learning Loop — weekly analysis of performance vs predictions (PRD Section 9.10)."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

SYSTEM_PROMPT = """\
You are the Learning Loop agent for Team Content Engine. You analyze post performance \
data and produce weekly recommendations.

INPUT: Post performance metrics for the week (actual comments, shares, saves, DMs, etc.) \
alongside the predicted scores from QA and template metadata.

RESPONSIBILITIES:
- Compare predicted vs actual performance
- Track which templates, CTAs, visuals, and angles worked
- Recommend template prior updates
- Downgrade patterns that repeatedly underperform
- Surface new hypotheses for operator review
- Track CTA keyword conversion rates
- Track visual direction performance
- Analyze feedback tag frequencies and recommend system adjustments

OUTPUT FORMAT (JSON):
- week_summary: 2-3 sentence overview
- template_recommendations: array of {template_name, action, reason}
- cta_recommendations: array of {keyword, performance, recommendation}
- voice_weight_adjustments: suggested changes to house voice weights
- top_feedback_tags: array of {tag, count, recommendation}
- cost_efficiency: notes on agent cost vs output quality
- action_items: prioritized list of changes for next week
"""


@register_agent
class LearningLoop(AgentBase):
    name = "learning_loop"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Analyze weekly performance and produce recommendations."""
        learning_events = context.get("learning_events", [])
        qa_scorecards = context.get("qa_scorecards", [])
        feedback_events = context.get("feedback_events", [])
        cost_summary = context.get("cost_summary", {})

        prompt_parts = [
            f"POST PERFORMANCE DATA:\n{json.dumps(learning_events, indent=2)}",
            f"\nQA SCORECARDS:\n{json.dumps(qa_scorecards, indent=2)}",
            f"\nOPERATOR FEEDBACK:\n{json.dumps(feedback_events, indent=2)}",
            f"\nCOST SUMMARY:\n{json.dumps(cost_summary, indent=2)}",
            "\nAnalyze this week's performance and produce recommendations.",
        ]

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.4,
        )

        text = self._extract_text(response)
        try:
            recommendations = self._parse_json_response(text)
        except json.JSONDecodeError:
            recommendations = {"week_summary": text, "action_items": []}

        return {"weekly_recommendations": recommendations}
