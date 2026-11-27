"""The trending video studio inside the hook studio (T-25711).

Once a day at most (or when he asks again), TCE looks up this week's most watched
short videos in his field on YouTube and ranks them by views per hour. Each one is
listed with its title, channel, views and a link. "Consider as a hook" puts it on
the hook library's list of new hooks to prove: a hook joins the library only after
its proof clip renders on one of his own takes, as the first ten did.

What it does not do, said on the page too: TCE reads the title and the numbers, not
the picture, so it does not claim which visual opening a video uses.

Without a YouTube key (TCE's settings, or one of the key files its settings name)
it says so and looks up nothing. A key YouTube turns down is said as that, not as the
day's allowance.
"""

from __future__ import annotations

import uuid
from pathlib import Path
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


KEY_NAMES = ("TCE_YOUTUBE_API_KEY", "YOUTUBE_API_KEY")
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"}


def youtube_key() -> str:
    """TCE's own key first, then the first key file that holds one. Never logged."""
    if settings.youtube_api_key:
        return settings.youtube_api_key
    for name in (settings.youtube_key_files or "").split(","):
        name = name.strip()
        if not name:
            continue
        try:
            lines = Path(name).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        found = {}
        for line in lines:
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].lstrip()
            k, sep, v = line.partition("=")
            if sep and k.strip() in KEY_NAMES:
                v = v.strip().strip('"').strip("'")
                if v:
                    found.setdefault(k.strip(), v)
        for k in KEY_NAMES:
            if found.get(k):
                return found[k]
    return ""


def _reason(exc: Exception) -> str:
    """YouTube's own reason word for a refusal (quotaExceeded, keyInvalid, ...)."""
    resp = getattr(exc, "response", None)
    try:
        return str(resp.json()["error"]["errors"][0]["reason"])
    except Exception:  # noqa: BLE001 - no body, not JSON, other shape
        return ""


async def _search_shorts(key: str, query: str, days: int = 7) -> list[str]:
    params = {
        "part": "snippet", "type": "video", "videoDuration": "short", "order": "viewCount",
        "publishedAfter": (_now() - timedelta(days=days)).isoformat(timespec="seconds"),
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
    key = youtube_key()
    if not key:
        return _page(ws, {"state": "no_key", "videos": saved.get("videos") or [], "at": saved.get("at")})
    found: dict[str, str] = {}
    failed = 0
    refused = 0
    for query in QUERIES:
        try:
            for vid in await _search_shorts(key, query):
                found.setdefault(vid, query)
        except Exception as exc:  # the rest of the queries still count
            failed += 1
            reason = _reason(exc)
            if reason and reason not in QUOTA_REASONS:
                refused += 1
            logger.info("hooks.trending_search_failed", query=query, error=type(exc).__name__, reason=reason)
            if refused:
                break  # a key YouTube turns down is turned down for every query
    if not found:
        state = "refused" if refused else ("quota" if failed else "none")
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
        "refused": "YouTube did not accept the key TCE uses, so nothing was looked up.",
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


# T-25834: real videos in a trend format, as its examples. A format lives longer than a
# week's news, so the look goes back FORMAT_DAYS; one query (100 units), on tap, 20 h cache.
FORMAT_DAYS = 45
FORMAT_SHOW = 6


async def format_examples(ws: uuid.UUID, format_id: str, *, again: bool = False) -> dict[str, Any]:
    """The most watched recent short videos in this format, from the saved list when fresh."""
    from tce.hooks import format_library
    from tce.hooks.formats import BY_ID

    fmt = BY_ID.get(format_id)
    if fmt is None:
        raise library.HookError("unknown_format", "That format is not in the studio.", status=404)
    saved = (library.read_store(ws).get("format_examples") or {}).get(format_id) or {}
    if saved.get("at") and not again:
        try:
            if _now() - datetime.fromisoformat(saved["at"]) < FRESH_FOR:
                return _examples_page(fmt, saved)
        except ValueError:
            pass
    key = youtube_key()
    if not key:
        return _examples_page(fmt, {"state": "no_key", "videos": saved.get("videos") or [], "at": saved.get("at")})
    try:
        ids = await _search_shorts(key, fmt.example_query, days=FORMAT_DAYS)
    except Exception as exc:  # said plainly; the saved list stays
        reason = _reason(exc)
        logger.info("hooks.format_examples_failed", format=format_id, error=type(exc).__name__, reason=reason)
        state = "refused" if reason and reason not in QUOTA_REASONS else "quota"
        return _examples_page(fmt, {"state": state, "videos": saved.get("videos") or [], "at": saved.get("at")})
    if not ids:
        return _examples_page(fmt, {"state": "none", "videos": saved.get("videos") or [], "at": saved.get("at")})
    stats = await YouTubeDemandService(api_key=key).fetch_video_stats(ids)
    stats.sort(key=lambda v: v.get("views", 0), reverse=True)
    videos = [
        {
            "video_id": v["video_id"], "title": v.get("title", ""), "channel": v.get("channel", ""),
            "url": f"https://www.youtube.com/shorts/{v['video_id']}", "views": v.get("views", 0),
            "hours_old": v.get("hours_old"),
        }
        for v in stats[:FORMAT_SHOW]
    ]
    fresh = {"state": "ok", "videos": videos, "at": _now().isoformat(timespec="seconds")}
    await format_library.save_examples(ws, format_id, fresh)
    return _examples_page(fmt, fresh)


def _examples_page(fmt: Any, found: dict[str, Any]) -> dict[str, Any]:
    state = found.get("state") or ("ok" if found.get("videos") else "none")
    count = len(found.get("videos") or [])
    said = {
        "ok": f"{count} short videos in this format, the most watched of the last {FORMAT_DAYS} days.",
        "no_key": "TCE has no YouTube key yet, so it cannot look up examples.",
        "quota": "YouTube refused the lookup (the free daily allowance is used up). Try again tomorrow.",
        "refused": "YouTube did not accept the key TCE uses, so nothing was looked up.",
        "none": f"YouTube found no short videos in this format in the last {FORMAT_DAYS} days.",
    }[state]
    return {
        "format_id": fmt.id, "state": state, "said": said, "at": found.get("at"),
        "videos": found.get("videos") or [],
        "note": "Found by searching YouTube for the format's words. TCE reads titles and numbers, not the picture.",
    }
