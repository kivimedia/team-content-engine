"""The owner's four choices for an idea (18-Nov-2026, T-22744).

Good (this_week), Bad (away), Needs AI work (improve: files the idea in a list of
its own and starts a fresh research pass on it) and Needs my thinking (discuss).
Save for later is no longer offered to the owner; an idea saved for later before
that waits under Needs my thinking.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from tce.editorial import voice_agent
from tce.models.editorial_workspace import IdeaResearch
from tce.settings import settings

from tests.unit.test_editorial_workspace_router import add_candidate, client, headers  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def owner_ws(monkeypatch):
    ws = uuid.uuid4()
    monkeypatch.setattr(settings, "owner_workspace_ids", str(ws))
    return ws


@pytest.fixture
def no_research_run(monkeypatch):
    """The research pass itself calls a model; here only its start is under test."""
    ran: list[uuid.UUID] = []

    async def fake_run(sm, ws, research_id):
        ran.append(research_id)

    monkeypatch.setattr(voice_agent, "run_research", fake_run)
    return ran


async def _titles(client, ws, filter_key):  # noqa: F811
    body = (await client.get(f"/api/v1/editorial/topics?filter={filter_key}", headers=headers(ws))).json()
    return [t["title"] for t in body["topics"]]


async def test_needs_ai_work_files_the_idea_and_starts_research(
    client, editorial_sessionmaker, owner_ws, no_research_run  # noqa: F811
):
    cid = await add_candidate(editorial_sessionmaker, owner_ws, "Shared skills read a live doc")

    response = await client.post(
        f"/api/v1/editorial/topics/{cid}/decide",
        json={"decision": "improve"},
        headers=headers(owner_ws),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["research_id"]
    assert [str(r) for r in no_research_run] == [body["research_id"]]

    async with editorial_sessionmaker() as s:
        rows = (await s.execute(select(IdeaResearch).where(IdeaResearch.workspace_id == owner_ws))).scalars().all()
    assert [r.state for r in rows] == ["running"]

    assert await _titles(client, owner_ws, "improve") == ["Shared skills read a live doc"]
    assert await _titles(client, owner_ws, "best") == []
    assert await _titles(client, owner_ws, "discuss") == []

    # Saying it again while that pass runs starts nothing new.
    again = await client.post(
        f"/api/v1/editorial/topics/{cid}/decide",
        json={"decision": "improve"},
        headers=headers(owner_ws),
    )
    assert again.status_code == 200
    assert again.json()["research_id"] is None
    assert len(no_research_run) == 1


async def test_needs_my_thinking_has_its_own_tab_and_holds_an_old_later(
    client, editorial_sessionmaker, owner_ws, no_research_run  # noqa: F811
):
    think = await add_candidate(editorial_sessionmaker, owner_ws, "Think it over", rank=1)
    old_later = await add_candidate(editorial_sessionmaker, owner_ws, "Saved last week", rank=2)
    await add_candidate(editorial_sessionmaker, owner_ws, "Still undecided", rank=3)

    for cid, decision in ((think, "discuss"), (old_later, "later")):
        r = await client.post(
            f"/api/v1/editorial/topics/{cid}/decide",
            json={"decision": decision},
            headers=headers(owner_ws),
        )
        assert r.status_code == 200, r.text

    assert sorted(await _titles(client, owner_ws, "discuss")) == ["Saved last week", "Think it over"]
    assert await _titles(client, owner_ws, "best") == ["Still undecided"]
    assert no_research_run == []


async def test_the_owner_tabs_are_the_four_choices_and_later_is_not_offered(
    client, editorial_sessionmaker, owner_ws  # noqa: F811
):
    body = (await client.get("/api/v1/editorial/topics?filter=best", headers=headers(owner_ws))).json()
    labels = {f["key"]: f["label"] for f in body["filters"]}
    assert labels["improve"] == "Needs AI work"
    assert labels["discuss"] == "Needs my thinking"
    assert labels["away"] == "Bad"
    assert "later" not in labels
    # An old saved link to the later list still opens rather than erroring.
    later = await client.get("/api/v1/editorial/topics?filter=later", headers=headers(owner_ws))
    assert later.status_code == 200


async def test_a_client_workspace_keeps_its_old_tabs(client, editorial_sessionmaker):  # noqa: F811
    ws = uuid.uuid4()
    body = (await client.get("/api/v1/editorial/topics?filter=best", headers=headers(ws))).json()
    keys = [f["key"] for f in body["filters"]]
    assert "later" in keys and "improve" not in keys and "discuss" not in keys


def test_the_page_offers_the_owner_four_buttons_and_hebrew_has_each():
    js = (ROOT / "src/tce/api/workspace.js").read_text(encoding="utf-8")
    he = (ROOT / "src/tce/api/i18n-he.js").read_text(encoding="utf-8")
    for label in ("Good: keep it", "Needs AI work", "Needs my thinking", "Bad: ditch it"):
        assert f">{label}<" in js or f'"{label}"' in js, label
        assert re.search(r'"' + re.escape(label) + r'"\s*:', he), label
    for value in ("this_week", "improve", "discuss", "away"):
        assert f'data-decide="{value}"' in js


def test_the_call_agent_knows_the_four_words():
    mjs = (ROOT / "mcp-server/tools/voice.mjs").read_text(encoding="utf-8")
    for word, value in (("good", "this_week"), ("bad", "away"), ("'needs ai work'", "improve"),
                        ("'needs my thinking'", "discuss")):
        assert re.search(re.escape(word) + r":\s*'" + value + "'", mjs), word
    brief = (ROOT / "deploy/voice-seat/tce-brief.md").read_text(encoding="utf-8")
    assert "needs AI work" in brief and "needs my thinking" in brief
