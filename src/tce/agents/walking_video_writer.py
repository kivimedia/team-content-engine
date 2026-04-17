"""Walking Video Writer - produces short (60-120s) walking-monologue scripts.

Style ground truth: TJ Robertson (@tjrobertsondigital), 268 posts analyzed by
InstaIQ. Writer is trained on TJ's hook formulas and failure patterns from
corpus/tj_robertson/deliverable_5_deep_analysis.md.

Key difference from video_lead_writer:
  - Single continuous take (no sections / chapter markers)
  - 150-300 words (walking pace is slower than teleprompter pace)
  - Stance-driven, not teaching-driven (opinion first, why second)
  - Phone-held vertical (shot_notes.aspect_ratio = "9:16")
  - Emits a CutSense prompt so the operator can cut their recorded footage
    in one click after capture.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

logger = structlog.get_logger()


# Hook formulas extracted from deliverable_5_deep_analysis.md section
# "Hook Formula Patterns". Each opens with strong concrete specifics and
# creates immediate stakes. Failure patterns (bottom 10 posts, all scoring 0)
# are explicitly listed under "NEVER DO" so the model can avoid them.
SYSTEM_PROMPT = """\
You are a walking-video script writer. You produce short (60-120 second),
phone-held, vertical-format monologue scripts that read like a founder
thinking out loud while walking to a meeting.

Model: TJ Robertson (@tjrobertsondigital). His top hooks hit 24-40%
engagement by pairing a named actor + specific stat + immediate stakes.
Your job is to sound like him without copying him.

STRUCTURE (single take, NO sections):
1. HOOK (first 1-2 sentences, 5-8 seconds)
   - Open with one of the seven proven formulas below.
   - No questions, no personal metaphors, no vague urgency.
2. THE REVEAL (next 15-25 seconds)
   - Name the mechanism. What just changed? Who did what?
   - One concrete number or product name inside this section.
3. THE IMPLICATION (25-45 seconds)
   - What this means for the viewer's business, right now.
   - Stance: take a position. Do not hedge the core claim.
4. CLOSE (last 5-10 seconds)
   - A short call to attention, not a sales pitch.
   - "If you want to know how to prepare, I'll be posting more on this."
   - Or a single specific next step.

HOOK FORMULAS (use one, match the topic):
A. Crisis signal + named actor + specific outcome
   "Code red at [company]. [Executive] reportedly [dramatic action] after [competitor] [achievement]."
B. Massive number + misconception correction
   "The [industry] just [gained/lost] [$X] in [timeframe] and most people are getting the reason completely wrong."
C. Counterintuitive ownership claim
   "You should absolutely [do the thing that sounds wrong]."
D. Hidden process reveal
   "[AI/Google/platform] is [secretly doing something] to your [owned asset] before [consequence]."
E. Paradigm reframe
   "Your [familiar thing] isn't just for [old purpose] anymore. [New actor] is [doing the thing you thought only humans did]."
F. Authority confirmation + paradigm shift
   "[Company]'s [executive title] just confirmed that [familiar concept] is turning into [unfamiliar concept]."
G. Patent/filing reveal
   "[Company] just filed a [patent/doc] that reveals they intend on [disrupting your owned asset]."

NEVER DO (failure patterns that scored 0 views in 268-post analysis):
- Personal metaphors unrelated to the topic ("my kids' school / Disney line")
- Vague urgency without specifics ("changing too fast", "you're already losing")
- Question hooks without stakes ("Are people searching for what you sell?")
- Broad predictions with no named catalyst ("here's what I think 2027 looks like")
- Foundational beginner content framed as insider intelligence

VOICE RULES:
- Short sentences. 8-14 words average. You are walking and breathing.
- First person throughout ("I", "we").
- Contractions, rhetorical pauses, natural speech rhythm.
- Concrete nouns over adjectives. Specific numbers over "huge".
- Never "exciting", "revolutionary", "game-changing" (filler).
- One stat or named product inside the first three sentences.

TARGET LENGTH:
- 150-300 words (at walking pace of ~140 WPM, this is 60-130 seconds).
- User sets duration_target_seconds in context; hit within +/- 10%.

OUTPUT FORMAT:
Return a JSON object with:
{{
  "title": "Short shareable title (under 80 chars)",
  "hook": "The opening 1-2 sentence hook",
  "full_script": "The complete script as one continuous paragraph with natural line breaks for breathing points. No section markers.",
  "hook_formula": "A|B|C|D|E|F|G - which formula was used",
  "word_count": 200,
  "estimated_duration_seconds": 85,
  "shot_notes": {{
    "location_cue": "outdoor sidewalk / quiet street / before a meeting",
    "camera_angle": "phone held at face level, slight upward tilt",
    "aspect_ratio": "9:16",
    "energy_level": "calm-urgent | conversational | intense",
    "b_roll_suggestion": "optional cutaway that could be layered in post"
  }},
  "cutsense_prompt": "Natural-language instruction for CutSense to edit the recorded footage. e.g. 'Cut this walking video down to 90 seconds, preserve the hook and the main claim, remove filler words and dead air, add jumbo captions, crop to 9:16 vertical.'",
  "seo_description": "YouTube/Reels description, 2-3 sentences",
  "tags": ["relevant", "search", "tags"],
  "repurpose": {{
    "fb_caption_draft": "Draft Facebook caption reusing the hook and key claim",
    "li_caption_draft": "Draft LinkedIn caption reusing the hook but reshaped for LI's longer-form pacing"
  }}
}}
"""


@register_agent
class WalkingVideoWriter(AgentBase):
    """Produces a walking-monologue video script (60-120s) from story + research briefs."""

    name = "walking_video_writer"
    default_model = "claude-sonnet-4-20250514"

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        story_brief = context.get("story_brief") or {}
        research_brief = context.get("research_brief") or {}
        creator_profile = context.get("creator_profile") or {}

        if not story_brief:
            self._report("No story_brief in context - cannot generate walking video script")
            return {"walking_video_script": None}

        duration_target_s = int(context.get("duration_target_seconds") or 90)
        duration_target_s = max(45, min(180, duration_target_s))

        topic = story_brief.get("topic", "Unknown topic")
        thesis = story_brief.get("thesis", "")
        audience = story_brief.get("audience", "small business owners")
        angle_type = story_brief.get("angle_type", "")

        prompt_parts = [
            f"Write a {duration_target_s}-second walking-monologue video script about the topic below.",
            f"\nTOPIC: {topic}",
            f"THESIS: {thesis}",
            f"TARGET AUDIENCE: {audience}",
        ]
        if angle_type:
            prompt_parts.append(f"ANGLE: {angle_type}")

        claims = research_brief.get("verified_claims") or []
        findings = research_brief.get("key_findings") or []
        if claims:
            prompt_parts.append("\nVERIFIED CLAIMS (pick ONE specific number to cite - do not include all):")
            for c in claims[:5]:
                if isinstance(c, dict):
                    prompt_parts.append(f"- {c.get('claim', c.get('text', str(c)))}")
                else:
                    prompt_parts.append(f"- {c}")
        if findings:
            prompt_parts.append("\nKEY FINDINGS:")
            for f in findings[:5]:
                if isinstance(f, dict):
                    prompt_parts.append(f"- {f.get('finding', f.get('text', str(f)))}")
                else:
                    prompt_parts.append(f"- {f}")

        creator_name = creator_profile.get("creator_name")
        if creator_name:
            prompt_parts.append(
                f"\nSTYLE ANCHOR: emulate the pacing + hook style of {creator_name} "
                f"but do NOT copy their specific phrasings or signature lines."
            )

        duration_word_target = int(duration_target_s * 140 / 60)
        prompt_parts.append(
            f"\nTARGET WORD COUNT: approximately {duration_word_target} words "
            f"(+/- 10%) to hit {duration_target_s} seconds at walking pace."
        )

        self._report(f"Generating {duration_target_s}s walking-video script: {topic}")

        response = await self._call_llm(
            messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
            system=SYSTEM_PROMPT,
            max_tokens=2048,
            temperature=0.7,
        )

        text = self._extract_text(response)
        try:
            script = self._parse_json_response(text)
        except json.JSONDecodeError:
            self._report("Failed to parse JSON - returning raw text as full_script")
            word_count = len(text.split())
            script = {
                "title": topic[:80],
                "hook": "",
                "full_script": text,
                "hook_formula": None,
                "word_count": word_count,
                "estimated_duration_seconds": int(word_count * 60 / 140),
                "shot_notes": {"aspect_ratio": "9:16", "camera_angle": "phone at face level"},
                "cutsense_prompt": (
                    f"Cut this walking video to {duration_target_s} seconds. "
                    "Preserve the hook and main claim. Remove filler words and dead air. "
                    "Add jumbo captions. Crop to 9:16 vertical."
                ),
            }

        # Normalize shot_notes so downstream code can trust the shape.
        shot_notes = script.get("shot_notes") or {}
        if not isinstance(shot_notes, dict):
            shot_notes = {}
        shot_notes.setdefault("aspect_ratio", "9:16")
        shot_notes.setdefault("camera_angle", "phone at face level, slight upward tilt")
        shot_notes.setdefault("energy_level", "calm-urgent")
        script["shot_notes"] = shot_notes

        # Ensure cutsense_prompt exists
        if not script.get("cutsense_prompt"):
            script["cutsense_prompt"] = (
                f"Cut this walking video to {duration_target_s} seconds. "
                "Preserve the hook and the main claim. Remove filler words and dead air. "
                "Add jumbo captions. Crop to 9:16 vertical."
            )

        word_count = script.get("word_count") or len((script.get("full_script") or "").split())
        duration = script.get("estimated_duration_seconds") or int(word_count * 60 / 140)
        title = script.get("title", "Untitled")
        self._report(f'Script: "{title}" | {word_count} words | ~{duration}s')

        return {"walking_video_script": script}
