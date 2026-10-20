"""Owner news workflow: durable handoff, honest mix and recording readiness."""
import uuid
from datetime import datetime

import pytest

from tce.models.news import NewsItem
from tce.editorial.news_packet import news_errors
from tce.settings import settings


def test_operational_metadata_is_separate_from_source_text():
    assert "editorial_meta" in NewsItem.__table__.columns


def test_owner_can_open_with_a_sourced_product_fact():
    packet = {
        "script_phrases": ["Google now lets a Gemini app become a private Sites draft."],
        "hook_options": [{"text": "Google lets your next lead magnet do something."}],
        "beats": [{"start_phrase_id": "p001", "end_phrase_id": "p001"}],
    }
    assert news_errors(packet, ["Google"], allow_announcement=True) == []
    assert news_errors(packet, ["Google"])
    packet["script_phrases"] = ["Act now before it's too late."]
    assert any("urgency" in e for e in news_errors(packet, [], allow_announcement=True))


def test_submission_urls_remove_tracking_but_refuse_credentials():
    from tce.editorial.news_workflow import submission_url
    assert submission_url("https://example.com/story?utm_source=mail#top") == (
        "https://example.com/story"
    )
    with pytest.raises(ValueError):
        submission_url("http://localhost:8200/private")
    with pytest.raises(ValueError):
        submission_url("https://name:password@example.com/story")
    with pytest.raises(ValueError):
        submission_url("https://example.com/story?token=secret")


def test_published_mix_deduplicates_platforms_and_excludes_software():
    from tce.editorial.news_workflow import published_mix
    rows = [
        {"original_id": "ai", "category": "ai", "posted_at": datetime(2026, 10, 20)},
        {"original_id": "ai", "category": "ai", "posted_at": datetime(2026, 10, 20)},
        {"original_id": "crm", "category": "software", "posted_at": datetime(2026, 10, 19)},
        {"original_id": "build", "category": "other", "posted_at": datetime(2026, 10, 18)},
        {"original_id": "call", "category": "other", "posted_at": datetime(2026, 10, 17)},
    ]
    result = published_mix(rows)
    assert result["published_originals"] == 4
    assert result["ai_news_originals"] == 1
    assert result["share"] == .25
    assert result["target"] == .25
    assert published_mix([])["share"] is None


@pytest.mark.asyncio
async def test_handoff_is_idempotent_and_preserves_source(editorial_session):
    from tce.editorial.news_workflow import record_submission
    ws = uuid.uuid4()
    item = NewsItem(workspace_id=ws, external_id="one", url="https://example.com/story",
                    canonical_url="https://example.com/story", title="A release",
                    raw_private="actual source text", matched=False)
    editorial_session.add(item)
    await editorial_session.flush()
    first = await record_submission(editorial_session, ws, item, "km-bot", "A useful angle")
    again = await record_submission(editorial_session, ws, item, "km-bot", "A useful angle")
    assert first["receipt_id"] == again["receipt_id"]
    assert len(item.editorial_meta["submissions"]) == 1
    assert item.raw_private == "actual source text"
    assert item.published_at is None


@pytest.mark.asyncio
async def test_owner_submission_routes_are_scoped_and_reuse_the_item(
    editorial_sessionmaker, monkeypatch,
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from tce.api.routers import news
    owner, other = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(owner))
    monkeypatch.setattr(settings, "owner_workspace_ids", "")
    monkeypatch.setattr(settings, "private_access_key", SecretStr("test-news-key"))
    async with editorial_sessionmaker() as db:
        item = NewsItem(workspace_id=owner, external_id="source",
                        url="https://example.com/story", title="Real source", matched=True,
                        editorial_meta={"primary_source_verified": True})
        db.add(item)
        await db.commit()
        item_id = item.id
    app = FastAPI()
    app.include_router(news.router, prefix="/api/v1")
    app.dependency_overrides[news.get_news_sessionmaker] = lambda: editorial_sessionmaker
    client = TestClient(app)
    owner_headers = {"Authorization": "Bearer test-news-key", "X-Workspace-Id": str(owner)}
    body = {"url": "https://example.com/story?utm_source=mail",
            "angle": "An explicit proposed audience use."}
    first = client.post("/api/v1/news/submissions", json=body, headers=owner_headers)
    assert first.status_code == 200, first.text
    second = client.post("/api/v1/news/submissions", json=body, headers=owner_headers)
    assert second.json()["receipt_id"] == first.json()["receipt_id"]
    assert first.json()["item_id"] == str(item_id)
    assert client.post("/api/v1/news/submissions", json=body).status_code == 401
    foreign = {**owner_headers, "X-Workspace-Id": str(other)}
    assert client.post("/api/v1/news/submissions", json=body, headers=foreign).status_code == 403
    status = client.get(f"/api/v1/news/items/{item_id}/handoff", headers=owner_headers)
    assert status.status_code == 200
    assert status.json()["receipt_id"] == first.json()["receipt_id"]
    assert client.get("/api/v1/news/workflow", headers=foreign).json() == {"enabled": False}
    retry = client.post(f"/api/v1/news/items/{item_id}/retry", headers=owner_headers,
                        json={"reason": "New source availability evidence to check."})
    assert retry.status_code == 200
    async with editorial_sessionmaker() as db:
        saved = await db.get(NewsItem, item_id)
        assert saved.editorial_meta["retry_nonce"]
        assert len(saved.editorial_meta["submissions"]) == 1
        saved.editorial_meta = {**saved.editorial_meta, "primary_source_verified": False}
        await db.commit()
    checks = []
    async def check_source(db, ws, *, url, fetch_text):
        checks.append(url)
        return {"status": "held", "item_id": str(item_id)}
    from tce.news import discovery
    monkeypatch.setattr(discovery, "check_one", check_source)
    rechecked = client.post("/api/v1/news/submissions", json=body, headers=owner_headers)
    assert rechecked.status_code == 200
    assert checks == ["https://example.com/story"]
    from datetime import date
    from tce.models.editorial import TopicCandidate, RecordingPacket
    async with editorial_sessionmaker() as db:
        saved = await db.get(NewsItem, item_id)
        saved.editorial_meta = {**saved.editorial_meta, "primary_source_verified": True}
        cand = TopicCandidate(workspace_id=owner, week_start=date.today(), title="Reviewed story",
                              lesson="A useful test", audience="both", public_angle="A proposed test",
                              moment_ids=[], gates={}, status="proposed", news_item_id=item_id)
        db.add(cand)
        await db.flush()
        packet = RecordingPacket(workspace_id=owner, candidate_id=cand.id, version=1,
                                 status="ready", bullets=[], script_phrases=[],
                                 facebook_post="", linkedin_post="", interviewer_prompt="",
                                 prompt_version="test", citations_private=[])
        db.add(packet)
        await db.commit()
        packet_id = str(packet.id)
    current = client.post("/api/v1/news/submissions", json=body, headers=owner_headers)
    assert current.status_code == 200
    assert current.json()["state"] == "ready_to_record"
    assert current.json()["packet_id"] == packet_id
    assert current.json()["receipt_id"] == first.json()["receipt_id"]


@pytest.mark.asyncio
async def test_selected_topic_is_visible_and_gets_one_brief_request(
    editorial_sessionmaker, monkeypatch,
):
    from datetime import date, timedelta
    from sqlalchemy import select
    from tce.models.editorial import TopicCandidate
    from tce.models.editorial_workspace import WeeklyLineupItem
    from tce.api.routers import editorial
    from tce.editorial.news_workflow import prepare_news_briefs, workflow_status
    owner = uuid.uuid4()
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(owner))
    monkeypatch.setattr(settings, "owner_workspace_ids", "")
    async with editorial_sessionmaker() as db:
        item = NewsItem(workspace_id=owner, external_id="source",
                        url="https://example.com/story", title="Real source", matched=True,
                        editorial_meta={"news_category": "ai"})
        db.add(item)
        await db.flush()
        cand = TopicCandidate(workspace_id=owner, week_start=date.today(),
                              title="Useful AI release", lesson="A proposed test",
                              audience="both", public_angle="Try with synthetic data",
                              moment_ids=[], gates={"_news_category": "ai"}, status="selected",
                              news_item_id=item.id, freshness_role="news",
                              expires_at=datetime.utcnow() + timedelta(days=3))
        db.add(cand)
        await db.commit()
        cid = cand.id
        data = await workflow_status(db, owner)
        assert data["queue"][0]["state"] == "needs_brief"
    requests = []
    async def start(cid, background, body, ws, sm):
        assert body.replace is False
        requests.append(cid)
        return {"status": "running", "candidate_id": cid}
    monkeypatch.setattr(editorial, "start_packet", start)
    result = await prepare_news_briefs(editorial_sessionmaker, owner)
    assert requests == [str(cid)]
    assert result["outcomes"][0]["state"] == "requested"
    async with editorial_sessionmaker() as db:
        entries = list((await db.execute(select(WeeklyLineupItem))).scalars())
        assert len(entries) == 1 and entries[0].slot == "reserve"
    assert await prepare_news_briefs(editorial_sessionmaker, uuid.uuid4()) == {"enabled": False}
