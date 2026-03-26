"""Notification service — sends operator alerts (PRD Section 43.1).

The operator must be notified when:
- Daily package is ready for review
- QA fails on a package
- Weekly learning update is available
- Costs exceed 80% / 90% / 100% of budget
- A new corpus upload has been parsed
- A model fallback was triggered
- A CTA fulfillment task is pending
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.notification import Notification
from tce.settings import settings

logger = structlog.get_logger()


class NotificationService:
    """Create and manage operator notifications."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def notify(
        self,
        notification_type: str,
        title: str,
        message: str,
        severity: str = "info",
        channel: str = "in_app",
        data: dict[str, Any] | None = None,
    ) -> Notification:
        """Create a new notification."""
        notification = Notification(
            notification_type=notification_type,
            title=title,
            message=message,
            severity=severity,
            channel=channel,
            data=data,
        )
        self.db.add(notification)
        await self.db.flush()
        logger.info(
            "notification.created",
            type=notification_type,
            severity=severity,
        )

        # GAP-09: Dispatch to external channels
        await self._dispatch_external(notification)

        return notification

    async def _dispatch_external(self, notification: Notification) -> None:
        """Send notification via email or webhook if configured."""
        # Email via Resend API
        if notification.channel == "email" or (
            notification.severity in ("warning", "critical", "error")
            and settings.resend_api_key
        ):
            await self._send_email(notification)

        # Webhook (Slack)
        if notification.channel == "webhook" or (
            notification.severity in ("critical", "error")
            and settings.slack_webhook_url
        ):
            await self._send_webhook(notification)

    async def _send_email(self, notification: Notification) -> None:
        """Send email notification via Resend API."""
        import httpx

        if not settings.resend_api_key or not settings.notification_email:
            return

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings.resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": "TCE <notifications@updates.kivimedia.co>",
                        "to": [settings.notification_email],
                        "subject": (
                            f"[TCE {notification.severity.upper()}] "
                            f"{notification.title}"
                        ),
                        "text": notification.message,
                    },
                )
            logger.info(
                "notification.email_sent",
                type=notification.notification_type,
            )
        except Exception:
            logger.exception("notification.email_failed")

    async def _send_webhook(self, notification: Notification) -> None:
        """Send notification to Slack webhook."""
        import httpx

        if not settings.slack_webhook_url:
            return

        severity_emoji = {
            "info": "i",
            "warning": "[!]",
            "error": "[ERROR]",
            "critical": "[CRITICAL]",
        }
        label = severity_emoji.get(notification.severity, "[*]")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    settings.slack_webhook_url,
                    json={
                        "text": (
                            f"{label} *{notification.title}*\n"
                            f"{notification.message}"
                        ),
                    },
                )
            logger.info(
                "notification.webhook_sent",
                type=notification.notification_type,
            )
        except Exception:
            logger.exception("notification.webhook_failed")

    # --- Convenience methods for common notification types ---

    async def package_ready(
        self, package_id: str
    ) -> Notification:
        return await self.notify(
            notification_type="package_ready",
            title="Daily package ready for review",
            message=(
                f"Package {package_id[:8]}... is ready. "
                "Review and approve in the draft queue."
            ),
            severity="info",
            data={"package_id": package_id},
        )

    async def qa_failure(
        self, package_id: str, reasons: list[str]
    ) -> Notification:
        return await self.notify(
            notification_type="qa_failure",
            title="QA failed on package",
            message=(
                f"Package {package_id[:8]}... failed QA: "
                f"{', '.join(reasons)}"
            ),
            severity="warning",
            data={
                "package_id": package_id,
                "failure_reasons": reasons,
            },
        )

    async def budget_alert(
        self,
        period: str,
        current: float,
        budget: float,
        pct: float,
    ) -> Notification:
        severity = "warning" if pct < 100 else "critical"
        return await self.notify(
            notification_type="budget_alert",
            title=f"{period.title()} budget at {pct:.0f}%",
            message=(
                f"${current:.2f} of ${budget:.2f} "
                f"{period} budget used ({pct:.0f}%)."
            ),
            severity=severity,
            data={
                "period": period,
                "current": current,
                "budget": budget,
                "pct": pct,
            },
        )

    async def corpus_parsed(
        self,
        document_id: str,
        example_count: int,
    ) -> Notification:
        return await self.notify(
            notification_type="corpus_parsed",
            title="Corpus upload parsed",
            message=(
                f"Document {document_id[:8]}... parsed: "
                f"{example_count} examples extracted. "
                "Review in the corpus dashboard."
            ),
            severity="info",
            data={
                "document_id": document_id,
                "example_count": example_count,
            },
        )

    async def model_fallback(
        self,
        agent_name: str,
        primary_model: str,
        fallback_model: str,
    ) -> Notification:
        return await self.notify(
            notification_type="model_fallback",
            title=f"Model fallback: {agent_name}",
            message=(
                f"{agent_name} fell back from {primary_model} "
                f"to {fallback_model}. Check rate limits."
            ),
            severity="warning",
            data={
                "agent_name": agent_name,
                "primary_model": primary_model,
                "fallback_model": fallback_model,
            },
        )

    async def weekly_update_ready(self) -> Notification:
        return await self.notify(
            notification_type="weekly_update",
            title="Weekly learning update ready",
            message=(
                "The weekly analysis is complete. "
                "Review recommendations in the learning dashboard."
            ),
            severity="info",
        )

    # --- Query methods ---

    async def get_unread(
        self, limit: int = 50
    ) -> list[Notification]:
        result = await self.db.execute(
            select(Notification)
            .where(
                Notification.read.is_(False),
                Notification.dismissed.is_(False),
            )
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_unread_count(self) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.read.is_(False),
                Notification.dismissed.is_(False),
            )
        )
        return result.scalar_one()

    async def mark_read(
        self, notification_id: str
    ) -> None:
        import uuid

        notification = await self.db.get(
            Notification, uuid.UUID(notification_id)
        )
        if notification:
            notification.read = True
            await self.db.flush()

    async def mark_all_read(self) -> int:
        result = await self.db.execute(
            select(Notification).where(
                Notification.read.is_(False)
            )
        )
        count = 0
        for n in result.scalars().all():
            n.read = True
            count += 1
        await self.db.flush()
        return count
