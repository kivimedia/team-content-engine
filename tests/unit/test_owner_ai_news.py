"""The owner's AI news lane judges AI tool changes at the owner's level (T-22611, 18-Nov).

Ziv, 18-Nov: too few topics "related to AI news". Measured that morning: nine
published AI stories in three days, zero topics. Two drop points, both reproduced here:

1. The daily selection was asked for two ideas, a size set for the old one-a-week
   news ceiling that the owner's workspace dropped on 20-Oct. With more good stories
   than slots the model rejected the rest ("It is a good candidate ... ranked below
   contract comparison and calendar buffers"), and that rejection is final.
2. The selector rejected changes to AI tools owners use as developer news: the
   GPT-6.2 launch as "advice for people who run agents or APIs", Gemini skills as
   "Kivi Media's skills run in Claude Code, not Gemini".

Synthetic fixtures only.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

from tce.api.routers import content_runs
from tce.editorial import selector
from tce.editorial.selector import build_selection_prompt
from tce.news import discovery
from tce.settings import settings
from tests.unit.test_news_selection import NOW, WS, _news_pm, _pm


def owner_on(monkeypatch, ws=WS):
    monkeypatch.setattr(settings, "owner_workspace_ids", str(ws))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")


def owner_off(monkeypatch):
    monkeypatch.setattr(settings, "owner_workspace_ids", str(uuid.uuid4()))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")


def news_prompt() -> str:
    anchor = _pm("standing_fact")
    return build_selection_prompt("s", "f", [_news_pm([anchor.id])], 3, NOW, context=[anchor])


def test_owner_news_shard_counts_ai_tools_owners_use_as_owner_relevant(monkeypatch):
    owner_on(monkeypatch)
    prompt = news_prompt()
    assert "OWNER AI TOOLS" in prompt
    for tool in ("ChatGPT", "Claude", "Gemini", "Copilot"):
        assert tool in prompt
    # A developer-facing item gets the owner-level angle, not a rejection.
    assert "instead of rejecting it" in prompt
    assert "a different vendor" in prompt
    # The anchor rule and the claims rules are not loosened.
    assert "MUST also cite at least one anchor" in prompt
    assert "Never invent a client anecdote" in prompt


def test_client_news_shard_is_unchanged(monkeypatch):
    owner_off(monkeypatch)
    prompt = news_prompt()
    assert "OWNER AI TOOLS" not in prompt
    assert "OWNER UPDATE (20-Oct)" not in prompt


async def _daily_max(monkeypatch) -> int:
    seen: dict = {}

    @asynccontextmanager
    async def fake_session(_sm):
        yield SimpleNamespace()

    async def awaiting(_db, _ws):
        return [uuid.uuid4() for _ in range(6)]

    async def key(_db, _ws, _ids):
        return "k"

    async def select_candidates(_sm, _ws, _start, **kw):
        seen.update(kw)
        return SimpleNamespace(candidates=[], status="complete", rejected=[], detail=None)

    monkeypatch.setattr(content_runs, "open_session", fake_session)
    monkeypatch.setattr(discovery, "news_awaiting_topic", awaiting)
    monkeypatch.setattr(discovery, "news_selection_key", key)
    monkeypatch.setattr(selector, "select_candidates", select_candidates)
    await content_runs._news_topics(None, SimpleNamespace(workspace_id=WS))
    return seen["max_candidates"]


async def test_owner_daily_news_selection_is_not_sized_for_the_old_weekly_ceiling(monkeypatch):
    owner_on(monkeypatch)
    asked = await _daily_max(monkeypatch)
    assert asked >= 4
    assert asked == content_runs.OWNER_NEWS_TOPICS_PER_DAY


async def test_client_daily_news_selection_keeps_two(monkeypatch):
    owner_off(monkeypatch)
    assert await _daily_max(monkeypatch) == content_runs.NEWS_TOPICS_PER_DAY == 2
