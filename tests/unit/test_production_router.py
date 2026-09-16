"""/production router: recordings, export, publications, activity, auth. Synthetic data."""

from __future__ import annotations

import subprocess
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.models.editorial import (
    EvidenceCollectionRun,
    RecordingPacket,
    RecordingUpload,
    TopicCandidate,
)
from tce.models.llm_job import LLMJob
from tce.production import media
from tce.settings import settings

KEY = "test-editor-key"
# Letters in the hex matter: SQLite gives a "UUID" column NUMERIC affinity, so an
# all-digit hex would be stored as a number.
WS = uuid.UUID("aaaaaaaa-1111-4111-8111-111111111111")
OTHER_WS = uuid.UUID("bbbbbbbb-2222-4222-8222-222222222222")
# Bearer callers may choose a workspace; proxy editors are pinned to the default one.
AUTH = {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(WS)}


def _candidate(ws=WS, title="Answer inquiries fast"):
    return TopicCandidate(
        id=uuid.uuid4(),
        workspace_id=ws,
        week_start=datetime(2026, 9, 7),
        moment_ids=[],
        title=title,
        lesson="Speed wins the first call.",
        audience="coaches",
        public_angle="Response time as a service.",
        gates={},
        status="selected",
    )


def _packet(candidate, ws=WS):
    return RecordingPacket(
        id=uuid.uuid4(),
        workspace_id=ws,
        candidate_id=candidate.id,
        version=1,
        bullets=[
            "Lead with the problem",
            "Name the ten minute rule",
            "Tell the walk story",
            "Show the checklist",
            "Close with one action",
        ],
        script_phrases=[
            "Most small studios lose leads in the first hour.",
            "Answer every new inquiry within ten minutes.",
        ],
        facebook_post="Synthetic Facebook draft.\nSecond paragraph.",
        linkedin_post="Synthetic LinkedIn draft.",
        citations_private=[{"moment_id": "m1", "excerpt_private": "PRIVATE-CITATION-TEXT"}],
        public_safety={"status": "clean", "issues": []},
    )


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path / "rec"))
    monkeypatch.setattr(settings, "production_google_export", "off")
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)

    app = FastAPI()
    app.include_router(prod.router, prefix="/api/v1")

    async def _db():
        async with editorial_sessionmaker() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def _seed(sessionmaker, *rows):
    async with sessionmaker() as s:
        for r in rows:
            s.add(r)
        await s.commit()


def _file(data=b"synthetic-video-bytes", name="walk.mp4", ctype="video/mp4"):
    return {"file": (name, data, ctype)}


async def test_auth_unset_503_and_missing_key_401(client, monkeypatch):
    r = await client.get("/api/v1/production/activity", headers={"X-Workspace-Id": str(WS)})
    assert r.status_code == 401
    monkeypatch.setattr(settings, "private_access_key", SecretStr(""))
    r = await client.get("/api/v1/production/activity", headers=AUTH)
    assert r.status_code == 503


async def test_editor_key_is_pinned_to_default_workspace(
    client, editorial_sessionmaker, monkeypatch
):
    cand = _candidate()
    await _seed(editorial_sessionmaker, cand)
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(WS))
    editor = {"X-TCE-Editor-Key": KEY}
    ok = await client.get(f"/api/v1/production/candidates/{cand.id}/recordings", headers=editor)
    assert ok.status_code == 200
    other = {"X-TCE-Editor-Key": KEY, "X-Workspace-Id": str(OTHER_WS)}
    assert (await client.get("/api/v1/production/activity", headers=other)).status_code == 403


async def test_recording_bound_dedupe_supersede_and_cross_workspace(client, editorial_sessionmaker):
    cand, other_cand, foreign = _candidate(), _candidate(title="Other idea"), _candidate(OTHER_WS)
    packet = _packet(cand)
    await _seed(editorial_sessionmaker, cand, other_cand, foreign, packet)
    url = f"/api/v1/production/candidates/{cand.id}/recording"

    r1 = await client.post(url, headers=AUTH, files=_file(b"take-one"))
    assert r1.status_code == 201, r1.text
    first = r1.json()
    assert first["candidate_id"] == str(cand.id)
    assert first["packet_id"] == str(packet.id)
    assert first["status"] == "uploaded" and first["deduplicated"] is False

    again = await client.post(url, headers=AUTH, files=_file(b"take-one", name="copy.mp4"))
    assert again.status_code == 200 and again.json()["deduplicated"] is True
    assert again.json()["id"] == first["id"]

    clash = await client.post(
        f"/api/v1/production/candidates/{other_cand.id}/recording",
        headers=AUTH,
        files=_file(b"take-one"),
    )
    assert clash.status_code == 409

    r2 = await client.post(url, headers=AUTH, files=_file(b"take-two"))
    assert r2.status_code == 201
    assert r2.json()["superseded_ids"] == [first["id"]]

    history = (
        await client.get(f"/api/v1/production/candidates/{cand.id}/recordings", headers=AUTH)
    ).json()
    statuses = {u["id"]: u["status"] for u in history["uploads"]}
    assert statuses[first["id"]] == "superseded"
    assert statuses[r2.json()["id"]] == "uploaded"

    async with editorial_sessionmaker() as s:
        c = (
            await s.execute(select(TopicCandidate).where(TopicCandidate.id == cand.id))
        ).scalar_one()
        assert c.status == "recorded"
        rows = (await s.execute(select(RecordingUpload))).scalars().all()
        assert len(rows) == 2 and all(r.workspace_id == WS for r in rows)
        assert all(str(WS) in r.storage_path and str(cand.id) in r.storage_path for r in rows)

    cross = await client.post(
        f"/api/v1/production/candidates/{foreign.id}/recording", headers=AUTH, files=_file(b"x")
    )
    assert cross.status_code == 404
    bad_type = await client.post(
        url, headers=AUTH, files=_file(b"y", name="a.txt", ctype="text/plain")
    )
    assert bad_type.status_code == 415


async def test_upload_size_limit(client, editorial_sessionmaker, monkeypatch):
    cand = _candidate()
    await _seed(editorial_sessionmaker, cand)
    monkeypatch.setattr(settings, "production_max_upload_bytes", 10)
    r = await client.post(
        f"/api/v1/production/candidates/{cand.id}/recording", headers=AUTH, files=_file(b"x" * 64)
    )
    assert r.status_code == 413


async def test_plan_edit_needs_review_and_captions(client, editorial_sessionmaker):
    cand = _candidate()
    packet = _packet(cand)
    packet.script_phrases = ["Do not send a price list before the first call."]
    await _seed(editorial_sessionmaker, cand, packet)
    up = (
        await client.post(
            f"/api/v1/production/candidates/{cand.id}/recording", headers=AUTH, files=_file(b"plan")
        )
    ).json()
    no_transcript = await client.post(
        f"/api/v1/production/uploads/{up['id']}/plan-edit", headers=AUTH
    )
    assert no_transcript.status_code == 409
    r = await client.post(
        f"/api/v1/production/uploads/{up['id']}/plan-edit",
        headers=AUTH,
        json={
            "transcript": [
                {
                    "start_s": 0,
                    "end_s": 3,
                    "text": "Do not send a price list before the first call.",
                },
                {"start_s": 3.5, "end_s": 6, "text": "Do send a price list before the first call."},
            ]
        },
    )
    body = r.json()
    assert body["status"] == "needs_review"
    assert "not" in body["status_detail"]
    render = await client.post(f"/api/v1/production/uploads/{up['id']}/render", headers=AUTH)
    assert render.status_code == 409  # blocked plan never renders silently
    srt = await client.get(f"/api/v1/production/uploads/{up['id']}/captions.srt", headers=AUTH)
    assert srt.status_code == 200 and "-->" in srt.text


async def test_transcribe_unavailable_without_local_worker(
    client, editorial_sessionmaker, monkeypatch
):
    monkeypatch.setattr(settings, "production_transcribe_ws_url", "")
    cand = _candidate()
    await _seed(editorial_sessionmaker, cand)
    up = (
        await client.post(
            f"/api/v1/production/candidates/{cand.id}/recording", headers=AUTH, files=_file(b"tr")
        )
    ).json()
    r = await client.post(f"/api/v1/production/uploads/{up['id']}/transcribe", headers=AUTH)
    assert r.json()["status"] == "unavailable"
    assert "Paid transcription is intentionally not used" in r.json()["status_detail"]


class FakeGoogle:
    def __init__(self, extra_perms=None):
        self.shared = []
        self.written = []
        self.extra = extra_perms or []

    async def available(self):
        return True, "fake"

    async def create_document(self, title):
        return {"id": "doc-123", "url": "https://docs.google.com/document/d/doc-123/edit"}

    async def write_blocks(self, document_id, blocks):
        self.written = blocks

    async def share_with_user(self, document_id, email, role):
        self.shared.append((email, role))

    async def list_permissions(self, document_id):
        perms = [{"type": "user", "role": "owner", "emailAddress": "owner@example.com"}]
        perms += [{"type": "user", "role": r, "emailAddress": e} for e, r in self.shared]
        return perms + self.extra


async def test_export_google_restricted_and_verified(client, editorial_sessionmaker, monkeypatch):
    cand = _candidate()
    packet = _packet(cand)
    await _seed(editorial_sessionmaker, cand, packet)
    fake = FakeGoogle()
    monkeypatch.setattr(prod, "google_client", lambda: fake)
    monkeypatch.setattr(settings, "production_doc_team_emails", "team@example.com")
    r = await client.post(f"/api/v1/production/packets/{packet.id}/export", headers=AUTH)
    body = r.json()
    assert body["status"] == "exported"
    assert body["access"]["verified"] is True
    assert "no link sharing" in body["access"]["intended"]
    assert fake.shared == [("team@example.com", "writer")]  # never type=anyone
    text = " ".join(b.text for b in fake.written)
    assert "PRIVATE-CITATION-TEXT" not in text
    assert [b.kind for b in fake.written][:3] == ["title", "heading", "bullet"]
    async with editorial_sessionmaker() as s:
        p = (
            await s.execute(select(RecordingPacket).where(RecordingPacket.id == packet.id))
        ).scalar_one()
        assert p.google_doc_id == "doc-123" and p.google_doc_access["verified"] is True

    leaky = FakeGoogle(extra_perms=[{"type": "anyone", "role": "reader"}])
    monkeypatch.setattr(prod, "google_client", lambda: leaky)
    r = await client.post(f"/api/v1/production/packets/{packet.id}/export", headers=AUTH)
    assert r.json()["status"] == "access_problem"
    assert r.json()["access"]["verified"] is False


async def test_export_not_connected_returns_private_docx(client, editorial_sessionmaker):
    from docx import Document

    cand = _candidate()
    packet = _packet(cand)
    await _seed(editorial_sessionmaker, cand, packet)
    r = await client.post(f"/api/v1/production/packets/{packet.id}/export", headers=AUTH)
    body = r.json()
    assert body["status"] == "not_connected"
    assert body["access"]["verified"] is False
    doc = await client.get(body["docx_url"], headers=AUTH)
    assert doc.status_code == 200
    assert (await client.get(body["docx_url"])).status_code == 401
    import io

    paras = [p.text for p in Document(io.BytesIO(doc.content)).paragraphs]
    assert "Answer every new inquiry within ten minutes." in paras
    assert paras.index("Walking bullets") < paras.index(
        "Most small studios lose leads in the first hour."
    )
    assert not any("PRIVATE-CITATION-TEXT" in p for p in paras)
    async with editorial_sessionmaker() as s:
        p = (
            await s.execute(select(RecordingPacket).where(RecordingPacket.id == packet.id))
        ).scalar_one()
        assert p.google_doc_access["status"] == "not_connected"
        assert p.google_doc_url is None


async def test_publication_receipt_dedup_and_outcome(client, editorial_sessionmaker):
    cand = _candidate()
    await _seed(editorial_sessionmaker, cand)
    url = f"/api/v1/production/candidates/{cand.id}/publications"
    payload = {
        "platform": "LinkedIn",
        "external_post_id": "post-1",
        "url": "https://example.com/p/1",
    }
    r1 = await client.post(url, headers=AUTH, json=payload)
    assert r1.status_code == 201 and r1.json()["duplicate"] is False
    r2 = await client.post(url, headers=AUTH, json=payload)
    assert r2.status_code == 200 and r2.json()["duplicate"] is True
    assert r2.json()["publication"]["id"] == r1.json()["publication"]["id"]
    pid = r1.json()["publication"]["id"]
    p = await client.patch(
        f"/api/v1/production/publications/{pid}",
        headers=AUTH,
        json={
            "outcome": {
                "qualified_conversations": 2,
                "strategy_sessions_booked": 1,
                "notes": "synthetic",
            }
        },
    )
    assert p.json()["outcome"]["qualified_conversations"] == 2
    p = await client.patch(
        f"/api/v1/production/publications/{pid}",
        headers=AUTH,
        json={"outcome": {"mentions": ["a"]}},
    )
    assert p.json()["outcome"]["strategy_sessions_booked"] == 1 and p.json()["outcome"][
        "mentions"
    ] == ["a"]
    other = {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(OTHER_WS)}
    assert (
        await client.patch(
            f"/api/v1/production/publications/{pid}",
            headers=other,
            json={"outcome": {"notes": "x"}},
        )
    ).status_code == 404


async def test_activity_is_workspace_scoped(client, editorial_sessionmaker):
    mine, theirs = _candidate(), _candidate(OTHER_WS)
    await _seed(
        editorial_sessionmaker,
        mine,
        theirs,
        LLMJob(
            workspace_id=WS,
            job_type="moment_extraction",
            agent_name="extractor",
            idempotency_key="k1",
            request_json={},
            policy_model="claude-opus-5",
            input_hash="h",
            status="waiting_capacity",
            attempt_count=1,
            retry_at=datetime(2026, 9, 16, 14, 5),
            receipt_json={
                "auth_method": "subscription",
                "modelUsage": {"claude-opus-5": {}},
                "session_token": "never-shown",
            },
        ),
        LLMJob(
            workspace_id=OTHER_WS,
            job_type="secret_other",
            agent_name="x",
            idempotency_key="k2",
            request_json={},
            policy_model="claude-opus-5",
            input_hash="h",
        ),
        EvidenceCollectionRun(
            workspace_id=WS,
            source_kind="fathom_meeting",
            window_start=datetime(2026, 9, 7),
            window_end=datetime(2026, 9, 14),
            status="running",
            counts={"listed": 3},
            current_activity="Fetching meeting 2 of 3",
        ),
        EvidenceCollectionRun(
            workspace_id=OTHER_WS,
            source_kind="github_commit_group",
            window_start=datetime(2026, 9, 7),
            window_end=datetime(2026, 9, 14),
        ),
        RecordingUpload(
            workspace_id=OTHER_WS,
            candidate_id=theirs.id,
            original_filename="o.mp4",
            storage_path="x",
            sha256="b" * 64,
            status="uploaded",
        ),
    )
    body = (await client.get("/api/v1/production/activity", headers=AUTH)).json()
    assert "now" in body
    assert [j["job_type"] for j in body["llm_jobs"]] == ["moment_extraction"]
    job = body["llm_jobs"][0]
    assert (
        "Waiting for subscription capacity" in job["current_activity"]
        and "14:05" in job["current_activity"]
    )
    assert job["receipt"] == {"auth_method": "subscription", "models": ["claude-opus-5"]}
    assert "never-shown" not in str(body)
    assert [r["source_kind"] for r in body["collection_runs"]] == ["fathom_meeting"]
    assert body["uploads"] == []


# ---------------------------------------------------------------------------
# Restart recovery and captioned render


def _busy_upload(cand, tmp_path, status, job_ids, name="walk.mp4"):
    src = tmp_path / f"{uuid.uuid4()}{Path(name).suffix}"
    src.write_bytes(b"synthetic original upload")
    return RecordingUpload(
        id=uuid.uuid4(),
        workspace_id=WS,
        candidate_id=cand.id,
        original_filename=name,
        storage_path=str(src),
        sha256=uuid.uuid4().hex + uuid.uuid4().hex[:32],
        duration_s=6.0,
        status=status,
        status_detail="Transcribing 6s file with local faster-whisper",
        job_ids=job_ids,
    )


def _foreign_lease(step, minutes_ago):
    at = prod._utcnow() - timedelta(minutes=minutes_ago)
    return f"{prod.LEASE_PREFIX}{step}|a1b2c3|other-host:4242:deadbeef|{at.isoformat()}"


async def _row(sessionmaker, upload_id):
    async with sessionmaker() as s:
        return (
            await s.execute(select(RecordingUpload).where(RecordingUpload.id == upload_id))
        ).scalar_one()


async def test_live_foreign_lease_is_left_alone_and_expired_one_becomes_retryable(
    client, editorial_sessionmaker, monkeypatch, tmp_path
):
    cand = _candidate()
    live = _busy_upload(cand, tmp_path, "transcribing", [_foreign_lease("transcribing", 0.5)])
    dead = _busy_upload(cand, tmp_path, "transcribing", [_foreign_lease("transcribing", 10)])
    await _seed(editorial_sessionmaker, cand, live, dead)

    r = await client.get(f"/api/v1/production/uploads/{live.id}", headers=AUTH)
    assert r.json()["status"] == "transcribing"  # another process is still heartbeating it
    r = await client.get(f"/api/v1/production/uploads/{dead.id}", headers=AUTH)
    body = r.json()
    assert body["status"] == "interrupted"
    assert "original upload is kept" in body["status_detail"]
    assert "Click Transcribe to retry" in body["status_detail"]
    assert Path(dead.storage_path).read_bytes() == b"synthetic original upload"

    spawned = []
    monkeypatch.setattr(prod, "_spawn", lambda coro: (spawned.append(coro), coro.close()))
    monkeypatch.setattr(settings, "production_transcribe_ws_url", "ws://127.0.0.1:9/none")
    retry = await client.post(f"/api/v1/production/uploads/{dead.id}/transcribe", headers=AUTH)
    assert retry.status_code == 202 and retry.json()["status"] == "transcribing"
    assert len(spawned) == 1
    lease = prod.parse_lease((await _row(editorial_sessionmaker, dead.id)).job_ids)
    assert lease["owner"] == prod.PROCESS_OWNER and lease["step"] == "transcribing"
    prod._active_attempts.discard(lease["attempt"])


async def test_startup_sweep_interrupts_pre_lease_rows_and_removes_partial_render(
    editorial_sessionmaker, tmp_path
):
    cand = _candidate()
    legacy = _busy_upload(cand, tmp_path, "transcribing", [])
    render = _busy_upload(cand, tmp_path, "rendering", [])
    src = Path(render.storage_path)
    partial = src.with_name(f".{src.stem}-edited.rendering.mp4")
    partial.write_bytes(b"half a file")
    gone = _busy_upload(cand, tmp_path, "rendering", [])
    Path(gone.storage_path).unlink()
    await _seed(editorial_sessionmaker, cand, legacy, render, gone)

    async with editorial_sessionmaker() as s:
        # A normal read does not touch lease-less rows that were just updated
        assert await prod.reconcile_interrupted_uploads(s, WS) == []
        changed = await prod.reconcile_interrupted_uploads(s, startup=True)
    assert set(changed) == {legacy.id, render.id, gone.id}
    assert (await _row(editorial_sessionmaker, legacy.id)).status == "interrupted"
    rendered = await _row(editorial_sessionmaker, render.id)
    assert rendered.status == "interrupted"
    assert "Click Render edit to retry" in rendered.status_detail
    assert not partial.exists() and src.exists()
    missing = await _row(editorial_sessionmaker, gone.id)
    assert missing.status == "failed" and "missing from storage" in missing.status_detail


async def test_own_process_lease_alive_while_running_dead_after(
    editorial_sessionmaker, monkeypatch, tmp_path
):
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    cand = _candidate()
    entry = prod._lease_entry("rendering", "mine123", prod._utcnow())
    row = _busy_upload(cand, tmp_path, "rendering", [entry])
    await _seed(editorial_sessionmaker, cand, row)
    prod._active_attempts.add("mine123")
    try:
        async with editorial_sessionmaker() as s:
            assert await prod.reconcile_interrupted_uploads(s, WS, startup=True) == []
    finally:
        prod._active_attempts.discard("mine123")
    async with editorial_sessionmaker() as s:
        assert await prod.reconcile_interrupted_uploads(s, WS) == [row.id]
    # The dead attempt can no longer write its late result
    assert not await prod._set_status(row.id, WS, "edited", "late result", "mine123")
    assert (await _row(editorial_sessionmaker, row.id)).status == "interrupted"


@pytest.mark.skipif(not media.ffmpeg_path(), reason="ffmpeg not installed")
async def test_blocked_plan_renders_uncut_captioned_mp4_with_sidecars(
    client, editorial_sessionmaker, monkeypatch, tmp_path
):
    cand = _candidate()
    src = tmp_path / "walk.mp4"
    subprocess.run(
        [
            media.ffmpeg_path(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=360x640:r=25:d=6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=330:duration=6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    whole = "whole_second_start_inferred_end"
    text = "I do not promise instant results."
    transcript = [
        {"start_s": 0.0, "end_s": 3.0, "text": text, "precision": whole},
        {"start_s": 3.0, "end_s": 6.0, "text": text, "precision": whole},
    ]
    plan = prod.plan_edit(transcript, [text], duration_s=6.0)
    assert plan["meaning_check"]["status"] == "blocked"
    row = RecordingUpload(
        id=uuid.uuid4(),
        workspace_id=WS,
        candidate_id=cand.id,
        original_filename="walk.mp4",
        storage_path=str(src),
        sha256="e" * 64,
        duration_s=6.0,
        transcript=transcript,
        edit_plan=plan,
        status="needs_review",
        status_detail="Needs review",
        job_ids=[],
    )
    await _seed(editorial_sessionmaker, cand, row)
    spawned = []
    monkeypatch.setattr(prod, "_spawn", lambda coro: spawned.append(coro))

    cut = await client.post(f"/api/v1/production/uploads/{row.id}/render", headers=AUTH)
    assert cut.status_code == 409 and "render uncut" in cut.json()["detail"]
    r = await client.post(
        f"/api/v1/production/uploads/{row.id}/render", headers=AUTH, json={"mode": "uncut"}
    )
    assert r.status_code == 202 and r.json()["status"] == "rendering"
    await spawned[0]  # run the leased render to completion
    body = (await client.get(f"/api/v1/production/uploads/{row.id}", headers=AUTH)).json()
    assert body["status"] == "edited", body["status_detail"]
    assert "Uncut captioned MP4" in body["status_detail"]
    out = tmp_path / "walk-edited.mp4"
    assert out.exists() and abs((await media.probe_duration(out)) - 6.0) < 0.2
    assert (tmp_path / "walk-edited.srt").read_text(encoding="utf-8").count("-->") == 2
    assert (tmp_path / "walk-edited.vtt").read_text(encoding="utf-8").startswith("WEBVTT")
    assert prod.parse_lease((await _row(editorial_sessionmaker, row.id)).job_ids) is None
    assert not prod._active_attempts
    edited = await client.get(f"/api/v1/production/uploads/{row.id}/edited", headers=AUTH)
    assert edited.status_code == 200 and edited.headers["content-type"] == "video/mp4"


async def test_receipt_rejects_a_packet_from_another_idea(client, editorial_sessionmaker):
    mine, theirs = _candidate(), _candidate(title="A different idea")
    other_packet = _packet(theirs)
    await _seed(editorial_sessionmaker, mine, theirs, other_packet)
    body = {
        "platform": "linkedin",
        "external_post_id": "synthetic-cross-packet",
        "packet_id": str(other_packet.id),
    }
    r = await client.post(
        f"/api/v1/production/candidates/{mine.id}/publications", headers=AUTH, json=body
    )
    assert r.status_code == 422 and "different idea" in r.json()["detail"]
    ok = await client.post(
        f"/api/v1/production/candidates/{theirs.id}/publications", headers=AUTH, json=body
    )
    assert ok.status_code == 201 and ok.json()["publication"]["packet_id"] == str(other_packet.id)
