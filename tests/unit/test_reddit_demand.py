"""Tests for RedditDemandService — listing parsing and demand normalization."""

from __future__ import annotations

import time

import pytest

from tce.services.reddit_demand import DEFAULT_SUBREDDITS, RedditDemandService


def _fake_listing(posts: list[dict]) -> dict:
    """Wrap raw post dicts in Reddit's `data.children[].data` envelope."""
    return {"data": {"children": [{"data": p} for p in posts]}}


def test_default_subreddits_present():
    assert "general" in DEFAULT_SUBREDDITS
    assert "coaching" in DEFAULT_SUBREDDITS
    assert all(isinstance(s, str) and s for s in DEFAULT_SUBREDDITS["general"])


def test_parse_listing_computes_velocity():
    now = time.time()
    listing = _fake_listing(
        [
            {
                "title": "Hot take on AI agents",
                "selftext": "body",
                "url": "https://example.com/a",
                "permalink": "/r/AI_Agents/comments/abc/hot_take/",
                "score": 600,
                "num_comments": 200,
                "created_utc": now - 7200,  # 2 hours ago
            }
        ]
    )

    posts = RedditDemandService._parse_listing(listing, "AI_Agents")

    assert len(posts) == 1
    p = posts[0]
    assert p["subreddit"] == "AI_Agents"
    assert p["score"] == 600
    assert p["num_comments"] == 200
    assert 1.9 <= p["hours_old"] <= 2.1
    # 200 comments / 2h = 100 c/h
    assert 99 <= p["comments_per_hour"] <= 101
    # demand_raw = 100*0.6 + 300*0.4 = 60 + 120 = 180
    assert 178 <= p["demand_raw"] <= 182
    assert p["permalink"].startswith("https://www.reddit.com/r/AI_Agents/")


def test_parse_listing_clamps_brand_new_posts():
    """Posts younger than 30min should be floored to avoid infinite velocity."""
    now = time.time()
    listing = _fake_listing(
        [{"title": "Just posted", "score": 10, "num_comments": 5, "created_utc": now - 60}]
    )
    posts = RedditDemandService._parse_listing(listing, "test")
    assert posts[0]["hours_old"] == 0.5


@pytest.mark.asyncio
async def test_fetch_demand_signals_normalizes_to_1_to_10(monkeypatch):
    """fetch_demand_signals maps raw demand to 1-10 via the 95th-percentile cap."""
    svc = RedditDemandService()

    async def fake_fetch_subreddit(self, subreddit, **kwargs):
        # Return a synthetic distribution per subreddit so we get >= 20 posts total.
        return [
            {
                "subreddit": subreddit,
                "title": f"post-{i}",
                "selftext": "",
                "url": "",
                "permalink": "/x",
                "score": i * 10,
                "num_comments": i * 5,
                "hours_old": 1.0,
                "comments_per_hour": float(i * 5),
                "score_velocity": float(i * 10),
                "demand_raw": float(i * 5 * 0.6 + i * 10 * 0.4),  # = i * 7
            }
            for i in range(1, 11)
        ]

    monkeypatch.setattr(RedditDemandService, "fetch_subreddit", fake_fetch_subreddit)

    out = await svc.fetch_demand_signals(["a", "b"], per_subreddit=10, max_total=15)

    assert len(out) == 15
    # Every post got a normalized 1-10 demand_velocity
    assert all(1.0 <= p["demand_velocity"] <= 10.0 for p in out)
    # Sorted descending
    for earlier, later in zip(out, out[1:]):
        assert earlier["demand_velocity"] >= later["demand_velocity"]
    # Top post must be at the 10.0 ceiling (it was at the 95th percentile cap)
    assert out[0]["demand_velocity"] == 10.0


@pytest.mark.asyncio
async def test_fetch_demand_signals_handles_empty():
    svc = RedditDemandService()

    async def fake_fetch_subreddit(self, subreddit, **kwargs):
        return []

    import types
    svc.fetch_subreddit = types.MethodType(fake_fetch_subreddit, svc)
    out = await svc.fetch_demand_signals(["empty"], per_subreddit=5)
    assert out == []
