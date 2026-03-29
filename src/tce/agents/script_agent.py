"""Script Agent - generates voiceover narration scripts from PostPackage context.

Uses LLM to write natural spoken narration adapted to a template style,
with segment-level visual type annotations for Remotion rendering.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent
from tce.services.audio_alignment import WPS_ESTIMATE, estimate_duration

logger = structlog.get_logger()

# Template style selection rules (same logic as VideoAgent)
STYLE_RULES = [
    ("mixed", lambda c: bool(
        c.get("story_brief", {}).get("thesis")
        and _has_stats(c)
        and _has_before_after(c)
    )),
    ("step_framework", lambda c: bool(_has_steps(c))),
    ("before_after", lambda c: bool(_has_before_after(c))),
    ("stat_heavy", lambda c: bool(_has_stats(c))),
    ("hook_cta", lambda c: bool(c.get("story_brief", {}).get("thesis"))),
]


def _has_stats(context: dict[str, Any]) -> bool:
    research = context.get("research_brief") or {}
    claims = research.get("verified_claims") or []
    return len(claims) > 0


def _has_before_after(context: dict[str, Any]) -> bool:
    story = context.get("story_brief") or {}
    shift = story.get("desired_belief_shift", "")
    return " -> " in shift


def _has_steps(context: dict[str, Any]) -> bool:
    guide_sections = context.get("guide_sections") or []
    for section in guide_sections:
        if isinstance(section, dict):
            steps = section.get("steps") or section.get("framework_steps")
            if steps and isinstance(steps, list) and len(steps) >= 2:
                return True
    research = context.get("research_brief") or {}
    findings = research.get("key_findings") or []
    return isinstance(findings, list) and len(findings) >= 3


def _select_style(context: dict[str, Any]) -> str:
    """Determine best template style based on available data."""
    for style, check in STYLE_RULES:
        if check(context):
            return style
    return "hook_cta"


SCRIPT_SYSTEM_PROMPT = """You are a narration script writer for short-form video.
You write conversational, spoken narration that sounds natural when read aloud.

Rules:
- Write how a person SPEAKS, not how they write posts
- Each segment is 5-15 seconds of narration
- Total script: 30-90 seconds
- Use contractions, rhetorical questions, natural pauses
- Each segment must specify a visualType for the Remotion component
- Available visualTypes: animated_text, number_counter, crossed_text, reveal_text, step_card, brand_footer, image_overlay, typing_text

Return ONLY a JSON array of segments:
[
  {
    "narratorText": "What you say out loud",
    "visualType": "animated_text",
    "visualProps": { "text": "Text on screen", "fontSize": 44 }
  }
]

visualProps reference:
- animated_text: { text, fontSize?, fontWeight?, wordByWord? }
- number_counter: { value (number), suffix (string like "%" or "x") }
- crossed_text: { text, fontSize? }
- reveal_text: { text, fontSize? }
- step_card: { num (number), text, isLast? }
- brand_footer: { ctaText }
- image_overlay: { src (file path), caption? }
- typing_text: { text, fontSize? }
"""


@register_agent
class ScriptAgent(AgentBase):
    """Generates voiceover narration scripts from pipeline context."""

    name: str = "script_agent"
    default_model: str = "claude-haiku-4-5-20251001"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        # Override model from settings if configured
        self.default_model = getattr(self.settings, "script_model", self.default_model)

        style = _select_style(context)
        self._report(f"Selected template style: {style}")

        # Build the LLM prompt with available data
        story_brief = context.get("story_brief") or {}
        research = context.get("research_brief") or {}
        cta = context.get("cta_keyword") or context.get("weekly_keyword") or "zivraviv.com"
        creator = context.get("creator_name", "Ziv Raviv")

        user_prompt = f"""Generate a narration script for a {style} video.

Available content:
- Thesis: {story_brief.get('thesis', 'N/A')}
- Topic: {story_brief.get('topic', 'N/A')}
- Desired belief shift: {story_brief.get('desired_belief_shift', 'N/A')}
- Verified claims: {json.dumps(research.get('verified_claims', [])[:3])}
- Key findings: {json.dumps(research.get('key_findings', [])[:3])}
- CTA keyword: {cta}
- Creator name: {creator}

Template style: {style}
- hook_cta: INTRO -> THESIS -> CTA (short, punchy)
- stat_heavy: INTRO -> STAT -> STAT2 -> CTA (data-driven)
- before_after: INTRO -> BEFORE -> AFTER -> CTA (transformation)
- step_framework: INTRO -> STEP1 -> STEP2 -> STEP3 -> CTA (how-to)
- mixed: INTRO -> STAT -> BEFORE -> AFTER -> CTA (comprehensive)

Write the narration script as a JSON array of segments. Each segment should be conversational spoken language."""

        response = await self._call_llm(
            messages=[{"role": "user", "content": user_prompt}],
            system=SCRIPT_SYSTEM_PROMPT,
            max_tokens=2048,
            temperature=0.7,
        )

        text = self._extract_text(response)

        # Parse segments from LLM response
        try:
            # Handle both raw array and wrapped object
            parsed = json.loads(text.strip().strip("`").strip())
            if isinstance(parsed, dict):
                segments = parsed.get("segments", [])
            elif isinstance(parsed, list):
                segments = parsed
            else:
                segments = []
        except json.JSONDecodeError:
            # Try extracting JSON from markdown fences
            import re
            match = re.search(r"\[[\s\S]*?\](?=\s*$)", text, re.DOTALL)
            if match:
                segments = json.loads(match.group(0))
            else:
                self._report("Failed to parse script segments from LLM response")
                segments = []

        # Calculate duration estimates
        total_words = 0
        for seg in segments:
            narrator_text = seg.get("narratorText", "")
            word_count = len(narrator_text.split())
            total_words += word_count
            seg["estimatedDurationSec"] = round(estimate_duration(narrator_text), 1)

        estimated_total = round(total_words / WPS_ESTIMATE, 1)
        self._report(
            f"Generated {len(segments)} segments, "
            f"~{total_words} words, ~{estimated_total}s estimated"
        )

        return {
            "narration_script": {
                "template_style": style,
                "segments": segments,
                "word_count": total_words,
                "estimated_duration_sec": estimated_total,
                "status": "ready_to_record",
            }
        }
