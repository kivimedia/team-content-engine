"""Competitor / Source Creator Monitoring (PRD Section 43.4).

Read-only monitoring of source creator activity to detect
overlap and trend signals.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

# PRD Section 49.4: Source creators to monitor
SOURCE_CREATORS = [
    {
        "name": "Omri Barak",
        "platforms": ["facebook", "linkedin"],
        "topics": ["AI news", "tech industry", "startups"],
    },
    {
        "name": "Ben Z. Yabets",
        "platforms": ["facebook", "linkedin"],
        "topics": ["consulting", "positioning", "CTA strategy"],
    },
    {
        "name": "Nathan Savis",
        "platforms": ["facebook"],
        "topics": ["marketing", "creatives", "conversion"],
    },
    {
        "name": "Eden Bibas",
        "platforms": ["facebook", "linkedin"],
        "topics": ["AI tools", "automation", "guides"],
    },
    {
        "name": "Alex Kap",
        "platforms": ["linkedin"],
        "topics": ["strategy", "AI implications", "business"],
    },
]


class CompetitorMonitorService:
    """Monitors source creator activity for overlap detection."""

    def __init__(self) -> None:
        self.alerts: list[dict[str, Any]] = []

    def check_topic_overlap(
        self,
        planned_topic: str,
        creator_posts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Check if a planned topic overlaps with recent creator posts.

        PRD Section H.7: If a source creator publishes on the same topic,
        flag for operator review.
        """
        overlaps = []
        topic_lower = planned_topic.lower()

        for post in creator_posts:
            post_topic = post.get("topic", "").lower()
            creator = post.get("creator_name", "unknown")

            # Simple keyword overlap check
            topic_words = set(topic_lower.split())
            post_words = set(post_topic.split())
            common = topic_words & post_words

            if len(common) >= 2:
                overlaps.append(
                    {
                        "creator": creator,
                        "post_topic": post.get("topic"),
                        "overlap_words": list(common),
                        "recommendation": (
                            "Consider a distinctly different angle or defer this topic."
                        ),
                    }
                )

        return {
            "planned_topic": planned_topic,
            "overlaps_found": len(overlaps),
            "overlaps": overlaps,
            "should_review": len(overlaps) > 0,
        }

    def detect_trend_convergence(self, creator_posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect when multiple creators cover the same topic.

        PRD Section 43.4: If multiple source creators cover the same
        topic, surface it as a potential angle.
        """
        topic_creators: dict[str, list[str]] = {}

        for post in creator_posts:
            topic = post.get("topic", "").lower()
            creator = post.get("creator_name", "")
            for word in topic.split():
                if len(word) > 3:  # Skip short words
                    topic_creators.setdefault(word, []).append(creator)

        convergences = []
        for keyword, creators in topic_creators.items():
            unique_creators = set(creators)
            if len(unique_creators) >= 2:
                convergences.append(
                    {
                        "keyword": keyword,
                        "creators": list(unique_creators),
                        "signal_strength": len(unique_creators),
                        "suggestion": (
                            f"Multiple creators covering '{keyword}' "
                            "— consider as a trending angle."
                        ),
                    }
                )

        return sorted(
            convergences,
            key=lambda x: x["signal_strength"],
            reverse=True,
        )[:5]

    def get_source_creators(self) -> list[dict[str, Any]]:
        """Get the list of monitored source creators."""
        return SOURCE_CREATORS.copy()
