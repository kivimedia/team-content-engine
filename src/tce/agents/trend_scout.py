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
- source_type: news, social, company_blog, paper, creator_post, reddit
- freshness: estimated hours since publication (MUST be under 336 for 14-day cutoff)
- relevance_score: 1-10 based on alignment with the audience's interests
- demand_velocity: 1-10 estimate of "how hungry is the audience for this RIGHT NOW?"
  When the input candidate already has a demand_velocity (Reddit-sourced), USE IT VERBATIM.
  When estimating from news alone, infer from social cues:
    1-3 = quiet niche update    4-6 = active discussion in pockets
    7-9 = trending hard         10  = explosive front-page energy
- hook_strength: 1-10 — does this trend MAP CLEANLY to one of our proven hook templates?
  Score the strongest matching template family from this list:
    big_shift_explainer       contrarian_diagnosis       hidden_feature_shortcut
    tactical_workflow_guide   founder_reflection         case_study_build_story
    second_order_implication  weekly_roundup             teardown_myth_busting
    comment_keyword_cta_guide
  10 = obvious template fit + naturally strong hook (e.g. a clear before/after,
       a sharp contrarian read, a hidden capability the audience hasn't noticed).
  5  = topic could work but the angle is muddy or the hook needs a stretch.
  1-3 = no template gives this trend a strong hook. Trends in this band will be
       FILTERED OUT downstream — only include them if you genuinely can't find
       enough higher-scoring candidates.
- template_fit: list of template families this story could power (must include the
  family you scored hook_strength against)
- angle_suggestions: 2-3 possible angles a writer could take
- source_creator_overlap: boolean - is a known source creator already covering this?
- evidence_available: how easy it is to find primary sources (easy/moderate/hard)

RANK by composite_score =
  freshness_factor × relevance_factor × demand_factor × hook_factor × evidence_factor
where each factor is normalized to 0.1-1.0:
  freshness_factor = max(0.1, 1 - hours/336)
  relevance_factor = relevance_score / 10
  demand_factor    = demand_velocity / 10
  hook_factor      = hook_strength / 10
  evidence_factor  = {easy: 1.0, moderate: 0.7, hard: 0.4}

This is MULTIPLICATIVE — a weakness in any single factor severely penalizes the
topic. A 12h-old story with relevance 5, demand 3, hook 4 (composite ~0.058) loses
to a 60h-old story with relevance 8, demand 8, hook 9 (composite ~0.472). Viral
topics need to be strong on EVERY axis, not just one.

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
            self._report("User-provided topic detected, skipping web search")
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
        from tce.services.reddit_demand import DEFAULT_SUBREDDITS, RedditDemandService
        from tce.services.web_search import WebSearchService
        from tce.services.youtube_demand import (
            DEFAULT_QUERIES as DEFAULT_YT_QUERIES,
        )
        from tce.services.youtube_demand import (
            YouTubeDemandService,
        )

        search = WebSearchService()
        search_results = []
        reddit_signals: list[dict[str, Any]] = []
        youtube_signals: list[dict[str, Any]] = []
        niche = context.get("niche", "general")

        # Workspace-aware: a tenant may override the query lists. When set,
        # `source_queries`, `topical_queries`, and optionally `subreddits` come
        # from the DB; otherwise we fall through to the niche-based defaults below.
        ws_override = None
        ws_id_for_focus = context.get("workspace_id")
        if ws_id_for_focus:
            try:
                from tce.services.strategy_loader import load_trend_focus_for_workspace
                ws_override = await load_trend_focus_for_workspace(self.db, ws_id_for_focus)
            except Exception:
                ws_override = None

        # Pull learning-loop multipliers — what template families have actually
        # performed in the last N days. Bias hook_strength scoring toward winners.
        template_multipliers: dict[str, float] = {}
        if self.db is not None and context.get("apply_learning_multipliers", True):
            try:
                from tce.services.learning import LearningService
                learning = LearningService(self.db)
                template_multipliers = await learning.get_template_performance_multipliers(
                    days=int(context.get("learning_window_days", 30))
                )
                if template_multipliers:
                    self._report(
                        f"Loaded {len(template_multipliers)} template multipliers from "
                        f"posted-content performance: {template_multipliers}"
                    )
            except Exception:
                # Don't let a learning-loop hiccup take down trend discovery.
                template_multipliers = {}

        if search.api_key and ws_override and isinstance(ws_override, dict):
            source_queries = list(ws_override.get("source_queries") or [])
            topical_queries = list(ws_override.get("topical_queries") or [])
            if not source_queries and not topical_queries:
                ws_override = None  # empty override - fall through to defaults
            else:
                self._report(
                    f"Using workspace trend focus override "
                    f"({len(source_queries)} sources + {len(topical_queries)} topicals)"
                )
        if search.api_key and not ws_override:
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

        # Reddit demand signals — leading indicator of viral demand, often 12-48h
        # ahead of news pickup. Runs independently of the Brave search API.
        ws_subreddits: list[str] = []
        ws_yt_queries: list[str] = []
        if ws_override and isinstance(ws_override, dict):
            ws_subreddits = list(ws_override.get("subreddits") or [])
            ws_yt_queries = list(ws_override.get("youtube_queries") or [])
        subreddits = ws_subreddits or DEFAULT_SUBREDDITS.get(
            niche, DEFAULT_SUBREDDITS["general"]
        )
        try:
            reddit = RedditDemandService()
            reddit_signals = await reddit.fetch_demand_signals(
                subreddits, per_subreddit=15, max_total=20
            )
            self._report(
                f"Pulled {len(reddit_signals)} Reddit demand signals "
                f"from {len(subreddits)} subreddits"
            )
            for r in reddit_signals[:5]:
                self._report(
                    f"  r/{r['subreddit']} [demand:{r['demand_velocity']}, "
                    f"{r['comments_per_hour']}c/h]: {r['title'][:80]}"
                )
        except Exception:
            self._report("Reddit demand fetch failed; proceeding without it")
            reddit_signals = []

        # YouTube demand signals — view-velocity is the cleanest paid-attention
        # signal we can measure. Skipped silently when YOUTUBE_API_KEY is unset
        # or the daily quota is exhausted.
        youtube = YouTubeDemandService()
        if youtube.api_key:
            yt_queries = ws_yt_queries or DEFAULT_YT_QUERIES.get(
                niche, DEFAULT_YT_QUERIES["general"]
            )
            try:
                youtube_signals = await youtube.fetch_demand_signals(
                    yt_queries, days_back=7, per_query=10, max_total=15
                )
                self._report(
                    f"Pulled {len(youtube_signals)} YouTube demand signals "
                    f"from {len(yt_queries)} queries"
                )
                for v in youtube_signals[:5]:
                    self._report(
                        f"  YT [demand:{v['demand_velocity']}, "
                        f"{v['views_per_hour']}v/h] {v['channel']}: {v['title'][:70]}"
                    )
            except Exception:
                self._report("YouTube demand fetch failed; proceeding without it")
                youtube_signals = []
        else:
            self._report("YOUTUBE_API_KEY not set; skipping YouTube demand layer")

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
                "Rank by the multiplicative composite formula in your instructions."
            )
        elif not reddit_signals and not youtube_signals:
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

        if reddit_signals:
            prompt_parts.append("\n## Reddit Demand Signals (live)\n")
            prompt_parts.append(
                "These are top-of-day posts from niche subreddits, sorted by demand_velocity "
                "(comments_per_hour weighted 60% + score_velocity 40%, normalized 1-10). "
                "Reddit demand often leads news pickup by 12-48h — a Reddit thread spiking "
                "right now is a stronger viral signal than yesterday's TechCrunch headline. "
                "When you adopt a Reddit signal as a trend, USE the demand_velocity verbatim, "
                "set source_type='reddit', and set source_url to the permalink.\n"
            )
            for i, r in enumerate(reddit_signals, 1):
                prompt_parts.append(
                    f"{i}. r/{r['subreddit']} [demand:{r['demand_velocity']}/10, "
                    f"{r['comments_per_hour']}c/h, {r['hours_old']}h old]\n"
                    f"   Title: {r['title']}\n"
                    f"   Permalink: {r['permalink']}"
                )

        if template_multipliers:
            prompt_parts.append("\n## Posted-Content Performance Multipliers (last 30d)\n")
            prompt_parts.append(
                "Based on actual engagement on what we've published, the audience has been "
                "responding at these relative rates per template family (1.0 = average, "
                ">1.0 = above average, <1.0 = below average). When you score hook_strength, "
                "favor families that are currently working in market. Use these multipliers "
                "as a tilt — don't blindly assign hook_strength=10 to a winning family if "
                "the topic genuinely doesn't fit; just give the benefit of the doubt at the "
                "margins.\n"
            )
            for fam, mult in sorted(template_multipliers.items(), key=lambda x: -x[1]):
                tag = "↑↑" if mult >= 1.5 else "↑" if mult > 1.05 else "↓" if mult < 0.95 else "·"
                prompt_parts.append(f"  {tag} {fam}: {mult}×")

        if youtube_signals:
            prompt_parts.append("\n## YouTube Demand Signals (live)\n")
            prompt_parts.append(
                "Recent niche videos sorted by demand_velocity (views_per_hour + "
                "engagement_per_hour, normalized 1-10). View-velocity is the cleanest "
                "'paid attention' signal — these are topics audiences are actively watching. "
                "When adopting a YouTube signal, USE the demand_velocity verbatim, set "
                "source_type='creator_post', and set source_url to the video URL. "
                "The video TITLE is itself a battle-tested hook — study it for hook_strength.\n"
            )
            for i, v in enumerate(youtube_signals, 1):
                prompt_parts.append(
                    f"{i}. {v['channel']} [demand:{v['demand_velocity']}/10, "
                    f"{v['views']:,} views in {v['hours_old']}h]\n"
                    f"   Title: {v['title']}\n"
                    f"   URL: {v['url']}"
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

        # Hard filters: reject trends that are stale, unsourced, or hookless.
        # min_hook_strength is contextual (default 4) so workspaces in starvation
        # mode can drop the floor temporarily.
        raw_trends = brief.get("trends", [])
        min_hook_strength = float(context.get("min_hook_strength", 4))
        trends = []
        rejected_stale = 0
        rejected_unsourced = 0
        rejected_hookless = 0
        for t in raw_trends:
            freshness = t.get("freshness")
            if freshness is not None:
                try:
                    if float(freshness) > 336:
                        rejected_stale += 1
                        continue
                except (ValueError, TypeError):
                    pass
            if search_results and not t.get("source_url"):
                rejected_unsourced += 1
                continue
            hook_strength = t.get("hook_strength")
            if hook_strength is not None:
                try:
                    if float(hook_strength) < min_hook_strength:
                        rejected_hookless += 1
                        continue
                except (ValueError, TypeError):
                    pass
            # Pre-compute composite_score so downstream agents (story_strategist)
            # can sort without re-deriving the formula.
            try:
                f = max(0.1, 1.0 - float(freshness or 0) / 336.0)
                r = float(t.get("relevance_score", 5)) / 10.0
                d = float(t.get("demand_velocity", 5)) / 10.0
                h = float(t.get("hook_strength", 5)) / 10.0
                ev_map = {"easy": 1.0, "moderate": 0.7, "hard": 0.4}
                e = ev_map.get(str(t.get("evidence_available", "moderate")).lower(), 0.7)
                base = f * r * d * h * e
                # Apply learning multiplier if the matched template family is in
                # the multipliers dict. Falls back to 1.0 (no tilt) otherwise.
                template_fit = t.get("template_fit") or []
                if isinstance(template_fit, str):
                    template_fit = [template_fit]
                family_multiplier = 1.0
                for fam in template_fit:
                    if fam in template_multipliers:
                        # If multiple templates fit, pick the strongest multiplier
                        family_multiplier = max(family_multiplier, template_multipliers[fam])
                t["composite_score"] = round(base * family_multiplier, 4)
                if family_multiplier != 1.0:
                    t["learning_multiplier"] = family_multiplier
            except (ValueError, TypeError):
                t["composite_score"] = 0.0
            trends.append(t)

        # Re-sort by composite_score so the LLM's ordering can't override the formula.
        trends.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)
        brief["trends"] = trends
        rejected = rejected_stale + rejected_unsourced + rejected_hookless
        if rejected:
            self._report(
                f"Filtered out {rejected} trends "
                f"(stale:{rejected_stale}, unsourced:{rejected_unsourced}, "
                f"hookless:{rejected_hookless}, min_hook_strength={min_hook_strength})"
            )

        self._report(f"Found {len(trends)} trending stories:")
        for i, t in enumerate(trends, 1):
            headline = t.get("headline", t.get("topic", "untitled"))
            source = t.get("source_url", t.get("source_type", "no source"))
            relevance = t.get("relevance_score", "?")
            demand = t.get("demand_velocity", "?")
            hook = t.get("hook_strength", "?")
            composite = t.get("composite_score", "?")
            freshness = t.get("freshness", "?")
            self._report(
                f"  {i}. [comp:{composite} rel:{relevance} dem:{demand} hook:{hook}] {headline}"
            )
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
