"""Talk to the editor (30-Sep): the render stamp, the sitting, its notes and its gates.

Synthetic data. ffmpeg and the subscription are replaced; the database rows, the
routes and the clock are the real code.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.api.routers import production as prod
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.production.retakes import frame_keep
from tce.settings import settings

KEY = "synthetic-test-key"


def words(text: str, start: float = 0.0, step: float = 0.5) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start_s": t, "end_s": t + step - 0.1, "precision": "word"})
        t += step
    return out


SPOKEN = "Getting them back is really smart. After you've finished your service. Call them."


async def seed(sm, tmp_path: Path, *, planned: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
    ws = uuid.uuid4()
    src = tmp_path / f"walk-{uuid.uuid4().hex[:6]}.mp4"
    src.write_bytes(b"synthetic")
    async with sm() as s:
        cand = TopicCandidate(
            workspace_id=ws, week_start=datetime(2026, 9, 28), moment_ids=["m"],
            title="Call them after the service", lesson="l", audience="a",
            public_angle="p", gates={}, status="recorded",
        )
        s.add(cand)
        await s.flush()
        up = RecordingUpload(
            workspace_id=ws, candidate_id=cand.id, original_filename="walk.mp4",
            storage_path=str(src), sha256=uuid.uuid4().hex * 2, status="transcribed",
            transcript=words(SPOKEN), duration_s=8.0,
        )
        s.add(up)
        await s.commit()
        if planned:
            await prod._compute_plan(s, ws, up)
            await s.commit()
        return ws, up.id


@pytest.fixture
def renders(monkeypatch, editorial_sessionmaker):
    """The real _run_render with ffmpeg replaced: records each keep it was asked to cut."""
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    cut: list[list[list[float]]] = []
    fail: list[str] = []

    async def fake_render_edit(src, keep, out, **_kw):
        if fail:
            raise RuntimeError(fail[0])
        cut.append([list(r) for r in keep])
        Path(out).write_bytes(b"edited")
        return Path(out)

    async def fake_size(_src):
        return (1080, 1920)

    monkeypatch.setattr(prod.media, "render_edit", fake_render_edit)
    monkeypatch.setattr(prod.media, "probe_video_size", fake_size)
    monkeypatch.setattr(prod.wordbox, "usable", lambda *_a, **_k: False)
    return {"sm": editorial_sessionmaker, "cut": cut, "fail": fail}


async def render_once(sm, ws, uid, mode: str = "cut") -> RecordingUpload:
    async with sm() as s:
        row = await prod._load(s, uid, ws)
        attempt = prod._claim(row, "rendering", "Queued")
        await s.commit()
    await prod._run_leased(uid, ws, "rendering", attempt, lambda: prod._run_render(uid, ws, attempt, mode))
    async with sm() as s:
        return await prod._load(s, uid, ws)


# ---------------------------------------------------------------- render stamp


async def test_a_successful_render_stamps_the_keep_that_made_the_file(renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    row = await render_once(renders["sm"], ws, uid)
    assert row.status == "edited"
    assert row.rendered_keep == frame_keep(renders["cut"][0])
    assert row.rendered_keep and all(abs(s * 30 - round(s * 30)) < 1e-9 for r in row.rendered_keep for s in r)
    assert row.render_ref and len(row.render_ref) == 16
    assert prod.upload_json(row)["render_ref"] == row.render_ref


async def test_every_render_gets_its_own_ref_even_with_the_same_keep(renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    first = (await render_once(renders["sm"], ws, uid)).render_ref
    second = await render_once(renders["sm"], ws, uid)
    assert renders["cut"][0] == renders["cut"][1]
    assert second.render_ref != first


async def test_a_failed_render_keeps_the_stamp_of_the_file_that_exists(renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    good = await render_once(renders["sm"], ws, uid)
    assert good.render_ref and good.rendered_keep
    renders["fail"].append("ffmpeg exploded")
    bad = await render_once(renders["sm"], ws, uid)
    assert bad.status == "failed"
    assert bad.render_ref == good.render_ref
    assert bad.rendered_keep == good.rendered_keep


async def test_a_plan_that_never_renders_does_not_move_the_stamp(renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    good = await render_once(renders["sm"], ws, uid)
    assert good.render_ref and good.rendered_keep
    async with renders["sm"]() as s:
        row = await prod._load(s, uid, ws)
        plan = dict(row.edit_plan)
        plan["overrides"] = {"cut": [[0.0, 1.4]], "restore": []}
        row.edit_plan = plan
        await prod._compute_plan(s, ws, row)
        await s.commit()
        assert row.edit_plan["keep"] != renders["cut"][0]
        assert row.render_ref == good.render_ref and row.rendered_keep == good.rendered_keep


async def test_an_uncut_render_stamps_the_whole_recording(renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    row = await render_once(renders["sm"], ws, uid, mode="uncut")
    assert row.rendered_keep == [[0.0, 8.0]]


def test_the_watch_button_puts_the_render_on_the_address():
    js = (Path(__file__).parents[2] / "src/tce/api/workspace.js").read_text(encoding="utf-8")
    assert '"v=" + encodeURIComponent(item.render_ref)' in js
    assert 'query.push("preview=1")' in js


# ---------------------------------------------------------------- the library


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(workspace_router.production_router, prefix="/api/v1")
    app.include_router(prod.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: (
        editorial_sessionmaker
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def headers(ws) -> dict:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


async def test_the_library_card_carries_the_render_it_would_play(client, renders, tmp_path):
    ws, uid = await seed(renders["sm"], tmp_path)
    row = await render_once(renders["sm"], ws, uid)
    body = (await client.get("/api/v1/production/library", headers=headers(ws))).json()
    item = body["items"][0]
    assert item["upload_id"] == str(uid)
    assert row.render_ref and item["render_ref"] == row.render_ref
