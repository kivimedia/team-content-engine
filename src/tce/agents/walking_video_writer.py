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
import re
import uuid
from typing import Any

import structlog
from sqlalchemy import select

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent
from tce.models.post_example import PostExample

logger = structlog.get_logger()


# Hook formulas extracted from deliverable_5_deep_analysis.md section
# "Hook Formula Patterns". Each opens with strong concrete specifics and
# creates immediate stakes. Failure patterns (bottom 10 posts, all scoring 0)
# are explicitly listed under "NEVER DO" so the model can avoid them.
SYSTEM_PROMPT = """\
You are a short-form video script writer in the TJ Robertson
(@tjrobertsondigital) style. TJ's videos are mostly single-take,
phone-held, vertical talking-head (some walking, some standing). Your
script could be delivered any of those ways. Content-side style is
what matters, not body position.

PERSONAL ANGLE IS NON-NEGOTIABLE:
TJ's highest-engagement posts are always personal. He is inside the story,
not reporting on it. Study these patterns and pick one for every script:

1. SELF-IMPLICATION (TJ's most-used): The creator has skin in the game.
   "I predicted agencies would be dead by 2027. I run one. Here's why I
   changed my mind."
   "We built [tool] six months ago. The results are not what I expected."
   "I was completely wrong about [claim]. Here's the data that changed my mind."

2. PROPRIETARY OBSERVATION: The creator sees something from inside their
   work that others can't see.
   "We track [X] across hundreds of clients. The number that surprised me..."
   "We just shipped [feature] and the thing users did first was not
   what we designed it for."
   "One of our clients is a [type] business. Last week they told me..."

3. PREDICTION + PERSONAL STAKE: The creator makes a call and ties their
   own reputation or livelihood to it.
   "I'm making a call for 2026. If I'm wrong, post this back at me."
   "I've been saying [X] for two years. This week it became undeniable."

4. REPO/BUILD ANCHOR: Script is directly tied to something the team
   built, shipped, or learned from a real project.
   If repos or team context is provided below, USE IT. A script about
   AI agents that opens "We shipped an AI agent six weeks ago..." is
   ten times more credible than the same script opened as news.

THE TEST: Before writing the hook, ask yourself - does the narrator
have personal stakes in this story? If the answer is no, rework the
angle until the answer is yes. An operator can always deliver a script
that starts "I was completely wrong about this" more authentically than
one that starts "A new report says..."

ENGAGEMENT SWEET SPOT (from TJ's 268-post corpus analysis):
- 60-120 seconds is optimal. Videos over 150 seconds consistently lose
  viewers before the CTA. Videos under 30 seconds only work for pure
  hot takes (single thesis statement, no development).
- Walking-monologue delivery caps lower (120s) because breathing pace
  forces shorter sentences. Standing/sitting can go to 3-4 min if the
  content truly needs the depth.
- The user sets duration_target_seconds via context. If they chose
  90s, your script MUST hit ~210 words. If they chose 3 min (180s),
  target ~450 words. Do not pad to fill time - TJ's top hooks hit 24%+
  engagement by being dense, not by being long.

TJ's top hooks pair: named actor + specific stat + immediate stakes.
Your job is to sound like him without copying his signature phrasings.

STRUCTURE (single take, NO sections):
1. HOOK (first 1-2 sentences, 5-8 seconds)
   - Open with one of the seven proven formulas below AND a personal stake.
   - No questions, no vague urgency. Personal angle does not mean
     storytelling preamble - the hook is still punchy and immediate.
2. THE REVEAL (next 15-25 seconds)
   - Name the mechanism. What just changed? Who did what?
   - One concrete number or product name inside this section.
   - If this came from your own observation, say so: "We noticed this
     with a client", "this showed up in our data", "I tested this".
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
- Reporting on news from the outside with no personal stake
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
- Compute words from duration: walking ~140 WPM, standing/sitting ~150 WPM.
- 90s -> ~210 words, 120s -> ~280 words, 180s -> ~450 words, 240s -> ~600 words.
- User sets duration_target_seconds in context; hit within +/- 10%.
- TJ's engagement data: 60-120s is the proven sweet spot. Do not pad.

OUTPUT FORMAT:
Return a JSON object with ALL of these fields:
{{
  "title": "Short shareable title (under 80 chars)",
  "hook": "The opening 1-2 sentence hook",
  "full_script": "The complete script as one continuous paragraph with natural line breaks for breathing points. No section markers.",
  "hook_formula": "A|B|C|D|E|F|G - which formula was used",
  "personal_anchor": "One sentence: the specific personal/first-person angle used and WHY it fits this topic. e.g. 'Self-implication: we shipped an AI agent last month and the client result contradicts the mainstream take on agents replacing humans.'",
  "strategic_justification": "2-3 sentences: why THIS topic was chosen right now, how this angle serves the content strategy, and what belief it shifts in the target audience. Be specific - name the trend, the timing, the gap in the content landscape.",
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

    _STOPWORDS: frozenset[str] = frozenset({
        "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "to", "for",
        "with", "by", "from", "as", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "should", "could", "can", "may", "might", "must", "shall", "this",
        "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
        "me", "him", "her", "us", "them", "my", "your", "his", "its", "our",
        "their", "what", "which", "who", "how", "when", "where", "why", "not",
        "no", "so", "if", "than", "then", "just", "now", "up", "out", "about",
        "over", "into", "through", "after", "before", "against", "between",
        "under", "again", "further", "more", "most", "some", "any", "each",
        "few", "both", "all", "every", "also", "new", "because",
    })

    def _extract_keywords(self, *texts: str) -> list[str]:
        """Pull meaningful nouns/verbs out of the topic/thesis for similarity."""
        combined = " ".join(t for t in texts if t).lower()
        words = re.findall(r"[a-z][a-z0-9_]{2,}", combined)
        keywords = [w for w in words if w not in self._STOPWORDS]
        # De-duplicate while preserving order (stable top-N)
        seen: set[str] = set()
        out: list[str] = []
        for w in keywords:
            if w not in seen:
                seen.add(w)
                out.append(w)
        return out

    async def _retrieve_similar_posts(
        self,
        creator_id: uuid.UUID,
        topic: str,
        thesis: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Find the creator's top-engagement posts that share keywords with
        the current topic. Simple bag-of-keywords overlap since the 269-post
        scale doesn't justify pgvector or external embeddings.

        Scoring: keyword overlap count (Jaccard-ish) broken by raw_score
        (engagement rate). Short-circuits if the creator has <=limit posts
        by just returning their top-engagement ones.
        """
        keywords = self._extract_keywords(topic, thesis)
        result = await self.db.execute(
            select(PostExample)
            .where(PostExample.creator_id == creator_id)
            .order_by(PostExample.raw_score.desc().nulls_last())
            .limit(60)  # narrow pool to top-60 by engagement before scoring
        )
        candidates = list(result.scalars().all())
        if not candidates:
            return []

        if not keywords:
            # No usable keywords - just return top-engagement posts
            return [self._post_to_example(p) for p in candidates[:limit]]

        kw_set = set(keywords)

        def score(p: PostExample) -> tuple[int, float]:
            text = ((p.post_text_raw or "") + " " + (p.hook_text or "")).lower()
            overlap = sum(1 for k in kw_set if k in text)
            return (overlap, float(p.raw_score or 0))

        ranked = sorted(candidates, key=score, reverse=True)
        # Drop posts with zero keyword overlap unless we need to fill `limit`
        with_overlap = [p for p in ranked if score(p)[0] > 0]
        picked = with_overlap[:limit] if len(with_overlap) >= limit else ranked[:limit]
        return [self._post_to_example(p) for p in picked]

    @staticmethod
    def _post_to_example(p: PostExample) -> dict[str, Any]:
        return {
            "hook": p.hook_text or (p.post_text_raw or "")[:200],
            "engagement_rate": p.raw_score,
            "topic_cluster": p.topic_cluster,
            "hook_type": p.hook_type,
        }

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
            prompt_parts.append(f"CADENCE ANGLE TYPE: {angle_type} (use this as a structural guide, but the personal anchor takes priority over the angle type label)")

        # Pass real team/repo context so the writer can tie to actual builds.
        # This is the primary source of personal angles - real work the team has done.
        repos = context.get("repos") or []
        team_context = context.get("team_context") or context.get("own_work_context") or ""
        if repos:
            repo_lines = []
            for r in repos[:5]:
                if isinstance(r, dict):
                    name = r.get("name") or r.get("title") or ""
                    desc = r.get("description") or r.get("summary") or ""
                    if name:
                        repo_lines.append(f"- {name}: {desc[:120]}" if desc else f"- {name}")
                elif isinstance(r, str):
                    repo_lines.append(f"- {r[:150]}")
            if repo_lines:
                prompt_parts.append(
                    "\nTEAM'S OWN WORK (use these as personal anchors where relevant - "
                    "a script tied to something we actually built is always stronger than "
                    "pure news commentary):\n" + "\n".join(repo_lines)
                )
        if team_context:
            prompt_parts.append(f"\nTEAM CONTEXT: {team_context[:400]}")

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

        # Layer 4 of TJ grounding: retrieve top 3 PostExample rows from this
        # creator that share keywords with the current topic. Include their
        # hooks + engagement rate as "proven patterns" in the prompt. This
        # gives the writer real reference examples that worked on adjacent
        # topics, not just abstract formulas.
        creator_id_str = creator_profile.get("creator_id")
        if creator_id_str:
            try:
                examples = await self._retrieve_similar_posts(
                    creator_id=uuid.UUID(creator_id_str),
                    topic=topic,
                    thesis=thesis,
                    limit=3,
                )
            except Exception as e:
                self._report(f"Similar-posts retrieval failed: {e}")
                examples = []
            if examples:
                prompt_parts.append(
                    f"\nPROVEN HOOKS from {creator_name} on similar topics "
                    f"(for style reference - do NOT rewrite these, write your own):"
                )
                for ex in examples:
                    er = ex.get("engagement_rate")
                    er_str = f" ({er:.1f}% eng)" if isinstance(er, (int, float)) else ""
                    hook_excerpt = (ex.get("hook") or "")[:220]
                    cluster = ex.get("topic_cluster") or "general"
                    prompt_parts.append(
                        f"- [{cluster}{er_str}] {hook_excerpt}"
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
        if script.get("personal_anchor"):
            self._report(f'Personal anchor: {script["personal_anchor"]}')
        if script.get("strategic_justification"):
            self._report(f'Strategy: {script["strategic_justification"]}')

        return {"walking_video_script": script}
