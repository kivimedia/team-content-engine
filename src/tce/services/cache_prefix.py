"""Multi-segment prompt cache prefix builder (PRD Section 36.8).

Builds a structured system message with multiple cache_control breakpoints
so that stable context (house voice, templates, rubric, etc.) is cached
across agent calls.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.creator_profile import CreatorProfile
from tce.models.founder_voice_profile import FounderVoiceProfile
from tce.models.pattern_template import PatternTemplate

logger = structlog.get_logger()


def _cache_block(text: str) -> dict[str, Any]:
    """Create a text block with ephemeral cache control."""
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def _plain_block(text: str) -> dict[str, Any]:
    """Create a plain text block without cache control."""
    return {"type": "text", "text": text}


class CachePrefixBuilder:
    """Loads stable context from DB and builds cached system message segments."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._profiles: list[CreatorProfile] | None = None
        self._templates: list[PatternTemplate] | None = None
        self._voice: FounderVoiceProfile | None = None

    async def _load(self) -> None:
        """Load context data from DB (cached per builder instance)."""
        if self._profiles is not None:
            return

        result = await self.db.execute(select(CreatorProfile).order_by(CreatorProfile.creator_name))
        self._profiles = list(result.scalars().all())

        result = await self.db.execute(
            select(PatternTemplate)
            .where(PatternTemplate.status.in_(["active", "provisional"]))
            .order_by(PatternTemplate.template_name)
        )
        self._templates = list(result.scalars().all())

        result = await self.db.execute(
            select(FounderVoiceProfile).order_by(FounderVoiceProfile.created_at.desc()).limit(1)
        )
        self._voice = result.scalars().first()

    async def build_system_message(self, agent_system_prompt: str) -> list[dict[str, Any]]:
        """Build the full system message with up to 4 cached segments.

        Anthropic API allows max 4 cache_control blocks. We use:
        1. Agent-specific system prompt (cached)
        2. House voice + template library (cached, combined)
        3. QA rubric + CTA rules (cached, combined - static content)
        4. Founder voice profile (cached)

        Returns list of content blocks for the Anthropic system parameter.
        """
        await self._load()
        blocks: list[dict[str, Any]] = []

        # Segment 1: Agent system prompt (always present, cached)
        blocks.append(_cache_block(agent_system_prompt))

        # Segment 2: House voice config + template library (combined)
        segment2_parts: list[str] = []
        if self._profiles:
            lines = ["## House Voice Configuration\n"]
            for p in self._profiles:
                weight = p.allowed_influence_weight or 0.2
                lines.append(
                    f"- {p.creator_name} (weight: {weight:.2f}): "
                    f"{p.style_notes or 'No style notes'}"
                )
            segment2_parts.append("\n".join(lines))

        if self._templates:
            lines = ["## Active Template Library\n"]
            for t in self._templates:
                score_info = f"median={t.median_score:.1f}" if t.median_score else "unscored"
                lines.append(
                    f"- {t.template_name} ({t.template_family or 'general'}): "
                    f"{t.hook_formula or 'N/A'} [{t.status}, {score_info}]"
                )
            segment2_parts.append("\n".join(lines))

        if segment2_parts:
            blocks.append(_cache_block("\n\n".join(segment2_parts)))

        # Segment 3: QA Scoring Rubric + CTA rules (static, combined)
        rubric_and_cta = (
            "## QA Scoring Rubric (12 dimensions)\n"
            "- Evidence completeness: 12% weight\n"
            "- Freshness: 8%\n"
            "- Clarity: 12%\n"
            "- Novelty: 8%\n"
            "- Non-cloning: 12%\n"
            "- Audience fit: 8%\n"
            "- CTA honesty: 8% (HARD GATE: >= 9)\n"
            "- Platform fit: 5%\n"
            "- Visual coherence: 5%\n"
            "- House voice fit: 5%\n"
            "- Humanitarian sensitivity: 10% (HARD GATE: >= 8)\n"
            "- Founder voice alignment: 7%\n"
            "\nPass threshold: composite >= 7.0 AND both hard gates met.\n\n"
            "## CTA Rules\n"
            "- 'Say XXX' CTAs only - no fake lead magnets\n"
            "- Weekly guide is the shared resource for all 5 posts\n"
            "- CTA keyword must be unique per week\n"
            "- DM flow: acknowledge comment -> deliver resource -> optional group invite\n"
            "- Platforms: Facebook (comment-to-DM) and LinkedIn (comment-to-DM)\n"
            "- Never promise something the guide doesn't deliver"
        )
        blocks.append(_cache_block(rubric_and_cta))

        # Segment 4: Founder voice profile
        if self._voice:
            lines = ["## Founder Voice Profile\n"]
            if self._voice.tone_range and isinstance(self._voice.tone_range, dict):
                tone_str = ", ".join(
                    f"{k}={v}" for k, v in list(self._voice.tone_range.items())[:6]
                )
                lines.append(f"Tone range: {tone_str}")
            if self._voice.values_and_beliefs:
                lines.append(f"Values: {', '.join(self._voice.values_and_beliefs[:10])}")
            if self._voice.recurring_themes:
                lines.append(f"Themes: {', '.join(self._voice.recurring_themes[:10])}")
            if self._voice.metaphor_families:
                lines.append(f"Metaphors: {', '.join(self._voice.metaphor_families[:10])}")
            if self._voice.taboos:
                lines.append(f"Taboos: {', '.join(self._voice.taboos[:10])}")
            blocks.append(_cache_block("\n".join(lines)))

        return blocks
