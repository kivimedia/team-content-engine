"""DOCX Guide Builder — creates one polished weekly guide (PRD Section 9.9)."""

from __future__ import annotations

import json
from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

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
        weekly_theme = context.get("weekly_theme", "")
        research_brief = context.get("research_brief", {})
        story_briefs = context.get("story_briefs", [])
        weekly_keyword = context.get("weekly_keyword", "guide")

        prompt_parts = [
            f"Weekly theme: {weekly_theme}",
            f"Weekly CTA keyword: {weekly_keyword}",
            f"Research evidence bank:\n{json.dumps(research_brief, indent=2)}",
        ]

        if story_briefs:
            prompt_parts.append(
                f"This week's 5 daily angles:\n{json.dumps(story_briefs, indent=2)}"
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

        return {"guide_content": guide_content}
