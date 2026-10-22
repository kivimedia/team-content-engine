"""Explicit acceptance of a verified solution title, never a background rewrite."""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.db.workspace_filter import set_workspace_context
from tce.editorial import briefs
from tce.models.editorial import RecordingPacket, TopicCandidate
from tce.models.editorial_workspace import TopicDecision, WeeklyLineup
from tce.settings import settings

KEY = "synthetic-test-key"
ARTICLE = (
    "https://workspaceupdates.googleblog.com/2026/10/"
    "publish-interactive-apps-from-gemini-app-to-Google-Sites.html"
)
SUGGESTED = "Google Sites: build an interactive coaching diagnostic"


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(settings, "owner_workspace_ids", "")
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: (
        editorial_sessionmaker
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def headers(ws: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


async def candidate(sm, ws: uuid.UUID, *, verified: bool = True) -> uuid.UUID:
    citations = [
        {
            "source_kind": "news_item",
            "moment_id": str(uuid.uuid4()),
            "url_private": ARTICLE if verified else "https://example.com/unverified",
        },
        {"source_kind": "standing_fact", "moment_id": str(uuid.uuid4())},
    ]
    async with sm() as db:
        row = TopicCandidate(
            workspace_id=ws,
            week_start=datetime(2026, 10, 19),
            moment_ids=[str(uuid.uuid4())],
            title="Build a coaching diagnostic",
            lesson="Show clients a concrete self-assessment.",
            audience="coaches",
            reasons_to_care=["Clients need a clear starting point."],
            public_angle="A practical demo.",
            gates={"small_service_business": {"pass": True, "reason": "yes"}},
            citations_private=citations,
            status="proposed",
            origin="selector",
            freshness_role="news",
            rank=1,
        )
        db.add(row)
        await db.commit()
        return row.id


def url(cid: uuid.UUID) -> str:
    return f"/api/v1/editorial/topics/{cid}/suggested-title/accept"


def body(*, title: str = "Build a coaching diagnostic", suggestion: str = SUGGESTED):
    return {"expected_title": title, "suggested_title": suggestion}


async def test_accepting_title_updates_candidate_and_versions_only_matching_brief(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    monkeypatch.setattr(settings, "owner_workspace_ids", str(ws))
    cid = await candidate(editorial_sessionmaker, ws)
    async with editorial_sessionmaker() as db:
        row = await db.get(TopicCandidate, cid)
        old_brief = await briefs.ensure_brief(db, ws, row)
        old_brief_version = old_brief.version
        db.add(TopicDecision(workspace_id=ws, candidate_id=cid, decision="later", note="keep"))
        db.add(WeeklyLineup(workspace_id=ws, week_start=datetime(2026, 10, 19), revision=7))
        packet = RecordingPacket(
            workspace_id=ws,
            candidate_id=cid,
            version=1,
            bullets=["Keep this"],
            script_phrases=["Keep that"],
            citations_private=[],
            public_safety={"checked": True, "issues": [], "status": "clean"},
            status="ready",
        )
        db.add(packet)
        await db.commit()
        packet_id = packet.id

    response = await client.post(url(cid), json=body(), headers=headers(ws))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["candidate_id"] == str(cid)
    assert result["previous_title"] == "Build a coaching diagnostic"
    assert result["title"] == SUGGESTED
    assert result["suggested_title"] == SUGGESTED
    assert result["solution_label"] == "Google Sites"
    assert result["brief_version"] == old_brief_version + 1
    assert result["accepted_at"]

    async with editorial_sessionmaker() as db:
        row = await db.get(TopicCandidate, cid)
        current = await briefs.latest_version(db, ws, cid)
        history = await briefs.list_versions(db, ws, cid)
        decision = (
            await db.execute(
                select(TopicDecision).where(
                    TopicDecision.workspace_id == ws, TopicDecision.candidate_id == cid
                )
            )
        ).scalar_one()
        lineup = (
            await db.execute(select(WeeklyLineup).where(WeeklyLineup.workspace_id == ws))
        ).scalar_one()
        script = await db.get(RecordingPacket, packet_id)
        assert row.title == SUGGESTED
        audit = row.gates["_title_acceptances"]
        assert len(audit) == 1
        assert audit[0]["before"] == "Build a coaching diagnostic"
        assert audit[0]["after"] == SUGGESTED
        assert history[0].brief["topic"] == "Build a coaching diagnostic"
        assert current.brief["topic"] == SUGGESTED
        assert current.brief["big_idea"] == history[0].brief["big_idea"]
        assert decision.decision == "later" and decision.note == "keep"
        assert lineup.revision == 7
        assert script.bullets == ["Keep this"] and script.script_phrases == ["Keep that"]

    duplicate = await client.post(url(cid), json=body(), headers=headers(ws))
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "stale_title"
    async with editorial_sessionmaker() as db:
        assert len((await db.get(TopicCandidate, cid)).gates["_title_acceptances"]) == 1
        assert len(await briefs.list_versions(db, ws, cid)) == 2


async def test_changed_brief_is_never_overwritten_by_title_acceptance(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    monkeypatch.setattr(settings, "owner_workspace_ids", str(ws))
    cid = await candidate(editorial_sessionmaker, ws)
    async with editorial_sessionmaker() as db:
        row = await db.get(TopicCandidate, cid)
        first = await briefs.ensure_brief(db, ws, row)
        edited = dict(first.brief)
        edited["topic"] = "My own title"
        await briefs.write_version(
            db, ws, cid, brief=edited, parent_version=1,
            origin="manual", created_by="ziv", note="Edited in the room",
        )
        await db.commit()

    response = await client.post(url(cid), json=body(), headers=headers(ws))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "brief_title_changed"
    async with editorial_sessionmaker() as db:
        assert (await db.get(TopicCandidate, cid)).title == "Build a coaching diagnostic"
        assert (await briefs.latest_version(db, ws, cid)).brief["topic"] == "My own title"
        assert len(await briefs.list_versions(db, ws, cid)) == 2


async def test_acceptance_requires_current_verified_suggestion_and_owner_workspace(
    client, editorial_sessionmaker, monkeypatch
):
    owner = uuid.uuid4()
    other = uuid.uuid4()
    monkeypatch.setattr(settings, "owner_workspace_ids", str(owner))
    cid = await candidate(editorial_sessionmaker, owner)
    unverified = await candidate(editorial_sessionmaker, owner, verified=False)

    assert (await client.post(url(cid), json=body())).status_code in (401, 403)
    client_denied = await client.post(url(cid), json=body(), headers=headers(other))
    assert client_denied.status_code == 403
    assert client_denied.json()["detail"]["code"] == "owner_only"
    stale = await client.post(url(cid), json=body(title="Old tab"), headers=headers(owner))
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_title"
    swapped = await client.post(
        url(cid), json=body(suggestion="KM Hub: different"), headers=headers(owner)
    )
    assert swapped.status_code == 409
    assert swapped.json()["detail"]["code"] == "suggestion_changed"
    unsupported = await client.post(url(unverified), json=body(), headers=headers(owner))
    assert unsupported.status_code == 409
    assert unsupported.json()["detail"]["code"] == "suggestion_unavailable"

    async with editorial_sessionmaker() as db:
        assert (await db.get(TopicCandidate, cid)).title == "Build a coaching diagnostic"
        assert (await db.get(TopicCandidate, unverified)).title == "Build a coaching diagnostic"


async def test_acceptance_without_a_brief_keeps_later_seeding_consistent(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    monkeypatch.setattr(settings, "owner_workspace_ids", str(ws))
    cid = await candidate(editorial_sessionmaker, ws)

    response = await client.post(url(cid), json=body(), headers=headers(ws))
    assert response.status_code == 200, response.text
    assert response.json()["brief_version"] is None

    async with editorial_sessionmaker() as db:
        assert await briefs.latest_version(db, ws, cid) is None
        row = await db.get(TopicCandidate, cid)
        seed = await briefs.ensure_brief(db, ws, row)
        assert seed.brief["topic"] == SUGGESTED


async def test_one_owner_workspace_cannot_accept_another_workspaces_topic(
    client, editorial_sessionmaker, monkeypatch
):
    left, right = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(settings, "owner_workspace_ids", f"{left},{right}")
    cid = await candidate(editorial_sessionmaker, right)

    response = await client.post(url(cid), json=body(), headers=headers(left))
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"
    set_workspace_context(right)
    try:
        async with editorial_sessionmaker() as db:
            assert (await db.get(TopicCandidate, cid)).title == "Build a coaching diagnostic"
    finally:
        set_workspace_context(None)
