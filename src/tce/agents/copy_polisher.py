"""Copy Polisher — polishes user copy into FB/LI draft format matching template formulas."""

from __future__ import annotations

from typing import Any

from tce.agents.base import AgentBase
from tce.agents.platform_writer import _clean_writer_output
from tce.agents.registry import register_agent
from tce.services.strategy_loader import load_strategy as _load_strategy

_STRATEGY = _load_strategy()

SYSTEM_PROMPT = f"""\
You are the Copy Polisher for Team Content Engine. Your job is to take raw copy
the user wrote and polish it into platform-ready drafts for BOTH Facebook and LinkedIn.

VOICE AND AUDIENCE CONTEXT:
{_STRATEGY[:2500] if _STRATEGY else "(strategy doc not available)"}

ZIV'S VOICE RULES (non-negotiable — apply every time):
- Peer language: "another great coach I worked with" not "a client" or "a prospect"
- Underclaim for credibility: "minimal tweaking" beats "zero tweaking" — underclaiming is believable
- One idea per piece — never stack offers, secondary pitches, or alternate CTAs
- Conflict hooks outperform curiosity-gap: "her marketing company made a mess" beats "a story from last week"
- Anonymize heroes, specify villains fairly — concede villain's strengths BEFORE the critique ("his books are great - his team made a mess")
- Bulleted pain points with emotional words: "super annoying", "ignored", "felt dismissed" — never sanitize
- Three-beat emotional cadence for the turn: Feeling → interpretation → wish. Short lines, space between.
- Diagnosis over observation: "they templatized her without studying her voice" beats "they used a questionnaire"
- Process language over result language: "a process that creates voice precision" beats "voice precision"
- Show the hero being patient before they snap — makes the decision feel measured, not reactive
- One profanity maximum ("shit show" once = intimate and honest, twice = vulgar)
- Never use agency-speak: "maximize ROI", "AI-powered solutions", "leverage synergies", "seamlessly integrates"
- Meta-rule: after drafting, ask "could a peer with no stake in the outcome have written this?" If no, cut until yes.

CRITICAL RULES:
- PRESERVE the author's voice, personality, and core message - this is NOT a rewrite
- The output MUST be AT LEAST as long as the original copy, ideally longer
- Keep ALL specific details, examples, numbers, and anecdotes from the original
- Add structure (line breaks, spacing) but do NOT cut substance
- Apply the matched template's hook and body formulas to ENHANCE structure, not replace content
- Facebook: conversational, punchy hooks, short paragraphs, engagement-optimized
- LinkedIn: authority-building, slightly longer, professional but warm
- Never use emdashes or double dashes - use single dash " - " instead
- Never use generic AI filler ("In today's fast-paced world...")
- Each draft should feel like the user wrote it, just sharper and better structured
- If the original is already good, your job is to polish - not to shrink

You always respond in valid JSON only, no markdown fences.
"""

USER_PROMPT_TEMPLATE = """\
Here is the user's raw copy:
---
{raw_copy}
---

Story brief (extracted by copy analyzer):
{story_brief_json}

Copy analysis:
{copy_analysis_json}

Matched template:
- Name: {template_name}
- Hook formula: {hook_formula}
- Body formula: {body_formula}
- Match reason: {match_reason}

{keyword_section}
{platform_section}

Produce a JSON object with exactly this structure:
{{
  "facebook_draft": {{
    "facebook_post": "the full polished Facebook post text",
    "hook_variants": ["3 alternative opening hooks for Facebook"],
    "word_count": 0,
    "rationale": "brief explanation of what was changed and why"
  }},
  "linkedin_draft": {{
    "linkedin_post": "the full polished LinkedIn post text",
    "hook_variants": ["3 alternative opening hooks for LinkedIn"],
    "word_count": 0,
    "rationale": "brief explanation of what was changed and why"
  }}
}}

If the user only wants one platform, still produce both but note which is primary.
The drafts must be ready to post - complete, polished, with a strong hook and clear CTA area.

IMPORTANT: The original copy is {raw_word_count} words. Each draft MUST be at least {raw_word_count} words.
Do NOT summarize or condense - enhance and structure. Keep every detail, story, and example.
"""


@register_agent
class CopyPolisher(AgentBase):
    """Polishes user copy into platform-ready FB/LI drafts aligned to a template."""

    name = "copy_polisher"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        import json

        raw_copy = context.get("raw_copy", "")
        story_brief = context.get("story_brief", {})
        copy_analysis = context.get("copy_analysis", {})
        matched_template = context.get("matched_template", {})
        weekly_keyword = context.get("weekly_keyword", "")
        cta_keyword = context.get("cta_keyword", "")
        platform = context.get("platform", "both")

        if not raw_copy:
            self._report("No raw_copy in context - nothing to polish.")
            return {"error": "No raw_copy provided"}

        self._report(f"Polishing copy ({len(raw_copy.split())} words) using template: {matched_template.get('template_name', 'none')}...")

        keyword = cta_keyword or weekly_keyword
        keyword_section = f"CTA keyword to weave in: {keyword}" if keyword else "No specific CTA keyword provided."
        platform_section = f"Primary platform: {platform}" if platform != "both" else "Produce equal-quality drafts for both platforms."

        raw_word_count = len(raw_copy.split())
        prompt = USER_PROMPT_TEMPLATE.format(
            raw_copy=raw_copy,
            raw_word_count=raw_word_count,
            story_brief_json=json.dumps(story_brief, indent=2),
            copy_analysis_json=json.dumps(copy_analysis, indent=2),
            template_name=matched_template.get("template_name", "none"),
            hook_formula=matched_template.get("hook_formula", "N/A"),
            body_formula=matched_template.get("body_formula", "N/A"),
            match_reason=matched_template.get("match_reason", "N/A"),
            keyword_section=keyword_section,
            platform_section=platform_section,
        )

        response = await self._call_llm(
            messages=[{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT,
            max_tokens=4096,
        )

        text = self._extract_text(response)
        result = self._parse_json_response(text)
        if not result:
            self._report("Failed to parse LLM response as JSON.")
            return {"error": "Failed to parse polished copy"}

        fb_draft = result.get("facebook_draft", {})
        li_draft = result.get("linkedin_draft", {})

        # Clean emdashes from both drafts
        fb_draft = _clean_writer_output(fb_draft)
        li_draft = _clean_writer_output(li_draft)

        fb_wc = fb_draft.get("word_count", len(fb_draft.get("facebook_post", "").split()))
        li_wc = li_draft.get("word_count", len(li_draft.get("linkedin_post", "").split()))
        fb_hooks = fb_draft.get("hook_variants", [])
        li_hooks = li_draft.get("hook_variants", [])

        self._report(f"Facebook draft: {fb_wc} words, {len(fb_hooks)} hook variants")
        self._report(f"LinkedIn draft: {li_wc} words, {len(li_hooks)} hook variants")
        if fb_draft.get("rationale"):
            self._report(f"FB rationale: {fb_draft['rationale'][:120]}")
        if li_draft.get("rationale"):
            self._report(f"LI rationale: {li_draft['rationale'][:120]}")

        # Return in the exact format save_post_package expects:
        # context["facebook_draft"] and context["linkedin_draft"]
        return {
            "facebook_draft": fb_draft,
            "linkedin_draft": li_draft,
        }
