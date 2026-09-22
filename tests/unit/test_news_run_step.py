"""The news step inside the daily run: invisible when off, harmless when broken."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from tce.api.routers import content_runs
from tce.news import discovery
from tce.settings import settings


def _run(scope="week"):
    return SimpleNamespace(workspace_id=uuid.uuid4(), scope_kind=scope)


@pytest.mark.asyncio
async def test_off_means_the_run_is_exactly_as_before(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "news_lane", False)
    assert await content_runs._news_step(editorial_sessionmaker, _run(), appraise=False) is None
    assert await content_runs._news_step(editorial_sessionmaker, _run(), appraise=True) is None


@pytest.mark.asyncio
async def test_a_targeted_run_over_chosen_meetings_skips_news(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "news_lane", True)
    out = await content_runs._news_step(editorial_sessionmaker, _run("sources"), appraise=True)
    assert out is None


@pytest.mark.asyncio
async def test_news_breaking_never_breaks_the_evidence_run(editorial_sessionmaker, monkeypatch):
    """'News had a bad day' must never become 'your calls were not collected'."""
    monkeypatch.setattr(settings, "news_lane", True)

    async def explode(*args, **kwargs):
        raise RuntimeError("feed parser fell over")

    monkeypatch.setattr(discovery, "appraise_pending", explode)
    monkeypatch.setattr(discovery, "discover", explode)
    for appraise in (True, False):
        out = await content_runs._news_step(editorial_sessionmaker, _run(), appraise=appraise)
        assert out == {"error": "RuntimeError: feed parser fell over"}
