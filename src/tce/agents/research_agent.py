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
        story_brief = context.get("story_brief", {})
        topic = context.get("topic", "") or story_brief.get("topic", "")
        evidence_requirements = context.get("evidence_requirements", []) or story_brief.get(
            "evidence_requirements", []
        )
        thesis = story_brief.get("thesis", "")

        self._report(f"Researching: {topic[:80] or 'general topic'}")
        if thesis:
            self._report(f"  Thesis to verify: {thesis[:100]}")
        prompt_parts = [f"Research this topic thoroughly: {topic}"]
        if thesis:
            prompt_parts.append(f"Core thesis to verify: {thesis}")
            prompt_parts.append(
                "CRITICAL: Your job is to find EVIDENCE supporting or challenging the thesis above. "
                "Do NOT introduce new topics or angles. Stay focused on verifying THIS thesis."
            )

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

        # GAP-01: Use web search to verify claims from primary sources
        from tce.services.web_search import WebSearchService

        search = WebSearchService()
        search_context = []
        if search.api_key and topic:
            # Search anchored to planned thesis, not generic topic
            search_query = f"{thesis} {topic}" if thesis else topic
            results = await search.search(search_query, count=8)
            search_context.extend(results)
            # Search for specific evidence requirements
            for req in evidence_requirements[:3]:
                if isinstance(req, str):
                    req_results = await search.search(req, count=3)
                    search_context.extend(req_results)

        if search_context:
            self._report(f"Verifying claims against {len(search_context)} web sources")
            prompt_parts.append("\n## Web Search Results for Verification\n")
            for i, r in enumerate(search_context[:15], 1):
                prompt_parts.append(f"{i}. **{r['title']}** ({r['url']})\n   {r['description']}")
            prompt_parts.append(
                "\nUse these sources to verify claims. Cite URLs when available. "
                "Flag anything not supported by these results as uncertain."
            )
        else:
            prompt_parts.append(
                "Verify all claims using your knowledge of primary sources. "
                "Flag anything you cannot verify with high confidence."
            )

        prompt_parts.append(
            "\nIMPORTANT: Respond ONLY with a valid JSON object. "
            "No commentary before or after the JSON."
        )

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=6144,
            temperature=0.3,
        )

        self._report("Parsing research brief...")
        text = self._extract_text(response)
        try:
            brief = self._parse_json_response(text)
        except json.JSONDecodeError:
            self._report("JSON parse failed, asking LLM to repair...")
            try:
                repair = await self._call_llm(
                    messages=[
                        {"role": "user", "content": "\n\n".join(prompt_parts)},
                        {"role": "assistant", "content": text},
                        {
                            "role": "user",
                            "content": (
                                "Your previous response was not valid JSON. "
                                "Please output ONLY a valid JSON object with keys: "
                                "topic, verified_claims, uncertain_claims, rejected_claims, "
                                "source_refs, thesis_candidates, risk_flags, safe_to_publish. "
                                "No markdown, no commentary."
                            ),
                        },
                    ],
                    system=SYSTEM_PROMPT,
                    max_tokens=6144,
                    temperature=0.1,
                )
                brief = self._parse_json_response(self._extract_text(repair))
            except (json.JSONDecodeError, Exception):
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

        # Verbose reporting
        verified = brief.get("verified_claims", [])
        uncertain = brief.get("uncertain_claims", [])
        rejected = brief.get("rejected_claims", [])
        self._report(
            f"Research complete: {len(verified)} verified,"
            f" {len(uncertain)} uncertain,"
            f" {len(rejected)} rejected claims"
        )
        for i, c in enumerate(verified[:5], 1):
            claim_text = c.get("claim", c) if isinstance(c, dict) else str(c)
            source = c.get("source", "N/A") if isinstance(c, dict) else "N/A"
            self._report(f"  Verified {i}: {str(claim_text)[:120]}")
            self._report(f"    Source: {str(source)[:100]}")
        if len(verified) > 5:
            self._report(f"  ... and {len(verified) - 5} more verified claims")
        for c in rejected[:3]:
            claim_text = c.get("claim", c) if isinstance(c, dict) else str(c)
            reason = c.get("reason", "N/A") if isinstance(c, dict) else "N/A"
            self._report(f"  REJECTED: {str(claim_text)[:100]} - {str(reason)[:60]}")
        safe = brief.get("safe_to_publish", "unknown")
        self._report(f"  Safe to publish: {safe}")
        thesis_candidates = brief.get("thesis_candidates", [])
        if thesis_candidates:
            self._report(f"  Thesis candidates: {len(thesis_candidates)}")
            for t in thesis_candidates[:3]:
                self._report(f"    - {str(t)[:120]}")

        return {"research_brief": brief}
