"""Platform Writers — Facebook (engagement engine) and LinkedIn (authority engine)."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent


def _clean_dash(s: str) -> str:
    """Replace all dash-like Unicode chars and double dashes with single dash."""
    for ch in "\u2014\u2013\u2015\u2012\u2015\u2053\u2E3A\u2E3B\uFE58\uFF0D":
        s = s.replace(ch, " - ")
    return s.replace("--", " - ")


def _build_template_block(context: dict) -> str:
    """Build an explicit template formula block for the writer prompt."""
    tpl = context.get("_resolved_template")
    if not tpl:
        return ""
    lines = ["ASSIGNED TEMPLATE FORMULA (follow this structure):"]
    lines.append(f"Template: {tpl.get('template_name', '?')} ({tpl.get('template_family', '?')})")
    if tpl.get("hook_formula"):
        lines.append(f"Hook formula: {tpl['hook_formula']}")
    if tpl.get("body_formula"):
        lines.append(f"Body formula: {tpl['body_formula']}")
    if tpl.get("anti_patterns"):
        lines.append(f"Anti-patterns to AVOID: {tpl['anti_patterns']}")
    return "\n".join(lines)


def _clean_writer_output(result: dict) -> dict:
    """Clean all text fields in writer output of emdashes/en dashes."""
    for key in ("facebook_post", "linkedin_post", "rationale"):
        if key in result and isinstance(result[key], str):
            result[key] = _clean_dash(result[key])
    if "hook_variants" in result and isinstance(result["hook_variants"], list):
        result["hook_variants"] = [
            _clean_dash(h) if isinstance(h, str) else h
            for h in result["hook_variants"]
        ]
    return result

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

EVIDENCE RULES (STRICT - ZERO TOLERANCE FOR FABRICATION):
- Every hard claim must come from the Research Brief's verified_claims WITH a source
- Uncertain claims must use signal words: "suggests," "points to," "early data shows"
- Rejected claims must NOT be used
- NEVER invent specific details: no fake product names, feature descriptions, code behaviors, \
company actions, statistics, quotes, or technical mechanisms that aren't in the Research Brief
- If a claim sounds like a fact (X does Y, company Z launched W), it MUST be in verified_claims. \
If it's not there, DO NOT WRITE IT - not even as opinion
- If the research brief has no verified claims or safe_to_publish is false: \
write the post as a THOUGHT PIECE using general observations and your thesis as a question, \
NOT as an exposé with specific allegations. Frame as "here's a pattern worth examining" \
not "here's what's secretly happening." Do NOT refuse to write - but keep claims general and honest.
- When in doubt, be LESS specific. "AI tools have hidden behaviors" is fine. \
"Claude removes Co-Authored-By lines" is fabrication unless verified_claims confirms it.

PLAN ADHERENCE (NON-NEGOTIABLE):
- Your topic and thesis come from STORY BRIEF - this is your assignment
- Research brief provides supporting evidence ONLY - it does NOT change your topic
- If research findings contradict the story brief, note the tension but STAY ON the assigned topic
- Your post MUST be recognizably about the story_brief topic - a reader should identify it in the first 2 sentences

ANTI-CLONE CHECK:
- Do not use the same opening structure as recent posts
- Do not contain phrases signature to a source creator
- Do not follow the template so rigidly it reads like fill-in-the-blank
"""

CREATOR_INSPIRATION_PROMPT = """\

CREATOR INSPIRATION REFERENCE:
You are writing a post INSPIRED by the style of {creator_name}. \
Study the reference post below and absorb its structural patterns, \
tone, pacing, and engagement techniques. Then write an ORIGINAL post \
on today's topic using those techniques. Do NOT copy the content - \
borrow the craft.

Reference post ({word_count} words):
---
{post_text}
---

Style notes to emulate:
- Hook type: {hook_type}
- Body structure: {body_structure}
- Story arc: {story_arc}
- CTA approach: {cta_type}
{extra_notes}

IMPORTANT: The output must be ORIGINAL content on today's story brief topic. \
Only the STYLE and STRUCTURE should be inspired by the reference. \
Maximum allowed influence: {influence_weight}% - the rest must be your own voice.
"""


def _build_inspiration_block(context: dict) -> str:
    """Build the creator inspiration prompt section if creator_inspiration is in context."""
    insp = context.get("creator_inspiration")
    if not insp:
        return ""
    extra = ""
    if insp.get("tone_tags"):
        extra += f"- Tone: {', '.join(insp['tone_tags'])}\n"
    if insp.get("topic_tags"):
        extra += f"- Topics: {', '.join(insp['topic_tags'])}\n"
    if insp.get("style_notes"):
        extra += f"- Creator style: {insp['style_notes']}\n"
    return CREATOR_INSPIRATION_PROMPT.format(
        creator_name=insp.get("creator_name", "Unknown"),
        word_count=insp.get("word_count", "?"),
        post_text=insp.get("post_text", ""),
        hook_type=insp.get("hook_type", "unknown"),
        body_structure=insp.get("body_structure", "unknown"),
        story_arc=insp.get("story_arc", "unknown"),
        cta_type=insp.get("cta_type", "unknown"),
        extra_notes=extra,
        influence_weight=insp.get("influence_weight", 20),
    )


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
            f'Weekly CTA keyword: "{weekly_keyword}"',
            f'CTA line must end with: Comment "{weekly_keyword}" and I\'ll send it to you.',
        ]

        template_block = _build_template_block(context)
        if template_block:
            prompt_parts.insert(1, template_block)

        if founder_voice:
            prompt_parts.insert(0, f"FOUNDER VOICE LAYER:\n{json.dumps(founder_voice, indent=2)}")

        inspiration_block = _build_inspiration_block(context)
        if inspiration_block:
            prompt_parts.append(inspiration_block)

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

        # Clean emdashes/en dashes from all text fields
        result = _clean_writer_output(result)

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

        template_block = _build_template_block(context)
        if template_block:
            prompt_parts.insert(1, template_block)

        if founder_voice:
            prompt_parts.insert(0, f"FOUNDER VOICE LAYER:\n{json.dumps(founder_voice, indent=2)}")

        inspiration_block = _build_inspiration_block(context)
        if inspiration_block:
            prompt_parts.append(inspiration_block)

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

        # Clean emdashes/en dashes from all text fields
        result = _clean_writer_output(result)

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
