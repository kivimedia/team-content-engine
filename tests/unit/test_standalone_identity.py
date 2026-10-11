"""The client entry point never trusts a workspace header or owner login."""

from __future__ import annotations

import base64
import secrets
import subprocess
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from tce.db.base import Base
from tce.db.session import get_db
from tce.standalone import materials as materials_module
from tce.standalone import recording as recording_module
from tce.standalone import secrets as secrets_module
from tce.standalone.app import create_standalone_app
from tce.standalone.auth import CSRF_COOKIE, hash_password, token_hash
from tce.standalone.models import (
    StandaloneAccount,
    StandaloneInvite,
    StandaloneMembership,
    StandaloneWorkspace,
)

INVITE_TOKEN = secrets.token_urlsafe(32)
TEST_PASSWORD = secrets.token_urlsafe(24)
UNUSED_PASSWORD = secrets.token_urlsafe(24)
ACTIVATE_PASSWORD = secrets.token_urlsafe(24)
DIFFERENT_PASSWORD = secrets.token_urlsafe(24)
WRONG_PASSWORD = secrets.token_urlsafe(24)
FAKE_OPENAI_KEY = secrets.token_urlsafe(24)


@pytest.fixture
async def clients(monkeypatch, tmp_path):
    monkeypatch.setenv("TCE_STANDALONE_INSECURE_DEV_COOKIES", "1")
    monkeypatch.setenv("TCE_STANDALONE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("TCE_STANDALONE_ENCRYPTION_KEY", base64.b64encode(b"k" * 32).decode())
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[t for t in Base.metadata.tables.values() if t.name.startswith("standalone_")],
        )
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    ws_ids = []
    async with sessionmaker() as db:
        for name in ("ken", "other"):
            account = StandaloneAccount(
                email=f"{name}@example.test",
                password_hash=hash_password(TEST_PASSWORD),
                email_verified_at=datetime.now(UTC),
            )
            workspace = StandaloneWorkspace(name=name.title(), slug=name, timezone="UTC")
            db.add_all([account, workspace])
            await db.flush()
            db.add(
                StandaloneMembership(workspace_id=workspace.id, account_id=account.id, role="owner")
            )
            ws_ids.append(workspace.id)
        invited = StandaloneAccount(
            email="new@example.test", password_hash=hash_password(UNUSED_PASSWORD)
        )
        new_workspace = StandaloneWorkspace(name="New", slug="new", timezone="UTC")
        db.add_all([invited, new_workspace])
        await db.flush()
        db.add_all(
            [
                StandaloneMembership(
                    workspace_id=new_workspace.id, account_id=invited.id, role="owner"
                ),
                StandaloneInvite(
                    workspace_id=new_workspace.id,
                    account_id=invited.id,
                    token_hash=token_hash(INVITE_TOKEN),
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                ),
            ]
        )
        await db.commit()

    async def test_db():
        async with sessionmaker() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app = create_standalone_app()
    app.dependency_overrides[get_db] = test_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, ws_ids
    await engine.dispose()


def config(name: str):
    return {
        "display_name": name,
        "timezone": "America/New_York",
        "audience": "Coaches",
        "focus": "Good ideas from actual work",
        "voice_notes": "Direct and specific",
        "avoid": "Generic claims",
        "brain_mode": "claude_code",
        "source_lanes": [
            {"name": "Book", "kind": "book", "filter": "Chapter 1", "comments": "Use examples"},
            {"name": "Research", "kind": "research", "filter": "coaching", "comments": ""},
            {"name": "Course", "kind": "course", "filter": "module 3", "comments": ""},
        ],
    }


@pytest.mark.asyncio
async def test_client_assets_use_a_content_version(clients):
    client, _ = clients
    response = await client.get("/app")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    import re

    versions = re.findall(r"/static/app\.(?:css|js)\?v=([0-9a-f]{12})", response.text)
    assert len(versions) == 2 and versions[0] == versions[1]


@pytest.mark.asyncio
async def test_saved_source_preview_shows_only_active_material_from_own_lane(clients):
    client, _ = clients
    login = await client.post(
        "/auth/login",
        json={"email": "ken@example.test", "password": TEST_PASSWORD, "workspace": "ken"},
    )
    assert login.status_code == 200
    headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    saved = await client.put(
        "/api/config",
        json={"expected_revision": 0, "config": config("Ken")},
        headers=headers,
    )
    assert saved.status_code == 200
    material = await client.post(
        "/api/materials",
        data={"kind": "source", "lane_index": "0", "notes": "A real example"},
        files={
            "file": (
                "chapter.txt",
                b"A client fixed the intake form before adding AI.",
                "text/plain",
            )
        },
        headers=headers,
    )
    assert material.status_code == 201, material.text
    preview = await client.post("/api/sources/0/preview", headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["items_found"] == 1
    assert preview.json()["items"][0]["title"] == "chapter.txt"
    assert "intake form" in preview.json()["items"][0]["excerpt"]
    assert preview.json()["filter"] == "Chapter 1"
    assert (await client.post("/api/sources/4/preview", headers=headers)).status_code == 404
    paused = await client.post(
        f"/api/materials/{material.json()['id']}/active?active=false", headers=headers
    )
    assert paused.status_code == 200
    assert (await client.post("/api/sources/0/preview", headers=headers)).json()["items_found"] == 0

    other = await client.post(
        "/auth/login",
        json={"email": "other@example.test", "password": TEST_PASSWORD, "workspace": "other"},
    )
    assert other.status_code == 200
    other_headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    assert (await client.post("/api/sources/0/preview", headers=other_headers)).status_code == 409


@pytest.mark.asyncio
async def test_jennifer_visual_review_uses_client_video_frames_and_stays_private(
    clients, monkeypatch, tmp_path
):
    client, _ = clients
    assert (
        await client.post(
            "/auth/login",
            json={"email": "ken@example.test", "password": TEST_PASSWORD, "workspace": "ken"},
        )
    ).status_code == 200
    headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    idea = await client.post(
        "/api/ideas",
        json={"title": "Real intake lesson", "angle": "Fix intake before adding AI"},
        headers=headers,
    )
    assert idea.status_code == 200
    video_path = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-nostdin", "-v", "error", "-f", "lavfi",
            "-i", "color=c=blue:s=320x240:d=2", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=2", "-c:v", "libx264",
            "-c:a", "aac", str(video_path),
        ],
        check=True,
        capture_output=True,
    )
    upload = await client.post(
        f"/api/ideas/{idea.json()['id']}/recordings",
        files={"file": ("sample.mp4", video_path.read_bytes(), "video/mp4")},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    observed = {}

    async def fake_brain(db, workspace_id, system, prompt, *, images=None, **kwargs):
        if not images:
            return "Fix intake before adding AI."
        observed["workspace_id"] = workspace_id
        observed["system"] = system
        observed["images"] = images
        return "The speaker is centered against a plain blue background."

    monkeypatch.setattr(recording_module, "ask_brain", fake_brain)
    review = await client.post(
        f"/api/recordings/{upload.json()['id']}/visual-review", headers=headers
    )
    assert review.status_code == 200, review.text
    assert len(observed["images"]) == 3
    assert all(image.startswith(b"\xff\xd8") for image in observed["images"])
    assert review.json()["audio_reviewed"] is False
    assert "centered" in review.json()["summary"]
    assert (
        await client.get(f"/api/recordings/{upload.json()['id']}")
    ).json()["qc"]["visual_review"]["summary"] == review.json()["summary"]

    async def verified(kind, value):
        return kind == "openai_live"

    monkeypatch.setattr(secrets_module, "_verify", verified)
    key = await client.put(
        "/api/secrets/openai_live", json={"value": FAKE_OPENAI_KEY}, headers=headers
    )
    assert key.status_code == 200 and key.json()["verified"]

    class FakeCaptionProvider:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            assert kwargs["data"]["model"] == "whisper-1"
            assert kwargs["data"]["response_format"] == "verbose_json"
            return httpx.Response(
                200,
                json={
                    "text": "Fix intake before adding AI.",
                    "segments": [
                        {"start": 0.0, "end": 1.8, "text": "Fix intake before adding AI."}
                    ],
                },
            )

    monkeypatch.setattr(
        recording_module.httpx, "AsyncClient", lambda **kwargs: FakeCaptionProvider()
    )
    prepared = await client.post(
        f"/api/recordings/{upload.json()['id']}/prepare-export", headers=headers
    )
    assert prepared.status_code == 200, prepared.text
    assert "00:00:00,000 --> 00:00:01,800" in prepared.json()["captions"]
    manifest = await client.get(f"/api/recordings/{upload.json()['id']}/export-manifest")
    assert manifest.status_code == 200
    assert manifest.json()["transcript"] == "Fix intake before adding AI."
    assert manifest.json()["suggested_post_copy"] == "Fix intake before adding AI."
    assert (await client.post(
        f"/api/recordings/{upload.json()['id']}/prepare-export", headers=headers
    )).json() == prepared.json()
    assert (
        await client.post(
            "/auth/login",
            json={"email": "other@example.test", "password": TEST_PASSWORD, "workspace": "other"},
        )
    ).status_code == 200
    other_headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    assert (
        await client.post(
            f"/api/recordings/{upload.json()['id']}/visual-review", headers=other_headers
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/recordings/{upload.json()['id']}/prepare-export", headers=other_headers
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_audio_voice_sample_transcribes_only_with_clients_verified_key(
    clients, monkeypatch
):
    client, _ = clients
    assert (
        await client.post(
            "/auth/login",
            json={"email": "ken@example.test", "password": TEST_PASSWORD, "workspace": "ken"},
        )
    ).status_code == 200
    headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    sample = await client.post(
        "/api/materials",
        data={"kind": "voice", "notes": "Short and direct"},
        files={"file": ("voice.wav", b"RIFFsynthetic voice", "audio/wav")},
        headers=headers,
    )
    assert sample.status_code == 201
    endpoint = f"/api/materials/{sample.json()['id']}/transcribe"
    assert (await client.post(endpoint, headers=headers)).status_code == 409

    async def verified(kind, value):
        return kind == "openai_live"

    monkeypatch.setattr(secrets_module, "_verify", verified)
    key = await client.put(
        "/api/secrets/openai_live", json={"value": FAKE_OPENAI_KEY}, headers=headers
    )
    assert key.status_code == 200 and key.json()["verified"]

    class FakeProvider:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            assert url.endswith("/audio/transcriptions")
            assert kwargs["data"]["model"] == "gpt-4o-mini-transcribe"
            assert kwargs["headers"]["Authorization"].startswith("Bearer ")
            return httpx.Response(200, json={"text": "I speak plainly about real client work."})

    monkeypatch.setattr(materials_module.httpx, "AsyncClient", lambda **kwargs: FakeProvider())
    result = await client.post(endpoint, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["transcribed"] is True
    assert "real client work" in result.json()["transcript_excerpt"]

    assert (
        await client.post(
            "/auth/login",
            json={"email": "other@example.test", "password": TEST_PASSWORD, "workspace": "other"},
        )
    ).status_code == 200
    other_headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    assert (await client.post(endpoint, headers=other_headers)).status_code == 404


@pytest.mark.asyncio
async def test_claude_code_worker_leases_only_own_jobs_and_retries_failures(clients):
    client, _ = clients
    login = await client.post(
        "/auth/login",
        json={"email": "ken@example.test", "password": TEST_PASSWORD, "workspace": "ken"},
    )
    assert login.status_code == 200
    headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    assert (
        await client.put(
            "/api/config", json={"expected_revision": 0, "config": config("Ken")}, headers=headers
        )
    ).status_code == 200
    uploaded = await client.post(
        "/api/materials",
        data={"kind": "source", "lane_index": "0"},
        files={"file": ("chapter.txt", b"Fix client intake before adding AI.", "text/plain")},
        headers=headers,
    )
    assert uploaded.status_code == 201
    queued = await client.post("/api/scout", headers=headers)
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["job_id"]
    assert (await client.get(f"/api/jobs/{job_id}")).json()["status"] == "queued"
    assert (
        await client.post(
            "/auth/login",
            json={"email": "other@example.test", "password": TEST_PASSWORD, "workspace": "other"},
        )
    ).status_code == 200
    other_headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    other_grant = await client.post(
        "/api/tokens", json={"label": "Other worker", "scopes": ["worker"]},
        headers=other_headers,
    )
    assert other_grant.status_code == 200
    await client.post("/auth/logout", headers=other_headers)
    other_bearer = {"Authorization": f"Bearer {other_grant.json()['token']}"}
    assert (await client.post("/api/jobs/lease", headers=other_bearer)).json()["job"] is None
    assert (
        await client.post(
            "/auth/login",
            json={"email": "ken@example.test", "password": TEST_PASSWORD, "workspace": "ken"},
        )
    ).status_code == 200
    headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    granted = await client.post(
        "/api/tokens",
        json={"label": "Native Claude Code", "scopes": ["worker"]},
        headers=headers,
    )
    assert granted.status_code == 200
    token_id = granted.json()["id"]
    bearer = {"Authorization": f"Bearer {granted.json()['token']}"}
    await client.post("/auth/logout", headers=headers)
    identity = (await client.get("/auth/me", headers=bearer)).json()
    assert identity["scopes"] == ["worker"]
    assert datetime.fromisoformat(identity["token_expires_at"]) > datetime.now(UTC)
    assert (await client.get("/api/ideas", headers=bearer)).status_code == 403
    lease = await client.post("/api/jobs/lease", headers=bearer)
    assert lease.status_code == 200 and lease.json()["job"]["id"] == job_id
    assert "Fix client intake" in lease.json()["job"]["prompt"]
    lease_token = lease.json()["job"]["lease_token"]
    assert (await client.post("/api/jobs/lease", headers=bearer)).json()["job"] is None
    completed = await client.post(
        f"/api/jobs/{job_id}/complete",
        json={
            "lease_token": lease_token,
            "output": '[{"title":"Intake before AI","angle":"Fix intake before automation",'
            '"why_now":"Client asked","evidence":"Chapter example","source_ref":1}]',
        },
        headers=bearer,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "done"
    idea_id = completed.json()["result"]["ideas"][0]["id"]
    assert (await client.post(
        f"/api/jobs/{job_id}/complete",
        json={"lease_token": lease_token, "output": "repeat"}, headers=bearer
    )).status_code == 409

    login_again = await client.post(
        "/auth/login",
        json={"email": "ken@example.test", "password": TEST_PASSWORD, "workspace": "ken"},
    )
    assert login_again.status_code == 200
    headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    script = await client.post(f"/api/ideas/{idea_id}/script", headers=headers)
    assert script.status_code == 202
    script_job = script.json()["job_id"]
    await client.post("/auth/logout", headers=headers)
    first_lease = (await client.post("/api/jobs/lease", headers=bearer)).json()["job"]
    assert first_lease["id"] == script_job
    failed = await client.post(
        f"/api/jobs/{script_job}/fail",
        json={"lease_token": first_lease["lease_token"], "error_code": "needs_context"},
        headers=bearer,
    )
    assert failed.status_code == 200 and failed.json()["status"] == "failed"
    assert (
        await client.post(
            "/auth/login",
            json={"email": "ken@example.test", "password": TEST_PASSWORD, "workspace": "ken"},
        )
    ).status_code == 200
    headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    retried = await client.post(f"/api/jobs/{script_job}/retry", headers=headers)
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    await client.post("/auth/logout", headers=headers)
    second_lease = (await client.post("/api/jobs/lease", headers=bearer)).json()["job"]
    assert second_lease["id"] == script_job
    finished = await client.post(
        f"/api/jobs/{script_job}/complete",
        json={
            "lease_token": second_lease["lease_token"],
            "output": "First fix the intake questions. Then add AI only where it saves time.",
        },
        headers=bearer,
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["result"]["version"] == 1
    assert (
        await client.post(
            "/auth/login",
            json={"email": "ken@example.test", "password": TEST_PASSWORD, "workspace": "ken"},
        )
    ).status_code == 200
    headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    assert (await client.delete(f"/api/tokens/{token_id}", headers=headers)).status_code == 200
    await client.post("/auth/logout", headers=headers)
    assert (await client.post("/api/jobs/lease", headers=bearer)).status_code == 401

    assert (
        await client.post(
            "/auth/login",
            json={"email": "other@example.test", "password": TEST_PASSWORD, "workspace": "other"},
        )
    ).status_code == 200
    assert (await client.get(f"/api/jobs/{job_id}")).status_code == 404
    assert (await client.get(f"/api/jobs/{script_job}")).status_code == 404


@pytest.mark.asyncio
async def test_one_time_invitation_activates_client_without_exposing_another_workspace(clients):
    client, (ken_ws, _) = clients
    assert (
        await client.post(
            "/auth/login",
            json={
                "email": "new@example.test",
                "password": UNUSED_PASSWORD,
                "workspace": "new",
            },
        )
    ).status_code == 401
    assert (
        await client.post(
            "/auth/accept-invite",
            json={
                "token": secrets.token_urlsafe(32),
                "password": ACTIVATE_PASSWORD,
            },
        )
    ).status_code == 400
    accepted = await client.post(
        "/auth/accept-invite",
        json={"token": INVITE_TOKEN, "password": ACTIVATE_PASSWORD},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"email": "new@example.test", "workspace": "new"}
    assert (await client.get("/api/config")).status_code == 200
    assert (
        await client.get("/api/config", headers={"X-Workspace-Id": str(ken_ws)})
    ).status_code == 403
    assert (
        await client.post(
            "/auth/accept-invite",
            json={"token": INVITE_TOKEN, "password": DIFFERENT_PASSWORD},
        )
    ).status_code == 400


@pytest.mark.asyncio
async def test_login_config_history_and_workspace_boundary(clients):
    client, (ken_ws, other_ws) = clients
    assert (await client.get("/api/config")).status_code == 401
    assert (
        await client.post(
            "/auth/login",
            json={"email": "ken@example.test", "password": WRONG_PASSWORD, "workspace": "ken"},
        )
    ).status_code == 401
    response = await client.post(
        "/auth/login",
        json={
            "email": "ken@example.test",
            "password": TEST_PASSWORD,
            "workspace": "ken",
        },
    )
    assert response.status_code == 200
    assert response.json()["workspace_id"] == str(ken_ws)
    csrf = client.cookies[CSRF_COOKIE]
    assert (
        await client.get("/api/config", headers={"X-Workspace-Id": str(other_ws)})
    ).status_code == 403
    assert (
        await client.put("/api/config", json={"expected_revision": 0, "config": config("Ken")})
    ).status_code == 403
    saved = await client.put(
        "/api/config",
        json={"expected_revision": 0, "config": config("Ken")},
        headers={"X-TCE-CSRF": csrf},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert saved.json()["config"]["source_lanes"][0]["comments"] == "Use examples"
    conflict = await client.put(
        "/api/config",
        json={"expected_revision": 0, "config": config("Changed")},
        headers={"X-TCE-CSRF": csrf},
    )
    assert conflict.status_code == 409
    assert (await client.get("/api/config/history")).json()[0]["revision"] == 1
    token = await client.post(
        "/api/tokens",
        json={"label": "Claude", "scopes": ["read", "write"]},
        headers={"X-TCE-CSRF": csrf},
    )
    assert token.status_code == 200, token.text
    raw = token.json()["token"]
    await client.post("/auth/logout", headers={"X-TCE-CSRF": csrf})
    assert (await client.get("/api/config")).status_code == 401
    bearer = {"Authorization": f"Bearer {raw}"}
    assert (await client.get("/api/config", headers=bearer)).json()["revision"] == 1
    assert (
        await client.get("/api/config", headers={**bearer, "X-Workspace-Id": str(other_ws)})
    ).status_code == 403
    assert (
        await client.post("/api/tokens", headers=bearer, json={"label": "bad", "scopes": ["read"]})
    ).status_code == 403
    assert (await client.post("/api/publish", headers=bearer)).status_code == 404


@pytest.mark.asyncio
async def test_second_client_cannot_read_first_clients_config(clients):
    client, _ = clients
    for user in ("ken", "other"):
        response = await client.post(
            "/auth/login",
            json={
                "email": f"{user}@example.test",
                "password": TEST_PASSWORD,
                "workspace": user,
            },
        )
        assert response.status_code == 200
        if user == "ken":
            csrf = client.cookies[CSRF_COOKIE]
            assert (
                await client.put(
                    "/api/config",
                    json={"expected_revision": 0, "config": config("Ken")},
                    headers={"X-TCE-CSRF": csrf},
                )
            ).status_code == 200
        else:
            own = await client.get("/api/config")
            assert own.status_code == 200
            assert own.json()["revision"] == 0
            assert own.json()["config"]["display_name"] == "Other"


@pytest.mark.asyncio
async def test_private_material_and_secret_do_not_cross_clients(clients):
    client, _ = clients
    assert (
        await client.post(
            "/auth/login",
            json={
                "email": "ken@example.test",
                "password": TEST_PASSWORD,
                "workspace": "ken",
            },
        )
    ).status_code == 200
    csrf = client.cookies[CSRF_COOKIE]
    uploaded = await client.post(
        "/api/materials",
        files={"file": ("book.txt", b"An original client example", "text/plain")},
        data={"kind": "source", "lane_index": "0", "notes": "Source for ideas"},
        headers={"X-TCE-CSRF": csrf},
    )
    assert uploaded.status_code == 201, uploaded.text
    material_id = uploaded.json()["id"]
    assert (
        await client.get(f"/api/materials/{material_id}/download")
    ).content == b"An original client example"
    secret_value = "not-a-real-github-key"
    saved = await client.put(
        "/api/secrets/github",
        json={"value": secret_value},
        headers={"X-TCE-CSRF": csrf},
    )
    assert saved.status_code == 200
    assert secret_value not in saved.text
    assert secret_value not in (await client.get("/api/secrets")).text
    assert (
        await client.post(
            "/auth/login",
            json={
                "email": "other@example.test",
                "password": TEST_PASSWORD,
                "workspace": "other",
            },
        )
    ).status_code == 200
    assert (await client.get(f"/api/materials/{material_id}/download")).status_code == 404
    assert (await client.get("/api/materials")).json() == []
    assert (await client.get("/api/secrets")).json() == []


@pytest.mark.asyncio
async def test_web_scout_keeps_a_workspace_bound_source_link(clients, monkeypatch):
    from tce.standalone import workflow

    result = [
        '[{"title":"A current finding","angle":"Apply the finding to coaching",'
        '"evidence":"A specific published finding","source_ref":null,'
        '"source_url":"https://www.nist.gov/news-events/news/example",'
        '"source_lane_index":1}]'
    ]

    async def fake_brain(db, ws, system, prompt, **kwargs):
        assert kwargs["web_search"] is True
        return result[0]

    monkeypatch.setattr(workflow, "ask_brain", fake_brain)
    client, _ = clients
    assert (await client.post(
        "/auth/login",
        json={"email": "ken@example.test", "password": TEST_PASSWORD, "workspace": "ken"},
    )).status_code == 200
    headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    own_config = {**config("Ken"), "brain_mode": "anthropic_api"}
    assert (await client.put(
        "/api/config", json={"expected_revision": 0, "config": own_config}, headers=headers
    )).status_code == 200
    scout = await client.post("/api/scout", headers=headers)
    assert scout.status_code == 200, scout.text
    idea = scout.json()["ideas"][0]
    assert idea["source_item_id"] and idea["lane_index"] == 1
    assert idea["source_url"] == "https://www.nist.gov/news-events/news/example"
    listed = (await client.get("/api/ideas")).json()
    assert listed[0]["source_url"] == idea["source_url"]

    result[0] = result[0].replace("https://www.nist.gov/news-events/news/example", "http://localhost/private")
    assert (await client.post("/api/scout", headers=headers)).status_code == 422
    assert len((await client.get("/api/ideas")).json()) == 1

    assert (await client.post(
        "/auth/login",
        json={"email": "other@example.test", "password": TEST_PASSWORD, "workspace": "other"},
    )).status_code == 200
    assert (await client.get("/api/ideas")).json() == []


@pytest.mark.asyncio
async def test_claude_code_web_scout_requires_a_linked_source(clients):
    client, _ = clients
    assert (await client.post(
        "/auth/login",
        json={"email": "ken@example.test", "password": TEST_PASSWORD, "workspace": "ken"},
    )).status_code == 200
    headers = {"X-TCE-CSRF": client.cookies[CSRF_COOKIE]}
    assert (await client.put(
        "/api/config", json={"expected_revision": 0, "config": config("Ken")}, headers=headers
    )).status_code == 200
    queued = await client.post("/api/scout", headers=headers)
    assert queued.status_code == 202
    grant = await client.post(
        "/api/tokens", json={"label": "Synthetic worker", "scopes": ["worker"]}, headers=headers
    )
    bearer = {"Authorization": f"Bearer {grant.json()['token']}"}
    await client.post("/auth/logout", headers=headers)
    lease = (await client.post("/api/jobs/lease", headers=bearer)).json()["job"]
    assert lease["id"] == queued.json()["job_id"]
    body = {"lease_token": lease["lease_token"], "output": (
        '[{"title":"A current finding","angle":"Apply the finding to coaching",'
        '"evidence":"A published finding","source_ref":null,'
        '"source_url":"https://www.nist.gov/news-events/news/example",'
        '"source_lane_index":1}]'
    )}
    completed = await client.post(
        f"/api/jobs/{lease['id']}/complete", json=body, headers=bearer
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["result"]["ideas"][0]["source_url"].startswith("https://")


@pytest.mark.asyncio
async def test_scout_script_week_and_talk_are_workspace_bound(clients, monkeypatch):
    from tce.standalone import workflow

    async def fake_brain(db, ws, system, prompt, **kwargs):
        if "Find 3 to 6" in prompt:
            assert "An original client example" in prompt
            return (
                '[{"title":"An idea from the book","angle":"A specific coaching lesson",'
                '"why_now":"Clients ask about it","evidence":"Chapter one","source_ref":1}]'
            )
        if "Write a natural" in prompt:
            return (
                "Here is a practical lesson from my work. First, notice the pattern. "
                "Then try one concrete change with your next client."
            )
        return "I would put this idea first because the example is concrete."

    monkeypatch.setattr(workflow, "ask_brain", fake_brain)
    client, (ken_ws, _) = clients
    assert (
        await client.post(
            "/auth/login",
            json={
                "email": "ken@example.test",
                "password": TEST_PASSWORD,
                "workspace": "ken",
            },
        )
    ).status_code == 200
    csrf = client.cookies[CSRF_COOKIE]
    sync_config = {**config("Ken"), "brain_mode": "anthropic_api"}
    assert (
        await client.put(
            "/api/config",
            json={"expected_revision": 0, "config": sync_config},
            headers={"X-TCE-CSRF": csrf},
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/materials",
            files={"file": ("book.txt", b"An original client example", "text/plain")},
            data={"kind": "source", "lane_index": "0"},
            headers={"X-TCE-CSRF": csrf},
        )
    ).status_code == 201
    scouted = await client.post("/api/scout", headers={"X-TCE-CSRF": csrf})
    assert scouted.status_code == 200, scouted.text
    idea_id = scouted.json()["ideas"][0]["id"]
    assert scouted.json()["ideas"][0]["source_item_id"]
    scripted = await client.post(f"/api/ideas/{idea_id}/script", headers={"X-TCE-CSRF": csrf})
    assert scripted.status_code == 200, scripted.text
    assert scripted.json()["version"] == 1
    assert (
        await client.patch(
            f"/api/ideas/{idea_id}",
            json={"status": "this_week", "week_start": "2026-10-12"},
            headers={"X-TCE-CSRF": csrf},
        )
    ).status_code == 200
    week = await client.get("/api/week/2026-10-12")
    assert week.json()["ideas"][0]["id"] == idea_id
    talked = await client.post(
        "/api/talk/week",
        json={"message": "Which idea first?"},
        headers={"X-TCE-CSRF": csrf},
    )
    assert talked.status_code == 200, talked.text
    assert "concrete" in talked.json()["answer"]
    assert (
        await client.post(
            "/auth/login",
            json={
                "email": "other@example.test",
                "password": TEST_PASSWORD,
                "workspace": "other",
            },
        )
    ).status_code == 200
    assert (await client.get("/api/ideas")).json() == []
    assert (await client.get(f"/api/ideas/{idea_id}/scripts")).status_code == 404


@pytest.mark.asyncio
async def test_recording_review_and_edit_versions_are_private(clients, monkeypatch):
    from tce.standalone import delivery, recording, workflow

    monkeypatch.setattr(
        recording,
        "_probe",
        lambda path: {"duration_s": 5, "width": 1080, "height": 1920, "has_audio": True},
    )
    monkeypatch.setattr(
        recording,
        "_trim",
        lambda source, target, start, end: target.write_bytes(source.read_bytes()),
    )

    async def fake_brain(*args, **kwargs):
        return "I can suggest a cut. I have the technical check and your notes."

    monkeypatch.setattr(workflow, "ask_brain", fake_brain)
    client, _ = clients
    assert (
        await client.post(
            "/auth/login",
            json={
                "email": "ken@example.test",
                "password": TEST_PASSWORD,
                "workspace": "ken",
            },
        )
    ).status_code == 200
    csrf = client.cookies[CSRF_COOKIE]
    assert (
        await client.put(
            "/api/config",
            json={"expected_revision": 0, "config": config("Ken")},
            headers={"X-TCE-CSRF": csrf},
        )
    ).status_code == 200
    idea = await client.post(
        "/api/ideas",
        json={"title": "A coaching lesson", "angle": "One practical change"},
        headers={"X-TCE-CSRF": csrf},
    )
    idea_id = idea.json()["id"]
    upload = await client.post(
        f"/api/ideas/{idea_id}/recordings",
        files={"file": ("take.webm", b"fake-video-for-test", "video/webm")},
        headers={"X-TCE-CSRF": csrf},
    )
    assert upload.status_code == 201, upload.text
    recording_id = upload.json()["id"]
    assert upload.json()["qc"]["width"] == 1080
    talked = await client.post(
        f"/api/talk/jennifer?context_id={recording_id}",
        json={"message": "What would you cut?"},
        headers={"X-TCE-CSRF": csrf},
    )
    assert talked.status_code == 200, talked.text
    edited = await client.post(
        f"/api/recordings/{recording_id}/trim",
        json={"start_s": 1, "end_s": 3, "note": "Remove the lead-in"},
        headers={"X-TCE-CSRF": csrf},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 1
    manifest = await client.get(f"/api/recordings/{recording_id}/export-manifest")
    assert manifest.status_code == 200, manifest.text
    assert manifest.json()["render_version"] == 1
    assert manifest.json()["video"]["sha256"]
    assert manifest.json()["video"]["url"].endswith("version=selected")
    assert (await client.get(f"/api/recordings/{recording_id}/renders")).json()[0][
        "note"
    ] == "Remove the lead-in"
    monkeypatch.setenv("TCE_STANDALONE_FROM_EMAIL", "videos@example.test")
    monkeypatch.setenv("TCE_STANDALONE_PUBLIC_URL", "https://tce.example.test")
    sent_payloads = []

    async def fake_send(payload, key):
        sent_payloads.append((payload, key))
        return "email-receipt-123"

    monkeypatch.setattr(delivery, "_send_provider", fake_send)
    idem = uuid.uuid4().hex
    sent = await client.post(
        f"/api/recordings/{recording_id}/send-to-self",
        json={"idempotency_key": idem},
        headers={"X-TCE-CSRF": csrf},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"
    assert sent.json()["render_id"] == edited.json()["render_id"]
    assert sent_payloads[0][0]["to"] == ["ken@example.test"]
    again = await client.post(
        f"/api/recordings/{recording_id}/send-to-self",
        json={"idempotency_key": idem},
        headers={"X-TCE-CSRF": csrf},
    )
    assert again.status_code == 200
    assert len(sent_payloads) == 1
    assert (
        await client.post(
            f"/api/recordings/{recording_id}/original/select", headers={"X-TCE-CSRF": csrf}
        )
    ).json()["status"] == "uploaded"
    assert (
        await client.post(
            "/auth/login",
            json={
                "email": "other@example.test",
                "password": TEST_PASSWORD,
                "workspace": "other",
            },
        )
    ).status_code == 200
    assert (await client.get(f"/api/recordings/{recording_id}/video")).status_code == 404
    assert (await client.get(f"/api/recordings/{recording_id}/export-manifest")).status_code == 404


@pytest.mark.asyncio
async def test_live_session_uses_only_clients_verified_key(clients, monkeypatch):
    from tce.standalone import live, secrets

    async def verified(kind, value):
        return True

    async def provider(key, session, sdp):
        assert key == FAKE_OPENAI_KEY
        assert session["model"] == "gpt-live-1"
        assert session["delegation"] == {"type": "client"}
        assert "Ken" in session["instructions"]
        return {"session": {"id": "live_test"}, "transport": {"sdp": "answer-sdp"}}

    async def client_brain(db, workspace_id, system, prompt, **kwargs):
        assert "Actual client question" in prompt
        assert "this week's ideas" in system
        return "Use the book example first, then the research point."

    monkeypatch.setattr(secrets, "_verify", verified)
    monkeypatch.setattr(live, "_create_provider_session", provider)
    monkeypatch.setattr(live, "ask_brain", client_brain)
    client, _ = clients
    assert (
        await client.post(
            "/auth/login",
            json={
                "email": "ken@example.test",
                "password": TEST_PASSWORD,
                "workspace": "ken",
            },
        )
    ).status_code == 200
    csrf = client.cookies[CSRF_COOKIE]
    assert (
        await client.put(
            "/api/config",
            json={"expected_revision": 0, "config": config("Ken")},
            headers={"X-TCE-CSRF": csrf},
        )
    ).status_code == 200
    key = await client.put(
        "/api/secrets/openai_live",
        json={"value": FAKE_OPENAI_KEY},
        headers={"X-TCE-CSRF": csrf},
    )
    assert key.status_code == 200
    result = await client.post(
        "/api/live/session",
        json={"sdp": "offer-sdp-more-than-ten", "mode": "week"},
        headers={"X-TCE-CSRF": csrf},
    )
    assert result.status_code == 201, result.text
    assert result.json() == {"session_id": "live_test", "sdp": "answer-sdp"}
    assert FAKE_OPENAI_KEY not in result.text
    delegated = await client.post(
        "/api/live/delegation",
        json={
            "session_id": "live_test",
            "delegation_id": "delegate_test",
            "transcript": "Actual client question",
        },
        headers={"X-TCE-CSRF": csrf},
    )
    assert delegated.status_code == 200, delegated.text
    assert delegated.json()["answer"].startswith("Use the book example")
    assert (
        await client.post(
            "/api/live/delegation",
            json={"session_id": "wrong_test", "delegation_id": "delegate_test", "transcript": "X"},
            headers={"X-TCE-CSRF": csrf},
        )
    ).status_code == 404
