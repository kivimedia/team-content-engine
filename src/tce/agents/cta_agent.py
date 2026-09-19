"""CTA / Funnel Agent.

The workspace's effective strategy decides the call to action (tce.services.cta_policy).
For the default coaching strategy that is a strategy-session invitation with no keyword,
DM flow or giveaway. The "say XXX" keyword model below (PRD Section 9.7) only runs for a
workspace whose own strategy calls for it, or an explicit operator keyword with a real guide.
"""

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

NO-ASSET PLAYBOOK (PRD Section 18.3):
If the weekly guide is NOT ready yet, use one of these fallback CTAs:
1. WhatsApp group invite: "Comment 'join' to get added to our private AI group"
2. "I'm building this" teaser: "Comment 'beta' to get early access when it drops"
3. Waitlist: "Comment 'waitlist' for the full breakdown I'm writing this week"
4. Manual conversation: "DM me 'question' and I'll send a voice note"
5. Post-specific reply: "Comment your biggest challenge with [topic] and I'll reply"
Only fall back to these if guide_title is empty or guide is explicitly not ready.

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
    default_model = "claude-sonnet-5"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate CTA keyword and DM flow."""
        story_brief = context.get("story_brief", {})
        weekly_theme = context.get("weekly_theme", "") or story_brief.get("topic", "")
        weekly_keyword = context.get("weekly_keyword")  # May be pre-set
        guide_title = str(context.get("guide_title", "") or "")

        # The workspace's effective strategy decides the CTA. Ziv's default strategy (and
        # overrides that extend it) has one CTA: a strategy session. The keyword/DM flow
        # below only runs when that strategy allows it; nothing is invented.
        from tce.services.cta_policy import (
            FB_STRATEGY_SESSION_LINE,
            LI_STRATEGY_SESSION_LINE,
            STRATEGY_SESSION,
            resolve_cta_policy,
        )

        policy = await resolve_cta_policy(self.db, context)
        for note in policy.notes:
            self._report(f"CTA policy: {note}")

        repo_brief = context.get("repo_brief") or {}
        repo_url = repo_brief.get("repo_url") or context.get("repo_url")
        is_repo_run = context.get("_source") == "repo"

        if not policy.allow_comment_keyword:
            base = {
                "weekly_keyword": None,
                "secondary_keyword": None,
                "dm_flow": None,
                "whatsapp_group_link": None,
                "fulfillment_checklist": [],
                "policy": policy.to_dict(),
            }
            if policy.mode == STRATEGY_SESSION:
                # Repo runs too: the repository is evidence for the lesson, never the CTA,
                # and its (possibly private) link is not published.
                cta_package = base | {
                    "fb_cta_line": FB_STRATEGY_SESSION_LINE,
                    "li_cta_line": LI_STRATEGY_SESSION_LINE,
                    "cta_type": "strategy_session",
                }
            elif is_repo_run and repo_url and policy.allow_public_repo_link:
                cta_package = base | {
                    "fb_cta_line": f"Code's open: {repo_url}",
                    "li_cta_line": f"Repo (open source): {repo_url}",
                    "cta_type": "repo_link",
                    "repo_url": repo_url,
                }
            else:
                cta_package = base | {
                    "fb_cta_line": "",
                    "li_cta_line": "",
                    "cta_type": "workspace_defined",
                    "cta_instruction": "use the call to action in this workspace's strategy",
                }
            self._report(f"CTA package ready: {cta_package['cta_type']} (no keyword/DM flow)")
            if cta_package["fb_cta_line"]:
                self._report(f"  FB CTA: {cta_package['fb_cta_line'][:120]}")
            if cta_package["li_cta_line"]:
                self._report(f"  LI CTA: {cta_package['li_cta_line'][:120]}")
            return {"cta_package": cta_package}

        weekly_keyword = policy.keyword or weekly_keyword

        prompt_parts = []

        # PRD Section 18.3: Detect no-asset situation
        guide_ready = bool(guide_title and guide_title.strip())
        if not guide_ready:
            prompt_parts.append(
                "IMPORTANT: The weekly guide is NOT ready yet. "
                "Use the NO-ASSET PLAYBOOK - pick one of the 5 fallback CTA types."
            )

        if policy.strategy_excerpt:
            prompt_parts.append(
                "WORKSPACE STRATEGY (follow its CTA rules):\n" + policy.strategy_excerpt
            )

        if weekly_keyword:
            prompt_parts.append(
                f'The weekly primary keyword is already set: "{weekly_keyword}"\n'
                f"Generate the DM flow and CTA lines for today's post."
            )
        else:
            prompt_parts.append("Choose a weekly primary keyword based on the theme and guide.")

        prompt_parts.extend(
            [
                f"Weekly theme: {weekly_theme}",
                f"Guide title: {guide_title}",
                f"Story brief: {json.dumps(story_brief, indent=2)}",
                "Generate the CTA package.",
            ]
        )

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
        if isinstance(cta_package, dict):
            cta_package["policy"] = policy.to_dict()

        self._report("CTA package ready:")
        self._report(f'  Weekly keyword: "{cta_package.get("weekly_keyword", "N/A")}"')
        secondary = cta_package.get("secondary_keyword")
        if secondary:
            self._report(f'  Secondary keyword: "{secondary}"')
        fb_cta = cta_package.get("fb_cta_line", "")
        if fb_cta:
            self._report(f"  FB CTA: {fb_cta[:120]}")
        li_cta = cta_package.get("li_cta_line", "")
        if li_cta:
            self._report(f"  LI CTA: {li_cta[:120]}")
        dm_flow = cta_package.get("dm_flow", {})
        if dm_flow:
            self._report(f'  DM trigger: "{dm_flow.get("trigger", "N/A")}"')
            self._report(f"  DM ack: {str(dm_flow.get('ack_message', 'N/A'))[:100]}")
        checklist = cta_package.get("fulfillment_checklist", [])
        if checklist:
            self._report(f"  Fulfillment checklist ({len(checklist)} items):")
            for item in checklist[:5]:
                self._report(f"    - {str(item)[:80]}")
        return {"cta_package": cta_package}
