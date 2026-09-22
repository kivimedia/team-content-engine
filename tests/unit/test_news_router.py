"""The Timely tab's API: private, tenant-scoped, and honest about a dead feed."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tce.api.routers import news as news_router
from tce.models.news import NewsAnchor, NewsFeed
from tce.settings import settings

KEY = "synthetic-test-key"
WS_A = uuid.uuid4()
WS_B = uuid.uuid4()


@pytest.fixture
def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    app = FastAPI()
    app.include_router(news_router.router, prefix="/api/v1")
    app.dependency_overrides[news_router.get_news_sessionmaker] = lambda: editorial_sessionmaker
    return TestClient(app)


def h(ws):
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


@pytest.fixture
async def seeded(editorial_sessionmaker):
    async with editorial_sessionmaker() as s:
        s.add_all(
            [
                NewsFeed(id=uuid.uuid4(), workspace_id=WS_A, name="Healthy", url="https://a/x",
                         kind="atom", tier="1a", consecutive_failures=0, last_status="ok"),
                NewsFeed(id=uuid.uuid4(), workspace_id=WS_A, name="Dead", url="https://a/y",
                         kind="atom", tier="1a", consecutive_failures=4, last_status="failed",
                         last_error="HTTP 500"),
                NewsAnchor(id=uuid.uuid4(), workspace_id=WS_A, kind="vendor", term="twilio",
                           normalized_term="twilio", origin_kind="env", active=True),
                NewsAnchor(id=uuid.uuid4(), workspace_id=WS_B, kind="vendor", term="other-tenant",
                           normalized_term="other tenant", origin_kind="env", active=True),
            ]
        )
        await s.commit()


async def test_it_is_private(client):
    assert client.get("/api/v1/news/overview").status_code == 401


async def test_overview_is_tenant_scoped(client, seeded):
    data = client.get("/api/v1/news/overview", headers=h(WS_A)).json()
    terms = [a["term"] for kind in data["anchors"].values() for a in kind]
    assert terms == ["twilio"], "another workspace's anchors leaked into this one"


async def test_a_dead_feed_is_named_not_hidden(client, seeded):
    data = client.get("/api/v1/news/overview", headers=h(WS_A)).json()
    dead = next(f for f in data["feeds"] if f["name"] == "Dead")
    assert dead["down"] is True
    assert data["feeds"][0]["name"] == "Dead", "a broken feed should sort first"
    assert any(line.startswith("DOWN  Dead") for line in data["feed_alarms"])


async def test_the_page_says_when_the_lane_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "news_lane", False)
    assert client.get("/api/v1/news/overview", headers=h(WS_A)).json()["lane_on"] is False


async def test_standing_facts_round_trip(client):
    body = {"facts": [
        {"anchor_kind": "problem_pattern", "anchor_term": "leads go cold",
         "lesson": "Nobody follows up."},
        {"anchor_kind": "client_solution", "anchor_term": "an AI receptionist for shops",
         "lesson": "Voice reception."},
    ]}
    saved = client.put("/api/v1/news/standing-facts", headers=h(WS_A), json=body)
    assert saved.status_code == 200 and saved.json()["written"] == 2
    facts = client.get("/api/v1/news/overview", headers=h(WS_A)).json()["standing_facts"]
    assert {f["anchor_term"] for f in facts} == {"leads go cold", "an AI receptionist for shops"}


async def test_a_standing_fact_naming_someone_is_refused_with_the_reason(client):
    body = {"facts": [{"anchor_kind": "client_solution",
                       "anchor_term": "reception for ziv@kivimedia.co", "lesson": "x"}]}
    r = client.put("/api/v1/news/standing-facts", headers=h(WS_A), json=body)
    assert r.status_code == 422
    assert "categories" in r.json()["detail"]


# --- the manual request -------------------------------------------------------

from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from tce.models.editorial import EvidenceMoment, EvidenceSource  # noqa: E402

PAGE = (
    "Twilio forwarded calls that are not answered now fall back to the configured "
    "voicemail after twenty seconds."
)
VERDICT = {
    "verdict": "publish",
    "verdict_reason": "Changes a shop's unanswered calls.",
    "what_happened": "Unanswered forwarded calls fall back to voicemail.",
    "audience_consequence": "Missed calls route differently.",
    "distinct_claim": "I run reception for shops.",
    "do_differently": ["Check where an unanswered call ends up."],
    "confirmed_facts": [{"claim": "Fallback", "quote": "fall back to the configured voicemail"}],
    "ziv_interpretation": ["Owners never check this."],
    "predictions": ["Fewer silent calls."],
    "format": "changes_my_product",
    "perishability": "week",
    "story_weight": "small",
    "weight_reason": "",
    "scores": {"owner_relevance": 5, "consequence_specificity": 4, "distinctiveness": 4},
}


@pytest.fixture
def fakes(monkeypatch):
    import tce.llm
    import tce.services.url_fetcher as fetcher

    async def page(url, timeout_s=15.0):
        return {"title": "Forwarding fallback", "body_text": PAGE}

    async def model(request):
        return SimpleNamespace(structured=VERDICT, job_id=uuid.uuid4())

    monkeypatch.setattr(fetcher, "fetch_url_text", page)
    monkeypatch.setattr(tce.llm, "complete", model)


@pytest.fixture
async def his_commit(editorial_sessionmaker):
    async with editorial_sessionmaker() as s:
        src = EvidenceSource(
            id=uuid.uuid4(), workspace_id=WS_A, source_kind="github_commit_group",
            external_id="kivimedia/receptionist@1", version_hash="v1",
            occurred_at=datetime.utcnow() - timedelta(days=2), fetch_status="ok",
            payload_private={"repo": "kivimedia/receptionist", "commits": []},
        )
        s.add(src)
        s.add(EvidenceMoment(
            id=uuid.uuid4(), workspace_id=WS_A, source_id=src.id, source_version_hash="v1",
            excerpt_private="Route unanswered Twilio calls to after-hours voicemail.",
            lesson_summary="Unanswered calls should land somewhere.", claim_type="demonstrated",
            speaker_confidence="high", status="active", sensitivity_flags=[],
        ))
        await s.commit()


async def test_a_news_site_writeup_is_refused_with_what_to_do(client):
    r = client.post("/api/v1/news/check", headers=h(WS_A),
                    json={"url": "https://techcrunch.com/2026/09/story"})
    assert r.json()["status"] == "unverified"
    assert "announcement itself" in r.json()["why"]


async def test_a_manual_check_matches_names_it_and_appraises(client, fakes, his_commit):
    r = client.post("/api/v1/news/check", headers=h(WS_A),
                    json={"url": "https://vendor.example/r/forwarding"})
    body = r.json()
    assert body["status"] == "matched" and body["appraising"] is True
    assert "twilio" in body["why"].lower(), "the match was not named"

    item = client.get(f"/api/v1/news/items/{body['item_id']}", headers=h(WS_A)).json()
    assert item["state"] == "appraised"
    assert item["appraisal"]["verdict"] == "publish"
    assert "next weekly selection" in item["appraisal"]["next"]


async def test_a_non_match_says_why_and_spends_nothing(client, fakes, monkeypatch):
    import tce.llm
    import tce.services.url_fetcher as fetcher

    async def page(url, timeout_s=15.0):
        return {"title": "A theme", "body_text": "A new colour theme for the settings page."}

    calls = []

    async def model(request):  # pragma: no cover - must not run
        calls.append(request)

    monkeypatch.setattr(fetcher, "fetch_url_text", page)
    monkeypatch.setattr(tce.llm, "complete", model)
    body = client.post("/api/v1/news/check", headers=h(WS_A),
                       json={"url": "https://vendor.example/r/theme"}).json()
    assert body["status"] == "no_match" and body["why"]
    assert "appraising" not in body and calls == []


async def test_another_workspace_cannot_read_the_item(client, fakes, his_commit):
    body = client.post("/api/v1/news/check", headers=h(WS_A),
                       json={"url": "https://vendor.example/r/forwarding"}).json()
    assert client.get(f"/api/v1/news/items/{body['item_id']}", headers=h(WS_B)).status_code == 404
