"""Creative Director — generates 3 fal.ai image prompts per post (PRD Section 9.8)."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

SYSTEM_PROMPT = """\
You are the Creative Director for Team Content Engine. You generate 3 visual directions \
per post for image generation.

REQUIRED OUTPUTS (3 per post):
1. Hero scroll-stopper: cinematic, attention-grabbing
2. Proof / diagram / system visual: informational, credible
3. Alternate emotional visual: mood-based, human connection

EACH PROMPT MUST INCLUDE:
- prompt_name: descriptive name
- visual_job: what the image needs to accomplish
- visual_intent: the emotional/conceptual goal
- prompt_text: detailed image generation prompt (50-150 words)
- negative_prompt: what to exclude
- aspect_ratio: platform-appropriate (16:9 for FB link, 1:1 for square, 4:5 for portrait)
- mood: emotional register
- color_logic: color palette and reasoning
- platform_fit: which social platform this is optimized for
- rationale: why this visual matches the post
- best_platform: which AI image platform is best for THIS specific prompt (see guide below)
- best_platform_reason: 1-2 sentence explanation of why this platform fits best

PLATFORM SELECTION GUIDE (pick the best match for each prompt):
- "fal_ai": Best for photorealistic scenes, cinematic lighting, editorial photography, \
  dramatic compositions, real-world settings. Default choice for most prompts.
- "midjourney": Best for artistic/stylized visuals, illustration-like aesthetics, abstract \
  concepts, brand mood boards, painterly or surreal compositions, logo-adjacent designs.
- "gemini": Best for images containing readable text (overlays, quotes, headlines), \
  infographics, diagrams with labels, screenshots with UI text, data visualizations.
- "dall_e": Good general-purpose alternative, handles unusual compositions, conceptual \
  mashups, and creative metaphors well.

Be honest about platform fit. If the prompt involves text overlays or readable words, \
recommend gemini. If it's artistic/abstract, recommend midjourney. Only recommend fal_ai \
when photorealism is genuinely the best approach.

GUARDRAILS:
- No copyrighted mimicry of source screenshots
- No fake UI screenshots presented as real evidence
- No deceptive charts unless labeled as conceptual
- No visuals that imply false news events
- No stock photo energy

OUTPUT: JSON array of 3 prompt objects.
"""


@register_agent
class CreativeDirector(AgentBase):
    name = "creative_director"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate 3 image prompts for a post."""
        story_brief = context.get("story_brief", {})
        facebook_draft = context.get("facebook_draft", {})
        linkedin_draft = context.get("linkedin_draft", {})

        prompt_parts = [
            f"STORY BRIEF:\n{json.dumps(story_brief, indent=2)}",
            f"FACEBOOK POST:\n{facebook_draft.get('facebook_post', 'N/A')[:500]}",
            f"LINKEDIN POST:\n{linkedin_draft.get('linkedin_post', 'N/A')[:500]}",
            "Generate 3 image prompts that match these posts.",
        ]

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.7,
        )

        text = self._extract_text(response)
        try:
            prompts = self._parse_json_response(text)
            if not isinstance(prompts, list):
                prompts = [prompts]
        except json.JSONDecodeError:
            prompts = []

        self._report(f"Generated {len(prompts)} image prompts:")
        for i, p in enumerate(prompts, 1):
            name = p.get("prompt_name", p.get("visual_job", f"Prompt {i}"))
            aspect = p.get("aspect_ratio", "N/A")
            mood = p.get("mood", "N/A")
            platform = p.get("platform_fit", "both")
            best = p.get("best_platform", "fal_ai")
            self._report(f"  {i}. {name} ({aspect}, {mood}, {platform})")
            self._report(f"     Best platform: {best}")
            reason = p.get("best_platform_reason", "")
            if reason:
                self._report(f"     Reason: {str(reason)[:120]}")
            prompt_text = p.get("prompt_text", p.get("detailed_prompt", ""))
            if prompt_text:
                self._report(f"     Prompt: {str(prompt_text)[:150]}...")
            negative = p.get("negative_prompt", "")
            if negative:
                self._report(f"     Negative: {str(negative)[:80]}")
        return {"image_prompts": prompts}
