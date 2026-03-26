"""Trend Scout — discovers stories and trends worth writing about (PRD Section 49)."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

SYSTEM_PROMPT = """\
You are the Trend Scout for a content engine focused on AI, technology, and business.

Your job is to analyze the provided news and signals and produce a ranked Trend Brief \
with candidate stories for a social media content calendar.

For each candidate story, provide:
- trend_id: a short unique slug
- headline: 1-sentence summary
- source_url: primary source (if available)
- source_type: news, social, company_blog, paper, creator_post
- freshness: estimated hours since publication
- relevance_score: 1-10 based on alignment with AI/business audience interests
- template_fit: list of template families this story could power
- angle_suggestions: 2-3 possible angles a writer could take
- source_creator_overlap: boolean — is a known source creator already covering this?
- evidence_available: how easy it is to find primary sources (easy/moderate/hard)

Rank stories by: freshness * 0.3 + relevance_score * 0.5 + evidence_available * 0.2

Output a JSON object with:
- trends: array of trend objects (minimum 5)
- summary: 2-sentence overview of the trend landscape
"""


@register_agent
class TrendScout(AgentBase):
    name = "trend_scout"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Produce a trend brief from provided signals or general knowledge."""
        scan_type = context.get("scan_type", "daily")  # daily or weekly
        operator_topics = context.get("operator_topics", [])
        focus_areas = context.get("focus_areas", ["AI", "technology", "business automation"])

        prompt_parts = [
            f"Produce a {scan_type} Trend Brief for today.",
            f"Focus areas: {', '.join(focus_areas)}",
        ]

        if operator_topics:
            prompt_parts.append(
                f"The operator has specifically requested coverage of: {', '.join(operator_topics)}"
            )

        prompt_parts.append(
            "Identify the top trending AI/tech stories right now based on your knowledge. "
            "For each, assess its potential as social media content for a business audience."
        )

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.5,
        )

        text = self._extract_text(response)
        try:
            brief = self._parse_json_response(text)
        except json.JSONDecodeError:
            brief = {"trends": [], "summary": "Failed to parse trend brief"}

        return {
            "trend_brief": brief,
            "scan_type": scan_type,
            "trend_count": len(brief.get("trends", [])),
        }
