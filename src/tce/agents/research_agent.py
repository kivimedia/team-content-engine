"""Research Agent — verifies claims from primary sources before drafting."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

SYSTEM_PROMPT = """\
You are the Research Agent for a content engine. Your job is to verify claims, \
build an evidence bank, and ensure every publishable post is grounded in truth.

RULES (PRD Section 17):
- Hard claims (statistics, launches, pricing, funding, timing) REQUIRE source support
- Soft claims (interpretations) require evidence + signal words ("suggests", "likely")
- Opinion claims must be framed as opinion, not fact
- No unsupported stats, no invented timelines, no "everyone is saying" claims
- Prefer first-party documentation for product/feature claims

For each claim you evaluate, provide:
- claim: the statement
- claim_class: hard / soft / opinion
- source: where this comes from
- source_type: official_docs / news / blog / filing / transcript / inference
- confidence: verified / uncertain / unsupported
- approved_wording: safe way to state this claim
- caveats: any qualifications needed
- freshness: how recent is the source

Output a JSON object with:
- topic: the research topic
- verified_claims: array of verified claim objects
- uncertain_claims: array of uncertain claim objects
- rejected_claims: array of rejected claims with reasons
- source_refs: array of source references
- thesis_candidates: 2-3 possible thesis statements supported by evidence
- risk_flags: any concerns about the topic
- safe_to_publish: boolean
"""


@register_agent
class ResearchAgent(AgentBase):
    name = "research_agent"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Build a research brief for a given topic."""
        topic = context.get("topic", "")
        evidence_requirements = context.get("evidence_requirements", [])
        story_brief = context.get("story_brief", {})

        prompt_parts = [f"Research this topic thoroughly: {topic}"]

        if evidence_requirements:
            prompt_parts.append(
                "The Story Strategist requires verification of: "
                f"{json.dumps(evidence_requirements)}"
            )

        if story_brief:
            prompt_parts.append(
                f"Story context — thesis: {story_brief.get('thesis', 'N/A')}, "
                f"audience: {story_brief.get('audience', 'N/A')}"
            )

        prompt_parts.append(
            "Verify all claims using your knowledge of primary sources. "
            "Flag anything you cannot verify with high confidence."
        )

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=6144,
            temperature=0.3,
        )

        text = self._extract_text(response)
        try:
            brief = self._parse_json_response(text)
        except json.JSONDecodeError:
            brief = {
                "topic": topic,
                "verified_claims": [],
                "uncertain_claims": [],
                "rejected_claims": [],
                "source_refs": [],
                "thesis_candidates": [],
                "risk_flags": ["Failed to parse research output"],
                "safe_to_publish": False,
            }

        return {"research_brief": brief}
