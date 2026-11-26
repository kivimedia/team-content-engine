"""The trending video studio inside the hook studio (T-25711).

Once a day at most (or when he asks again), TCE looks up this week's most watched
short videos in his field on YouTube and ranks them by views per hour. Each one is
listed with its title, channel, views and a link. "Consider as a hook" puts it on
the hook library's list of new hooks to prove: a hook joins the library only after
its proof clip renders on one of his own takes, as the first ten did.

What it does not do, said on the page too: TCE reads the title and the numbers, not
the picture, so it does not claim which visual opening a video uses.

Without a YouTube key in TCE's settings it says so and looks up nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from tce.hooks import library
from tce.services.youtube_demand import DEFAULT_QUERIES, YT_BASE, YouTubeDemandService
from tce.settings import settings

logger = structlog.get_logger()

FRESH_FOR = timedelta(hours=20)
SHOW = 12
QUERIES = tuple(DEFAULT_QUERIES["coaching"])  # 100 quota units each: six a day of 10,000


def _now() -> datetime:
    return datetime.now(UTC)


async def _search_shorts(key: str, query: str) -> list[str]:
    params = {
        "part": "snippet", "type": "video", "videoDuration": "short", "order": "viewCount",
        "publishedAfter": (_now() - timedelta(days=7)).isoformat(timespec="seconds"),
        "q": query, "maxResults": 10, "relevanceLanguage": "en", "key": key,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{YT_BASE}/search", params=params)
        resp.raise_for_status()
        data = resp.json()
    return [i["id"]["videoId"] for i in data.get("items", []) if i.get("id", {}).get("videoId")]


async def look(ws: uuid.UUID, *, again: bool = False) -> dict[str, Any]:
    """This week's trending short videos, from the saved list when it is fresh."""
    saved = library.read_store(ws).get("trending") or {}
    if saved.get("at") and not again:
        try:
            if _now() - datetime.fromisoformat(saved["at"]) < FRESH_FOR:
                return _page(ws, saved)
        except ValueError:
            pass
    key = settings.youtube_api_key
    if not key:
        return _page(ws, {"state": "no_key", "videos": saved.get("videos") or [], "at": saved.get("at")})
    found: dict[str, str] = {}
    failed = 0
    for query in QUERIES:
        try:
            for vid in await _search_shorts(key, query):
                found.setdefault(vid, query)
        except Exception as exc:  # 403 is usually the day's quota; the rest still count
            failed += 1
            logger.info("hooks.trending_search_failed", query=query, error=type(exc).__name__)
    if not found:
        state = "quota" if failed else "none"
        return _page(ws, {"state": state, "videos": saved.get("videos") or [], "at": saved.get("at")})
    stats = await YouTubeDemandService(api_key=key).fetch_video_stats(list(found))
    stats.sort(key=lambda v: v.get("views_per_hour", 0), reverse=True)
    videos = [
        {
            "video_id": v["video_id"], "title": v.get("title", ""), "channel": v.get("channel", ""),
            "url": f"https://www.youtube.com/shorts/{v['video_id']}", "views": v.get("views", 0),
            "views_per_hour": round(v.get("views_per_hour", 0)), "hours_old": v.get("hours_old"),
            "query": found.get(v["video_id"], ""),
        }
        for v in stats[:SHOW]
    ]
    fresh = {"state": "ok", "videos": videos, "at": _now().isoformat(timespec="seconds")}
    await library.save_trending(ws, fresh)
    return _page(ws, fresh)


def _page(ws: uuid.UUID, trending: dict[str, Any]) -> dict[str, Any]:
    proposals = library.read_store(ws).get("proposals") or []
    considered = {p.get("video_id") for p in proposals}
    state = trending.get("state") or ("ok" if trending.get("videos") else "none")
    said = {
        "ok": f"{len(trending.get('videos') or [])} short videos in your field, most watched per hour this week.",
        "no_key": "TCE has no YouTube key yet, so it cannot look up trending videos.",
        "quota": "YouTube refused today's lookups (the free daily allowance is used up). It looks again tomorrow.",
        "none": "YouTube found no short videos in your field this week.",
    }[state]
    return {
        "state": state,
        "said": said,
        "at": trending.get("at"),
        "videos": [{**v, "considered": v.get("video_id") in considered} for v in trending.get("videos") or []],
        "proposals": proposals,
        "note": "TCE reads each video's title and numbers, not its picture, so it does not say which visual opening it uses. "
                "Consider as a hook puts it on the list to prove on one of your takes.",
    }


async def consider(ws: uuid.UUID, video_id: str) -> dict[str, Any]:
    saved = library.read_store(ws).get("trending") or {}
    video = next((v for v in saved.get("videos") or [] if v.get("video_id") == video_id), None)
    if video is None:
        raise library.HookError("not_trending", "That video is not on this week's trending list.", status=404)
    await library.add_proposal(ws, {
        "video_id": video_id, "title": video.get("title", ""), "url": video.get("url", ""),
        "state": "waiting for a proof clip on one of your takes",
    })
    return _page(ws, saved)
