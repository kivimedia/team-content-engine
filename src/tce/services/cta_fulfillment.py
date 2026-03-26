"""CTA fulfillment service - comment-to-DM detection for FB and LinkedIn (PRD Section 24.4).

Handles:
1. Facebook: Webhook for comment notifications + Messenger DM dispatch
2. LinkedIn: Polling for comments + InMail/message dispatch
Both create DMFulfillmentLog records for tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.dm_fulfillment import DMFulfillmentLog
from tce.models.post_package import PostPackage
from tce.settings import settings

logger = structlog.get_logger()


class CTAFulfillmentService:
    """Detects CTA keyword comments and dispatches DMs on FB and LinkedIn."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_active_keywords(self) -> list[dict[str, Any]]:
        """Get all active CTA keywords from approved post packages."""
        result = await self.db.execute(
            select(PostPackage.id, PostPackage.cta_keyword, PostPackage.dm_flow)
            .where(
                PostPackage.approval_status == "approved",
                PostPackage.cta_keyword.isnot(None),
            )
            .order_by(PostPackage.created_at.desc())
            .limit(20)
        )
        rows = result.all()
        return [
            {"package_id": str(r[0]), "keyword": r[1], "dm_flow": r[2] or {}}
            for r in rows
            if r[1]
        ]

    def match_keyword(
        self, comment_text: str, keywords: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Check if comment text matches any active CTA keyword."""
        text_lower = comment_text.lower().strip()
        for kw in keywords:
            if kw["keyword"] and kw["keyword"].lower() in text_lower:
                return kw
        return None

    async def process_facebook_comment(
        self,
        comment_id: str,
        commenter_id: str,
        comment_text: str,
        post_id: str,
    ) -> dict[str, Any]:
        """Process a Facebook comment for CTA keyword matching.

        Called from the webhook endpoint when FB sends a comment notification.
        """
        keywords = await self.get_active_keywords()
        match = self.match_keyword(comment_text, keywords)

        if not match:
            return {"matched": False}

        # Create fulfillment log
        log = DMFulfillmentLog(
            package_id=match["package_id"] if match.get("package_id") else None,
            cta_keyword=match["keyword"],
            promised_asset=match.get("dm_flow", {}).get("asset_name", "guide"),
            platform="facebook",
            commenter_id=commenter_id,
            comment_text=comment_text,
            comment_timestamp=datetime.now(timezone.utc),
            delivery_method="automated",
            status="pending",
        )
        self.db.add(log)
        await self.db.flush()

        # Attempt to send DM via FB Messenger
        if settings.facebook_page_token:
            sent = await self._send_facebook_dm(
                commenter_id, match.get("dm_flow", {}), match["keyword"]
            )
            if sent:
                log.dm_sent = True
                log.dm_sent_at = datetime.now(timezone.utc)
                log.status = "sent"
            else:
                log.status = "pending"
                log.failure_reason = "DM send failed"
            await self.db.flush()
        else:
            logger.info("cta.no_fb_token", keyword=match["keyword"])

        return {
            "matched": True,
            "keyword": match["keyword"],
            "log_id": str(log.id),
            "dm_sent": log.dm_sent or False,
        }

    async def _send_facebook_dm(
        self, recipient_id: str, dm_flow: dict, keyword: str
    ) -> bool:
        """Send a DM via Facebook Messenger Send API."""
        message_text = dm_flow.get(
            "delivery_message",
            f"Thanks for commenting '{keyword}'! Here's what you requested.",
        )

        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": message_text},
            "messaging_type": "RESPONSE",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://graph.facebook.com/v19.0/me/messages",
                    params={"access_token": settings.facebook_page_token},
                    json=payload,
                )
                resp.raise_for_status()
                logger.info("cta.fb_dm_sent", recipient=recipient_id, keyword=keyword)
                return True
        except Exception:
            logger.exception("cta.fb_dm_failed", recipient=recipient_id)
            return False

    async def process_linkedin_comment(
        self,
        commenter_urn: str,
        comment_text: str,
        post_urn: str,
    ) -> dict[str, Any]:
        """Process a LinkedIn comment for CTA keyword matching."""
        keywords = await self.get_active_keywords()
        match = self.match_keyword(comment_text, keywords)

        if not match:
            return {"matched": False}

        log = DMFulfillmentLog(
            package_id=match["package_id"] if match.get("package_id") else None,
            cta_keyword=match["keyword"],
            promised_asset=match.get("dm_flow", {}).get("asset_name", "guide"),
            platform="linkedin",
            commenter_id=commenter_urn,
            comment_text=comment_text,
            comment_timestamp=datetime.now(timezone.utc),
            delivery_method="manual",  # LI messaging API is restricted
            status="pending",
        )
        self.db.add(log)
        await self.db.flush()

        logger.info(
            "cta.li_match",
            keyword=match["keyword"],
            commenter=commenter_urn,
        )

        return {
            "matched": True,
            "keyword": match["keyword"],
            "log_id": str(log.id),
            "dm_sent": False,
            "note": "LinkedIn DM requires manual send or Messaging API access",
        }

    async def verify_facebook_webhook(
        self, mode: str, token: str, challenge: str
    ) -> str | None:
        """Verify Facebook webhook subscription."""
        if mode == "subscribe" and token == settings.facebook_verify_token:
            return challenge
        return None
