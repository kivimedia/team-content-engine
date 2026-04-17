"""Populate TJ Robertson's CreatorProfile fields from InstaIQ deliverable_5
analysis so trend_scout + story_strategist + writer can all read them
uniformly via context["creator_profile"].

top_patterns stores TJ's 3 highest-engagement topic clusters + top 3 hook
formulas (what to do more of). disallowed_clone_markers stores the
5 failure patterns from his bottom 10 posts (what to avoid). voice_axes
captures the tonal dimensions a writer should hit to sound TJ-like
without copying him.

Run once after instaiq_import:
    python -m tce.services.seed_tj_creator_profile
"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select

from tce.db.session import async_session
from tce.models.creator_profile import CreatorProfile

logger = structlog.get_logger()


TJ_NAME = "TJ Robertson"

# Top 3 topic clusters by avg engagement rate from deliverable_5 analysis:
# - AI competition dynamics (avg engagement 6.28)
# - Website strategy for AI agents (avg engagement 4.87)
# - SaaS / software industry disruption (avg engagement 5.62)
# Plus top hook formulas from same doc.
TJ_TOP_PATTERNS = [
    "topic:ai_competition_dynamics",
    "topic:website_for_ai_agents",
    "topic:saas_industry_shift",
    "hook:crisis_signal",
    "hook:massive_number",
    "hook:paradigm_reframe",
    "hook:patent_reveal",
    "format:trend_reaction",
    "format:news_peg_with_stakes",
]

# Failure patterns from bottom 10 posts - all scored 0 views.
TJ_DISALLOWED = [
    "personal_metaphor_unrelated_to_topic",
    "vague_urgency_without_specifics",
    "question_hook_without_stakes",
    "broad_prediction_without_named_catalyst",
    "beginner_content_framed_as_insider",
]

# Voice axes: 1-10 scales that capture the TJ sound without copying him.
# These become inputs to any agent that needs to calibrate voice.
TJ_VOICE_AXES = {
    "directness": 9,           # "You should absolutely..." - no hedging on core claim
    "specificity": 10,         # Named actors, exact numbers, dates
    "authority_vs_humility": 7,  # Strong POV but not preachy
    "urgency": 8,              # Stakes are concrete, not vague "AI is coming"
    "humor": 3,                # Low - content is stakes-driven, not joking
    "teaching_vs_reporting": 4, # Leans reporting/framing, not curriculum
    "first_person": 9,         # "I've seen...", "we're watching..." - not abstract
    "sentence_brevity": 8,     # Short punchy sentences for walking pace
    "opinion_density": 9,      # Takes a stance, doesn't summarize both sides
    "emotional_range": 5,      # Calm-urgent, not explosive
}

# These angle_type labels align with what the weekly_planner + story_strategist
# already emit. angle_weights tells them which of TJ's formula-compatible
# angles to favor when generating walking-video content for his style.
TJ_ANGLE_WEIGHTS = {
    "big_shift_explainer": 1.0,       # paradigm reframes fit here
    "contrarian_diagnosis": 1.0,      # counterintuitive + misconception correction
    "second_order_implication": 0.9,  # hidden process reveal
    "case_study_build_story": 0.3,    # works but not his strongest
    "tactical_workflow_guide": 0.2,   # dense how-tos bad for walking pace
}


async def seed() -> bool:
    """Upsert TJ's creator profile with deliverable_5-derived patterns."""
    async with async_session() as db:
        result = await db.execute(
            select(CreatorProfile).where(CreatorProfile.creator_name == TJ_NAME)
        )
        creator = result.scalar_one_or_none()
        if not creator:
            print(f"ERROR: '{TJ_NAME}' not found. Run instaiq_import first.")
            return False

        style_preamble = (
            "TJ Robertson (@tjrobertsondigital) - AI/tech commentary for business owners. "
            "268 posts analyzed via InstaIQ; top hooks hit 24-40% engagement by pairing "
            "a named actor (OpenAI, Google, Anthropic) with a specific stat and immediate "
            "stakes for business owners. Prefers walking-monologue and trend-reaction formats."
        )
        existing_style = (creator.style_notes or "")
        if style_preamble[:60] not in existing_style:
            creator.style_notes = (
                style_preamble
                + ("\n\n" + existing_style if existing_style else "")
            )[:4000]

        creator.top_patterns = TJ_TOP_PATTERNS
        creator.disallowed_clone_markers = TJ_DISALLOWED
        creator.voice_axes = TJ_VOICE_AXES
        creator.angle_weights = TJ_ANGLE_WEIGHTS
        # Bump influence weight: deliverable_5 is ground truth, trust it more.
        creator.allowed_influence_weight = 0.40

        await db.commit()
        print(f"Seeded {TJ_NAME} creator profile: "
              f"top_patterns={len(TJ_TOP_PATTERNS)}, "
              f"disallowed={len(TJ_DISALLOWED)}, "
              f"voice_axes={len(TJ_VOICE_AXES)} dims, "
              f"angle_weights={len(TJ_ANGLE_WEIGHTS)}")
        return True


async def _amain() -> int:
    ok = await seed()
    return 0 if ok else 2


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
