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
1. An opening narrative that hooks with a REAL statistic, study, or event from \
   the research brief. NO invented characters or fictional stories. If the \
   research brief contains a verified claim with a number, lead with it. \
   Weave in the audience's frustration naturally - don't label it.
2. A callout box with the key insight from the opening.
3. A Quick Win section - a single concrete exercise the reader can complete in \
   under 15 minutes that produces a VISIBLE result (a filled worksheet, a score, \
   a decision). This appears BEFORE the framework so the reader has already DONE \
   something before they even get to the main content.
4. A comparison table showing the before/after belief shift visually.
5. A framework section with 3-5 numbered steps. Each step must be completable \
   in ONE SITTING (not "evaluate your entire org"). Each step MUST include a \
   specific deliverable: "After this step you'll have: [a list / a score / a \
   decision / a document]". At least one step must include a fill-in template, \
   checklist, or scoring rubric. Ban vague actions like "identify", "consider", \
   "evaluate" unless paired with a specific method or tool.
6. A scenario section with 3-5 "What to do when..." situations with concrete \
   responses.
7. A closing section with a bold headline, a "you_now_have" list of 3-4 concrete \
   things the reader produced by following the guide, and a soft CTA.

EVIDENCE RULES (CRITICAL - low accuracy = instant fail):
- EVERY factual claim MUST include the source name in parentheses. Example: \
  "Resolution rates jumped to 73% (Intercom Fin Apex benchmarks, VentureBeat \
  March 2026)" - NOT "resolution rates jumped to 73%."
- The opening MUST use a real stat, study, or event from the research brief's \
  verified_claims array. Copy the claim text and source directly. Do not \
  paraphrase into something that loses the source attribution.
- NO invented stories, companies, or characters. If "Buffer" isn't in the \
  verified_claims, do NOT write about Buffer. ONLY use companies/orgs that \
  appear in the research brief.
- Include at least 5 specific numbers/stats from the research brief, each \
  with named source in parentheses.
- BANNED phrases that trigger accuracy failure: "Studies show", "Research \
  indicates", "Experts say", "According to research", "Data suggests" - these \
  are all ways of claiming evidence without naming it. Name the study or don't \
  make the claim.
- When the research brief gives you a claim with source and caveats, include \
  the caveats too. Nuance builds trust.

ANTI-SLOP RULES - these phrases are BANNED:
- "In today's..." / "In an era of..." / "In the rapidly evolving..."
- "It's no secret..." / "The landscape is shifting..."
- "Here's the thing:" / "Let's dive in" / "Let's break it down"
- "Game-changer" / "Unlock" / "Leverage" / "Navigate" / "Harness"
- "Embrace" / "Empower" / "Revolutionize" / "Cutting-edge"
- Rhetorical questions as transitions ("But what does this mean for you?")
- Any sentence that could appear in any guide on any topic - be specific.

GENEROSITY TEST:
Before finalizing, ask yourself: if someone paid $49 for this guide, would they \
feel they got their money's worth? If not, add more substance. The reader gave \
you their email - that's currency. Respect it.

DESIGN RULES:
- Write as if the reader is a smart professional who values their time
- Use specific numbers, names, and examples - never generic filler
- Scenarios must feel like real situations the reader has faced or will face
- Length: 2000-4000 words of actual content (not counting structure)

OUTPUT FORMAT (JSON):
{
  "guide_title": "Compelling title (max 12 words)",
  "subtitle": "One sentence describing what the reader will learn and a credibility signal",
  "sections": [
    {
      "type": "narrative",
      "title": "Section title",
      "content": "Multiple paragraphs separated by double newlines. Opening MUST use a real stat or event from the research brief. No fictional characters."
    },
    {
      "type": "callout",
      "label": "KEY INSIGHT",
      "content": "Important callout text",
      "callout_style": "amber"
    },
    {
      "type": "quick_win",
      "title": "Your 15-Minute Quick Win",
      "instruction": "MUST be a fill-in exercise with a TABLE the reader completes. Not 'think about X' - the reader physically fills in rows. Example: 'List your top 5 [items], score each 1-5 on [criteria], calculate total. If total < 15, you need [action].' The table_headers define the worksheet columns. The instruction tells them how to fill it and what the result means.",
      "table_headers": ["Column 1 Header", "Column 2 Header", "Column 3 Header"],
      "table_rows": 5,
      "what_you_learn": "One sentence: 'If your score is above X, you [result]. Below X means [other result].' Must be a binary or scored outcome, NOT 'you will gain clarity.'"
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
          "action": "Concrete thing the reader does in ONE SITTING - not 'evaluate your org'. At least 2 of your steps MUST include a fill-in template like: 'Fill in: [My current X] uses [Y approach]. The gap is [Z]. My next move is [action].'",
          "deliverable": "After this step you'll have: [specific tangible output - a list, a score, a completed template, a decision]"
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
      "you_now_have": ["Concrete thing 1 the reader produced", "Concrete thing 2", "Concrete thing 3"],
      "cta": "Soft CTA - invitation to connect or learn more"
    }
  ],
  "cta_keyword": "the weekly keyword"
}

QUALITY GATE: This guide is automatically scored on 6 dimensions after generation. \
You must earn a composite score of 8.0/10 or above. The dimensions and what earns 8+:

- practical (8+): At least 2 framework steps include a fill-in template, checklist, \
or rubric. Quick Win produces something the reader physically fills in or scores.
- valuable (8+): At least 3 insights the reader cannot find with a Google search. \
Every number/stat is contextualized - not just cited, but explained why it matters.
- generous (8+): Complete framework. Reader can implement without outside help. \
No teasing, no "contact us for the full method."
- accurate (8+): ZERO unsourced claims. "Studies show" without naming the study = 0 \
points. Every claim traces to a named source.
- quick_win (8+): 15-minute exercise with a concrete output: a score, a completed \
worksheet, a binary decision. NOT "you'll gain clarity."
- transformation (8+): The comparison table must show a genuine paradigm shift. \
Not "bad habits vs good habits" - show a belief the reader holds that is WRONG.

Low scores on any dimension will trigger a full rewrite. Write to pass on the \
first attempt.

SECTION ORDER: You must include sections in this order:
1. narrative (opening - real stat/event, no fake stories)
2. callout (key insight from the opening)
3. quick_win (15-minute exercise with visible output)
4. comparison (before/after belief shift)
5. framework (steps with completable actions + deliverables)
6. scenarios (practical "what to do when" situations)
7. closing (bottom line + "what you now have" + soft CTA)

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
        weekly_keyword = context.get("weekly_keyword") or cta_package.get("weekly_keyword", "guide")
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
                f"- {t.get('headline', t.get('topic', ''))}" for t in trend_brief["trends"][:6]
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

        # Quality gate feedback from previous iteration (if re-running)
        quality_feedback = context.get("_quality_feedback")
        if quality_feedback:
            self._report("Incorporating quality gate feedback for reiteration...")
            prompt_parts.append(quality_feedback)

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
                        {
                            "role": "user",
                            "content": (
                                "Your response was not valid JSON. Please output ONLY a valid "
                                "JSON object matching the OUTPUT FORMAT spec. No markdown."
                            ),
                        },
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
            elif sec_type == "quick_win":
                self._report(f"    [{sec_type}] {title} ({len(s.get('table_headers', []))} cols)")
            elif sec_type == "closing":
                self._report(f"    [{sec_type}] {s.get('headline', '')[:80]}")
                you_now_have = s.get("you_now_have", [])
                if you_now_have:
                    self._report(f"      you_now_have: {len(you_now_have)} items")
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
