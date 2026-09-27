"""New ideas from a call: a spoken idea and a research run, both through the gates.

Synthetic fixtures only. Nothing here constructs a TopicCandidate outside the
selector; test_no_ungated_topic_source.py checks that for the whole tree.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

import tce.llm
from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_voice
from tce.editorial import idea_lane
from tce.editorial import status as job_status
from tce.editorial.common import current_week_start
from tce.llm import LLMResult
from tce.models.editorial import REJECTION_GATES, EvidenceMoment, EvidenceSource, TopicCandidate
from tce.models.news import NewsItem
from tce.settings import settings

KEY = "synthetic-test-key"


def gates(fail: str | None = None) -> dict:
    out = {g: {"pass": True, "reason": f"synthetic reason for {g}"} for g in REJECTION_GATES}
    if fail:
        out[fail] = {"pass": False, "reason": "not something a coach would act on"}
    return out


@pytest.fixture
def spoken_llm(monkeypatch, editorial_sessionmaker):
    """The selector's model, answering with a candidate that cites the spoken moment."""
    state: dict = {"calls": 0, "fail_gate": None}

    async def fake_complete(req, *, wait_timeout_s=None):
        state["calls"] += 1
        async with editorial_sessionmaker() as s:
            ids = (
                await s.execute(
                    select(EvidenceMoment.id)
                    .join(EvidenceSource, EvidenceSource.id == EvidenceMoment.source_id)
                    .where(EvidenceSource.source_kind == idea_lane.SPOKEN_KIND)
                )
            ).scalars().all()
        cand = {
            "moment_ids": [str(i) for i in ids],
            "title": "Price the outcome, not the hours",
            "lesson": "Coaches who quote hours cap their own income.",
            "audience": "coaches",
            "reasons_to_care": ["raises the price ceiling"],
            "public_angle": "What a client is really buying.",
            "public_safety_notes": "",
            "gates": gates(state["fail_gate"]),
            "freshness_role": "evergreen",
            "scores": {"owner_relevance": 4, "useful_lesson": 4, "support_strength": 3},
        }
        return LLMResult(
            job_id=uuid.uuid4(), text="",
            structured={"candidates": [cand], "rejections": []}, model="claude-opus-5",
        )

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    return state


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    job_status.clear()
    app = FastAPI()
    app.include_router(editorial_voice.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: (
        editorial_sessionmaker
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    job_status.clear()


def headers(ws) -> dict:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


async def wait_done(client, ws, run_id) -> dict:
    for _ in range(100):
        r = await client.get(f"/api/v1/editorial/idea-runs/{run_id}", headers=headers(ws))
        assert r.status_code == 200, r.text
        if r.json()["state"] != "running":
            return r.json()
        await asyncio.sleep(0.02)
    raise AssertionError("idea run never finished")


async def add_proposed(sm, ws, title="Already on the week") -> TopicCandidate:
    week = current_week_start()
    async with sm() as s:
        c = TopicCandidate(
            workspace_id=ws, week_start=datetime(week.year, week.month, week.day),
            moment_ids=[str(uuid.uuid4())], title=title, lesson="l", audience="coaches",
            public_angle="a", gates={}, status="proposed", rank=1,
        )
        s.add(c)
        await s.commit()
        return c


async def test_spoken_idea_passes_the_gates_and_keeps_the_week(
    client, editorial_sessionmaker, spoken_llm, monkeypatch
):
    ws = uuid.uuid4()
    other = await add_proposed(editorial_sessionmaker, ws)
    started: list = []

    async def fake_run_packet(sm, w, cid, resume_job_id=None, **kw):
        started.append(cid)
        job_status.update(w, "packet", str(cid), state="done")

    monkeypatch.setattr(editorial_router, "_run_packet", fake_run_packet)

    r = await client.post(
        "/api/v1/editorial/spoken-idea",
        json={
            "said": "I want a video about why coaches should stop selling hours",
            "idea": "Coaches should price the outcome, not the hours",
            "write_script": True,
        },
        headers=headers(ws),
    )
    assert r.status_code == 202, r.text
    run = await wait_done(client, ws, r.json()["run_id"])
    assert run["state"] == "done", run
    assert run["result"]["saved"] is True
    assert run["said"].startswith('is saved as "Price the outcome, not the hours"')
    assert "script is being written" in run["said"]
    await asyncio.sleep(0.05)
    assert [str(c) for c in started] == [run["result"]["candidate_id"]]

    async with editorial_sessionmaker() as s:
        rows = (
            await s.execute(select(TopicCandidate).where(TopicCandidate.workspace_id == ws))
        ).scalars().all()
        src = (
            await s.execute(
                select(EvidenceSource).where(EvidenceSource.source_kind == idea_lane.SPOKEN_KIND)
            )
        ).scalar_one()
    proposed = {r.title: r for r in rows if r.status == "proposed"}
    assert set(proposed) == {"Already on the week", "Price the outcome, not the hours"}
    assert proposed["Already on the week"].id == other.id
    assert "said on a call" in proposed["Price the outcome, not the hours"].editor_notes
    assert src.payload_private["said"].startswith("I want a video about why coaches")


async def test_spoken_idea_that_fails_a_gate_is_not_saved(
    client, editorial_sessionmaker, spoken_llm
):
    ws = uuid.uuid4()
    gate = REJECTION_GATES[0]
    spoken_llm["fail_gate"] = gate
    r = await client.post(
        "/api/v1/editorial/spoken-idea",
        json={"said": "a video about the new VC funding round", "idea": "Funding news",
              "write_script": True},
        headers=headers(ws),
    )
    run = await wait_done(client, ws, r.json()["run_id"])
    assert run["result"]["saved"] is False
    assert run["said"].startswith("was not saved. It did not pass the")
    async with editorial_sessionmaker() as s:
        rows = (
            await s.execute(select(TopicCandidate).where(TopicCandidate.workspace_id == ws))
        ).scalars().all()
    assert [r.status for r in rows] == ["rejected"]


async def test_unknown_run_is_404(client):
    r = await client.get(
        f"/api/v1/editorial/idea-runs/{uuid.uuid4()}", headers=headers(uuid.uuid4())
    )
    assert r.status_code == 404


class FakeSearch:
    def __init__(self, hits, api_key="k"):
        self.api_key = api_key
        self.hits = hits
        self.queries: list[str] = []

    async def search(self, query, count=10, freshness=None, *, raise_errors=False):
        self.queries.append(query)
        return self.hits


async def test_research_skips_news_sites_and_spends_no_model_call_without_an_anchor(
    editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    calls: list = []

    async def no_llm(req, *, wait_timeout_s=None):
        calls.append(req)
        raise AssertionError("no model call expected")

    fetched: list[str] = []

    async def fetch_text(url):
        fetched.append(url)
        return {"title": "A vendor page", "body_text": "Nothing that matches any anchor at all."}

    search = FakeSearch([
        {"url": "https://techcrunch.com/2026/09/some-funding-story"},
        {"url": "https://vendor.example/announcing-a-thing"},
    ])
    run_id = uuid.uuid4()
    job_status.start(ws, idea_lane.KIND_RESEARCH, str(run_id), "Starting")
    await idea_lane.run_idea_research(
        editorial_sessionmaker, ws, run_id, topic="pricing for coaches",
        search=search, fetch_text=fetch_text, complete=no_llm,
    )
    run = job_status.get(ws, idea_lane.KIND_RESEARCH, str(run_id))
    assert run["state"] == "done", run
    assert search.queries == ["pricing for coaches"]
    assert fetched == ["https://vendor.example/announcing-a-thing"]
    assert run["result"]["counts"]["news_sites_skipped"] == 1
    assert run["result"]["counts"]["no_match"] == 1
    assert "No new idea" in run["said"]
    assert calls == []
    async with editorial_sessionmaker() as s:
        assert (
            await s.execute(select(TopicCandidate).where(TopicCandidate.workspace_id == ws))
        ).scalars().all() == []
        items = (
            (await s.execute(select(NewsItem).where(NewsItem.workspace_id == ws))).scalars().all()
        )
    assert [i.prefilter_reason for i in items] == ["no_anchor"]


async def test_research_without_a_search_key_says_so(editorial_sessionmaker):
    ws = uuid.uuid4()
    run_id = uuid.uuid4()
    job_status.start(ws, idea_lane.KIND_RESEARCH, str(run_id), "Starting")
    await idea_lane.run_idea_research(
        editorial_sessionmaker, ws, run_id, topic="anything", search=FakeSearch([], api_key=""),
    )
    run = job_status.get(ws, idea_lane.KIND_RESEARCH, str(run_id))
    assert run["state"] == "done"
    assert run["said"].startswith("could not search: web search is not set up")
    assert run["result"]["web_status"] == "no_key"


async def test_surprise_me_seeds_from_his_own_recent_work(editorial_sessionmaker):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        src = EvidenceSource(
            workspace_id=ws, source_kind="fathom_meeting", external_id="m1",
            title="call", occurred_at=idea_lane._now(), version_hash="a" * 64,
            fetch_status="ok", payload_private={}, meta={},
        )
        s.add(src)
        await s.flush()
        s.add(EvidenceMoment(
            workspace_id=ws, source_id=src.id, source_version_hash="a" * 64,
            excerpt_private="x", lesson_summary="Follow up within a day of the demo call",
            claim_type="paraphrased", sensitivity_flags=[], status="active",
        ))
        await s.commit()
        queries = await idea_lane.seed_queries(s, ws)
    assert queries == ["Follow up within a day of the demo call"]
