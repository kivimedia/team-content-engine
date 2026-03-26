"""DOCX Guide Builder - creates a reader-facing lead magnet (not an internal brief).

The guide is what a reader receives after commenting a keyword. It must:
- Teach something valuable
- Make the author look like a strategic authority
- Leave the reader wanting more
- Contain ZERO internal/campaign content
"""

from __future__ import annotations

import json
import tempfile
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent
from tce.utils.docx import create_guide_docx

SYSTEM_PROMPT = """\
You are the Guide Builder for Team Content Engine. You create a polished, \
reader-facing PDF/DOCX lead magnet that readers receive after commenting a keyword.

CRITICAL RULE: This guide is for the READER, not the operator. It must contain \
ZERO internal content. The following must NEVER appear in the guide:
- Social media post summaries or schedules
- Visual direction / creative briefs
- CTA keywords, DM flows, or fulfillment checklists
- Engagement metrics or success definitions
- Postmortem or review templates
- The word "operator" or references to content scheduling

THE GUIDE MUST INCLUDE:
1. An opening narrative that hooks with a real story, builds tension, and \
   establishes the problem. Weave in the audience's frustration naturally - \
   don't label it "Audience and Current Frustration."
2. A comparison table showing the before/after belief shift visually. \
   The reader should see which side they're currently on.
3. A framework section with 3-5 numbered steps/layers. Each step must include \
   an explanation, bullet points, and end with a concrete ACTION the reader can take.
4. A scenario section with 3-5 "What to do when..." situations. Each gives a \
   specific situation the reader might face and a concrete response/recommendation.
5. A closing section with a bold headline summarizing the core message, \
   3-4 numbered recap steps, and a soft CTA.

DESIGN RULES:
- Write as if the reader is a smart professional who values their time
- Every claim must be grounded in evidence from the research brief
- Use specific numbers, names, and examples - never generic filler
- The framework must be something the reader can actually implement
- Scenarios must feel like real situations the reader has faced or will face
- No AI-slop preambles ("In today's fast-paced world...")
- Length: 2000-4000 words of actual content (not counting structure)

OUTPUT FORMAT (JSON):
{
  "guide_title": "Compelling title (max 12 words)",
  "subtitle": "One sentence describing what the reader will learn and a credibility signal",
  "sections": [
    {
      "type": "narrative",
      "title": "Section title",
      "content": "Multiple paragraphs separated by double newlines. Use - for bullet lists."
    },
    {
      "type": "callout",
      "label": "KEY INSIGHT",
      "content": "Important callout text",
      "callout_style": "amber"
    },
    {
      "type": "comparison",
      "title": "Section title",
      "bad_label": "Label for the wrong approach",
      "bad_items": ["Item 1", "Item 2", "Item 3", "Item 4"],
      "good_label": "Label for the right approach",
      "good_items": ["Item 1", "Item 2", "Item 3", "Item 4"]
    },
    {
      "type": "framework",
      "title": "Framework title",
      "intro": "Brief intro paragraph",
      "steps": [
        {
          "label": "Step name",
          "explanation": "What this step means and why it matters",
          "bullets": ["Specific point 1", "Specific point 2"],
          "action": "Concrete thing the reader should do right now"
        }
      ]
    },
    {
      "type": "scenarios",
      "title": "What To Do When...",
      "intro": "Brief intro",
      "scenarios": [
        {
          "situation": "A specific situation the reader might face",
          "response": "Concrete recommendation with reasoning"
        }
      ]
    },
    {
      "type": "closing",
      "headline": "Bold statement summarizing the core message (1-2 sentences)",
      "recap_steps": ["Step 1 recap", "Step 2 recap", "Step 3 recap"],
      "cta": "Soft CTA - invitation to connect or learn more"
    }
  ],
  "cta_keyword": "the weekly keyword"
}

SECTION ORDER: You must include sections in this order:
1. narrative (opening story/hook)
2. callout (key insight from the opening)
3. comparison (before/after belief shift)
4. framework (the main value - numbered steps with actions)
5. scenarios (practical "what to do when" situations)
6. closing (bottom line + recap)

You may add additional narrative or callout sections between framework steps \
for flow, but the core structure must follow this order.
"""


@register_agent
class DocxGuideBuilder(AgentBase):
    name = "docx_guide_builder"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate reader-facing guide content and DOCX file."""
        story_brief = context.get("story_brief", {})
        trend_brief = context.get("trend_brief", {})
        research_brief = context.get("research_brief", {})
        cta_package = context.get("cta_package", {})

        weekly_theme = (
            context.get("weekly_theme")
            or story_brief.get("topic")
            or trend_brief.get("summary", "")
        )
        weekly_keyword = (
            context.get("weekly_keyword")
            or cta_package.get("weekly_keyword", "guide")
        )
        story_briefs = context.get("story_briefs", [])
        if not story_briefs and story_brief:
            story_briefs = [story_brief]

        # Get author info from house voice config or defaults
        house_voice = context.get("house_voice_config", {})
        author_name = house_voice.get("author_name", "Ziv Raviv")
        author_url = house_voice.get("author_url", "zivraviv.com")

        self._report(f"Building reader-facing guide for: {weekly_theme}")
        self._report(f"CTA keyword: {weekly_keyword}")
        self._report(f"Research claims: {len(research_brief.get('verified_claims', []))}")

        prompt_parts = [
            f"Weekly theme: {weekly_theme}",
            f"Weekly CTA keyword: {weekly_keyword}",
            f"Author name: {author_name}",
        ]

        # Thesis and audience from story brief
        if story_brief.get("thesis"):
            prompt_parts.append(f"Core thesis: {story_brief['thesis']}")
        if story_brief.get("audience"):
            prompt_parts.append(f"Target audience: {story_brief['audience']}")
        if story_brief.get("desired_belief_shift"):
            prompt_parts.append(f"Desired belief shift: {story_brief['desired_belief_shift']}")

        # Trend landscape
        if trend_brief.get("trends"):
            trends_summary = [
                f"- {t.get('headline', t.get('topic', ''))}"
                for t in trend_brief["trends"][:6]
            ]
            prompt_parts.append("Current trends:\n" + "\n".join(trends_summary))

        # Research evidence - the factual foundation
        if research_brief.get("verified_claims"):
            prompt_parts.append(
                "VERIFIED EVIDENCE (use these facts in the guide):\n"
                f"{json.dumps(research_brief['verified_claims'], indent=2)}"
            )
        if research_brief.get("source_refs"):
            prompt_parts.append(
                f"Sources: {json.dumps(research_brief['source_refs'][:10], indent=2)}"
            )

        # Story angles for context only
        if story_briefs:
            angles = [s.get("topic", "") for s in story_briefs if s.get("topic")]
            if angles:
                prompt_parts.append(
                    f"Related angles (for context only, do NOT list as posts): {', '.join(angles)}"
                )

        prompt_parts.append(
            "\nCreate the complete reader-facing guide. Remember: this is a GIFT "
            "for the reader, not an internal brief. Zero campaign/ops content."
        )

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
            temperature=0.5,
        )

        text = self._extract_text(response)
        try:
            guide_content = self._parse_json_response(text)
        except Exception:
            self._report("JSON parse failed, attempting LLM repair...")
            try:
                repair = await self._call_llm(
                    messages=[
                        {"role": "user", "content": "\n\n".join(prompt_parts)},
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": (
                            "Your response was not valid JSON. Please output ONLY a valid "
                            "JSON object matching the OUTPUT FORMAT spec. No markdown."
                        )},
                    ],
                    system=SYSTEM_PROMPT,
                    max_tokens=8192,
                    temperature=0.3,
                )
                guide_content = self._parse_json_response(self._extract_text(repair))
                self._report("Repair succeeded")
            except Exception:
                guide_content = {
                    "guide_title": weekly_theme,
                    "subtitle": "",
                    "sections": [{"type": "narrative", "title": "Content", "content": text}],
                }
                self._report("Using raw text fallback")

        # Inject author info for DOCX generation
        guide_content["author_name"] = author_name
        guide_content["author_url"] = author_url

        # Reporting
        self._report("Guide ready:")
        self._report(f"  Title: {guide_content.get('guide_title', 'N/A')}")
        self._report(f"  Subtitle: {str(guide_content.get('subtitle', ''))[:100]}")
        sections = guide_content.get("sections", [])
        self._report(f"  Sections ({len(sections)}):")
        for s in sections:
            sec_type = s.get("type", "narrative")
            title = s.get("title", s.get("label", sec_type))
            if sec_type == "framework":
                self._report(f"    [{sec_type}] {title} ({len(s.get('steps', []))} steps)")
            elif sec_type == "scenarios":
                self._report(f"    [{sec_type}] {title} ({len(s.get('scenarios', []))} scenarios)")
            elif sec_type == "closing":
                self._report(f"    [{sec_type}] {s.get('headline', '')[:80]}")
            else:
                self._report(f"    [{sec_type}] {title} ({len(s.get('content', ''))} chars)")

        # Generate DOCX
        docx_path = None
        title = guide_content.get("guide_title", "Weekly Guide")
        if sections:
            output_dir = tempfile.mkdtemp(prefix="tce_guide_")
            docx_path = f"{output_dir}/{title}.docx"
            try:
                create_guide_docx(guide_content, docx_path)
                self._report(f"DOCX generated: {docx_path}")
            except Exception as e:
                self._report(f"DOCX generation failed: {str(e)[:100]}")
                docx_path = None

        return {
            "guide_content": guide_content,
            "_guide_docx_path": docx_path,
        }
