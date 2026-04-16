"""Weekly Planner - coordinates the entire week's content strategy.

Runs trend_scout ONCE, then selects 5 topics (one per day) that form a
coherent weekly narrative arc, plus a gift/guide theme that ties them together.
"""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import get_agent_class, register_agent

# 5-day cadence (same as story_strategist)
CADENCE = {
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
You are the Weekly Content Planner for Team Content Engine. This is the most \
consequential decision of the week: you choose ALL 5 daily topics in one shot \
so they form a coherent weekly narrative arc.

INPUT: A Trend Brief with 10-20 candidate stories from THIS WEEK's news (all verified \
to be from the last 14 days).

YOUR JOB:
1. Select 5 topics (one per day) from the trend pool
2. Each day has a fixed cadence angle (provided below)
3. The 5 topics should connect to ONE overarching weekly theme
4. Design a weekly gift/guide that ties all 5 posts together
5. Choose ONE CTA keyword that all 5 posts will use

RECENCY RULES (NON-NEGOTIABLE):
- Every topic MUST be based on a trend from the provided brief (which contains only recent stories).
- NEVER substitute with older stories from your own knowledge or training data.
- If a trend mentions a specific event, product launch, or announcement, it must have happened \
within the last 14 days. If you're unsure, pick a different trend.
- Do NOT reference announcements, launches, or news from months or years ago.

CONSTRAINTS:
- Each day's topic MUST match its cadence angle
- No two days should cover the same story - pick diverse angles from different trends
- The weekly theme should feel natural, not forced
- The gift must deliver real value (not filler)
- Topics should build on each other: Monday sets context, Tuesday gives tools, \
  Wednesday challenges assumptions, Thursday proves it works, Friday zooms out

DIVERSITY RULES (CRITICAL - read carefully):
- The 3 options for each day MUST come from 3 DIFFERENT trends/stories. Never give \
  3 variations of the same news item. If Monday option 1 is about "Google Gemini", \
  option 2 must be about a completely different story (e.g. "Shopify AI tools") and \
  option 3 about yet another (e.g. "remote work productivity study").
- Across all 5 days, aim for at least 10 distinct underlying stories/trends used. \
  Do not reuse the same trend for multiple days unless you genuinely have no alternatives.
- If the trend brief has fewer than 10 unique stories, say so in the weekly_theme \
  and do your best - but NEVER pad by rephrasing the same story 3 ways.
- Variety in topic TYPE matters too: mix product launches, research findings, \
  case studies, cultural shifts, tool reviews, and opinion pieces. Do not make all \
  5 days about product launches or all about research papers.

HUMANITARIAN SENSITIVITY (non-negotiable):
Before choosing any topic, consider:
- Is there an active crisis, war, disaster, or mass layoffs this week? Avoid topics \
that trivialize or exploit human suffering.
- Never use fear as a hook ("AI is coming for your job and there's nothing you can do"). \
Instead empower: show what's possible.
- Never punish the audience ("if you're not using AI by now, you deserve to be left behind"). \
Instead help them catch up.
- Avoid casual war/military metaphors during sensitive periods.
- Every topic must pass the dignity test: does it treat every person - including \
competitors, beginners, and the "most people" you reference - with basic respect?
- If a trend involves layoffs or job displacement, acknowledge the human cost before \
offering the opportunity angle.

CRITICAL - WRITING STYLE FOR TOPICS AND THESES:
Write like a smart friend explaining what the post is about over coffee. NOT like \
a corporate whitepaper or AI-generated summary.

BAD (AI slop - never write like this):
- "Hyperautomation trends in 2026 focus on enabling non-technical domain experts \
with platform guardrails and responsible innovation frameworks"
- "Organizations leveraging agentic AI workflows are experiencing paradigm shifts \
in operational efficiency and stakeholder engagement"

GOOD (how a real person would describe it):
- "Most teams are using AI wrong - they automate the easy stuff and ignore the \
hard decisions. Here's what the 1% do differently."
- "Google just released Gemini 2.5 and nobody's talking about the one feature \
that changes everything for solo founders."
- "I rebuilt my entire client onboarding in 2 hours with Claude. Here's the exact \
workflow so you can steal it."

Rules for topic/thesis writing:
- Use "you", "I", "we" - write in first or second person
- Name real tools, companies, people when possible
- Be specific and concrete, not abstract
- If you can't picture what the post actually says, the topic is too vague
- Short sentences. Plain words. No jargon unless the audience uses that jargon daily.
- The topic should make someone stop scrolling. The thesis should make them want to read.

OUTPUT: A JSON object with:
- weekly_theme: 1 sentence describing the week's narrative arc (conversational, not corporate)
- guide_options: array of 3 objects, each a different freebie/guide idea for the week:
  - title: guide title (max 12 words)
  - subtitle: what the reader gets from it
  - sections: array of 4-6 section titles
  - rationale: 1 sentence explaining why this guide fits the week's theme
- cta_keyword: ONE word in ALL CAPS (the comment keyword for all 5 posts)
- days: array of 5 objects, each containing:
  - day_of_week: 0-4
  - day_label: "Monday" through "Friday"
  - angle_type: from the cadence
  - options: array of 3 topic options for this day slot, each containing:
    - topic: 1 sentence, scroll-stopping, specific (name tools/companies/numbers)
    - thesis: the core argument in 1-2 plain sentences (what will the reader walk away believing?)
    - audience: who this targets (be specific, e.g. "agency owners doing $10-50K/mo")
    - desired_belief_shift: FROM -> TO (use plain language)
    - evidence_requirements: array of claims to verify
    - visual_job: cinematic_symbolic / proof_diagram / emotional_alternate
    - connection_to_gift: how this day's post connects to the weekly gift
    - platform_notes: any platform-specific adjustments
  The first option (index 0) should be your BEST pick. Options 1-2 are solid alternatives.
"""


@register_agent
class WeeklyPlanner(AgentBase):
    name = "weekly_planner"
    default_model = "claude-opus-4-7"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Plan the entire week's content from a single trend scan."""
        # Step 1: Run trend_scout (or reuse shared brief from monthly planner)
        if context.get("_skip_trend_scout") and context.get("trend_brief"):
            self._report("Using shared trend brief from monthly planner")
            trend_brief = context["trend_brief"]
            trends = trend_brief.get("trends", [])
            self._report(f"Shared brief has {len(trends)} trend candidates")
        else:
            self._report("Phase 1: Scanning trends for the week...")

            trend_scout_cls = get_agent_class("trend_scout")
            trend_scout = trend_scout_cls(
                db=self.db,
                settings=self.settings,
                cost_tracker=self.cost_tracker,
                prompt_manager=self.prompt_manager,
                run_id=self.run_id,
                progress_log=self._progress_log,
            )
            scout_context = {
                **context,
                "scan_type": "weekly",
                "focus_areas": context.get("focus_areas", ["AI", "technology", "business automation"]),
            }
            scout_result = await trend_scout._execute(scout_context)
            trend_brief = scout_result.get("trend_brief", {})
            trends = trend_brief.get("trends", [])
            self._report(f"Found {len(trends)} trend candidates for the week")

        # Step 2: Strategic 5-day planning
        self._report("Phase 2: Planning 5-day content arc...")

        recent_posts = context.get("recent_posts", [])
        operator_overrides = context.get("operator_overrides", {})

        cadence_desc = "\n".join(
            f"  Day {i} ({c['label']}): angle = {c['angle']}" for i, c in CADENCE.items()
        )

        prompt_parts = [
            "TREND BRIEF (this week's candidate stories):",
            json.dumps(trends[:25], indent=2),
            f"\nTrend landscape: {trend_brief.get('summary', 'N/A')}",
            f"\n5-DAY CADENCE:\n{cadence_desc}",
        ]

        if recent_posts:
            prompt_parts.append(
                f"\nRECENT POSTS (avoid repetition):\n{json.dumps(recent_posts[-10:], indent=2)}"
            )

        if operator_overrides:
            prompt_parts.append(f"\nOPERATOR OVERRIDES:\n{json.dumps(operator_overrides)}")

        # === Inject niche strategy context ===
        niche = context.get("niche", "general")
        if niche == "coaching":
            import os
            strategy_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                "docs", "super-coaching-strategy.md",
            )
            try:
                with open(strategy_path, "r", encoding="utf-8") as f:
                    strategy_text = f.read()
                if len(strategy_text) > 3000:
                    strategy_text = strategy_text[:3000]
                prompt_parts.append(
                    "\nNICHE STRATEGY - SUPER COACHING:\n"
                    "All 5 days MUST be framed for coaches who want to add AI agent teams "
                    "to their coaching business. The creator is Ziv Raviv (Kivi Media, 300+ clients, "
                    "replaced 13-person team with 160 AI agents, trademarked Super Coaching).\n\n"
                    f"{strategy_text}\n\n"
                    "Every topic should make a coach think: I need AI agents in my practice."
                )
                self._report("Loaded Super Coaching strategy for weekly planning")
            except FileNotFoundError:
                prompt_parts.append(
                    "\nNICHE: coaching - Target coaches who want to add AI agent teams. "
                    "All topics should be relevant to coaches scaling with AI, not generic tech."
                )

        # === Inject voice context so planner considers the team's identity ===
        founder_voice = context.get("founder_voice")
        if founder_voice:
            fv_parts = []
            if founder_voice.get("recurring_themes"):
                fv_parts.append(
                    "Recurring themes: " + ", ".join(founder_voice["recurring_themes"])
                )
            if founder_voice.get("values_and_beliefs"):
                fv_parts.append(
                    "Core values: " + ", ".join(founder_voice["values_and_beliefs"])
                )
            if founder_voice.get("taboos"):
                fv_parts.append(
                    "NEVER write about: " + ", ".join(founder_voice["taboos"])
                )
            if founder_voice.get("tone_range"):
                fv_parts.append(f"Tone range: {json.dumps(founder_voice['tone_range'])}")
            if fv_parts:
                prompt_parts.append("\nFOUNDER VOICE (the human behind the brand):\n" + "\n".join(fv_parts))

        creator_profiles = context.get("creator_profiles")
        if creator_profiles:
            creator_lines = []
            for cp in creator_profiles:
                axes = cp.get("voice_axes", {})
                strengths = [k for k, v in axes.items() if v and v >= 8]
                line = f"- {cp['name']} ({cp.get('style', 'N/A')})"
                if strengths:
                    line += f" | strengths: {', '.join(strengths)}"
                if cp.get("top_patterns"):
                    line += f" | best at: {', '.join(cp['top_patterns'][:2])}"
                creator_lines.append(line)
            prompt_parts.append(
                "\nCREATOR TEAM (the humans whose style you're channeling):\n"
                + "\n".join(creator_lines)
                + "\n\nConsider which creators are strongest at which angles when assigning topics. "
                "Pick topics that resonate with the founder's recurring themes and values. "
                "The weekly theme should sound like something the founder would actually say."
            )

        # === Humanitarian sensitivity context ===
        sensitive_period = context.get("sensitive_period", False)
        humanitarian_context = context.get("humanitarian_context", "")
        if sensitive_period or humanitarian_context:
            hum_parts = ["\nHUMANITARIAN CONTEXT (read carefully before choosing topics):"]
            if sensitive_period:
                hum_parts.append(
                    "** SENSITIVE PERIOD ACTIVE ** - Extra caution required. "
                    "Avoid humor about serious topics, war metaphors, fear-based hooks."
                )
            if humanitarian_context:
                hum_parts.append(humanitarian_context)
            prompt_parts.append("\n".join(hum_parts))

        prompt_parts.append(
            "\nPlan the entire week. Select 5 topics that build a coherent narrative, "
            "design the weekly gift, and choose the CTA keyword. "
            "Remember: every topic must pass the humanitarian dignity test."
        )

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
            temperature=0.75,
        )

        text = self._extract_text(response)
        try:
            weekly_plan = self._parse_json_response(text)
        except json.JSONDecodeError:
            self._report("JSON parse failed, attempting repair...")
            try:
                repair = await self._call_llm(
                    messages=[
                        {"role": "user", "content": "\n\n".join(prompt_parts)},
                        {"role": "assistant", "content": text},
                        {
                            "role": "user",
                            "content": (
                                "Your response was not valid JSON. Output ONLY the JSON object "
                                "with weekly_theme, guide_options, cta_keyword, and days array "
                                "(each day has an options array of 3). "
                                "No markdown, no commentary."
                            ),
                        },
                    ],
                    system=SYSTEM_PROMPT,
                    max_tokens=8192,
                    temperature=0.3,
                )
                weekly_plan = self._parse_json_response(self._extract_text(repair))
                self._report("Repair succeeded")
            except Exception:
                weekly_plan = {
                    "weekly_theme": "AI and business trends",
                    "gift_theme": "Weekly AI Insights Guide",
                    "cta_keyword": "GUIDE",
                    "days": [],
                    "_parsing_failed": True,
                }
                self._report("Using fallback weekly plan")

        # Report the plan
        theme = weekly_plan.get("weekly_theme", "N/A")
        keyword = weekly_plan.get("cta_keyword", "N/A")
        days = weekly_plan.get("days", [])

        # Backward compat: extract gift_theme from guide_options[0] or old format
        guide_options = weekly_plan.get("guide_options", [])
        if guide_options and isinstance(guide_options, list):
            gift = guide_options[0] if guide_options else {"title": "N/A", "subtitle": ""}
        else:
            gift = weekly_plan.get("gift_theme", "N/A")

        self._report("\nWeekly Plan:")
        self._report(f"  Theme: {theme}")
        self._report(f"  CTA Keyword: {keyword}")
        self._report(f"  Days planned: {len(days)}")
        if guide_options:
            self._report(f"  Guide options: {len(guide_options)}")
            for gi, go in enumerate(guide_options):
                self._report(f"    [{gi}] {go.get('title', '?')}")

        for d in days:
            day_label = d.get("day_label", f"Day {d.get('day_of_week', '?')}")
            angle = d.get("angle_type", "N/A")
            options = d.get("options", [])
            # Backward compat: if no options array, wrap the day itself as option 0
            if not options and d.get("topic"):
                options = [d]
            self._report(f"\n  {day_label} ({angle}) - {len(options)} option(s):")
            for oi, opt in enumerate(options):
                marker = " *" if oi == 0 else ""
                self._report(f"    [{oi}]{marker} {opt.get('topic', 'N/A')}")

        return {
            "weekly_plan": weekly_plan,
            "trend_brief": trend_brief,
            "weekly_theme": theme,
            "gift_theme": gift,
            "weekly_keyword": keyword,
            "guide_options": guide_options,
        }
