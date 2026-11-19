import uuid

import pytest

from tce.editorial import cut_reviews
from tce.models.editorial import RecordingUpload
from tce.models.jennifer import RenderCheck


@pytest.mark.asyncio
async def test_review_version_retry_and_trial_membership(editorial_sessionmaker):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as db:
        u = RecordingUpload(
            workspace_id=ws,
            candidate_id=uuid.uuid4(),
            original_filename="clip.mp4",
            storage_path="clip.mp4",
            sha256="0" * 64,
            status="edited",
            edited_path="edited.mp4",
            render_ref="first",
        )
        db.add(u)
        await db.flush()
        db.add(
            RenderCheck(
                workspace_id=ws,
                upload_id=u.id,
                render_ref="first",
                state="passed",
                result={"checks": {"captions": {"state": "pass"}}},
            )
        )
        await db.flush()
        for _ in range(2):
            await cut_reviews.record(db, ws, u.id, "first", "team-angel", "accepted")
        summary = await cut_reviews.summary(db, ws, "team-angel")
        assert (summary["reviewed"], summary["accepted"]) == (1, 1)
        u.render_ref = "second"
        db.add(RenderCheck(workspace_id=ws, upload_id=u.id, render_ref="second", state="fixed"))
        await db.flush()
        assert await cut_reviews.record(db, ws, u.id, "first", "team-angel", "accepted") is False
        assert await cut_reviews.record(db, ws, u.id, "second", "team-angel", "changes")
        assert (await cut_reviews.summary(db, ws, "team-angel"))["reviewed"] == 1
        assert (await cut_reviews.summary(db, uuid.uuid4(), "team-angel"))["reviewed"] == 0


@pytest.mark.asyncio
async def test_old_watched_note_and_latest_measurement_keep_their_own_receipt(
    editorial_sessionmaker,
):
    ws = uuid.uuid4()
    from datetime import datetime, timedelta

    base = datetime(2026, 11, 19)
    gates = {k: {"state": "pass"} for k in ("audibility", "loudness", "captions", "gaps", "asides")}
    gates["captions"].update(playback_state="pass", frames={"state": "pass"})
    gates["audibility"]["listened"] = True
    async with editorial_sessionmaker() as db:
        upload = RecordingUpload(
            workspace_id=ws,
            candidate_id=uuid.uuid4(),
            original_filename="fixture.mp4",
            storage_path="src",
            sha256="a" * 64,
            status="edited",
            edited_path="out",
            render_ref="old",
        )
        db.add(upload)
        await db.flush()
        earlier = RenderCheck(
            workspace_id=ws,
            upload_id=upload.id,
            render_ref="old",
            state="held",
            created_at=base,
            result={"checks": {"captions": {"state": "fail"}}},
        )
        db.add_all(
            [
                earlier,
                RenderCheck(
                    workspace_id=ws,
                    upload_id=upload.id,
                    render_ref="old",
                    state="passed",
                    created_at=base + timedelta(minutes=1),
                    result={"checks": gates},
                ),
            ]
        )
        await db.flush()
        assert await cut_reviews.record(db, ws, upload.id, "old", "team-angel", "accepted")
        assert (await cut_reviews.summary(db, ws, "team-angel"))["incomplete_checks"] == 0
        upload.render_ref = "new"
        db.add(
            RenderCheck(
                workspace_id=ws,
                upload_id=upload.id,
                render_ref="new",
                state="passed",
                created_at=base + timedelta(minutes=2),
                result={"checks": gates},
            )
        )
        await db.flush()
        assert await cut_reviews.record(
            db, ws, upload.id, "old", "team-angel", "changes", allow_previous=True
        )
        assert not await cut_reviews.record(
            db, ws, upload.id, None, "team-angel", "changes", allow_previous=True
        )
        assert not await cut_reviews.record(
            db, ws, upload.id, "unknown", "team-angel", "changes", allow_previous=True
        )
        assert (await cut_reviews.summary(db, ws, "team-angel"))["accepted"] == 0
        assert (await cut_reviews.summary(db, ws, "team-angel"))["reviewed"] == 1


@pytest.mark.asyncio
async def test_reopened_count_starts_when_previous_fix_finished(editorial_sessionmaker):
    from datetime import datetime, timedelta

    from tce.models.editorial_workspace import EditingRequest

    ws = uuid.uuid4()
    base = datetime(2026, 11, 19)
    async with editorial_sessionmaker() as db:
        upload = RecordingUpload(
            workspace_id=ws,
            candidate_id=uuid.uuid4(),
            original_filename="fixture.mp4",
            storage_path="src",
            sha256="b" * 64,
            status="edited",
            edited_path="out",
            render_ref="one",
        )
        db.add(upload)
        await db.flush()
        db.add(RenderCheck(workspace_id=ws, upload_id=upload.id, render_ref="one", state="passed"))
        original = EditingRequest(
            workspace_id=ws,
            upload_id=upload.id,
            request="Cut the opening.",
            state="done",
            created_at=base,
            resolved_at=base + timedelta(minutes=5),
        )
        follow = 'About my earlier note "Cut the opening.": I still hear it.'
        early = EditingRequest(
            workspace_id=ws,
            upload_id=upload.id,
            request=follow,
            created_at=base + timedelta(minutes=2),
        )
        late = EditingRequest(
            workspace_id=ws,
            upload_id=upload.id,
            request=follow,
            created_at=base + timedelta(minutes=8),
        )
        db.add_all([original, early, late])
        await db.flush()
        await cut_reviews.record(db, ws, upload.id, "one", "team-angel", "changes", [early])
        assert (await cut_reviews.summary(db, ws, "team-angel"))["reopened_after_done"] == 0
        await cut_reviews.record(db, ws, upload.id, "one", "team-angel", "changes", [late])
        assert (await cut_reviews.summary(db, ws, "team-angel"))["reopened_after_done"] == 1


@pytest.mark.asyncio
async def test_old_library_media_ref_cannot_stream_a_newer_cut(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException
    from starlette.requests import Request

    from tce.api.routers import production

    file = tmp_path / "edit.mp4"
    file.write_bytes(b"current-version-bytes")
    uid, ws = uuid.uuid4(), uuid.uuid4()
    row = SimpleNamespace(render_ref="latest", edited_path=str(file))
    monkeypatch.setattr(production, "_upload", AsyncMock(return_value=row))

    def request(query):
        return Request(
            {
                "type": "http",
                "method": "GET",
                "headers": [(b"range", b"bytes=0-6")],
                "query_string": query,
            }
        )

    for key in (b"v=previous", b"review_ref=previous"):
        with pytest.raises(HTTPException) as stale:
            await production.edited_file(uid, request(key), False, False, ws, None)
        assert stale.value.status_code == 409
    for key in (b"v=latest", b""):
        response = await production.edited_file(uid, request(key), False, False, ws, None)
        assert response.status_code == 206
        assert b"".join([part async for part in response.body_iterator]) == b"current"
