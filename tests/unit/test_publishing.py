"""TCE publishes the edited video itself. Synthetic data; the skills and the model are faked.

26-Sep: "I want tce to be able to do the full publishing and to show me the post in
the library".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.llm.provider import LLMResult
from tce.models.editorial import RecordingUpload, TopicCandidate, VideoPublication
from tce.production import publishing
from tce.settings import settings

KEY = "publish-test-key"


# ------------------------------------------------------------------- pure parts


def test_copy_follows_his_dash_rule_and_each_platform_keeps_only_its_fields():
    out = publishing.clean_copy(
        {
            "instagram": {"caption": "Hook — line", "extra": "x"},
            "facebook": {"message": "One – two"},
            "youtube": {"title": "T", "description": "D", "tags": ["#shorts", " event "]},
            "linkedin": {"message": "M", "hashtags": ["#Event Industry", "Coaching"]},
        }
    )
    assert out["instagram"] == {"caption": "Hook - line"}
    assert out["facebook"]["message"] == "One - two"
    assert out["youtube"]["tags"] == ["shorts", "event"]
    assert out["linkedin"]["hashtags"] == ["EventIndustry", "Coaching"]


def test_each_platform_gets_the_tested_skill_command():
    ig = publishing.command("instagram", {"caption": "c"}, media_path="/v.mp4", media_url="u", at_iso=None)
    assert ig[:3] == ["node", "dist/cli.js", "publish"] and ["--type", "reel"] == ig[3:5]
    yt = publishing.command(
        "youtube", {"title": "t", "description": "d", "tags": ["a", "shorts"]},
        media_path="/v.mp4", media_url="u", at_iso="2026-10-01T06:00:00Z",
    )
    assert yt[2:4] == ["schedule", "--at"] and "a,shorts" in yt and "public" in yt
    li = publishing.command("linkedin", {"message": "m", "hashtags": ["X"]}, media_path="/v.mp4",
                            media_url="http://127.0.0.1:8200/f.mp4", at_iso=None)
    assert "http://127.0.0.1:8200/f.mp4" in li and "/v.mp4" not in li, "LinkedIn fetches a URL"


def test_the_live_post_is_read_back_from_each_skill():
    assert publishing.read_result("instagram", "Published: db_id=abc12345-1 ig_media=1 ig_post=178")["post_id"] == "178"
    fb = publishing.read_result("facebook", "Published: db_id=x fb_post_id=984_122 at=now")
    assert fb["url"] == "https://www.facebook.com/984_122"
    yt = publishing.read_result("youtube", "Published: video id=AbC123\nURL: ...")
    assert yt["url"] == "https://youtube.com/shorts/AbC123"
    li = publishing.read_result("linkedin", "Published: post_id=9f0e1d2c-aaaa  linkedin_post_id=urn:li:share:7 at=x")
    assert li["url"] == "https://www.linkedin.com/feed/update/urn:li:share:7/"
    assert publishing.read_result("linkedin", "linkedin_post_id=(not returned by service)")["post_id"] is None


def test_only_what_he_says_in_the_edit_feeds_the_copy():
    words = [
        {"text": "kept", "start_s": 0.0, "end_s": 0.5},
        {"text": "cut", "start_s": 2.0, "end_s": 2.5},
        {"text": "also", "start_s": 4.0, "end_s": 4.5},
    ]
    assert publishing.spoken_text(words, [[0.0, 1.0], [3.5, 5.0]]) == "kept also"


# -------------------------------------------------------------------- the flow


@pytest.fixture
async def app_client(editorial_sessionmaker, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    ran: list[tuple[str, list[str]]] = []

    async def fake_ask(kind, prompt, system, schema, ws, key):
        assert kind == publishing.COPY_JOB and "What he says in the edited video" in prompt
        return LLMResult(job_id=uuid.uuid4(), text="", model="claude-opus-5-5", structured={
            "instagram": {"caption": "IG caption"},
            "facebook": {"message": "FB post"},
            "youtube": {"title": "Put the follow-up call in the deal", "description": "D #shorts", "tags": ["shorts"]},
            "linkedin": {"message": "LI post", "hashtags": ["Coaching"]},
        })

    async def fake_social(upload_id, ws):
        return tmp_path / "social.mp4"

    outputs = {
        "instagram": (0, "Published: db_id=11111111-2222 ig_media=5 ig_post=178"),
        "facebook": (0, "Published: db_id=x fb_post_id=984_1 at=now"),
        "youtube": (0, "Published: video id=YT1"),
        "linkedin": (1, "Error: LinkedIn session logged_out"),
    }

    async def fake_run(platform, argv):
        ran.append((platform, argv))
        return outputs[platform]

    async def no_permalink(media_id):
        return f"https://www.instagram.com/reel/{media_id}/"

    monkeypatch.setattr(prod, "_ask", fake_ask)
    monkeypatch.setattr(prod, "_social_copy", fake_social)
    monkeypatch.setattr(prod, "run_platform", fake_run)
    monkeypatch.setattr(prod, "_instagram_permalink", no_permalink)

    app = FastAPI()
    app.include_router(prod.router, prefix="/api/v1")

    async def _db():
        async with editorial_sessionmaker() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, editorial_sessionmaker, ran


async def seed(sm) -> tuple[uuid.UUID, uuid.UUID]:
    ws = uuid.uuid4()
    async with sm() as s:
        cand = TopicCandidate(
            workspace_id=ws, week_start=datetime(2026, 9, 21), moment_ids=["m"], title="Walk",
            lesson="l", audience="a", public_angle="p", gates={}, status="recorded",
        )
        s.add(cand)
        await s.flush()
        up = RecordingUpload(
            workspace_id=ws, candidate_id=cand.id, original_filename="w.mp4", storage_path="/tmp/w.mp4",
            sha256=uuid.uuid4().hex * 2, status="edited", edited_path="/tmp/w-edited.mp4",
            transcript=[{"text": "hello", "start_s": 0.0, "end_s": 0.5, "precision": "word"}],
            edit_plan={"keep": [[0.0, 1.0]]},
        )
        s.add(up)
        await s.commit()
        return ws, up.id


def h(ws) -> dict:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


async def test_posts_are_written_edited_posted_and_each_live_link_is_kept(app_client):
    client, sm, ran = app_client
    ws, uid = await seed(sm)

    await prod.draft_posts(uid, ws)
    body = (await client.get(f"/api/v1/production/uploads/{uid}/publishing", headers=h(ws))).json()
    assert [p["status"] for p in body["platforms"]] == ["draft"] * 4

    # He changes the Instagram caption; what goes out is his version.
    saved = await client.put(f"/api/v1/production/uploads/{uid}/publishing/instagram",
                             json={"fields": {"caption": "My own caption — edited"}}, headers=h(ws))
    assert saved.json()["copy"]["caption"] == "My own caption - edited"

    started = await client.post(f"/api/v1/production/uploads/{uid}/publishing/publish",
                                json={"platforms": list(publishing.PLATFORMS)}, headers=h(ws))
    assert started.status_code == 202
    await prod.publish_video(uid, ws, list(publishing.PLATFORMS), None)

    async with sm() as s:
        pubs = {p.platform: p for p in (await s.execute(
            VideoPublication.__table__.select().where(VideoPublication.upload_id == uid))).all()}
    assert pubs["instagram"].status == "posted" and pubs["instagram"].url.endswith("/reel/178/")
    assert pubs["facebook"].url == "https://www.facebook.com/984_1"
    assert pubs["youtube"].url == "https://youtube.com/shorts/YT1"
    # One platform failing never stops the others, and says why.
    assert pubs["linkedin"].status == "failed" and "logged_out" in pubs["linkedin"].detail
    ig_argv = next(a for p, a in ran if p == "instagram")
    assert "My own caption - edited" in ig_argv

    # Already out: it cannot go out twice.
    again = await client.post(f"/api/v1/production/uploads/{uid}/publishing/publish",
                              json={"platforms": ["instagram"]}, headers=h(ws))
    assert again.status_code == 409


async def test_scheduling_needs_a_real_future_time(app_client):
    client, sm, _ = app_client
    ws, uid = await seed(sm)
    await prod.draft_posts(uid, ws)
    soon = await client.post(f"/api/v1/production/uploads/{uid}/publishing/publish",
                             json={"platforms": ["facebook"], "at": "2020-01-01T00:00:00Z"}, headers=h(ws))
    assert soon.status_code == 400


async def test_the_linkedin_file_link_only_opens_with_its_token(app_client, tmp_path):
    client, sm, _ = app_client
    ws, uid = await seed(sm)
    bad = await client.get(f"/api/v1/production/social-media/{uid}/nope.mp4")
    assert bad.status_code == 404
    assert Path(prod._media_token(uid)).name  # derived, stable
