"""Tests for YouTubeDemandService — parsing and demand normalization.

Network calls are not exercised here; we test the pure parsing + ranking
logic on synthetic API responses.
"""

from __future__ import annotations

import time
import types
from datetime import UTC, datetime, timedelta

import pytest

from tce.services.youtube_demand import DEFAULT_QUERIES, YouTubeDemandService


def _video_item(video_id: str, views: int, likes: int, comments: int, hours_ago: float) -> dict:
    published_at = (
        datetime.now(UTC) - timedelta(hours=hours_ago)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "id": video_id,
        "snippet": {
            "title": f"Title for {video_id}",
            "channelTitle": f"Channel-{video_id}",
            "publishedAt": published_at,
        },
        "statistics": {
            "viewCount": str(views),
            "likeCount": str(likes),
            "commentCount": str(comments),
        },
    }


def test_default_queries_present():
    assert "general" in DEFAULT_QUERIES
    assert "coaching" in DEFAULT_QUERIES
    assert all(isinstance(q, str) and q for q in DEFAULT_QUERIES["general"])


def test_parse_videos_computes_velocity_and_engagement():
    data = {
        "items": [
            _video_item("vid1", views=100_000, likes=5_000, comments=500, hours_ago=10),
        ]
    }
    parsed = YouTubeDemandService._parse_videos(data)
    assert len(parsed) == 1
    p = parsed[0]
    assert p["video_id"] == "vid1"
    assert p["views"] == 100_000
    assert 9.5 <= p["hours_old"] <= 10.5
    # 100k views / 10h = 10k v/h
    assert 9_900 <= p["views_per_hour"] <= 10_100
    # engagement = (500*5 + 5000) / 10 = 7500/10 = 750
    assert 740 <= p["engagement_per_hour"] <= 760
    assert p["url"] == "https://www.youtube.com/watch?v=vid1"


def test_parse_videos_skips_missing_published_at():
    data = {
        "items": [
            {"id": "vid-no-date", "snippet": {"title": "x"}, "statistics": {"viewCount": "100"}},
            _video_item("vid-ok", views=100, likes=0, comments=0, hours_ago=5),
        ]
    }
    parsed = YouTubeDemandService._parse_videos(data)
    assert len(parsed) == 1
    assert parsed[0]["video_id"] == "vid-ok"


def test_parse_videos_clamps_brand_new():
    """Videos posted seconds ago shouldn't divide by tiny numbers."""
    data = {"items": [_video_item("brand-new", views=1000, likes=10, comments=0, hours_ago=0.01)]}
    parsed = YouTubeDemandService._parse_videos(data)
    assert parsed[0]["hours_old"] == 0.5


def test_parse_videos_handles_missing_stats():
    """Some videos disable likes/comments; service should not crash."""
    data = {
        "items": [
            {
                "id": "no-stats",
                "snippet": {
                    "title": "x",
                    "channelTitle": "y",
                    "publishedAt": (
                        datetime.now(UTC) - timedelta(hours=2)
                    ).isoformat(timespec="seconds").replace("+00:00", "Z"),
                },
                "statistics": {},
            }
        ]
    }
    parsed = YouTubeDemandService._parse_videos(data)
    assert len(parsed) == 1
    assert parsed[0]["views"] == 0
    assert parsed[0]["demand_raw"] == 0


@pytest.mark.asyncio
async def test_search_videos_returns_empty_without_api_key():
    svc = YouTubeDemandService(api_key="")
    result = await svc.search_videos("anything")
    assert result == []


@pytest.mark.asyncio
async def test_fetch_video_stats_returns_empty_without_api_key():
    svc = YouTubeDemandService(api_key="")
    result = await svc.fetch_video_stats(["vid1", "vid2"])
    assert result == []


@pytest.mark.asyncio
async def test_fetch_demand_signals_normalizes_to_1_to_10():
    svc = YouTubeDemandService(api_key="fake-key")

    async def fake_search(self, query, days_back=7, max_results=25):
        # Return one ID per query, deterministic across calls
        return [f"vid-{query[:5]}-{i}" for i in range(3)]

    async def fake_stats(self, video_ids):
        # Build a synthetic distribution of demand_raw values
        return [
            {
                "video_id": vid,
                "title": f"Title-{vid}",
                "channel": "ch",
                "url": f"https://www.youtube.com/watch?v={vid}",
                "views": 1000 * (i + 1),
                "likes": 50 * (i + 1),
                "comments": 5 * (i + 1),
                "hours_old": 5.0,
                "views_per_hour": 200.0 * (i + 1),
                "engagement_per_hour": 10.0 * (i + 1),
                "demand_raw": float(100 * (i + 1)),
            }
            for i, vid in enumerate(video_ids)
        ]

    svc.search_videos = types.MethodType(fake_search, svc)
    svc.fetch_video_stats = types.MethodType(fake_stats, svc)

    out = await svc.fetch_demand_signals(["q1", "q2"], per_query=3, max_total=10)
    assert len(out) > 0
    assert all(1.0 <= v["demand_velocity"] <= 10.0 for v in out)
    # Sorted descending by demand_velocity
    for earlier, later in zip(out, out[1:]):
        assert earlier["demand_velocity"] >= later["demand_velocity"]
    # Top entry hits the 10.0 ceiling
    assert out[0]["demand_velocity"] == 10.0


@pytest.mark.asyncio
async def test_fetch_demand_signals_dedupes_video_ids():
    svc = YouTubeDemandService(api_key="fake-key")
    seen_ids: list[list[str]] = []

    async def fake_search(self, query, days_back=7, max_results=25):
        # Return overlapping IDs across queries
        return ["dup-1", "dup-2"]

    async def fake_stats(self, video_ids):
        seen_ids.append(list(video_ids))
        # Return one stats record per ID
        now = time.time()
        return [
            {
                "video_id": vid,
                "title": vid,
                "channel": "ch",
                "url": "",
                "views": 100,
                "likes": 0,
                "comments": 0,
                "hours_old": 1.0,
                "views_per_hour": 100.0,
                "engagement_per_hour": 0.0,
                "demand_raw": 100.0,
                "_now": now,
            }
            for vid in video_ids
        ]

    svc.search_videos = types.MethodType(fake_search, svc)
    svc.fetch_video_stats = types.MethodType(fake_stats, svc)

    out = await svc.fetch_demand_signals(["q1", "q2", "q3"], per_query=2, max_total=10)
    # Even with 3 queries returning the same 2 IDs each, stats was called with deduped IDs
    assert len(seen_ids) == 1
    assert sorted(seen_ids[0]) == ["dup-1", "dup-2"]
    assert len(out) == 2


@pytest.mark.asyncio
async def test_fetch_demand_signals_returns_empty_without_api_key():
    svc = YouTubeDemandService(api_key="")
    out = await svc.fetch_demand_signals(["any"])
    assert out == []
