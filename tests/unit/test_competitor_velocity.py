"""Tests for CompetitorVelocityService — snapshot delta computation + ranking.

The DB session is mocked. We don't validate ORM execution against a real engine
because Postgres-only types (JSONB, ARRAY) sit in unrelated models that SQLAlchemy
would still try to compile under in-memory SQLite. That's brittle test infra,
not a real signal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tce.services.competitor_velocity import (
    PLATFORM_YOUTUBE,
    CompetitorVelocityService,
)


def _creator(channel_id: str | None = "UC123", name: str = "TestCreator"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        creator_name=name,
        youtube_channel_id=channel_id,
        workspace_id=None,
    )


_UNSET = object()


def _mock_db(prior_snapshot=_UNSET, accelerating_rows=_UNSET, creators_rows=_UNSET):
    """Mock AsyncSession with controllable execute() returns by call order.

    Pass _UNSET (the default) to skip queuing that result — the caller's
    method shouldn't issue that DB call. Pass an explicit value (including
    None) to stage a result of that kind.
    """
    db = MagicMock()
    added: list = []
    db.add = MagicMock(side_effect=added.append)
    db.commit = AsyncMock()
    db._added = added

    def make_result(value, kind):
        result = MagicMock()
        if kind == "scalar":
            result.scalar_one_or_none = MagicMock(return_value=value)
        elif kind == "all":
            result.all = MagicMock(return_value=value)
        elif kind == "scalars":
            scalars = MagicMock()
            scalars.all = MagicMock(return_value=value)
            result.scalars = MagicMock(return_value=scalars)
        return result

    queue = []
    if prior_snapshot is not _UNSET:
        queue.append(make_result(prior_snapshot, "scalar"))
    if accelerating_rows is not _UNSET:
        queue.append(make_result(accelerating_rows, "all"))
    if creators_rows is not _UNSET:
        queue.append(make_result(creators_rows, "scalars"))

    async def fake_execute(*args, **kwargs):
        return queue.pop(0) if queue else make_result(None, "scalar")

    db.execute = AsyncMock(side_effect=fake_execute)
    return db


# --- _record_snapshot: delta computation -------------------------------------


@pytest.mark.asyncio
async def test_first_snapshot_has_no_delta():
    """A post's first-ever snapshot — no prior, so delta fields are null."""
    db = _mock_db(prior_snapshot=None)
    svc = CompetitorVelocityService(db, api_key="fake")
    snap = await svc._record_snapshot(
        _creator(),
        {"video_id": "vid1", "title": "First", "published_at": "2026-05-04T10:00:00Z",
         "views": 1000, "likes": 5, "comments": 1},
        captured_at=datetime(2026, 5, 5, 12, 0),
    )
    assert snap.delta_views is None
    assert snap.delta_views_per_hour is None
    assert snap.platform == PLATFORM_YOUTUBE
    assert snap.views == 1000
    assert snap.post_id == "vid1"
    assert len(db._added) == 1


@pytest.mark.asyncio
async def test_second_snapshot_computes_delta():
    """Second snapshot of the same post: delta = current.views - prior.views."""
    prior = SimpleNamespace(
        captured_at=datetime(2026, 5, 5, 0, 0), views=1000
    )
    db = _mock_db(prior_snapshot=prior)
    svc = CompetitorVelocityService(db, api_key="fake")
    snap = await svc._record_snapshot(
        _creator(),
        {"video_id": "vid1", "title": "x", "views": 13_000, "likes": 0, "comments": 0},
        captured_at=datetime(2026, 5, 5, 6, 0),
    )
    assert snap.delta_views == 12_000
    assert snap.delta_hours == 6.0
    assert snap.delta_views_per_hour == 2_000.0


@pytest.mark.asyncio
async def test_delta_views_floors_at_zero():
    """If view count drops (private toggle, etc.), delta is clamped at 0, not negative."""
    prior = SimpleNamespace(captured_at=datetime(2026, 5, 5, 0, 0), views=1000)
    db = _mock_db(prior_snapshot=prior)
    svc = CompetitorVelocityService(db, api_key="fake")
    snap = await svc._record_snapshot(
        _creator(),
        {"video_id": "vid1", "title": "x", "views": 800, "likes": 0, "comments": 0},
        captured_at=datetime(2026, 5, 5, 6, 0),
    )
    assert snap.delta_views == 0
    assert snap.delta_views_per_hour == 0.0


@pytest.mark.asyncio
async def test_delta_hours_floors_at_half_hour():
    """Snapshots taken seconds apart shouldn't divide by ~0 hours."""
    prior = SimpleNamespace(captured_at=datetime(2026, 5, 5, 12, 0, 0), views=100)
    db = _mock_db(prior_snapshot=prior)
    svc = CompetitorVelocityService(db, api_key="fake")
    snap = await svc._record_snapshot(
        _creator(),
        {"video_id": "vid1", "title": "x", "views": 200, "likes": 0, "comments": 0},
        captured_at=datetime(2026, 5, 5, 12, 0, 30),
    )
    assert snap.delta_hours == 0.5


@pytest.mark.asyncio
async def test_published_at_parses_iso_z_format():
    db = _mock_db(prior_snapshot=None)
    svc = CompetitorVelocityService(db, api_key="fake")
    snap = await svc._record_snapshot(
        _creator(),
        {"video_id": "vid1", "title": "x", "published_at": "2026-05-04T10:30:00Z",
         "views": 1, "likes": 0, "comments": 0},
        captured_at=datetime(2026, 5, 5, 12, 0),
    )
    assert snap.published_at == datetime(2026, 5, 4, 10, 30)


@pytest.mark.asyncio
async def test_published_at_invalid_string_is_silently_dropped():
    """Don't crash on garbage publishedAt strings; just leave the column null."""
    db = _mock_db(prior_snapshot=None)
    svc = CompetitorVelocityService(db, api_key="fake")
    snap = await svc._record_snapshot(
        _creator(),
        {"video_id": "vid1", "title": "x", "published_at": "not-a-date",
         "views": 1, "likes": 0, "comments": 0},
        captured_at=datetime(2026, 5, 5, 12, 0),
    )
    assert snap.published_at is None


# --- get_accelerating_posts: ranking + filtering -----------------------------


def _row(post_id, title, captured_at, delta_views, delta_hours, delta_vph,
         creator_name="TestCreator", views=0, likes=0, comments=0,
         published_at=None):
    snap = SimpleNamespace(
        post_id=post_id,
        title=title,
        captured_at=captured_at,
        post_url=f"https://www.youtube.com/watch?v={post_id}",
        published_at=published_at,
        views=views,
        likes=likes,
        comments=comments,
        delta_views=delta_views,
        delta_hours=delta_hours,
        delta_views_per_hour=delta_vph,
    )
    return (snap, creator_name)


@pytest.mark.asyncio
async def test_get_accelerating_posts_sorts_by_delta_velocity():
    rows = [
        _row("slow", "slow", datetime.utcnow() - timedelta(hours=1),
             delta_views=1_000, delta_hours=10.0, delta_vph=100.0),
        _row("fast", "fast", datetime.utcnow() - timedelta(hours=1),
             delta_views=55_000, delta_hours=11.0, delta_vph=5_000.0),
        _row("mid", "mid", datetime.utcnow() - timedelta(hours=1),
             delta_views=11_000, delta_hours=11.0, delta_vph=1_000.0),
    ]
    db = _mock_db(accelerating_rows=rows)
    svc = CompetitorVelocityService(db, api_key="fake")
    out = await svc.get_accelerating_posts(hours_back=24)
    assert [p["title"] for p in out] == ["fast", "mid", "slow"]
    assert out[0]["delta_views_per_hour"] == 5_000.0


@pytest.mark.asyncio
async def test_get_accelerating_posts_filters_low_delta_views():
    rows = [
        _row("tiny", "tiny", datetime.utcnow(), delta_views=20, delta_hours=1.0,
             delta_vph=20.0),
        _row("real", "real", datetime.utcnow(), delta_views=500, delta_hours=1.0,
             delta_vph=500.0),
    ]
    db = _mock_db(accelerating_rows=rows)
    svc = CompetitorVelocityService(db, api_key="fake")
    out = await svc.get_accelerating_posts(min_delta_views=100)
    assert [p["title"] for p in out] == ["real"]


@pytest.mark.asyncio
async def test_get_accelerating_posts_uses_only_latest_snapshot_per_post():
    """Three snapshots for the same post in the window — keep only the latest."""
    earlier = datetime.utcnow() - timedelta(hours=12)
    middle = datetime.utcnow() - timedelta(hours=6)
    latest = datetime.utcnow() - timedelta(hours=1)
    rows = [
        _row("p1", "p", earlier, delta_views=4_000, delta_hours=6.0, delta_vph=666.7),
        _row("p1", "p", middle, delta_views=10_000, delta_hours=6.0, delta_vph=1_666.7),
        _row("p1", "p", latest, delta_views=20_000, delta_hours=5.0, delta_vph=4_000.0),
    ]
    db = _mock_db(accelerating_rows=rows)
    svc = CompetitorVelocityService(db, api_key="fake")
    out = await svc.get_accelerating_posts(hours_back=24)
    assert len(out) == 1
    assert out[0]["delta_views_per_hour"] == 4_000.0
    assert out[0]["delta_views"] == 20_000


@pytest.mark.asyncio
async def test_get_accelerating_posts_empty_returns_empty():
    db = _mock_db(accelerating_rows=[])
    svc = CompetitorVelocityService(db, api_key="fake")
    assert await svc.get_accelerating_posts() == []


# --- poll_creator: short-circuits + orchestration ----------------------------


@pytest.mark.asyncio
async def test_poll_creator_skips_when_no_api_key():
    svc = CompetitorVelocityService(_mock_db(), api_key="")
    written = await svc.poll_creator(_creator())
    assert written == 0


@pytest.mark.asyncio
async def test_poll_creator_skips_when_no_channel_id():
    svc = CompetitorVelocityService(_mock_db(), api_key="fake")
    written = await svc.poll_creator(_creator(channel_id=None))
    assert written == 0


@pytest.mark.asyncio
async def test_poll_creator_writes_one_snapshot_per_video():
    db = _mock_db(prior_snapshot=None)
    # Two videos => two prior_snapshot lookups, both null. Pre-stage them.
    db.execute = AsyncMock(side_effect=[
        # First _record_snapshot's prior lookup
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        # Second _record_snapshot's prior lookup
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
    ])
    svc = CompetitorVelocityService(db, api_key="fake")
    svc._get_uploads_playlist = AsyncMock(return_value="UU123")
    svc._get_recent_video_ids = AsyncMock(return_value=["vidA", "vidB"])
    svc._fetch_video_stats = AsyncMock(return_value=[
        {"video_id": "vidA", "title": "A", "published_at": None,
         "views": 100, "likes": 5, "comments": 1},
        {"video_id": "vidB", "title": "B", "published_at": None,
         "views": 200, "likes": 10, "comments": 2},
    ])
    written = await svc.poll_creator(_creator())
    assert written == 2
    assert {s.post_id for s in db._added} == {"vidA", "vidB"}


@pytest.mark.asyncio
async def test_poll_creator_returns_zero_when_no_uploads_playlist():
    db = _mock_db()
    svc = CompetitorVelocityService(db, api_key="fake")
    svc._get_uploads_playlist = AsyncMock(return_value=None)
    written = await svc.poll_creator(_creator())
    assert written == 0


@pytest.mark.asyncio
async def test_poll_all_creators_skips_when_no_api_key():
    svc = CompetitorVelocityService(_mock_db(), api_key="")
    summary = await svc.poll_all_creators()
    assert summary == {}


@pytest.mark.asyncio
async def test_poll_all_creators_iterates_returned_creators():
    creators = [_creator(name="A", channel_id="UC1"), _creator(name="B", channel_id="UC2")]
    db = _mock_db(creators_rows=creators)
    svc = CompetitorVelocityService(db, api_key="fake")
    seen: list[str] = []

    async def fake_poll_creator(creator, max_videos=20):
        seen.append(creator.creator_name)
        return 3

    svc.poll_creator = fake_poll_creator  # type: ignore[method-assign]
    summary = await svc.poll_all_creators()
    assert seen == ["A", "B"]
    assert summary == {"A": 3, "B": 3}
    db.commit.assert_called_once()
