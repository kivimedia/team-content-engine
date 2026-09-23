"""The voice agent's long errands and how it finds a topic by what he calls it.

Three things a live call leans on that a quick test of the happy path misses:

- a topic named with filler words ("the one about the funnel") must not land on
  whichever title shares the most "the"s, because the edit is applied at once;
- an edit made while more openings are being written must survive them;
- research that a restart interrupted must not say "already running" forever,
  and a web search that failed must not be read out as "searched, 0 results".
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

import tce.llm
from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_voice as voice_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.editorial import packets as packet_service
from tce.editorial import voice_agent
from tce.llm import LLMResult
from tce.models.editorial import RecordingPacket
from tce.models.editorial_workspace import IdeaResearch
from tce.services import web_search
from tce.settings import settings
from tests.unit.test_editorial_voice_agent import (
    KEY,
    add_candidate,
    add_packet,
    change,
    headers,
    topic,
    undo,
)


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    # Offline always: no test may reach a real search engine.
    monkeypatch.setattr(voice_agent, "make_searcher", lambda: None)
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(voice_router.router, prefix="/api/v1")
    app.include_router(editorial_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: (
        editorial_sessionmaker
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ------------------------------------------------------------ finding a topic


async def three_titles(sm, ws):
    return {
        "one": await add_candidate(sm, ws, "The one thing I would never automate"),
        "funnel": await add_candidate(sm, ws, "Funnel pages are dead"),
        "pricing": await add_candidate(sm, ws, "How I set my pricing"),
    }


async def test_filler_words_do_not_pick_the_topic(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    ids = await three_titles(editorial_sessionmaker, ws)

    body = await topic(client, ws, "the one about the funnel")
    assert body["status"] == "found", body
    assert body["topic"]["candidate_id"] == str(ids["funnel"])

    body = await topic(client, ws, "the pricing one")
    assert body["status"] == "found", body
    assert body["topic"]["candidate_id"] == str(ids["pricing"])


async def test_a_misheard_word_finds_nothing_instead_of_the_title_full_of_the(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    await three_titles(editorial_sessionmaker, ws)
    # "fennel" for "funnel": only filler is left, and filler names no topic.
    assert (await topic(client, ws, "the one about the fennel"))["status"] == "none"
    assert (await topic(client, ws, "the fennel"))["status"] == "none"
    assert (await topic(client, ws, "the one"))["status"] == "none"


async def test_a_half_match_is_offered_back_not_picked(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    ids = await three_titles(editorial_sessionmaker, ws)
    # One of his two words is in one title. Close, but he may have meant
    # something else: the agent asks rather than writes to it.
    body = await topic(client, ws, "pricing fennel")
    assert body["status"] == "ambiguous", body
    assert [c["candidate_id"] for c in body["candidates"]] == [str(ids["pricing"])]


def test_a_phrase_is_matched_on_whole_words():
    assert voice_agent._score("the fun", "The funnel is dead") == 0.0
    assert voice_agent._score("one thing", "The one thing I would never automate") >= 1.0


# ------------------------------------------ an edit made while openings are written


def hook_answer(moment_id: str) -> dict:
    return {
        "hook_options": [
            {
                "id": "anything",
                "text": "Stop trusting the green tick.",
                "question": "Why not trust it?",
                "payoff_phrase_id": "p002",
                "moment_ids": [moment_id],
                "rationale": "Starts on the belief.",
            }
        ]
    }


async def test_a_script_edit_made_while_more_openings_are_written_is_kept(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    moment = str(uuid.uuid4())
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea", moment_ids=[moment])
    pid = await add_packet(editorial_sessionmaker, ws, cid)
    edits = []

    async def slow_worker(request, *, wait_timeout_s=None):
        # While the worker writes openings, he changes point 1 on the call.
        edited = await change(
            client,
            ws,
            cid,
            "script",
            [{"field": "bullets.0", "after": "VOICE EDIT", "expect": "First point."}],
        )
        assert edited.status_code == 200, edited.text
        edits.append(edited.json())
        return LLMResult(job_id=uuid.uuid4(), text="", structured=hook_answer(moment), model="m")

    monkeypatch.setattr(tce.llm, "complete", slow_worker)
    outcome = await packet_service.more_hook_options(editorial_sessionmaker, ws, pid)
    assert outcome.status == "ok", outcome.detail

    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["points"][0] == "VOICE EDIT", "the edit he heard confirmed must not be undone"
    assert [h["text"] for h in script["hooks"]][-1] == "Stop trusting the green tick."
    assert len(script["hooks"]) == 3
    assert script["hooks"][0]["chosen"] is True, "the opening in use stays in use"

    async with editorial_sessionmaker() as s:
        rows = (
            (await s.execute(select(RecordingPacket).where(RecordingPacket.candidate_id == cid)))
            .scalars()
            .all()
        )
    live = [r.version for r in rows if r.status != "superseded"]
    assert live == [script["version"]], "exactly one current version"

    # And the edit can still be taken back, on top of the new openings.
    back = await undo(client, ws, edits[0]["change_set_id"])
    assert back.status_code == 200, back.text
    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["points"][0] == "First point."
    assert len(script["hooks"]) == 3


# ------------------------------------------------------------------ research


async def running_row(sm, ws, cid, *, age: timedelta) -> uuid.UUID:
    async with sm() as s:
        row = IdeaResearch(
            workspace_id=ws,
            candidate_id=cid,
            state="running",
            requested_by="voice",
            query="An idea",
            evidence=[],
            web=[],
            web_status="skipped",
            created_at=voice_agent._now() - age,
        )
        s.add(row)
        await s.commit()
        return row.id


async def test_research_a_restart_left_running_does_not_block_a_new_one(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "An idea")
    ghost = await running_row(editorial_sessionmaker, ws, cid, age=timedelta(hours=2))

    started = await client.post(
        f"/api/v1/editorial/candidates/{cid}/research", json={"by": "voice"}, headers=headers(ws)
    )
    assert started.status_code == 202, started.text
    assert started.json()["already_running"] is False
    assert started.json()["research_id"] != str(ghost)

    old = (await client.get(f"/api/v1/editorial/research/{ghost}", headers=headers(ws))).json()
    assert old["state"] == "failed"
    assert old["finished_at"] is not None
    assert "started again" in old["summary"]


async def test_research_that_is_really_running_is_still_reported_once(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "An idea")
    live = await running_row(editorial_sessionmaker, ws, cid, age=timedelta(seconds=20))
    started = await client.post(
        f"/api/v1/editorial/candidates/{cid}/research", json={"by": "voice"}, headers=headers(ws)
    )
    assert started.json()["already_running"] is True
    assert started.json()["research_id"] == str(live)


async def test_the_startup_sweep_marks_research_the_restart_killed(editorial_sessionmaker):
    from tce.api import app as app_module

    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "An idea")
    ghost = await running_row(editorial_sessionmaker, ws, cid, age=timedelta(seconds=5))

    original = app_module.async_session
    app_module.async_session = editorial_sessionmaker
    try:
        await app_module._mark_stale_idea_research_interrupted()
    finally:
        app_module.async_session = original

    async with editorial_sessionmaker() as s:
        row = await s.get(IdeaResearch, ghost)
    assert row.state == "failed" and row.finished_at is not None
    assert "restart" in (row.detail or "")
    assert "Ask again" in (row.summary or "")


async def test_research_that_cannot_even_open_its_session_is_marked_failed(
    editorial_sessionmaker,
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "An idea")
    rid = await running_row(editorial_sessionmaker, ws, cid, age=timedelta(seconds=1))
    opened = []

    def flaky():
        opened.append(1)
        if len(opened) == 1:
            raise RuntimeError("database went away")
        return editorial_sessionmaker()

    await voice_agent.run_research(flaky, ws, rid)

    async with editorial_sessionmaker() as s:
        row = await s.get(IdeaResearch, rid)
    assert row.state == "failed", "a research row must never be left running by a crash"
    assert row.finished_at is not None


def brave_answers(monkeypatch, handler):
    """Every httpx client the search service opens talks to `handler` instead of Brave."""
    real = httpx.AsyncClient

    def offline(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(web_search.httpx, "AsyncClient", offline)


@pytest.mark.parametrize(
    ("status", "words"),
    [(401, "refused"), (429, "quota"), (402, "quota"), (503, "error")],
)
async def test_a_refused_or_exhausted_search_is_reported_as_failed_not_as_nothing_found(
    client, editorial_sessionmaker, monkeypatch, status, words
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "An idea")
    monkeypatch.setattr(
        voice_agent, "make_searcher", lambda: web_search.WebSearchService(api_key="k")
    )
    brave_answers(monkeypatch, lambda request: httpx.Response(status, json={"error": "no"}))

    rid = (
        await client.post(f"/api/v1/editorial/candidates/{cid}/research", headers=headers(ws))
    ).json()["research_id"]
    done = (await client.get(f"/api/v1/editorial/research/{rid}", headers=headers(ws))).json()
    assert done["state"] == "done"
    assert done["web_status"] == "failed", done
    assert "0 web results" not in done["summary"]
    assert "search failed" in done["summary"] and words in done["summary"]
    assert str(status) in (done["detail"] or "")


async def test_an_unreachable_search_is_reported_as_failed(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "An idea")
    monkeypatch.setattr(
        voice_agent, "make_searcher", lambda: web_search.WebSearchService(api_key="k")
    )

    def down(request):
        raise httpx.ConnectError("no route", request=request)

    brave_answers(monkeypatch, down)
    rid = (
        await client.post(f"/api/v1/editorial/candidates/{cid}/research", headers=headers(ws))
    ).json()["research_id"]
    done = (await client.get(f"/api/v1/editorial/research/{rid}", headers=headers(ws))).json()
    assert done["web_status"] == "failed", done
    assert "could not be reached" in done["summary"]


async def test_other_search_callers_still_get_an_empty_list_on_error(monkeypatch):
    brave_answers(monkeypatch, lambda request: httpx.Response(401, json={}))
    assert await web_search.WebSearchService(api_key="k").search("x") == []


async def test_a_search_that_worked_and_found_nothing_still_says_zero(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "An idea")
    monkeypatch.setattr(
        voice_agent, "make_searcher", lambda: web_search.WebSearchService(api_key="k")
    )
    brave_answers(monkeypatch, lambda request: httpx.Response(200, json={"web": {"results": []}}))
    rid = (
        await client.post(f"/api/v1/editorial/candidates/{cid}/research", headers=headers(ws))
    ).json()["research_id"]
    done = (await client.get(f"/api/v1/editorial/research/{rid}", headers=headers(ws))).json()
    assert done["web_status"] == "searched" and "0 web results" in done["summary"]
