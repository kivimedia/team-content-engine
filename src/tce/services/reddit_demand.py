"""Reddit demand-signal service — leading indicator of viral topic demand.

Reddit's `comments_per_hour` is a stronger viral predictor than upvote velocity
because comments require active engagement (passive upvotes are cheap). Posts
trending on niche subreddits often surface 12-48h before mainstream news pickup,
which is the window we want trend_scout to catch.

Public Reddit JSON endpoints don't require auth; only a polite User-Agent.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

REDDIT_BASE = "https://www.reddit.com"
USER_AGENT = "team-content-engine/1.0 (viral-trend-discovery)"

# Subreddit defaults per niche, mirroring the source_queries logic in trend_scout.
# Workspaces override via WorkspaceTrendFocus.queries["subreddits"].
DEFAULT_SUBREDDITS: dict[str, list[str]] = {
    "coaching": [
        "coaching",
        "Entrepreneur",
        "smallbusiness",
        "solopreneur",
        "Marketing",
        "OnlineBusiness",
    ],
    "general": [
        "singularity",
        "ChatGPT",
        "ClaudeAI",
        "OpenAI",
        "LocalLLaMA",
        "MachineLearning",
        "AI_Agents",
        "LangChain",
    ],
}


class RedditDemandService:
    """Fetches recent posts from subreddits and ranks by engagement velocity."""

    def __init__(self, user_agent: str = USER_AGENT) -> None:
        self.user_agent = user_agent

    async def fetch_subreddit(
        self,
        subreddit: str,
        listing: str = "top",
        time_filter: str = "day",
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Fetch posts from /r/<subreddit>/<listing>.json with velocity metrics.

        Args:
            subreddit: Subreddit name without the leading /r/.
            listing: 'hot', 'new', 'top', or 'rising'.
            time_filter: For 'top' — 'hour', 'day', 'week', 'month'.
            limit: Up to 100 (Reddit cap).
        """
        url = f"{REDDIT_BASE}/r/{subreddit}/{listing}.json"
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if listing == "top":
            params["t"] = time_filter

        try:
            async with httpx.AsyncClient(
                timeout=10,
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.exception("reddit.fetch_failed", subreddit=subreddit, listing=listing)
            return []

        return self._parse_listing(data, subreddit)

    @staticmethod
    def _parse_listing(data: dict[str, Any], subreddit: str) -> list[dict[str, Any]]:
        now = time.time()
        posts: list[dict[str, Any]] = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            created = float(d.get("created_utc", now))
            # Floor at 30 minutes to keep brand-new posts from infinite velocity.
            hours_old = max((now - created) / 3600.0, 0.5)
            score = float(d.get("score", 0))
            comments = float(d.get("num_comments", 0))
            comments_per_hour = comments / hours_old
            score_velocity = score / hours_old
            # Comments weighted heavier than upvotes — engagement > passive approval.
            demand_raw = (comments_per_hour * 0.6) + (score_velocity * 0.4)

            posts.append(
                {
                    "subreddit": subreddit,
                    "title": d.get("title", ""),
                    "selftext": (d.get("selftext", "") or "")[:500],
                    "url": d.get("url", ""),
                    "permalink": f"{REDDIT_BASE}{d.get('permalink', '')}",
                    "score": int(score),
                    "num_comments": int(comments),
                    "hours_old": round(hours_old, 1),
                    "comments_per_hour": round(comments_per_hour, 2),
                    "score_velocity": round(score_velocity, 2),
                    "demand_raw": round(demand_raw, 2),
                }
            )
        return posts

    async def fetch_demand_signals(
        self,
        subreddits: list[str],
        per_subreddit: int = 15,
        max_total: int = 30,
    ) -> list[dict[str, Any]]:
        """Pull top-of-day posts from each subreddit, rank by demand velocity, return top N.

        Each post gets a `demand_velocity` 1-10 score, normalized against the 95th
        percentile of `demand_raw` so a single explosive post doesn't compress the
        rest of the distribution to ~1.
        """
        all_posts: list[dict[str, Any]] = []
        for sub in subreddits:
            posts = await self.fetch_subreddit(
                sub, listing="top", time_filter="day", limit=per_subreddit
            )
            all_posts.extend(posts)

        if not all_posts:
            return []

        sorted_demand = sorted(p["demand_raw"] for p in all_posts)
        idx_95 = max(0, int(len(sorted_demand) * 0.95) - 1)
        cap = max(sorted_demand[idx_95], 1.0)
        for p in all_posts:
            normalized = min(p["demand_raw"], cap) / cap
            p["demand_velocity"] = round(1 + normalized * 9, 1)

        all_posts.sort(key=lambda p: p["demand_velocity"], reverse=True)
        return all_posts[:max_total]
