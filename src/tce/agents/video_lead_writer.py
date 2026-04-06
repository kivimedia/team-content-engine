"""Video Lead Writer - produces long-form talking-head video scripts (5-7 min).

Inspired by TJ Robertson's content machine model: one video recorded to camera,
then repurposed across all platforms. The script follows a proven 9-section
structure optimized for authority-building and lead generation.

Output is a teleprompter-ready script, NOT segment-based Remotion data.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

logger = structlog.get_logger()

SYSTEM_PROMPT = """\
You are a video script writer for long-form talking-head content (5-7 minutes).

YOUR JOB: Write a teleprompter-ready script that a coach/founder will record \
directly to camera. The script should educate, build authority, and end with \
a soft call to action. The viewer should walk away having learned something \
concrete they can apply.

SCRIPT STRUCTURE (follow this EXACT order):

1. HOOK (2-3 sentences, 15-20 seconds)
   - Open with a direct answer to the title question OR a provocative claim
   - Immediately add a contrarian twist ("but here's what most people get wrong")
   - Drop one stat or credential to establish stakes
   - Goal: stop the scroll, challenge an assumption

2. AUTHORITY BRIDGE (1 paragraph, 15-20 seconds)
   - Reference the creator's track record (clients served, years of experience)
   - Bridge to "which is why I'm sharing this today"
   - Establish why YOU are the right person to teach this

3. DEFINE THE CONCEPT (30-60 seconds)
   - Clear, jargon-free definition of the topic
   - One concrete example or analogy
   - Make sure a non-technical viewer can follow

4. WHY THE OLD WAY FAILS (30-60 seconds)
   - Name the specific failure pattern most people are stuck in
   - Include a data point or real example reinforcing the failure
   - Create tension: "if you keep doing X, here's what happens"

5. THE FRAMEWORK / STEPS (2-4 minutes - this is the meat)
   - 3 to 7 numbered steps, each with a clear name
   - Each step: 2-3 sentences explaining what to do and why
   - Be specific and actionable, not vague
   - This section should deliver so much value the viewer feels they got a free consultation

6. WHERE HUMANS STILL WIN (30-45 seconds)
   - Acknowledge what AI/automation/the new approach can't replace
   - Positions the creator as realistic, not hype-driven
   - Builds trust by showing nuance

7. WHAT THIS MEANS FOR YOUR BUSINESS (30-60 seconds)
   - "If you're a [target audience], here's what you should do right now..."
   - Urgency framing: "the [audience] that move in the next 12-18 months..."
   - Make it personal and direct

8. FAQ (60-90 seconds)
   - 3-5 questions the viewer is probably thinking
   - Short, direct answers - each a complete thought
   - Address the most common objection in here

9. CTA (15-20 seconds)
   - Soft close: offer a free strategy session or conversation
   - "No commitment. Just a clear picture of where you stand."
   - Include the calendar link or next step

VOICE RULES:
- First person throughout ("I've seen this with my clients", "we built")
- Short sentences: 10-15 words average
- Conversational urgency: "here's where it gets interesting", "most people have no idea"
- Anti-dogmatic: say "no one knows exactly" when appropriate to signal honesty
- Data-forward: cite a specific stat or number within the first 3 paragraphs
- Never hedge the core claim - open with directness, hedge the nuance inside
- Sound like a knowledgeable friend on a video call, not a keynote speaker
- Use contractions, rhetorical questions, natural pauses

{voice_profile_section}

TARGET LENGTH: 800-1200 words (5-7 minutes at natural speaking pace of ~150 WPM)

OUTPUT FORMAT:
Return a JSON object with:
{{
  "title": "The video title (following one of the 5 title patterns)",
  "title_pattern": "which pattern was used: how_to | contrarian_question | news_peg | concept_explainer | best_of",
  "hook": "The opening 2-3 sentences",
  "full_script": "The complete teleprompter-ready script with section markers",
  "sections": [
    {{
      "name": "hook",
      "text": "section text",
      "estimated_seconds": 15
    }},
    ...
  ],
  "word_count": 950,
  "estimated_duration_minutes": 6.3,
  "target_audience": "who this video is for",
  "key_takeaway": "the one thing the viewer should remember",
  "seo_description": "YouTube/blog description (2-3 sentences)",
  "tags": ["relevant", "search", "tags"],
  "blog_repurpose_outline": "Brief outline for turning this into a blog post"
}}
"""

TITLE_PATTERNS = {
    "how_to": 'How to [Specific Action] for [Audience] in [Year]',
    "contrarian_question": '[Will/Should/Is] [Provocative Question]? The Truth About [Topic]',
    "news_peg": '[Recent Event]: What It Means for [Audience]',
    "concept_explainer": 'What Is [Concept]? [Subtitle] Explained ([Year])',
    "best_of": 'Best [Thing] for [Audience] in [Year]: The [N]-Step [Framework]',
}


@register_agent
class VideoLeadWriter(AgentBase):
    name = "video_lead_writer"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Produce a long-form video script from story brief + research."""

        story_brief = context.get("story_brief", {})
        research_brief = context.get("research_brief", {})
        voice_profile = context.get("voice_profile", {})
        creator_profile = context.get("creator_profile", {})

        if not story_brief:
            self._report("No story_brief in context - cannot generate video lead script")
            return {"video_lead_script": None}

        # Build voice profile section for system prompt
        voice_section = ""
        if voice_profile:
            axes = voice_profile.get("voice_axes", {})
            phrases = voice_profile.get("signature_phrases", [])
            metaphors = voice_profile.get("metaphor_style", "")
            parts = ["CREATOR VOICE PROFILE:"]
            if axes:
                parts.append(f"Voice axes: {json.dumps(axes)}")
            if phrases:
                parts.append(f"Signature phrases: {', '.join(phrases[:10])}")
            if metaphors:
                parts.append(f"Metaphor style: {metaphors}")
            vocab = voice_profile.get("vocabulary_preferences", {})
            if vocab.get("never_use"):
                parts.append(f"NEVER use these words: {', '.join(vocab['never_use'])}")
            voice_section = "\n".join(parts)

        system = SYSTEM_PROMPT.format(voice_profile_section=voice_section)

        # Build the user prompt
        topic = story_brief.get("topic", "Unknown topic")
        thesis = story_brief.get("thesis", "")
        audience = story_brief.get("audience", "coaches and service providers")
        angle_type = story_brief.get("angle_type", "how_we_built_it")

        prompt_parts = [
            f"Write a 5-7 minute video lead script about the following topic.",
            f"\nTOPIC: {topic}",
            f"THESIS: {thesis}",
            f"TARGET AUDIENCE: {audience}",
            f"ANGLE: {angle_type}",
        ]

        # Add research findings if available
        if research_brief:
            claims = research_brief.get("verified_claims", [])
            findings = research_brief.get("key_findings", [])
            if claims:
                prompt_parts.append(f"\nVERIFIED CLAIMS (use these as data points):")
                for c in claims[:5]:
                    if isinstance(c, dict):
                        prompt_parts.append(f"- {c.get('claim', c.get('text', str(c)))}")
                    else:
                        prompt_parts.append(f"- {c}")
            if findings:
                prompt_parts.append(f"\nKEY FINDINGS:")
                for f in findings[:5]:
                    if isinstance(f, dict):
                        prompt_parts.append(f"- {f.get('finding', f.get('text', str(f)))}")
                    else:
                        prompt_parts.append(f"- {f}")

        # Add title pattern guidance
        prompt_parts.append(f"\nTITLE PATTERNS (choose the best fit):")
        for pattern_name, pattern_formula in TITLE_PATTERNS.items():
            prompt_parts.append(f"- {pattern_name}: {pattern_formula}")

        # Add creator context if available
        creator_name = creator_profile.get("creator_name", "")
        if creator_name:
            prompt_parts.append(f"\nCREATOR: {creator_name}")

        # Load niche strategy doc for positioning context
        niche = context.get("niche", "general")
        if niche == "coaching":
            import os
            strategy_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                "docs", "super-coaching-strategy.md",
            )
            try:
                with open(strategy_path, "r", encoding="utf-8") as f:
                    strategy_text = f.read()
                # Use key sections only to keep prompt size manageable
                if len(strategy_text) > 3000:
                    strategy_text = strategy_text[:3000]
                prompt_parts.append(
                    f"\nCREATOR STRATEGY CONTEXT:\n{strategy_text}\n\n"
                    "Use this context to inform the script's authority claims, "
                    "real stories, and positioning. The CTA should always point "
                    "to a strategy session."
                )
                self._report("Loaded Super Coaching strategy for script context")
            except FileNotFoundError:
                pass

        # Add CTA context
        cta_url = context.get("cta_url", "")
        if cta_url:
            prompt_parts.append(f"\nCTA CALENDAR LINK: {cta_url}")

        self._report(f"Generating video lead script for: {topic}")

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
            system=system,
            max_tokens=4096,
            temperature=0.7,
        )

        text = self._extract_text(response)
        try:
            script = self._parse_json_response(text)
        except json.JSONDecodeError:
            self._report("Failed to parse JSON - returning raw text as script")
            script = {
                "title": topic,
                "full_script": text,
                "word_count": len(text.split()),
                "sections": [],
                "estimated_duration_minutes": len(text.split()) / 150,
            }

        word_count = script.get("word_count", 0)
        duration = script.get("estimated_duration_minutes", 0)
        title = script.get("title", "Untitled")

        self._report(f"Script generated: \"{title}\"")
        self._report(f"Word count: {word_count} | Duration: {duration:.1f} min")

        sections = script.get("sections", [])
        if sections:
            self._report("Sections:")
            for s in sections:
                name = s.get("name", "?")
                secs = s.get("estimated_seconds", 0)
                self._report(f"  - {name}: ~{secs}s")

        return {
            "video_lead_script": script,
        }
