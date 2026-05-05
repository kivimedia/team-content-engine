"""Competitor velocity tracker — peer-acceleration is the cleanest viral signal.

Polls each tracked creator's YouTube channel every 6h, snapshots their recent
posts' view/like/comment counts, and computes the per-snapshot delta. trend_scout
reads the most accelerating posts and surfaces them as high-priority trends.

Quota plan (YouTube Data API v3 default = 10,000 units/day):
  channels.list    — 1 unit per creator (cached after first call)
  playlistItems    — 1 unit per creator per poll
  videos.list      — 1 unit per batch (≤ 50 video ids)
  ≈ 3 units per creator per poll. 5 creators × 4 polls/day = 60 units/day.

Why this beats the generic YouTube demand layer (#6):
  - The generic layer searches by query + sorts by viewCount, so it surfaces
    "popular videos in this niche overall" — biased toward old uploads with
    massive cumulative views.
  - This service measures *acceleration* (delta_views_per_hour) on a tight
    competitor set. A peer's video gaining 100k views in 6 hours is a stronger
    "hot right now" signal than any total-views ranking.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.competitor_post_snapshot import CompetitorPostSnapshot
from tce.models.creator_profile import CreatorProfile
from tce.services.youtube_demand import YT_BASE
from tce.settings import settings

logger = structlog.get_logger()

PLATFORM_YOUTUBE = "youtube"


class CompetitorVelocityService:
    """Polls competitor channels and computes intra-snapshot view velocity."""

    def __init__(self, db: AsyncSession, api_key: str | None = None) -> None:
        self.db = db
        self.api_key = api_key or settings.youtube_api_key
        # In-process cache: channel_id -> uploads playlist id. Survives the
        # life of a single poll batch; we don't persist it because YouTube's
        # uploads playlist id is deterministic from the channel id.
        self._uploads_playlist_cache: dict[str, str] = {}

    # ----- YouTube API helpers --------------------------------------------

    async def _get_uploads_playlist(self, channel_id: str) -> str | None:
        """Resolve channel_id → uploads playlist id (1 quota unit, cached)."""
        if channel_id in self._uploads_playlist_cache:
            return self._uploads_playlist_cache[channel_id]
        params = {"part": "contentDetails", "id": channel_id, "key": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{YT_BASE}/channels", params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.exception("competitor_velocity.channels_failed", channel=channel_id)
            return None
        items = data.get("items", [])
        if not items:
            return None
        playlist_id = (
            items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        )
        if playlist_id:
            self._uploads_playlist_cache[channel_id] = playlist_id
        return playlist_id

    async def _get_recent_video_ids(
        self, uploads_playlist_id: str, max_results: int = 20
    ) -> list[str]:
        """Pull most recent video IDs from the uploads playlist (1 quota unit)."""
        params = {
            "part": "contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": min(max_results, 50),
            "key": self.api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{YT_BASE}/playlistItems", params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.exception("competitor_velocity.playlist_failed")
            return []
        return [
            item.get("contentDetails", {}).get("videoId", "")
            for item in data.get("items", [])
            if item.get("contentDetails", {}).get("videoId")
        ]

    async def _fetch_video_stats(self, video_ids: list[str]) -> list[dict[str, Any]]:
        """Batch-fetch statistics + snippet (1 quota unit per ≤50 IDs)."""
        if not video_ids:
            return []
        out: list[dict[str, Any]] = []
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
                logger.exception("competitor_velocity.videos_failed")
                continue
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                out.append(
                    {
                        "video_id": item.get("id", ""),
                        "title": snippet.get("title", ""),
                        "published_at": snippet.get("publishedAt"),
                        "views": int(stats.get("viewCount", 0) or 0),
                        "likes": int(stats.get("likeCount", 0) or 0),
                        "comments": int(stats.get("commentCount", 0) or 0),
                    }
                )
        return out

    # ----- Snapshot persistence -------------------------------------------

    async def _prior_snapshot(
        self, post_id: str, before: datetime
    ) -> CompetitorPostSnapshot | None:
        """Most recent snapshot of `post_id` strictly before `before`."""
        result = await self.db.execute(
            select(CompetitorPostSnapshot)
            .where(CompetitorPostSnapshot.post_id == post_id)
            .where(CompetitorPostSnapshot.captured_at < before)
            .order_by(desc(CompetitorPostSnapshot.captured_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _record_snapshot(
        self,
        creator: CreatorProfile,
        video: dict[str, Any],
        captured_at: datetime,
    ) -> CompetitorPostSnapshot:
        """Insert a snapshot, computing delta vs the previous snapshot of this post."""
        prior = await self._prior_snapshot(video["video_id"], before=captured_at)
        delta_views = None
        delta_hours = None
        delta_vph = None
        if prior is not None:
            delta_views = max(0, int(video["views"]) - int(prior.views))
            delta_hours = max(
                (captured_at - prior.captured_at).total_seconds() / 3600.0, 0.5
            )
            delta_vph = round(delta_views / delta_hours, 2)

        published_at = None
        raw_pub = video.get("published_at")
        if raw_pub:
            try:
                # Strip timezone — DB column is naive. We treat all timestamps as UTC.
                published_at = datetime.fromisoformat(raw_pub.replace("Z", "+00:00"))
                published_at = published_at.astimezone(UTC).replace(tzinfo=None)
            except (ValueError, TypeError):
                published_at = None

        snap = CompetitorPostSnapshot(
            creator_id=creator.id,
            workspace_id=creator.workspace_id,
            platform=PLATFORM_YOUTUBE,
            post_id=video["video_id"],
            post_url=f"https://www.youtube.com/watch?v={video['video_id']}",
            title=video.get("title"),
            published_at=published_at,
            captured_at=captured_at,
            views=int(video["views"]),
            likes=int(video["likes"]),
            comments=int(video["comments"]),
            delta_views=delta_views,
            delta_hours=delta_hours,
            delta_views_per_hour=delta_vph,
        )
        self.db.add(snap)
        return snap

    # ----- Public API -----------------------------------------------------

    async def poll_creator(
        self, creator: CreatorProfile, max_videos: int = 20
    ) -> int:
        """Snapshot the top N most recent uploads for one creator. Returns count written."""
        if not self.api_key or not creator.youtube_channel_id:
            return 0
        playlist_id = await self._get_uploads_playlist(creator.youtube_channel_id)
        if not playlist_id:
            return 0
        video_ids = await self._get_recent_video_ids(playlist_id, max_results=max_videos)
        if not video_ids:
            return 0
        videos = await self._fetch_video_stats(video_ids)
        captured_at = datetime.now(UTC).replace(tzinfo=None)
        written = 0
        for v in videos:
            await self._record_snapshot(creator, v, captured_at)
            written += 1
        return written

    async def poll_all_creators(self, max_videos_per_creator: int = 20) -> dict[str, int]:
        """Poll every creator with a youtube_channel_id set."""
        if not self.api_key:
            logger.info("competitor_velocity.no_api_key")
            return {}
        result = await self.db.execute(
            select(CreatorProfile).where(CreatorProfile.youtube_channel_id.is_not(None))
        )
        creators = list(result.scalars().all())
        out: dict[str, int] = {}
        for creator in creators:
            try:
                written = await self.poll_creator(creator, max_videos=max_videos_per_creator)
                out[creator.creator_name] = written
            except Exception:
                logger.exception(
                    "competitor_velocity.creator_failed", creator=creator.creator_name
                )
                out[creator.creator_name] = 0
        await self.db.commit()
        return out

    async def get_accelerating_posts(
        self,
        hours_back: int = 24,
        top_n: int = 10,
        min_delta_views: int = 100,
    ) -> list[dict[str, Any]]:
        """Latest snapshot per post within the lookback window, ranked by delta_views_per_hour.

        Skips posts with very low absolute deltas (default 100 views) to keep low-traffic
        videos from cluttering the signal.
        """
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours_back)
        result = await self.db.execute(
            select(CompetitorPostSnapshot, CreatorProfile.creator_name)
            .join(CreatorProfile, CreatorProfile.id == CompetitorPostSnapshot.creator_id)
            .where(CompetitorPostSnapshot.captured_at >= cutoff)
            .where(CompetitorPostSnapshot.delta_views_per_hour.is_not(None))
        )
        rows = result.all()

        # Keep only the most recent snapshot per post_id within the window — earlier
        # snapshots in the window are just stepping stones for the latest delta.
        latest_by_post: dict[str, tuple[CompetitorPostSnapshot, str]] = {}
        for snap, name in rows:
            existing = latest_by_post.get(snap.post_id)
            if existing is None or snap.captured_at > existing[0].captured_at:
                latest_by_post[snap.post_id] = (snap, name)

        candidates = [
            (s, name)
            for s, name in latest_by_post.values()
            if (s.delta_views or 0) >= min_delta_views
        ]
        candidates.sort(key=lambda x: x[0].delta_views_per_hour or 0, reverse=True)
        return [
            {
                "creator_name": name,
                "title": s.title,
                "url": s.post_url,
                "published_at": s.published_at.isoformat() if s.published_at else None,
                "views": s.views,
                "likes": s.likes,
                "comments": s.comments,
                "delta_views": s.delta_views,
                "delta_hours": s.delta_hours,
                "delta_views_per_hour": s.delta_views_per_hour,
            }
            for s, name in candidates[:top_n]
        ]
