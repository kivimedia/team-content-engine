"""Orchestrator chatbot — translates natural language into system actions (PRD Section 44).

The chatbot is a thin conversational layer on top of the existing FastAPI backend.
It translates natural language into API calls against the orchestrator, editorial
calendar, cost tracker, and learning loop.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.content_calendar import ContentCalendarEntry
from tce.models.cost_event import CostEvent
from tce.models.learning_event import LearningEvent
from tce.models.post_package import PostPackage
from tce.settings import settings

logger = structlog.get_logger()

# Intent patterns — simple keyword matching for v1
# In production, this would use the LLM to classify intent
# Ordered by priority — more specific intents checked first
INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("skip_day", ["skip today", "skip", "cancel today", "don't post"]),
    ("override_topic", [
        "write about", "change topic", "switch to",
        "instead write", "cover this",
    ]),
    ("trigger_pipeline", [
        "run pipeline", "run the", "generate", "create post",
        "start daily", "run daily",
    ]),
    ("query_costs", ["cost", "spend", "budget", "how much"]),
    ("query_performance", [
        "best performing", "top cta", "engagement",
        "which template", "what worked",
    ]),
    ("query_package", ["show me", "latest draft", "last post", "today's package"]),
    ("query_week", ["this week", "week's plan", "weekly", "what's queued"]),
    ("query_today", ["today", "what's today", "today's post", "what's scheduled"]),
    ("approve", ["approve", "looks good", "ship it", "publish"]),
    ("reject", ["reject", "redo", "try again", "not good"]),
    ("status", ["status", "pipeline status", "is it done", "progress"]),
    ("help", ["help", "what can you do", "commands"]),
]


def classify_intent(message: str) -> str:
    """Classify user message into an intent. Returns 'unknown' if no match."""
    lower = message.lower().strip()
    for intent, patterns in INTENT_PATTERNS:
        for pattern in patterns:
            if pattern in lower:
                return intent
    return "unknown"


class ChatbotService:
    """Handles operator chat messages and executes system actions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def handle_message(
        self, message: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Process a chat message and return a response."""
        intent = classify_intent(message)
        logger.info("chatbot.intent", intent=intent, message=message[:100])

        handler = getattr(self, f"_handle_{intent}", self._handle_unknown)
        try:
            return await handler(message, context or {})
        except Exception as e:
            logger.exception("chatbot.error", intent=intent)
            return {
                "response": f"Something went wrong: {e}",
                "intent": intent,
                "success": False,
            }

    async def _handle_query_today(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """What's scheduled for today?"""
        result = await self.db.execute(
            select(ContentCalendarEntry).where(
                ContentCalendarEntry.date == date.today()
            )
        )
        entry = result.scalar_one_or_none()
        if entry:
            return {
                "response": (
                    f"Today's plan: **{entry.angle_type}**\n"
                    f"Topic: {entry.topic or 'Not yet assigned'}\n"
                    f"Status: {entry.status}"
                ),
                "intent": "query_today",
                "data": {
                    "date": str(entry.date),
                    "angle_type": entry.angle_type,
                    "topic": entry.topic,
                    "status": entry.status,
                },
                "success": True,
            }
        return {
            "response": "Nothing scheduled for today.",
            "intent": "query_today",
            "success": True,
        }

    async def _handle_query_week(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """What's the plan for this week?"""
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        friday = monday + timedelta(days=4)

        result = await self.db.execute(
            select(ContentCalendarEntry)
            .where(
                ContentCalendarEntry.date >= monday,
                ContentCalendarEntry.date <= friday,
            )
            .order_by(ContentCalendarEntry.date)
        )
        entries = result.scalars().all()

        if not entries:
            return {
                "response": (
                    "No entries for this week yet. "
                    "Use `POST /calendar/plan-week` to generate them."
                ),
                "intent": "query_week",
                "success": True,
            }

        days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
        lines = []
        for entry in entries:
            day_name = days[entry.day_of_week] if entry.day_of_week < 5 else "?"
            topic = entry.topic or "TBD"
            lines.append(
                f"- **{day_name}** ({entry.date}): "
                f"{entry.angle_type} — {topic} [{entry.status}]"
            )

        return {
            "response": "This week's plan:\n" + "\n".join(lines),
            "intent": "query_week",
            "data": [
                {
                    "date": str(e.date),
                    "angle": e.angle_type,
                    "topic": e.topic,
                    "status": e.status,
                }
                for e in entries
            ],
            "success": True,
        }

    async def _handle_query_costs(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """How much have we spent?"""
        today = date.today()

        # Daily total
        daily_result = await self.db.execute(
            select(func.coalesce(func.sum(CostEvent.computed_cost_usd), 0.0))
            .where(CostEvent.date == today)
        )
        daily_total = float(daily_result.scalar_one())

        # Monthly total
        month_start = today.replace(day=1)
        monthly_result = await self.db.execute(
            select(func.coalesce(func.sum(CostEvent.computed_cost_usd), 0.0))
            .where(CostEvent.date >= month_start)
        )
        monthly_total = float(monthly_result.scalar_one())

        daily_budget = float(settings.daily_budget_usd)
        monthly_budget = float(settings.monthly_budget_usd)

        return {
            "response": (
                f"**Today**: ${daily_total:.2f} / ${daily_budget:.2f} "
                f"({daily_total / daily_budget * 100:.0f}%)\n"
                f"**This month**: ${monthly_total:.2f} / ${monthly_budget:.2f} "
                f"({monthly_total / monthly_budget * 100:.0f}%)"
            ),
            "intent": "query_costs",
            "data": {
                "daily_total": daily_total,
                "daily_budget": daily_budget,
                "monthly_total": monthly_total,
                "monthly_budget": monthly_budget,
            },
            "success": True,
        }

    async def _handle_query_performance(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """What's performing well?"""
        # Get recent learning events with actual metrics
        result = await self.db.execute(
            select(LearningEvent)
            .where(LearningEvent.actual_comments.is_not(None))
            .order_by(
                (LearningEvent.actual_shares * 3 + LearningEvent.actual_comments).desc()
            )
            .limit(5)
        )
        events = result.scalars().all()

        if not events:
            return {
                "response": (
                    "No performance data yet. "
                    "Enter post metrics via the feedback endpoints."
                ),
                "intent": "query_performance",
                "success": True,
            }

        lines = []
        for e in events:
            shares = e.actual_shares or 0
            comments = e.actual_comments or 0
            score = shares * 3 + comments
            lines.append(
                f"- Package {str(e.package_id)[:8]}...: "
                f"{comments} comments, {shares} shares (score: {score})"
            )

        return {
            "response": "Top performing posts:\n" + "\n".join(lines),
            "intent": "query_performance",
            "data": [
                {
                    "package_id": str(e.package_id),
                    "comments": e.actual_comments,
                    "shares": e.actual_shares,
                }
                for e in events
            ],
            "success": True,
        }

    async def _handle_query_package(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """Show the latest package."""
        result = await self.db.execute(
            select(PostPackage)
            .order_by(PostPackage.created_at.desc())
            .limit(1)
        )
        pkg = result.scalar_one_or_none()

        if not pkg:
            return {
                "response": "No packages yet. Run the daily pipeline first.",
                "intent": "query_package",
                "success": True,
            }

        fb_preview = (pkg.facebook_post or "")[:200]
        li_preview = (pkg.linkedin_post or "")[:200]

        return {
            "response": (
                f"**Latest package** ({pkg.approval_status}):\n\n"
                f"**FB**: {fb_preview}...\n\n"
                f"**LI**: {li_preview}...\n\n"
                f"CTA: {pkg.cta_keyword or 'none'}"
            ),
            "intent": "query_package",
            "data": {
                "package_id": str(pkg.id),
                "status": pkg.approval_status,
                "cta": pkg.cta_keyword,
            },
            "success": True,
        }

    async def _handle_trigger_pipeline(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """Trigger the daily content pipeline."""
        return {
            "response": (
                "To trigger the daily pipeline, call:\n"
                "`POST /api/v1/pipeline/run` with "
                '`{"workflow": "daily_content"}`\n\n'
                "Or use the scheduler: "
                "`POST /api/v1/scheduler/trigger/daily_content`"
            ),
            "intent": "trigger_pipeline",
            "action": "trigger_daily_content",
            "success": True,
        }

    async def _handle_skip_day(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """Skip today's content."""
        result = await self.db.execute(
            select(ContentCalendarEntry).where(
                ContentCalendarEntry.date == date.today()
            )
        )
        entry = result.scalar_one_or_none()
        if entry:
            entry.status = "skipped"
            await self.db.flush()
            return {
                "response": f"Skipped today's {entry.angle_type} post.",
                "intent": "skip_day",
                "success": True,
            }
        return {
            "response": "Nothing scheduled for today to skip.",
            "intent": "skip_day",
            "success": True,
        }

    async def _handle_override_topic(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """Override today's topic."""
        # Extract topic from message (simple: everything after trigger phrase)
        topic = message
        for phrase in [
            "write about", "change topic to", "switch to",
            "instead write about", "cover",
        ]:
            if phrase in message.lower():
                idx = message.lower().index(phrase) + len(phrase)
                topic = message[idx:].strip().strip('"').strip("'")
                break

        result = await self.db.execute(
            select(ContentCalendarEntry).where(
                ContentCalendarEntry.date == date.today()
            )
        )
        entry = result.scalar_one_or_none()
        if entry:
            entry.topic = topic
            await self.db.flush()
            return {
                "response": f"Updated today's topic to: **{topic}**",
                "intent": "override_topic",
                "success": True,
            }
        return {
            "response": (
                f"No calendar entry for today. "
                f"Noted topic preference: {topic}"
            ),
            "intent": "override_topic",
            "success": True,
        }

    async def _handle_approve(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """Approve the latest draft package."""
        result = await self.db.execute(
            select(PostPackage)
            .where(PostPackage.approval_status == "draft")
            .order_by(PostPackage.created_at.desc())
            .limit(1)
        )
        pkg = result.scalar_one_or_none()
        if pkg:
            pkg.approval_status = "approved"
            await self.db.flush()
            return {
                "response": f"Package {str(pkg.id)[:8]}... approved!",
                "intent": "approve",
                "data": {"package_id": str(pkg.id)},
                "success": True,
            }
        return {
            "response": "No draft packages to approve.",
            "intent": "approve",
            "success": True,
        }

    async def _handle_reject(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """Reject the latest draft package."""
        result = await self.db.execute(
            select(PostPackage)
            .where(PostPackage.approval_status == "draft")
            .order_by(PostPackage.created_at.desc())
            .limit(1)
        )
        pkg = result.scalar_one_or_none()
        if pkg:
            pkg.approval_status = "rejected"
            await self.db.flush()
            return {
                "response": (
                    f"Package {str(pkg.id)[:8]}... rejected. "
                    "Add feedback tags via the feedback endpoint."
                ),
                "intent": "reject",
                "data": {"package_id": str(pkg.id)},
                "success": True,
            }
        return {
            "response": "No draft packages to reject.",
            "intent": "reject",
            "success": True,
        }

    async def _handle_status(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """Pipeline and system status."""
        # Count packages by status
        draft_count = await self._count_packages("draft")
        approved_count = await self._count_packages("approved")
        published_count = await self._count_packages("published")

        return {
            "response": (
                f"**System status**:\n"
                f"- Drafts: {draft_count}\n"
                f"- Approved: {approved_count}\n"
                f"- Published: {published_count}"
            ),
            "intent": "status",
            "success": True,
        }

    async def _handle_help(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """Show available commands."""
        return {
            "response": (
                "I can help you with:\n"
                "- **What's today?** — See today's scheduled post\n"
                "- **This week** — View the weekly plan\n"
                "- **Show costs** — Budget and spend overview\n"
                "- **Show me the latest draft** — Preview the last package\n"
                "- **What worked best?** — Top performing posts\n"
                "- **Write about [topic]** — Override today's topic\n"
                "- **Skip today** — Cancel today's post\n"
                "- **Approve** — Approve the latest draft\n"
                "- **Reject** — Send the latest draft back\n"
                "- **Status** — System overview\n"
                "- **Run pipeline** — Trigger content generation"
            ),
            "intent": "help",
            "success": True,
        }

    async def _handle_unknown(
        self, message: str, context: dict
    ) -> dict[str, Any]:
        """Fallback for unrecognized messages."""
        return {
            "response": (
                "I didn't understand that. Try 'help' to see "
                "what I can do, or be more specific about what "
                "you'd like to check or change."
            ),
            "intent": "unknown",
            "success": False,
        }

    async def _count_packages(self, status: str) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(PostPackage)
            .where(PostPackage.approval_status == status)
        )
        return result.scalar_one()
