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
        """Produce a trend brief from live web search results or general knowledge."""
        scan_type = context.get("scan_type", "daily")
        operator_topics = context.get("operator_topics", [])
        focus_areas = context.get("focus_areas", ["AI", "technology", "business automation"])

        # PRD Section 49.4: Multi-source web search for real trending stories
        from tce.services.web_search import WebSearchService

        search = WebSearchService()
        search_results = []
        if search.api_key:
            # Source diversity: query specific high-signal sources (PRD Section 49.4)
            source_queries = [
                "site:techcrunch.com AI",
                "site:theverge.com AI technology",
                "site:reddit.com/r/artificial AI news",
                "site:news.ycombinator.com AI",
                "site:venturebeat.com AI business",
                "site:arxiv.org AI machine learning",
            ]
            self._report(f"Searching {len(source_queries)} curated sources + {len(focus_areas)} focus areas")
            for sq in source_queries:
                results = await search.search_news(sq, count=3)
                search_results.extend(results)
            # General focus area searches
            for area in focus_areas[:3]:
                results = await search.search_news(f"latest {area} news trends 2026", count=5)
                search_results.extend(results)
            if operator_topics:
                self._report(f"Searching operator topics: {', '.join(operator_topics[:2])}")
                for topic in operator_topics[:2]:
                    results = await search.search_fresh(topic, count=5)
                    search_results.extend(results)
            self._report(f"Found {len(search_results)} search results from diverse sources")

        prompt_parts = [
            f"Produce a {scan_type} Trend Brief for today.",
            f"Focus areas: {', '.join(focus_areas)}",
        ]

        if operator_topics:
            prompt_parts.append(
                f"The operator has specifically requested coverage of: {', '.join(operator_topics)}"
            )

        if search_results:
            prompt_parts.append("\n## Live Web Search Results\n")
            for i, r in enumerate(search_results[:20], 1):
                prompt_parts.append(
                    f"{i}. **{r['title']}**\n"
                    f"   URL: {r['url']}\n"
                    f"   {r['description']}\n"
                    f"   Age: {r.get('age', 'unknown')}"
                )
            prompt_parts.append(
                "\nUse these real search results as your primary source of trending stories. "
                "Verify relevance and rank by the scoring formula in your instructions."
            )
        else:
            prompt_parts.append(
                "No live search results available. "
                "Identify the top trending AI/tech stories right now based on your knowledge. "
                "For each, assess its potential as social media content for a business audience."
            )

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.5,
        )

        self._report("Parsing trend brief...")
        text = self._extract_text(response)
        try:
            brief = self._parse_json_response(text)
        except json.JSONDecodeError:
            brief = {"trends": [], "summary": "Failed to parse trend brief"}

        trends = brief.get("trends", [])
        self._report(f"Found {len(trends)} trending stories:")
        for i, t in enumerate(trends, 1):
            headline = t.get("headline", t.get("topic", "untitled"))
            source = t.get("source_url", t.get("source_type", "no source"))
            relevance = t.get("relevance_score", "?")
            freshness = t.get("freshness", "?")
            self._report(f"  {i}. [{relevance}/10] {headline}")
            self._report(f"     Source: {source} | Freshness: {freshness}h ago")
            angles = t.get("angle_suggestions", [])
            if angles:
                self._report(f"     Angles: {', '.join(str(a) for a in angles[:3])}")
        if brief.get("summary"):
            self._report(f"Landscape: {brief['summary']}")

        # PRD Section 51.3: Build current_events_context for downstream QA humanitarian gate
        current_events_headlines = [
            t.get("headline", t.get("topic", ""))
            for t in trends[:10]
            if t.get("headline") or t.get("topic")
        ]
        current_events_context = (
            "Current events this week: " + "; ".join(current_events_headlines)
            if current_events_headlines
            else None
        )

        return {
            "trend_brief": brief,
            "scan_type": scan_type,
            "trend_count": len(trends),
            "web_search_used": bool(search_results),
            "current_events_context": current_events_context,
        }
