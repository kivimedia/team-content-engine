"""DOCX Guide Builder — creates one polished weekly guide (PRD Section 9.9)."""

from __future__ import annotations

import json
import tempfile
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent
from tce.utils.docx import create_guide_docx

SYSTEM_PROMPT = """\
You are the DOCX Guide Builder for Team Content Engine. You create one polished \
weekly guide that serves as the shared lead magnet across all 5 posts.

EVERY WEEKLY GUIDE MUST INCLUDE (PRD Section 20.3):
1. Cover page with weekly theme title
2. Objective: what the reader will be able to do or understand
3. Audience and current frustration
4. Desired belief shift for the week
5. Master thesis tying the week's 5 posts together
6. Evidence bank (key facts, sources, caveats)
7. Deeper analysis or framework beyond any single post
8. Summary of the week's 5 posts (angle, platform, hook)
9. Visual direction summary
10. CTA keyword and DM flow for the week
11. Definition of success
12. Postmortem section (to fill after week ends)

DESIGN RULES:
- Unique cover treatment and title per week
- Clean hierarchy
- Actionable — the reader should be able to DO something
- Must stand alone (someone who missed posts should still get value)
- Must feel like a gift worth commenting a keyword for

OUTPUT FORMAT (JSON):
- guide_title: compelling title
- weekly_theme: the overarching theme
- sections: array of {title, content} objects for each section
- cta_keyword: the weekly keyword
- fulfillment_checklist: what operator needs to set up
"""


@register_agent
class DocxGuideBuilder(AgentBase):
    name = "docx_guide_builder"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate the content for a weekly DOCX guide."""
        # Extract theme from story_brief or trend_brief
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
        # Build story briefs list from single brief if needed
        story_briefs = context.get("story_briefs", [])
        if not story_briefs and story_brief:
            story_briefs = [story_brief]

        self._report(f"Building guide for theme: {weekly_theme}")
        self._report(f"CTA keyword: {weekly_keyword}")
        self._report(f"Story briefs available: {len(story_briefs)}")
        self._report(f"Research brief topics: {len(research_brief.get('verified_claims', []))} verified claims")

        prompt_parts = [
            f"Weekly theme: {weekly_theme}",
            f"Weekly CTA keyword: {weekly_keyword}",
        ]

        # Add trend landscape
        if trend_brief.get("trends"):
            trends_summary = [
                f"- {t.get('headline', t.get('topic', ''))}: {t.get('angle_suggestions', [''])[0] if t.get('angle_suggestions') else ''}"
                for t in trend_brief["trends"][:6]
            ]
            prompt_parts.append(f"Current trend landscape:\n" + "\n".join(trends_summary))

        prompt_parts.append(f"Research evidence bank:\n{json.dumps(research_brief, indent=2)}")

        if story_briefs:
            prompt_parts.append(
                f"Story angles for the week:\n{json.dumps(story_briefs, indent=2)}"
            )

        prompt_parts.append("Create the complete weekly guide content.")

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
            temperature=0.5,
        )

        text = self._extract_text(response)
        try:
            guide_content = self._parse_json_response(text)
        except json.JSONDecodeError:
            guide_content = {
                "guide_title": weekly_theme,
                "sections": [{"title": "Content", "content": text}],
            }

        # Verbose reporting
        self._report(f"Guide content ready:")
        self._report(f"  Title: {guide_content.get('guide_title', 'N/A')}")
        self._report(f"  Theme: {guide_content.get('weekly_theme', 'N/A')}")
        self._report(f"  CTA keyword: {guide_content.get('cta_keyword', 'N/A')}")
        sections = guide_content.get("sections", [])
        self._report(f"  Sections ({len(sections)}):")
        for s in sections:
            title = s.get("title", "untitled")
            content_len = len(s.get("content", ""))
            self._report(f"    - {title} ({content_len} chars)")
        checklist = guide_content.get("fulfillment_checklist", [])
        if checklist:
            self._report(f"  Fulfillment checklist:")
            for item in checklist[:5]:
                self._report(f"    - {str(item)[:80]}")

        # Generate actual DOCX file
        docx_path = None
        sections = guide_content.get("sections", [])
        title = guide_content.get("guide_title", "Weekly Guide")
        if sections:
            output_dir = tempfile.mkdtemp(prefix="tce_guide_")
            docx_path = f"{output_dir}/{title}.docx"
            try:
                create_guide_docx(title, sections, docx_path)
            except Exception:
                docx_path = None  # DOCX generation failed; content still returned

        return {
            "guide_content": guide_content,
            "_guide_docx_path": docx_path,
        }
