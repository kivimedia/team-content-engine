"""Learning service — aggregates feedback and triggers the learning loop."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.learning_event import LearningEvent
from tce.models.operator_feedback import OperatorFeedback
from tce.models.qa_scorecard import QAScorecard


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

        # Aggregate feedback tags
        tag_counts: dict[str, int] = {}
        for fb in feedback:
            for tag in fb.feedback_tags or []:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

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
            "feedback_events": [
                {
                    "package_id": str(f.package_id),
                    "feedback_tags": f.feedback_tags,
                    "action_taken": f.action_taken,
                }
                for f in feedback
            ],
            "tag_frequency": tag_counts,
        }
