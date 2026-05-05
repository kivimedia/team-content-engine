"""Tests for LearningService.get_template_performance_multipliers — analytics feedback loop.

The method joins LearningEvent ↔ PatternTemplate via PostPackage/StoryBrief,
computes per-family engagement means, and returns multipliers vs. the global
mean. We mock the DB layer so these tests don't need a real Postgres.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tce.services.learning import LearningService


def _event(shares=0, comments=0, dms=0, clicks=0, saves=0, follows=0, joins=0,
           publish_date: date | None = None):
    """Build a LearningEvent stand-in — the service only reads attributes."""
    return SimpleNamespace(
        actual_shares=shares,
        actual_comments=comments,
        actual_dms=dms,
        actual_clicks=clicks,
        actual_saves=saves,
        actual_follows=follows,
        actual_joins=joins,
        publish_date=publish_date or date.today(),
    )


def _mock_db(rows: list[tuple]) -> MagicMock:
    """Make a mock AsyncSession whose execute() returns `rows` from .all()."""
    db = MagicMock()
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_returns_empty_dict_with_no_data():
    svc = LearningService(_mock_db([]))
    out = await svc.get_template_performance_multipliers()
    assert out == {}


@pytest.mark.asyncio
async def test_skips_families_below_min_sample_size():
    """Families with < 3 events shouldn't get a multiplier (noise too high)."""
    rows = [
        # 'big_shift_explainer': 5 events (above threshold)
        (_event(shares=10, comments=20), "big_shift_explainer"),
        (_event(shares=10, comments=20), "big_shift_explainer"),
        (_event(shares=10, comments=20), "big_shift_explainer"),
        (_event(shares=10, comments=20), "big_shift_explainer"),
        (_event(shares=10, comments=20), "big_shift_explainer"),
        # 'weekly_roundup': 2 events (below threshold)
        (_event(shares=5, comments=10), "weekly_roundup"),
        (_event(shares=5, comments=10), "weekly_roundup"),
    ]
    svc = LearningService(_mock_db(rows))
    out = await svc.get_template_performance_multipliers()
    assert "big_shift_explainer" in out
    assert "weekly_roundup" not in out


@pytest.mark.asyncio
async def test_winner_family_gets_multiplier_above_one():
    rows = [
        # winning family: ~3× the cohort mean
        (_event(shares=30, comments=60), "contrarian_diagnosis"),
        (_event(shares=30, comments=60), "contrarian_diagnosis"),
        (_event(shares=30, comments=60), "contrarian_diagnosis"),
        # losing family: well below mean
        (_event(shares=2, comments=4), "weekly_roundup"),
        (_event(shares=2, comments=4), "weekly_roundup"),
        (_event(shares=2, comments=4), "weekly_roundup"),
    ]
    svc = LearningService(_mock_db(rows))
    out = await svc.get_template_performance_multipliers()
    assert out["contrarian_diagnosis"] > 1.0
    assert out["weekly_roundup"] < 1.0


@pytest.mark.asyncio
async def test_multipliers_clamped_to_range():
    """Even with a 50× outlier family, multipliers stay within [0.5, 2.0]."""
    rows = [
        (_event(shares=1000, comments=1000), "outlier_winner"),
        (_event(shares=1000, comments=1000), "outlier_winner"),
        (_event(shares=1000, comments=1000), "outlier_winner"),
        (_event(shares=1, comments=0), "outlier_loser"),
        (_event(shares=1, comments=0), "outlier_loser"),
        (_event(shares=1, comments=0), "outlier_loser"),
    ]
    svc = LearningService(_mock_db(rows))
    out = await svc.get_template_performance_multipliers()
    assert out["outlier_winner"] == 2.0
    assert out["outlier_loser"] == 0.5


@pytest.mark.asyncio
async def test_engagement_score_weights_shares_higher_than_clicks():
    """Same raw count of actions, but shares (weight 3.0) outweigh clicks (weight 0.5)."""
    rows = [
        # 10 shares per event × weight 3.0 = score 30 each → family mean 30
        (_event(shares=10), "shares_family"),
        (_event(shares=10), "shares_family"),
        (_event(shares=10), "shares_family"),
        # 10 clicks per event × weight 0.5 = score 5 each → family mean 5
        (_event(clicks=10), "clicks_family"),
        (_event(clicks=10), "clicks_family"),
        (_event(clicks=10), "clicks_family"),
    ]
    svc = LearningService(_mock_db(rows))
    out = await svc.get_template_performance_multipliers()
    assert out["shares_family"] > out["clicks_family"]


@pytest.mark.asyncio
async def test_uniform_performance_yields_unit_multipliers():
    """When every family performs the same, multipliers should all be ~1.0."""
    rows = [
        (_event(shares=10, comments=20), "fam_a"),
        (_event(shares=10, comments=20), "fam_a"),
        (_event(shares=10, comments=20), "fam_a"),
        (_event(shares=10, comments=20), "fam_b"),
        (_event(shares=10, comments=20), "fam_b"),
        (_event(shares=10, comments=20), "fam_b"),
    ]
    svc = LearningService(_mock_db(rows))
    out = await svc.get_template_performance_multipliers()
    assert all(0.95 <= m <= 1.05 for m in out.values())


@pytest.mark.asyncio
async def test_zero_engagement_returns_empty():
    """No engagement on any post — global_mean = 0; can't divide. Bail out cleanly."""
    rows = [
        (_event(), "fam"),
        (_event(), "fam"),
        (_event(), "fam"),
    ]
    svc = LearningService(_mock_db(rows))
    out = await svc.get_template_performance_multipliers()
    assert out == {}
