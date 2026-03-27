"""Engagement Scorer — ranks posts using visible comments/shares with confidence adjustment."""

from __future__ import annotations

from typing import Any

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent

# Confidence multipliers (PRD Section 12.3)
CONFIDENCE_MULTIPLIERS = {
    "A": 1.00,  # Both comments and shares clearly visible
    "B": 0.75,  # One metric visible or partly readable
    "C": 0.40,  # Cropped, unclear, or low-confidence OCR
}

# Default weights (PRD Section 12.2)
DEFAULT_SHARES_WEIGHT = 3.0
DEFAULT_COMMENTS_WEIGHT = 1.0


@register_agent
class EngagementScorer(AgentBase):
    """Compute engagement scores for post examples. Mostly computation, minimal LLM use."""

    name = "engagement_scorer"
    default_model = "claude-haiku-4-5-20251001"  # Simple numeric computation

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Score and rank post examples."""
        post_examples = context.get("post_examples", [])
        shares_weight = context.get("shares_weight", DEFAULT_SHARES_WEIGHT)
        comments_weight = context.get("comments_weight", DEFAULT_COMMENTS_WEIGHT)

        scored: list[dict[str, Any]] = []
        for post in post_examples:
            shares = post.get("visible_shares") or 0
            comments = post.get("visible_comments") or 0
            confidence = post.get("engagement_confidence", "C")
            multiplier = CONFIDENCE_MULTIPLIERS.get(confidence, 0.40)

            raw_score = (shares * shares_weight) + (comments * comments_weight)
            final_score = raw_score * multiplier

            post["raw_score"] = raw_score
            post["final_score"] = final_score
            post["confidence_multiplier"] = multiplier
            scored.append(post)

        # Sort by final score descending
        scored.sort(key=lambda p: p.get("final_score", 0), reverse=True)

        # Compute per-creator rankings
        creator_rankings: dict[str, list[dict[str, Any]]] = {}
        for post in scored:
            creator = post.get("creator_name", "unknown")
            creator_rankings.setdefault(creator, []).append(post)

        # Compute per-creator stats
        creator_stats: dict[str, dict[str, Any]] = {}
        for creator, posts in creator_rankings.items():
            scores = [p["final_score"] for p in posts]
            creator_stats[creator] = {
                "count": len(posts),
                "avg_score": sum(scores) / len(scores) if scores else 0,
                "max_score": max(scores) if scores else 0,
                "min_score": min(scores) if scores else 0,
            }

        self._report(f"Scored {len(scored)} posts:")
        for i, p in enumerate(scored[:5], 1):
            creator = p.get("creator_name", "unknown")
            score = p.get("final_score", 0)
            confidence = p.get("engagement_confidence", "C")
            hook = p.get("hook_text", "")[:80]
            self._report(f"  {i}. [{score:.1f}pts, conf:{confidence}] {creator}: {hook}")
        if len(scored) > 5:
            self._report(f"  ... and {len(scored) - 5} more posts")
        self._report("Creator stats:")
        for creator, stats in creator_stats.items():
            avg = stats["avg_score"]
            mx = stats["max_score"]
            self._report(f"  {creator}: {stats['count']} posts, avg {avg:.1f}, max {mx:.1f}")

        return {
            "scored_examples": scored,
            "creator_rankings": {
                k: [p.get("post_text_raw", "")[:100] for p in v[:5]]
                for k, v in creator_rankings.items()
            },
            "creator_stats": creator_stats,
            "global_top_5": [
                {
                    "creator": p.get("creator_name"),
                    "score": p["final_score"],
                    "hook": p.get("hook_text", "")[:80],
                }
                for p in scored[:5]
            ],
        }
