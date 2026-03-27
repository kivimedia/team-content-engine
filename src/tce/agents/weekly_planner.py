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

INPUT: A Trend Brief with 10-20 candidate stories from this week's news.

YOUR JOB:
1. Select 5 topics (one per day) from the trend pool
2. Each day has a fixed cadence angle (provided below)
3. The 5 topics should connect to ONE overarching weekly theme
4. Design a weekly gift/guide that ties all 5 posts together
5. Choose ONE CTA keyword that all 5 posts will use

CONSTRAINTS:
- Each day's topic MUST match its cadence angle
- No two days should cover the same story - pick diverse angles from different trends
- The weekly theme should feel natural, not forced
- The gift must deliver real value (not filler)
- Topics should build on each other: Monday sets context, Tuesday gives tools, \
  Wednesday challenges assumptions, Thursday proves it works, Friday zooms out

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
- gift_theme: object with "title" and "subtitle" of the weekly guide/gift
- gift_sections: 4-6 section titles the guide should contain
- cta_keyword: ONE word in ALL CAPS (the comment keyword for all 5 posts)
- days: array of 5 objects, each containing:
  - day_of_week: 0-4
  - day_label: "Monday" through "Friday"
  - angle_type: from the cadence
  - topic: 1 sentence, scroll-stopping, specific (name tools/companies/numbers)
  - thesis: the core argument in 1-2 plain sentences (what will the reader walk away believing?)
  - audience: who this targets (be specific, e.g. "agency owners doing $10-50K/mo")
  - desired_belief_shift: FROM -> TO (use plain language)
  - evidence_requirements: array of claims to verify
  - visual_job: cinematic_symbolic / proof_diagram / emotional_alternate
  - connection_to_gift: how this day's post connects to the weekly gift
  - platform_notes: any platform-specific adjustments
"""


@register_agent
class WeeklyPlanner(AgentBase):
    name = "weekly_planner"
    default_model = "claude-opus-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Plan the entire week's content from a single trend scan."""
        # Step 1: Run trend_scout internally to get the full landscape
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
        # Ask for a weekly scan with more results
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
            json.dumps(trends[:15], indent=2),
            f"\nTrend landscape: {trend_brief.get('summary', 'N/A')}",
            f"\n5-DAY CADENCE:\n{cadence_desc}",
        ]

        if recent_posts:
            prompt_parts.append(
                f"\nRECENT POSTS (avoid repetition):\n{json.dumps(recent_posts[-10:], indent=2)}"
            )

        if operator_overrides:
            prompt_parts.append(f"\nOPERATOR OVERRIDES:\n{json.dumps(operator_overrides)}")

        prompt_parts.append(
            "\nPlan the entire week. Select 5 topics that build a coherent narrative, "
            "design the weekly gift, and choose the CTA keyword."
        )

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
            temperature=0.6,
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
                                "with weekly_theme, gift_theme, cta_keyword, and days array. "
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
        gift = weekly_plan.get("gift_theme", "N/A")
        keyword = weekly_plan.get("cta_keyword", "N/A")
        days = weekly_plan.get("days", [])

        self._report("\nWeekly Plan:")
        self._report(f"  Theme: {theme}")
        self._report(f"  Gift: {gift}")
        self._report(f"  CTA Keyword: {keyword}")
        self._report(f"  Days planned: {len(days)}")

        for d in days:
            day_label = d.get("day_label", f"Day {d.get('day_of_week', '?')}")
            topic = d.get("topic", "N/A")
            angle = d.get("angle_type", "N/A")
            connection = d.get("connection_to_gift", "")
            self._report(f"\n  {day_label} ({angle}):")
            self._report(f"    Topic: {topic}")
            self._report(f"    Thesis: {d.get('thesis', 'N/A')}")
            if connection:
                self._report(f"    Gift connection: {connection}")

        return {
            "weekly_plan": weekly_plan,
            "trend_brief": trend_brief,
            "weekly_theme": theme,
            "gift_theme": gift,
            "weekly_keyword": keyword,
        }
