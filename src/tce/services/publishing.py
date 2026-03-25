"""Publishing adapters — export and platform integration (PRD Section 24)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import structlog

logger = structlog.get_logger()


class PublishingAdapter(ABC):
    """Abstract base for publishing adapters."""

    @abstractmethod
    async def publish(self, package: dict[str, Any]) -> dict[str, Any]:
        """Publish a post package. Returns status dict."""
        ...

    @abstractmethod
    async def get_status(self, publish_id: str) -> dict[str, Any]:
        """Get the status of a published post."""
        ...


class ManualExportAdapter(PublishingAdapter):
    """Export package as a copy-paste-ready dict for manual publishing."""

    async def publish(self, package: dict[str, Any]) -> dict[str, Any]:
        """Format the package for manual export."""
        return {
            "adapter": "manual_export",
            "status": "exported",
            "facebook": {
                "post": package.get("facebook_post", ""),
                "hook_variants": package.get("hook_variants", []),
                "cta": package.get("cta_keyword", ""),
            },
            "linkedin": {
                "post": package.get("linkedin_post", ""),
            },
            "cta_flow": package.get("dm_flow", {}),
            "image_prompts": package.get("image_prompts", []),
            "instructions": (
                "Copy the post text to the platform. "
                "Use the CTA keyword in comments. "
                "Generate images from the prompts using fal.ai."
            ),
        }

    async def get_status(self, publish_id: str) -> dict[str, Any]:
        return {
            "adapter": "manual_export",
            "status": "manual_tracking",
            "message": "Track publishing status manually",
        }


class FacebookAdapter(PublishingAdapter):
    """Facebook publishing adapter — stub for v2."""

    async def publish(self, package: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "facebook.would_publish",
            post_length=len(package.get("facebook_post", "")),
        )
        return {
            "adapter": "facebook",
            "status": "not_implemented",
            "message": (
                "Facebook API publishing will be available in v2. "
                "Use manual export for now."
            ),
        }

    async def get_status(self, publish_id: str) -> dict[str, Any]:
        return {"adapter": "facebook", "status": "not_implemented"}


class LinkedInAdapter(PublishingAdapter):
    """LinkedIn publishing adapter — stub for v2."""

    async def publish(self, package: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "linkedin.would_publish",
            post_length=len(package.get("linkedin_post", "")),
        )
        return {
            "adapter": "linkedin",
            "status": "not_implemented",
            "message": (
                "LinkedIn API publishing will be available in v2. "
                "Use manual export for now."
            ),
        }

    async def get_status(self, publish_id: str) -> dict[str, Any]:
        return {"adapter": "linkedin", "status": "not_implemented"}


def get_adapter(platform: str = "manual") -> PublishingAdapter:
    """Get the appropriate publishing adapter."""
    adapters: dict[str, type[PublishingAdapter]] = {
        "manual": ManualExportAdapter,
        "facebook": FacebookAdapter,
        "linkedin": LinkedInAdapter,
    }
    adapter_cls = adapters.get(platform, ManualExportAdapter)
    return adapter_cls()
