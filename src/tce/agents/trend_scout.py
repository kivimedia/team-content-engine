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

RECENCY RULES (NON-NEGOTIABLE):
- ONLY include stories published within the last 14 days. This is a HARD cutoff.
- Ideally all stories should be from the last 7 days.
- NEVER include stories older than 14 days, no matter how relevant they seem.
- NEVER reference product launches, announcements, or events from months ago.
- If a search result has an age/date showing it is older than 14 days, SKIP IT entirely.
- If you are unsure of a story's age, do NOT include it.
- Today's date will be provided in the prompt. Use it to verify recency.

For each candidate story, provide:
- trend_id: a short unique slug
- headline: 1-sentence summary
- source_url: primary source (REQUIRED - must be a real URL from search results)
- source_type: news, social, company_blog, paper, creator_post
- freshness: estimated hours since publication (MUST be under 336 for 14-day cutoff)
- relevance_score: 1-10 based on alignment with AI/business audience interests
- template_fit: list of template families this story could power
- angle_suggestions: 2-3 possible angles a writer could take
- source_creator_overlap: boolean - is a known source creator already covering this?
- evidence_available: how easy it is to find primary sources (easy/moderate/hard)

Rank stories by: freshness * 0.5 + relevance_score * 0.3 + evidence_available * 0.2
(Freshness is the DOMINANT factor - recent stories always beat older ones.)

Output a JSON object with:
- trends: array of trend objects (minimum 15, aim for 20-25, all from the last 14 days)
- summary: 2-sentence overview of the trend landscape THIS WEEK
"""


@register_agent
class TrendScout(AgentBase):
    name = "trend_scout"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Produce a trend brief from live web search results or general knowledge.

        If context contains a "topic" key, the user has specified what to write about.
        In that case, skip web search and build a focused trend brief from the topic.
        """
        scan_type = context.get("scan_type", "daily")
        operator_topics = context.get("operator_topics", [])
        focus_areas = context.get("focus_areas", ["AI", "technology", "business automation"])
        user_topic = context.get("topic", "")

        # ---------------------------------------------------------------
        # FAST PATH: User provided a specific topic - skip web search,
        # build a trend brief directly from the topic description.
        # ---------------------------------------------------------------
        if user_topic:
            self._report(f"User-provided topic detected, skipping web search")
            self._report(f"Topic: {user_topic[:200]}")

            from datetime import date as date_cls
            today_str = date_cls.today().isoformat()

            topic_prompt = (
                f"The operator has provided a SPECIFIC topic for today's post. "
                f"Your job is to build a Trend Brief around this topic ONLY. "
                f"Do NOT search for or suggest alternative topics.\n\n"
                f"TODAY: {today_str}\n"
                f"ASSIGNED TOPIC:\n{user_topic}\n\n"
                f"Build a trend brief with:\n"
                f"- One primary trend entry for the assigned topic\n"
                f"- 2-3 angle suggestions the writer could take\n"
                f"- A summary that frames the topic's relevance right now\n"
                f"- Use relevance_score 10 for the primary topic\n"
                f"- Set source_url to 'operator_provided' and freshness to 1"
            )

            response = await self._call_llm(
                messages=[{"role": "user", "content": topic_prompt}],
                system=SYSTEM_PROMPT,
                max_tokens=4096,
                temperature=0.3,
            )

            text = self._extract_text(response)
            try:
                brief = self._parse_json_response(text)
            except json.JSONDecodeError:
                # Construct a minimal brief from the topic directly
                brief = {
                    "trends": [{
                        "trend_id": "user-topic",
                        "headline": user_topic[:200],
                        "source_url": "operator_provided",
                        "source_type": "operator",
                        "freshness": 1,
                        "relevance_score": 10,
                        "template_fit": [context.get("template_hint", "big_shift_explainer")],
                        "angle_suggestions": ["Direct analysis", "Practical guide", "Contrarian take"],
                        "evidence_available": "moderate",
                    }],
                    "summary": f"Operator-assigned topic: {user_topic[:200]}",
                }

            trends = brief.get("trends", [])
            self._report(f"Built trend brief with {len(trends)} entries from user topic")
            for i, t in enumerate(trends, 1):
                headline = t.get("headline", t.get("topic", "untitled"))
                self._report(f"  {i}. {headline}")

            current_events_context = f"Operator-assigned topic: {user_topic[:200]}"

            return {
                "trend_brief": brief,
                "scan_type": "operator_topic",
                "trend_count": len(trends),
                "web_search_used": False,
                "current_events_context": current_events_context,
            }

        # ---------------------------------------------------------------
        # STANDARD PATH: Web search for trending stories
        # ---------------------------------------------------------------

        # PRD Section 49.4: Multi-source web search for real trending stories
        from tce.services.web_search import WebSearchService

        search = WebSearchService()
        search_results = []
        niche = context.get("niche", "general")

        if search.api_key:
            if niche == "coaching":
                # Coaching-niche sources: topics that resonate with coaches
                # wondering about AI agents and growing their practice
                source_queries = [
                    "AI coaching tools automation this week",
                    "coaching business AI agents 2026",
                    "AI replacing virtual assistants coaching",
                    "coaching industry trends technology",
                    "online coaching business growth AI",
                    "AI content creation for coaches",
                    "coaching client retention strategies AI",
                    "solopreneur AI automation tools",
                ]
                topical_queries = [
                    "AI agents for small business owners",
                    "coaches using ChatGPT Claude AI",
                    "done for you services coaching AI",
                    "coaching business scalability without hiring",
                    "AI marketing for coaches consultants",
                    "vibe coding no code tools coaches",
                    "digital products coaching AI automation",
                    "coaching industry disruption AI 2026",
                ]
            else:
                # General tech/business + frontier-model release sources.
                # The version-specific queries surface stories about Claude 4.7,
                # Sonnet 4.6, Haiku 4.5, GPT-5 family, Gemini 2.5/3, etc., which
                # the planner needs to reference by name (vague version refs
                # read as AI slop).
                source_queries = [
                    "site:anthropic.com news this week",
                    "site:openai.com blog announcement this week",
                    "site:deepmind.google blog this week",
                    "site:techcrunch.com AI startups funding",
                    "site:theverge.com technology product launch",
                    "site:reddit.com/r/ClaudeAI new release",
                    "site:reddit.com/r/OpenAI new release",
                    "site:news.ycombinator.com Show HN AI",
                    "site:venturebeat.com enterprise AI automation",
                    "site:simonwillison.net new model release",
                    "site:semafor.com technology business",
                    "site:platformer.news AI",
                ]
                topical_queries = [
                    # Frontier-model recency - explicitly ask by version so we
                    # surface stories the planner can cite ("Sonnet 4.6 cut my
                    # agent costs 40%") instead of "a recent Claude model".
                    "Claude 4.7 release Anthropic this week",
                    "Claude Sonnet 4.6 update changelog",
                    "Claude Haiku 4.5 benchmark",
                    "Anthropic announcement Claude Code Skills",
                    "OpenAI GPT-5 release news this week",
                    "Google Gemini 2.5 update this week",
                    "Llama 4 DeepSeek V3 Qwen 3 open weights",
                    "Cursor Windsurf coding agent update",
                    # Builder + business angles (still relevant for the audience)
                    "AI agents production case study this week",
                    "AI tools small business owner this week",
                    "vibe coding solo founder shipped this week",
                    "agency owner AI agent stack this week",
                ]
            self._report(f"Searching {len(source_queries)} sources + {len(topical_queries)} topical + {len(focus_areas)} focus areas")
            for sq in source_queries:
                results = await search.search_news(sq, count=5)
                search_results.extend(results)
            for tq in topical_queries:
                results = await search.search_news(tq, count=5)
                search_results.extend(results)
            # General focus area searches
            for area in focus_areas[:3]:
                results = await search.search_news(f"latest {area} news this week", count=5)
                search_results.extend(results)
            if operator_topics:
                self._report(f"Searching operator topics: {', '.join(operator_topics[:2])}")
                for topic in operator_topics[:2]:
                    results = await search.search_fresh(topic, count=5)
                    search_results.extend(results)
            self._report(f"Found {len(search_results)} search results from diverse sources")

        from datetime import date as date_cls

        today_str = date_cls.today().isoformat()

        prompt_parts = [
            f"Produce a {scan_type} Trend Brief for today ({today_str}).",
            f"Focus areas: {', '.join(focus_areas)}",
            f"HARD RULE: Today is {today_str}. Only include stories from the last 14 days.",
        ]

        # Layer 2 of TJ grounding: when a creator_profile is in context (e.g.
        # TJ Robertson for walking-video generation), bias the trend scan
        # toward their high-engagement topic clusters so downstream agents
        # start with raw material that fits the creator's proven zones.
        creator_profile = context.get("creator_profile") or {}
        top_patterns = creator_profile.get("top_patterns") or []
        topic_prefs = [p.split(":", 1)[1].replace("_", " ")
                       for p in top_patterns if p.startswith("topic:")]
        if topic_prefs:
            creator_name = creator_profile.get("creator_name", "the reference creator")
            prompt_parts.append(
                f"\nPREFERRED TOPIC CLUSTERS (from {creator_name}'s engagement analysis):\n"
                + "\n".join(f"- {t}" for t in topic_prefs)
                + "\nRank trends that fit these clusters higher (multiply relevance_score by 1.3). "
                "Do not invent stories to fit - only prefer stories that organically match. "
                "If no eligible stories fit a cluster, do not force it."
            )

        if operator_topics:
            prompt_parts.append(
                f"The operator has specifically requested coverage of: {', '.join(operator_topics)}"
            )

        if search_results:
            prompt_parts.append("\n## Live Web Search Results\n")
            # Deduplicate by URL before passing to LLM
            seen_urls: set[str] = set()
            deduped: list[dict] = []
            for r in search_results:
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    deduped.append(r)
            search_results = deduped
            for i, r in enumerate(search_results[:40], 1):
                prompt_parts.append(
                    f"{i}. **{r['title']}**\n"
                    f"   URL: {r['url']}\n"
                    f"   {r['description']}\n"
                    f"   Age: {r.get('age', 'unknown')}"
                )
            prompt_parts.append(
                "\nUse ONLY these real search results as your source of trending stories. "
                "Do NOT add stories from your own knowledge or training data. "
                "Every trend MUST have a source_url from the search results above. "
                "Skip any result that appears older than 14 days based on its age field. "
                "Rank by the scoring formula in your instructions (freshness is dominant)."
            )
        else:
            prompt_parts.append(
                f"No live search results available (no search API configured). "
                f"Today is {today_str}. Using your knowledge, identify ONLY stories that "
                f"you are CERTAIN happened within the last 7-14 days (before {today_str}). "
                f"For each story you MUST include the actual publication date in the headline. "
                f"Example: 'Google announced Gemini 2.5 Pro (March 25, 2026)'. "
                f"If you cannot confidently date a story to within the last 14 days, "
                f"DO NOT include it. It is better to return 3 well-dated trends than "
                f"10 trends with uncertain dates. Set source_url to the actual article URL "
                f"if you know it, or 'unknown' if you don't."
            )

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
            temperature=0.5,
        )

        self._report("Parsing trend brief...")
        text = self._extract_text(response)
        try:
            brief = self._parse_json_response(text)
        except json.JSONDecodeError:
            brief = {"trends": [], "summary": "Failed to parse trend brief"}

        # Hard recency filter: reject any trend the LLM returned with freshness > 336h (14 days)
        raw_trends = brief.get("trends", [])
        trends = []
        rejected = 0
        for t in raw_trends:
            freshness = t.get("freshness")
            # Reject if freshness is explicitly > 14 days (336 hours)
            if freshness is not None:
                try:
                    if float(freshness) > 336:
                        rejected += 1
                        continue
                except (ValueError, TypeError):
                    pass
            # When we have search results, reject trends without real source URLs
            if search_results and not t.get("source_url"):
                rejected += 1
                continue
            trends.append(t)
        brief["trends"] = trends
        if rejected:
            self._report(f"Filtered out {rejected} stale/unsourced trends (>14 days or no URL)")

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
