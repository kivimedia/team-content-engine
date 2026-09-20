"""Hook chooser contract between the recorder and the API. Synthetic data only.

The recorder shows the three ranked openings of a packet v2, and choosing one
must (1) create a new immutable packet version whose first spoken phrase is the
chosen opening, (2) leave the original untouched, (3) move the recording queue
to the new version, and (4) be refused while a take set of that candidate has
clips bound to an existing version.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from tce.api.routers import editorial as editorial_router
from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.models.editorial import RecordingPacket, TopicCandidate
from tce.settings import settings
from tests.unit.test_editorial_packets import good_output

KEY = "hook-choice-test-key"
WS = uuid.UUID("cafecafe-1111-4111-8111-111111111111")
AUTH = {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(WS)}


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path / "rec"))
    monkeypatch.setattr(settings, "production_google_export", "off")
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)

    app = FastAPI()
    app.include_router(prod.router, prefix="/api/v1")
    app.include_router(editorial_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: (
        editorial_sessionmaker
    )

    async def _db():
        async with editorial_sessionmaker() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def seed_v2(sessionmaker) -> tuple[TopicCandidate, RecordingPacket]:
    output = good_output()
    cand = TopicCandidate(
        id=uuid.uuid4(),
        workspace_id=WS,
        week_start=datetime(2026, 9, 14),
        moment_ids=["11111111-1111-1111-1111-111111111111"],
        title="Plan the course from the problems",
        lesson="Start from what the person can do afterward.",
        audience="coaches",
        public_angle="The outline question.",
        gates={},
        status="selected",
    )
    packet = RecordingPacket(
        id=uuid.uuid4(),
        workspace_id=WS,
        candidate_id=cand.id,
        version=1,
        bullets=output["bullets"],
        script_phrases=output["script_phrases"],
        facebook_post=output["facebook_post"],
        linkedin_post=output["linkedin_post"],
        interviewer_prompt=output["interviewer_prompt"],
        hook_options=output["hook_options"],
        selected_hook_id=output["selected_hook_id"],
        beats=output["beats"],
        citations_private=[],
        public_safety={"status": "clean", "issues": []},
        status="ready",
    )
    async with sessionmaker() as s:
        s.add_all([cand, packet])
        await s.commit()
    return cand, packet


def hook_text(packet_json: dict, hook_id: str) -> str:
    return next(h["text"] for h in packet_json["hook_options"] if h["id"] == hook_id)


async def test_queue_exposes_ranked_hooks_and_a_choice_creates_a_new_bound_version(
    client, editorial_sessionmaker
):
    cand, original = await seed_v2(editorial_sessionmaker)

    queue = (await client.get("/api/v1/production/recording-queue", headers=AUTH)).json()
    idea = queue["ideas"][0]
    assert idea["packet_format"] == "v2"
    assert idea["packet_id"] == str(original.id) and idea["packet_version"] == 1
    assert [h["id"] for h in idea["hook_options"]] == ["hook-1", "hook-2", "hook-3"]
    assert idea["selected_hook_id"] == "hook-1"
    assert all(
        {"text", "question", "rationale", "payoff_phrase_id"} <= set(h)
        for h in idea["hook_options"]
    )
    assert idea["script_phrases"][0] == hook_text(idea, "hook-1")

    chosen = await client.post(
        f"/api/v1/editorial/packets/{original.id}/choose-hook",
        json={"hook_id": "hook-2"},
        headers=AUTH,
    )
    assert chosen.status_code == 200, chosen.text
    new = chosen.json()
    assert new["id"] != str(original.id)
    assert new["version"] == 2
    assert new["selected_hook_id"] == "hook-2"
    # The selected opening is the first spoken phrase; everything after it is unchanged.
    assert new["script_phrases"][0] == hook_text(new, "hook-2")
    assert new["script_phrases"][1:] == idea["script_phrases"][1:]
    assert new["bullets"] == idea["bullets"] and new["beats"] == idea["beats"]

    # The queue now hands the recorder the new version, with no session bound yet.
    queue = (await client.get("/api/v1/production/recording-queue", headers=AUTH)).json()
    assert queue["count"] == 1
    idea = queue["ideas"][0]
    assert idea["packet_id"] == new["id"] and idea["packet_version"] == 2
    assert idea["selected_hook_id"] == "hook-2"
    assert idea["active_session_id"] is None


async def test_original_packet_is_immutable_after_a_choice(client, editorial_sessionmaker):
    cand, original = await seed_v2(editorial_sessionmaker)
    before = (await client.get(f"/api/v1/editorial/packets/{original.id}", headers=AUTH)).json()
    r = await client.post(
        f"/api/v1/editorial/packets/{original.id}/choose-hook",
        json={"hook_id": "hook-3"},
        headers=AUTH,
    )
    assert r.status_code == 200
    after = (await client.get(f"/api/v1/editorial/packets/{original.id}", headers=AUTH)).json()
    assert after == before
    assert after["version"] == 1 and after["selected_hook_id"] == "hook-1"
    versions = (
        await client.get(f"/api/v1/editorial/candidates/{cand.id}/packets", headers=AUTH)
    ).json()["packets"]
    assert sorted(p["version"] for p in versions) == [1, 2]


async def test_choice_is_refused_while_a_take_set_has_clips(client, editorial_sessionmaker):
    cand, original = await seed_v2(editorial_sessionmaker)

    # A draft take set (opened, nothing recorded) does not freeze the opening.
    draft = await client.post(
        "/api/v1/production/recording-sessions",
        json={"candidate_id": str(cand.id), "packet_id": str(original.id)},
        headers=AUTH,
    )
    assert draft.status_code == 201, draft.text
    assert draft.json()["session"]["status"] == "draft"
    allowed = await client.post(
        f"/api/v1/editorial/packets/{original.id}/choose-hook",
        json={"hook_id": "hook-2"},
        headers=AUTH,
    )
    assert allowed.status_code == 200
    second = allowed.json()

    # The first clip binds the draft take set to version 1: from now on no
    # version of this candidate may change its opening until that set is finished.
    clip = await client.post(
        f"/api/v1/production/recording-sessions/{draft.json()['session']['id']}/clips",
        json={"local_clip_id": str(uuid.uuid4()), "mime_type": "video/webm", "extension": "webm"},
        headers=AUTH,
    )
    assert clip.status_code == 201, clip.text
    session = (
        await client.get(
            f"/api/v1/production/recording-sessions/{draft.json()['session']['id']}", headers=AUTH
        )
    ).json()["session"]
    assert session["status"] == "recording"

    for packet_id in (original.id, second["id"]):
        refused = await client.post(
            f"/api/v1/editorial/packets/{packet_id}/choose-hook",
            json={"hook_id": "hook-3"},
            headers=AUTH,
        )
        assert refused.status_code == 409, refused.text
        assert "take set is in progress on packet version 1" in refused.json()["detail"]

    versions = (
        await client.get(f"/api/v1/editorial/candidates/{cand.id}/packets", headers=AUTH)
    ).json()["packets"]
    assert sorted(p["version"] for p in versions) == [1, 2]


async def test_legacy_packet_offers_no_hook_choice(client, editorial_sessionmaker):
    cand, packet = await seed_v2(editorial_sessionmaker)
    async with editorial_sessionmaker() as s:
        row = await s.get(RecordingPacket, packet.id)
        row.hook_options = []
        row.selected_hook_id = None
        row.beats = []
        await s.commit()
    idea = (await client.get("/api/v1/production/recording-queue", headers=AUTH)).json()["ideas"][0]
    assert idea["packet_format"] == "legacy" and idea["hook_options"] == []
    r = await client.post(
        f"/api/v1/editorial/packets/{packet.id}/choose-hook",
        json={"hook_id": "hook-1"},
        headers=AUTH,
    )
    assert r.status_code == 404
