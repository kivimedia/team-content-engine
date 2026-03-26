"""WhatsApp Integration (PRD Section 40).

v1: Manual + semi-automated flows.
v2: WhatsApp Business API integration (stubs ready).
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

# PRD Section 40.2: v1 manual flow components
# PRD Section 40.4: Compliance requirements


class WhatsAppFlow:
    """Represents a complete WhatsApp DM flow for a CTA keyword."""

    def __init__(
        self,
        keyword: str,
        ack_message: str,
        delivery_message: str,
        follow_up: str | None = None,
        group_link: str | None = None,
        consent_required: bool = True,
    ) -> None:
        self.keyword = keyword
        self.ack_message = ack_message
        self.delivery_message = delivery_message
        self.follow_up = follow_up
        self.group_link = group_link
        self.consent_required = consent_required

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "ack_message": self.ack_message,
            "delivery_message": self.delivery_message,
            "follow_up": self.follow_up,
            "group_link": self.group_link,
            "consent_required": self.consent_required,
        }


class WhatsAppService:
    """Manages WhatsApp integration for CTA fulfillment."""

    # PRD Section 40.3: Message types
    SUPPORTED_MESSAGE_TYPES = [
        "group_invite_link",
        "waitlist_confirmation",
        "guide_ready_notification",
        "manual_conversation_opener",
    ]

    def generate_dm_flow(
        self,
        keyword: str,
        guide_title: str = "",
        group_link: str | None = None,
    ) -> WhatsAppFlow:
        """Generate a DM flow for a CTA keyword."""
        return WhatsAppFlow(
            keyword=keyword,
            ack_message=(
                f"Hey! Thanks for commenting '{keyword}'. "
                f"Here's what you requested."
            ),
            delivery_message=(
                f"Here's the guide: {guide_title}\n"
                "[Link will be inserted by operator]"
            ),
            follow_up=(
                "Let me know what you found most useful. "
                "I go deeper on this topic this week."
            ),
            group_link=group_link,
        )

    def generate_opt_in_message(self) -> str:
        """PRD Section 40.4: Explicit opt-in required."""
        return (
            "Would you like to join our WhatsApp community "
            "for exclusive AI insights? Reply YES to join. "
            "You can leave anytime."
        )

    def generate_opt_out_message(self) -> str:
        """PRD Section 40.4: Opt-out in every message."""
        return "Reply STOP to unsubscribe from future messages."

    def get_operator_checklist(
        self, keyword: str
    ) -> list[str]:
        """Checklist for the operator to set up fulfillment."""
        return [
            f"Keyword '{keyword}' is set in the CTA",
            "Guide/asset is uploaded and link is working",
            "DM template is ready in platform messaging",
            "WhatsApp group invite link is current",
            "Opt-in flow is tested",
            "Delivery time expectation is set (same day)",
        ]

    @staticmethod
    def validate_flow(flow: WhatsAppFlow) -> list[str]:
        """Validate a DM flow for compliance issues."""
        issues = []
        if not flow.keyword:
            issues.append("Keyword is required")
        if not flow.ack_message:
            issues.append("Acknowledgement message is required")
        if not flow.delivery_message:
            issues.append("Delivery message is required")
        if not flow.consent_required:
            issues.append(
                "Consent must be required per WhatsApp Business Policy"
            )
        return issues
