"""Learning service — aggregates feedback and triggers the learning loop."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.learning_event import LearningEvent
from tce.models.operator_feedback import OperatorFeedback
from tce.models.pattern_template import PatternTemplate
from tce.models.post_package import PostPackage
from tce.models.qa_scorecard import QAScorecard
from tce.models.story_brief import StoryBrief

# Engagement weighting matches EngagementScorer (PRD Section 12.2) so pre-publish
# scoring and post-publish learning operate on the same scale.
_ENGAGEMENT_WEIGHTS = {
    "shares": 3.0,
    "comments": 1.0,
    "dms": 2.0,
    "clicks": 0.5,
    "saves": 1.0,
    "follows": 1.5,
    "joins": 2.5,
}

# Multipliers are clamped to keep one outlier from collapsing the floor or
# the ceiling — e.g. a single 50× post on `contrarian_diagnosis` shouldn't
# make every other family look "broken."
_MULTIPLIER_MIN = 0.5
_MULTIPLIER_MAX = 2.0
# Below this many learning events for a family, we don't trust the signal.
_MIN_SAMPLES_PER_FAMILY = 3


class LearningService:
    """Aggregate performance data for the learning loop."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_weekly_data(self, package_ids: list[uuid.UUID]) -> dict[str, Any]:
        """Collect all learning-relevant data for a set of post packages."""
        # Get learning events
        events_result = await self.db.execute(
            select(LearningEvent).where(LearningEvent.package_id.in_(package_ids))
        )
        events = events_result.scalars().all()

        # Get QA scorecards
        qa_result = await self.db.execute(
            select(QAScorecard).where(QAScorecard.package_id.in_(package_ids))
        )
        scorecards = qa_result.scalars().all()

        # Get operator feedback
        feedback_result = await self.db.execute(
            select(OperatorFeedback).where(OperatorFeedback.package_id.in_(package_ids))
        )
        feedback = feedback_result.scalars().all()

        # Get original posts for copy comparison
        pkg_result = await self.db.execute(
            select(PostPackage).where(PostPackage.id.in_(package_ids))
        )
        packages = {str(p.id): p for p in pkg_result.scalars().all()}

        # Aggregate feedback tags
        tag_counts: dict[str, int] = {}
        for fb in feedback:
            for tag in fb.feedback_tags or []:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # Build feedback events with original vs revised copy for voice drift analysis
        feedback_events = []
        for f in feedback:
            entry: dict[str, Any] = {
                "package_id": str(f.package_id),
                "feedback_tags": f.feedback_tags,
                "feedback_notes": f.feedback_notes,
                "action_taken": f.action_taken,
                "revision_summary": f.revision_summary,
            }
            # Include original + revised copy when available for voice drift analysis
            pkg = packages.get(str(f.package_id))
            if f.revised_facebook_post:
                entry["original_facebook_post"] = pkg.facebook_post if pkg else None
                entry["revised_facebook_post"] = f.revised_facebook_post
            if f.revised_linkedin_post:
                entry["original_linkedin_post"] = pkg.linkedin_post if pkg else None
                entry["revised_linkedin_post"] = f.revised_linkedin_post
            feedback_events.append(entry)

        return {
            "learning_events": [
                {
                    "package_id": str(e.package_id),
                    "platform": e.platform,
                    "actual_comments": e.actual_comments,
                    "actual_shares": e.actual_shares,
                    "actual_clicks": e.actual_clicks,
                    "actual_dms": e.actual_dms,
                    "actual_saves": e.actual_saves,
                }
                for e in events
            ],
            "qa_scorecards": [
                {
                    "package_id": str(s.package_id),
                    "composite_score": s.composite_score,
                    "pass_status": s.pass_status,
                    "dimension_scores": s.dimension_scores,
                }
                for s in scorecards
            ],
            "feedback_events": feedback_events,
            "tag_frequency": tag_counts,
        }

    async def get_template_performance_multipliers(
        self, days: int = 30
    ) -> dict[str, float]:
        """Per-template-family engagement multipliers from posted-content performance.

        For each template_family with >= MIN_SAMPLES_PER_FAMILY learning events
        in the last `days`, returns multiplier = family_mean / global_mean,
        clamped to [MIN, MAX]. trend_scout uses these to bias hook_strength
        scoring toward families that have been working in market.

        Returns empty dict when there's not enough data overall — better to
        rank without a learning signal than to apply a noisy one.
        """
        cutoff = date.today() - timedelta(days=days)

        rows = await self.db.execute(
            select(LearningEvent, PatternTemplate.template_family)
            .join(PostPackage, PostPackage.id == LearningEvent.package_id)
            .join(StoryBrief, StoryBrief.id == PostPackage.brief_id)
            .join(PatternTemplate, PatternTemplate.id == StoryBrief.template_id)
            .where(LearningEvent.publish_date >= cutoff)
        )
        joined = rows.all()
        if not joined:
            return {}

        # Bucket scores by family
        by_family: dict[str, list[float]] = {}
        for event, family in joined:
            score = self._engagement_score(event)
            by_family.setdefault(family, []).append(score)

        # Need a meaningful global cohort before we can compute relatives.
        all_scores = [s for scores in by_family.values() for s in scores]
        if len(all_scores) < _MIN_SAMPLES_PER_FAMILY:
            return {}
        global_mean = sum(all_scores) / len(all_scores)
        if global_mean <= 0:
            return {}

        multipliers: dict[str, float] = {}
        for family, scores in by_family.items():
            if len(scores) < _MIN_SAMPLES_PER_FAMILY:
                continue
            family_mean = sum(scores) / len(scores)
            ratio = family_mean / global_mean
            multipliers[family] = round(
                max(_MULTIPLIER_MIN, min(_MULTIPLIER_MAX, ratio)), 2
            )
        return multipliers

    @staticmethod
    def _engagement_score(event: LearningEvent) -> float:
        """Single engagement scalar matching EngagementScorer's weighting."""
        return (
            (event.actual_shares or 0) * _ENGAGEMENT_WEIGHTS["shares"]
            + (event.actual_comments or 0) * _ENGAGEMENT_WEIGHTS["comments"]
            + (event.actual_dms or 0) * _ENGAGEMENT_WEIGHTS["dms"]
            + (event.actual_clicks or 0) * _ENGAGEMENT_WEIGHTS["clicks"]
            + (event.actual_saves or 0) * _ENGAGEMENT_WEIGHTS["saves"]
            + (event.actual_follows or 0) * _ENGAGEMENT_WEIGHTS["follows"]
            + (event.actual_joins or 0) * _ENGAGEMENT_WEIGHTS["joins"]
        )
