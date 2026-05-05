"""YouTube Data API v3 demand signals — viral video supply leads written news.

Pattern mirrors RedditDemandService: pull recent videos in niche queries,
compute view-velocity, normalize to 1-10 demand_velocity, hand to trend_scout.

Why YouTube matters separately from Reddit/news:
- Video creators move on AI/tech topics 24-72h *after* a launch but their
  view-velocity is the cleanest "audience interest" signal we can measure
  (paid attention vs. drive-by upvote).
- Hook patterns lifted from high-velocity videos are the richest input we
  have to pattern_miner — titles + thumbnails are the tightest hooks online.

Quota notes:
- search.list costs 100 units/call; videos.list costs 1 unit/call.
- Default daily quota = 10000, so 6 search queries + 1 batch videos.list = 601
  units per run. ~16 runs/day on default quota.
- This service silently degrades on quota errors so the rest of trend_scout
  keeps working.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from tce.settings import settings

logger = structlog.get_logger()

YT_BASE = "https://www.googleapis.com/youtube/v3"

# Niche query lists — mirror the source/topical query split in trend_scout.
# Workspaces override via WorkspaceTrendFocus.queries["youtube_queries"].
DEFAULT_QUERIES: dict[str, list[str]] = {
    "coaching": [
        "AI for coaches",
        "coaching business automation",
        "build coaching business AI",
        "AI tools solopreneur",
        "online coaching scale",
        "coaching content marketing AI",
    ],
    "general": [
        "Claude AI agents",
        "Cursor coding agent",
        "AI agents production",
        "Claude Code workflow",
        "GPT-5 vs Claude",
        "vibe coding tutorial",
        "AI startup MVP",
        "LangGraph LangChain agents",
    ],
}


class YouTubeDemandService:
    """Fetches recent niche videos and ranks by view velocity."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.youtube_api_key

    async def search_videos(
        self,
        query: str,
        days_back: int = 7,
        max_results: int = 25,
    ) -> list[str]:
        """Return video IDs matching `query` published in the last `days_back` days.

        Sorted by viewCount descending so we surface viral candidates first.
        """
        if not self.api_key:
            return []
        published_after = (datetime.now(UTC) - timedelta(days=days_back)).isoformat(
            timespec="seconds"
        )
        params = {
            "part": "snippet",
            "type": "video",
            "order": "viewCount",
            "publishedAfter": published_after,
            "q": query,
            "maxResults": min(max_results, 50),
            "key": self.api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{YT_BASE}/search", params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            # 403 typically = quota exceeded; degrade silently and let other
            # signals (Reddit, Brave) carry the trend brief.
            logger.warning("youtube.search_failed", status=e.response.status_code, query=query)
            return []
        except Exception:
            logger.exception("youtube.search_error", query=query)
            return []

        return [
            item["id"]["videoId"]
            for item in data.get("items", [])
            if item.get("id", {}).get("videoId")
        ]

    async def fetch_video_stats(self, video_ids: list[str]) -> list[dict[str, Any]]:
        """Batch-fetch statistics + snippet for video IDs (1 quota unit/call).

        YouTube allows up to 50 IDs per call; we batch to stay under that.
        """
        if not self.api_key or not video_ids:
            return []
        results: list[dict[str, Any]] = []
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i : i + 50]
            params = {
                "part": "statistics,snippet",
                "id": ",".join(chunk),
                "key": self.api_key,
            }
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(f"{YT_BASE}/videos", params=params)
                    resp.raise_for_status()
                    data = resp.json()
            except Exception:
                logger.exception("youtube.videos_error")
                continue
            results.extend(self._parse_videos(data))
        return results

    @staticmethod
    def _parse_videos(data: dict[str, Any]) -> list[dict[str, Any]]:
        now = time.time()
        out: list[dict[str, Any]] = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            published_at = snippet.get("publishedAt")
            if not published_at:
                continue
            try:
                published_ts = datetime.fromisoformat(
                    published_at.replace("Z", "+00:00")
                ).timestamp()
            except (ValueError, TypeError):
                continue
            hours_old = max((now - published_ts) / 3600.0, 0.5)
            views = float(stats.get("viewCount", 0) or 0)
            likes = float(stats.get("likeCount", 0) or 0)
            comments = float(stats.get("commentCount", 0) or 0)
            views_per_hour = views / hours_old
            # Comments/likes weighted heavily relative to passive views, same
            # philosophy as Reddit: engagement > drive-by attention.
            engagement_per_hour = (comments * 5.0 + likes) / hours_old
            demand_raw = (views_per_hour * 0.5) + (engagement_per_hour * 50.0)
            out.append(
                {
                    "video_id": item.get("id", ""),
                    "title": snippet.get("title", ""),
                    "channel": snippet.get("channelTitle", ""),
                    "url": f"https://www.youtube.com/watch?v={item.get('id', '')}",
                    "views": int(views),
                    "likes": int(likes),
                    "comments": int(comments),
                    "hours_old": round(hours_old, 1),
                    "views_per_hour": round(views_per_hour, 2),
                    "engagement_per_hour": round(engagement_per_hour, 2),
                    "demand_raw": round(demand_raw, 2),
                }
            )
        return out

    async def fetch_demand_signals(
        self,
        queries: list[str],
        days_back: int = 7,
        per_query: int = 10,
        max_total: int = 20,
    ) -> list[dict[str, Any]]:
        """Search queries, batch-fetch stats, normalize demand_velocity 1-10.

        Same 95th-percentile cap as RedditDemandService so a single mega-viral
        video doesn't compress the rest of the distribution to ~1.
        """
        if not self.api_key:
            return []
        all_ids: list[str] = []
        for q in queries:
            ids = await self.search_videos(q, days_back=days_back, max_results=per_query)
            all_ids.extend(ids)
        # Dedupe — same video can hit multiple queries
        seen: set[str] = set()
        unique_ids = [i for i in all_ids if not (i in seen or seen.add(i))]
        if not unique_ids:
            return []
        videos = await self.fetch_video_stats(unique_ids)
        if not videos:
            return []
        sorted_demand = sorted(v["demand_raw"] for v in videos)
        idx_95 = max(0, int(len(sorted_demand) * 0.95) - 1)
        cap = max(sorted_demand[idx_95], 1.0)
        for v in videos:
            normalized = min(v["demand_raw"], cap) / cap
            v["demand_velocity"] = round(1 + normalized * 9, 1)
        videos.sort(key=lambda v: v["demand_velocity"], reverse=True)
        return videos[:max_total]
