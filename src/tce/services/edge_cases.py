"""Edge case handlers (PRD Appendix H).

Handles the 10 stress test scenarios defined in the PRD.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.post_package import PostPackage
from tce.models.qa_scorecard import QAScorecard

logger = structlog.get_logger()

# Thresholds
QA_CONSECUTIVE_FAILURE_LIMIT = 3
APPROVAL_TIMEOUT_HOURS = 48
BUFFER_POST_COUNT = 3


class EdgeCaseHandler:
    """Detects and handles edge cases from PRD Appendix H."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def check_consecutive_qa_failures(self) -> dict[str, Any]:
        """H.3: QA fails three days in a row -> pause pipeline.

        Returns action recommendation.
        """
        result = await self.db.execute(
            select(QAScorecard)
            .where(QAScorecard.pass_status == "fail")
            .order_by(QAScorecard.created_at.desc())
            .limit(QA_CONSECUTIVE_FAILURE_LIMIT)
        )
        recent_failures = result.scalars().all()

        if len(recent_failures) >= QA_CONSECUTIVE_FAILURE_LIMIT:
            # Check if they're consecutive (within last 3 days)
            if recent_failures:
                oldest = recent_failures[-1].created_at
                span = datetime.utcnow() - oldest
                if span <= timedelta(days=QA_CONSECUTIVE_FAILURE_LIMIT + 1):
                    return {
                        "triggered": True,
                        "action": "pause_pipeline",
                        "message": (
                            f"QA has failed {QA_CONSECUTIVE_FAILURE_LIMIT} "
                            "consecutive days. Pipeline paused. "
                            "Review the QA failure report."
                        ),
                        "failure_count": len(recent_failures),
                    }

        return {"triggered": False, "failure_count": len(recent_failures)}

    async def check_approval_timeout(self) -> list[dict[str, Any]]:
        """H.4: Operator doesn't approve for 48+ hours -> archive.

        Returns list of timed-out packages.
        """
        cutoff = datetime.utcnow() - timedelta(hours=APPROVAL_TIMEOUT_HOURS)
        result = await self.db.execute(
            select(PostPackage)
            .where(
                PostPackage.approval_status == "draft",
                PostPackage.created_at < cutoff,
            )
        )
        stale_packages = result.scalars().all()

        archived = []
        for pkg in stale_packages:
            pkg.approval_status = "archived"
            archived.append({
                "package_id": str(pkg.id),
                "created_at": str(pkg.created_at),
                "hours_pending": (
                    (datetime.utcnow() - pkg.created_at).total_seconds() / 3600
                ),
            })

        if archived:
            await self.db.flush()
            logger.warning(
                "edge_case.approval_timeout",
                archived_count=len(archived),
            )

        return archived

    async def check_budget_spike(
        self, daily_total: float, daily_budget: float
    ) -> dict[str, Any]:
        """H.9: Cost spike exceeds daily budget.

        The run completes (no mid-run abort) but operator is alerted.
        """
        if daily_total > daily_budget:
            return {
                "triggered": True,
                "action": "alert_operator",
                "message": (
                    f"Daily spend ${daily_total:.2f} exceeds "
                    f"budget ${daily_budget:.2f}."
                ),
                "overage": daily_total - daily_budget,
                "recommendation": (
                    "Check which agent caused the overage. "
                    "Consider model downgrade for next run."
                ),
            }
        return {"triggered": False}

    @staticmethod
    def get_fallback_cta_for_missing_guide(
        keyword: str = "notify",
    ) -> dict[str, Any]:
        """H.6: Weekly guide isn't ready by Monday.

        Switch to a fallback CTA that's honest about timing.
        """
        return {
            "keyword": keyword,
            "fb_cta_line": (
                f"I'm putting together this week's guide — "
                f"comment '{keyword}' and I'll send it when it's ready."
            ),
            "li_cta_line": (
                f"This week's guide is in progress. "
                f"Drop '{keyword}' in the comments and I'll "
                "send it over once it's ready."
            ),
            "dm_flow": {
                "trigger": keyword,
                "ack_message": (
                    "Thanks! The guide is being finalized. "
                    "I'll send it as soon as it's ready."
                ),
            },
        }

    @staticmethod
    def get_fallback_topic() -> dict[str, Any]:
        """H.1: Trend Scout finds nothing relevant.

        Fall back to evergreen topics from the template library.
        """
        evergreen_topics = [
            "5 AI tools most professionals don't know about",
            "The mistake most founders make with AI automation",
            "How to evaluate any AI tool in 10 minutes",
            "What changed in AI this month (and what it means for you)",
            "The one AI workflow that saves 10 hours per week",
            "Why most AI implementations fail (and how to avoid it)",
            "Building your first AI-powered process: a step-by-step guide",
            "The hidden cost of NOT using AI in 2026",
            "AI for non-technical founders: where to start",
            "From chatbot to workflow: the AI adoption ladder",
        ]
        return {
            "source": "evergreen_library",
            "topics": evergreen_topics,
            "message": (
                "No strong trending stories found. "
                "Using evergreen topic from the library."
            ),
        }

    @staticmethod
    def handle_research_failure(
        failed_claim: str,
    ) -> dict[str, Any]:
        """H.2: Research Agent can't verify the key claim.

        Do NOT proceed to drafting. Re-invoke strategist.
        """
        return {
            "action": "reinvoke_strategist",
            "reason": f"Could not verify: {failed_claim}",
            "options": [
                "Choose a different angle that doesn't depend on this claim",
                "Downgrade to soft claim with signal words",
                "Switch to an evergreen topic",
            ],
        }

    @staticmethod
    def handle_source_creator_overlap(
        creator_name: str, topic: str
    ) -> dict[str, Any]:
        """H.7: A source creator publishes the same story first."""
        return {
            "action": "flag_for_review",
            "message": (
                f"{creator_name} posted about '{topic}' this week. "
                "Options: proceed with a distinctly different angle, "
                "swap template, or defer the topic."
            ),
            "options": [
                "proceed_different_angle",
                "swap_template",
                "defer_topic",
            ],
        }
