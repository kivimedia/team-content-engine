"""Platform Writers — Facebook (engagement engine) and LinkedIn (authority engine)."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

FB_SYSTEM_PROMPT = """\
You are the Facebook Writer for Team Content Engine. Your job is to write a \
scroll-stopping, comment-triggering post that makes people engage.

FACEBOOK-SPECIFIC RULES:
- The first 2 lines must survive the "See more" cut - they ARE the hook
- Short paragraphs: 1-3 sentences max per block
- Use whitespace aggressively - a blank line between every block
- Tone: emotional, conversational, punchy. Permission to be provocative
- NEVER use emdashes or en dashes. Use a single hyphen (-) instead. No exceptions
- Build toward the CTA
- No hashtags. No emoji unless the voice naturally uses them
- No AI-slop preamble ("In today's fast-paced world...")
- Length: 600-1200 words. LONGER IS ALWAYS BETTER. Develop every idea fully with examples, \
micro-stories, and specific details. A 400-word post is a skeleton - flesh it out. \
Each proof block should be 2-3 paragraphs minimum, not a single sentence

OUTPUT FORMAT (JSON):
- facebook_post: the complete post text
- hook_variants: 5 alternative opening lines, each <= 2 sentences
- word_count: integer
- rationale: brief explanation of platform-specific choices made
"""

LI_SYSTEM_PROMPT = """\
You are the LinkedIn Writer for Team Content Engine. Your job is to write an \
authority-building post that makes people save, follow, and think differently.

LINKEDIN-SPECIFIC RULES:
- Clear thesis in the first 3 lines
- Longer, more developed argument - can include frameworks, numbered insights
- Stronger evidence packaging - more data, more "here's what most people miss"
- NEVER use emdashes or en dashes. Use a single hyphen (-) instead. No exceptions
- Professional close with a takeaway, not a hard CTA
- May include a soft CTA (follow for more, share if useful)
- NEVER a "say XXX" comment-trigger
- Length: 800-2000 words. Go DEEP. Develop complete frameworks with full explanations, \
give numbered insights with examples for each, tell full stories with specific details. \
A 500-word LinkedIn post is a tweet thread - write a real article. \
Each section/insight should be a full paragraph with evidence, not a bullet point
- Executive, precise, deeper tone

OUTPUT FORMAT (JSON):
- linkedin_post: the complete post text
- hook_variants: 5 alternative opening lines
- word_count: integer
- rationale: brief explanation of platform-specific choices made
"""

SHARED_PROMPT_SUFFIX = """\

EVIDENCE RULES:
- Every hard claim must come from the Research Brief's verified_claims
- Uncertain claims must use signal words: "suggests," "points to," "early data shows"
- Rejected claims must NOT be used
- If the research brief has no verified claims or safe_to_publish is false, \
write the post using only soft/opinion claims with appropriate signal words. \
Use the story brief thesis as your foundation. Do NOT refuse to write - \
frame everything as perspective and opinion instead.

ANTI-CLONE CHECK:
- Do not use the same opening structure as recent posts
- Do not contain phrases signature to a source creator
- Do not follow the template so rigidly it reads like fill-in-the-blank
"""


@register_agent
class FacebookWriter(AgentBase):
    name = "facebook_writer"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        story_brief = context.get("story_brief", {})
        research_brief = context.get("research_brief", {})
        founder_voice = context.get("founder_voice", {})
        weekly_keyword = context.get("weekly_keyword", "guide")
        thesis = story_brief.get("thesis", "N/A")[:60]
        self._report(f"Writing FB post - thesis: {thesis}")

        prompt_parts = [
            f"STORY BRIEF:\n{json.dumps(story_brief, indent=2)}",
            f"RESEARCH BRIEF:\n{json.dumps(research_brief, indent=2)}",
            f"Weekly CTA keyword: \"{weekly_keyword}\"",
            f"CTA line must end with: Comment \"{weekly_keyword}\" and I'll send it to you.",
        ]

        if founder_voice:
            prompt_parts.insert(0, f"FOUNDER VOICE LAYER:\n{json.dumps(founder_voice, indent=2)}")

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=FB_SYSTEM_PROMPT + SHARED_PROMPT_SUFFIX,
            max_tokens=6144,
            temperature=0.7,
        )

        text = self._extract_text(response)
        try:
            result = self._parse_json_response(text)
        except json.JSONDecodeError:
            result = {"facebook_post": text, "hook_variants": [], "rationale": "raw output"}

        wc = result.get("word_count", len(result.get("facebook_post", "").split()))
        hooks = result.get("hook_variants", [])
        self._report(f"FB post drafted ({wc} words, {len(hooks)} hook variants)")
        post_text = result.get("facebook_post", "")
        if post_text:
            first_lines = post_text.strip().split("\n")[:3]
            self._report(f"  Opening: {' '.join(first_lines)[:150]}...")
        for i, h in enumerate(hooks[:3], 1):
            self._report(f"  Hook {i}: {str(h)[:120]}")
        if len(hooks) > 3:
            self._report(f"  ... and {len(hooks) - 3} more hooks")
        rationale = result.get("rationale", "")
        if rationale:
            self._report(f"  Rationale: {str(rationale)[:150]}")
        return {"facebook_draft": result}


@register_agent
class LinkedInWriter(AgentBase):
    name = "linkedin_writer"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        story_brief = context.get("story_brief", {})
        research_brief = context.get("research_brief", {})
        founder_voice = context.get("founder_voice", {})
        thesis = story_brief.get("thesis", "N/A")[:60]
        self._report(f"Writing LI post - thesis: {thesis}")

        prompt_parts = [
            f"STORY BRIEF:\n{json.dumps(story_brief, indent=2)}",
            f"RESEARCH BRIEF:\n{json.dumps(research_brief, indent=2)}",
        ]

        if founder_voice:
            prompt_parts.insert(0, f"FOUNDER VOICE LAYER:\n{json.dumps(founder_voice, indent=2)}")

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=LI_SYSTEM_PROMPT + SHARED_PROMPT_SUFFIX,
            max_tokens=8192,
            temperature=0.7,
        )

        text = self._extract_text(response)
        try:
            result = self._parse_json_response(text)
        except json.JSONDecodeError:
            result = {"linkedin_post": text, "hook_variants": [], "rationale": "raw output"}

        wc = result.get("word_count", len(result.get("linkedin_post", "").split()))
        hooks = result.get("hook_variants", [])
        self._report(f"LI post drafted ({wc} words, {len(hooks)} hook variants)")
        post_text = result.get("linkedin_post", "")
        if post_text:
            first_lines = post_text.strip().split("\n")[:3]
            self._report(f"  Opening: {' '.join(first_lines)[:150]}...")
        for i, h in enumerate(hooks[:3], 1):
            self._report(f"  Hook {i}: {str(h)[:120]}")
        rationale = result.get("rationale", "")
        if rationale:
            self._report(f"  Rationale: {str(rationale)[:150]}")
        return {"linkedin_draft": result}
