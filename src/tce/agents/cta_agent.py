"""CTA / Funnel Agent — handles "say XXX" tactic and DM flows (PRD Section 9.7)."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

SYSTEM_PROMPT = """\
You are the CTA Agent for Team Content Engine. You manage the "say XXX" comment \
keyword tactic and DM fulfillment flows.

WEEKLY KEYWORD MODEL (PRD Section 9.7):
- Set ONE primary keyword per week that maps to the weekly DOCX guide
- All 5 daily posts can use this keyword
- Individual posts may also have a secondary micro-CTA for variety
- The operator sets up ONE fulfillment flow per week, not five

CORE RULE: Promise only what can be fulfilled the same day.

APPROVED CTA FAMILIES:
- comment keyword for delivery (e.g., "comment 'guide'")
- comment keyword for waitlist
- comment keyword for invite
- DM me for consult slot
- follow for series continuation
- share/comment prompt for discussion

UNAPPROVED PATTERNS (never generate these):
- fake free guide that doesn't exist
- false scarcity
- "I'll send it immediately" when manual delivery isn't set up
- bait-and-switch from informational to hard pitch

OUTPUT FORMAT (JSON):
- weekly_keyword: the primary keyword for the week
- secondary_keyword: optional per-post secondary keyword (null if not needed)
- fb_cta_line: the CTA line for the Facebook post
- li_cta_line: the CTA line for the LinkedIn post (softer)
- dm_flow: object with {trigger, ack_message, delivery_message, follow_up}
- whatsapp_group_link: placeholder for WhatsApp integration
- fulfillment_checklist: list of things operator must set up
"""


@register_agent
class CTAAgent(AgentBase):
    name = "cta_agent"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate CTA keyword and DM flow."""
        story_brief = context.get("story_brief", {})
        weekly_theme = (
            context.get("weekly_theme", "")
            or story_brief.get("topic", "")
        )
        weekly_keyword = context.get("weekly_keyword")  # May be pre-set
        guide_title = context.get("guide_title", "")

        prompt_parts = []

        if weekly_keyword:
            prompt_parts.append(
                f"The weekly primary keyword is already set: \"{weekly_keyword}\"\n"
                f"Generate the DM flow and CTA lines for today's post."
            )
        else:
            prompt_parts.append(
                "Choose a weekly primary keyword based on the theme and guide."
            )

        prompt_parts.extend([
            f"Weekly theme: {weekly_theme}",
            f"Guide title: {guide_title}",
            f"Story brief: {json.dumps(story_brief, indent=2)}",
            "Generate the CTA package.",
        ])

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=2048,
            temperature=0.5,
        )

        text = self._extract_text(response)
        try:
            cta_package = self._parse_json_response(text)
        except json.JSONDecodeError:
            cta_package = {
                "weekly_keyword": weekly_keyword or "guide",
                "dm_flow": {"trigger": weekly_keyword or "guide"},
            }

        self._report(f"CTA package ready:")
        self._report(f"  Weekly keyword: \"{cta_package.get('weekly_keyword', 'N/A')}\"")
        secondary = cta_package.get("secondary_keyword")
        if secondary:
            self._report(f"  Secondary keyword: \"{secondary}\"")
        fb_cta = cta_package.get("fb_cta_line", "")
        if fb_cta:
            self._report(f"  FB CTA: {fb_cta[:120]}")
        li_cta = cta_package.get("li_cta_line", "")
        if li_cta:
            self._report(f"  LI CTA: {li_cta[:120]}")
        dm_flow = cta_package.get("dm_flow", {})
        if dm_flow:
            self._report(f"  DM trigger: \"{dm_flow.get('trigger', 'N/A')}\"")
            self._report(f"  DM ack: {str(dm_flow.get('ack_message', 'N/A'))[:100]}")
        checklist = cta_package.get("fulfillment_checklist", [])
        if checklist:
            self._report(f"  Fulfillment checklist ({len(checklist)} items):")
            for item in checklist[:5]:
                self._report(f"    - {str(item)[:80]}")
        return {"cta_package": cta_package}
