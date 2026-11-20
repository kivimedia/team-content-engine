import uuid

import pytest

from tce.editorial import cut_reviews
from tce.models.editorial import RecordingUpload
from tce.models.jennifer import RenderCheck

STAMP = {"generated_cut": {"release": cut_reviews.TRIAL_RELEASE, "first": True}}


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
                result={**STAMP, "checks": {"captions": {"state": "pass"}}},
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
            result={**STAMP, "checks": {"captions": {"state": "fail"}}},
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
                    result={**STAMP, "checks": gates},
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
                result={**STAMP, "checks": gates},
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
        db.add(
            RenderCheck(
                workspace_id=ws, upload_id=upload.id, render_ref="one", state="passed", result=STAMP
            )
        )
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


@pytest.mark.asyncio
async def test_trial_classification_api_counts_distinct_notes_across_versions(
    editorial_sessionmaker,
):
    from datetime import datetime, timedelta

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from tce.api.routers import editorial_workspace as routes
    from tce.models.editorial import TopicCandidate
    from tce.models.editorial_workspace import EditingRequest

    ws = uuid.uuid4()
    now = datetime(2026, 11, 19)
    async with editorial_sessionmaker() as db:
        candidate = TopicCandidate(
            workspace_id=ws,
            week_start=now,
            moment_ids=["fixture"],
            title="The video",
            lesson="lesson",
            audience="audience",
            public_angle="angle",
            gates={},
            status="recorded",
        )
        db.add(candidate)
        await db.flush()
        upload = RecordingUpload(
            workspace_id=ws,
            candidate_id=candidate.id,
            original_filename="fixture.mp4",
            storage_path="src",
            sha256="c" * 64,
            status="edited",
            edited_path="out",
            render_ref="first",
        )
        db.add(upload)
        await db.flush()
        db.add(
            RenderCheck(
                workspace_id=ws,
                upload_id=upload.id,
                render_ref="first",
                state="passed",
                result=STAMP,
                created_at=now,
            )
        )
        notes = [
            EditingRequest(workspace_id=ws, upload_id=upload.id, request=v, state="done")
            for v in (
                "Keep both words.",
                "Different music.",
                "The cut reverses the promise.",
                "One more thing.",
            )
        ]
        db.add_all(notes)
        await db.flush()
        uid = upload.id
        await cut_reviews.record(db, ws, uid, "first", "team-angel", "changes", notes[:2])
        upload.render_ref = "later"
        db.add(
            RenderCheck(
                workspace_id=ws,
                upload_id=uid,
                render_ref="later",
                state="passed",
                created_at=now + timedelta(hours=2),
            )
        )
        await db.flush()
        # The same note can be linked from two render receipts, including later versions.
        await cut_reviews.record(db, ws, uid, "later", "team-angel", "changes", notes[1:])
        ids = [n.id for n in notes]
        await db.commit()
    app = FastAPI()
    app.include_router(routes.production_router)
    actor = ["team-angel"]
    workspace = [ws]
    app.dependency_overrides[routes.require_private_workspace] = lambda: workspace[0]
    app.dependency_overrides[routes._reviewer] = lambda: actor[0]
    app.dependency_overrides[routes.get_editorial_sessionmaker] = lambda: editorial_sessionmaker
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        path = f"/production/recordings/{uid}/cut-review-notes"
        get = await client.get(path)
        assert get.status_code == 200
        assert len(get.json()["items"]) == 4 and all(
            i["classification"] == "unclassified" for i in get.json()["items"]
        )
        for i, label in enumerate(["corrective", "creative", "meaning_change"]):
            endpoint = f"{path}/{ids[i]}"
            response = await client.patch(endpoint, json={"classification": label})
            assert response.status_code == 200
            assert (
                await client.patch(endpoint, json={"classification": label})
            ).json() == response.json()
        result = response.json()["trial"]
        assert result["reviewed"] == 1 and result["proposed_acceptances"] == 18
        assert result["notes"] == {
            "corrective": 2,
            "meaning_changing": 1,
            "creative": 1,
            "unclassified": 1,
        }
        assert result["corrective_per_video"] == 2 and result["videos"][0]["title"] == "The video"
        assert result["videos"][0]["corrective"] == 2
        assert result["unexplained_changes"] == 0
        assert (
            await client.patch(f"{path}/{ids[1]}", json={"classification": "made_up"})
        ).status_code == 422
        assert (
            await client.patch(f"{path}/{ids[1]}", json={"classification": "unclassified"})
        ).json()["trial"]["notes"]["unclassified"] == 2
        actor[0] = "other-reviewer"
        assert (await client.get(path)).json()["items"] == []
        assert (
            await client.patch(f"{path}/{ids[0]}", json={"classification": "creative"})
        ).status_code == 404
        actor[0] = None
        assert (await client.get(path)).status_code == 403
        actor[0] = "team-angel"
        workspace[0] = uuid.uuid4()
        assert (
            await client.patch(f"{path}/{ids[0]}", json={"classification": "creative"})
        ).status_code == 404


@pytest.mark.asyncio
async def test_legacy_rechecks_and_revisions_are_recorded_outside_release_trial(
    editorial_sessionmaker,
):
    from datetime import datetime, timedelta

    ws = uuid.uuid4()
    now = datetime(2026, 11, 19)
    async with editorial_sessionmaker() as db:

        async def upload(tag):
            u = RecordingUpload(
                workspace_id=ws,
                candidate_id=uuid.uuid4(),
                original_filename="clip.mp4",
                storage_path="src",
                sha256=tag * 64,
                status="edited",
                edited_path="out",
                render_ref=tag,
            )
            db.add(u)
            await db.flush()
            return u

        old = await upload("a")

        def checked(u, ref, state, stamp=None, minutes=0):
            db.add(
                RenderCheck(
                    workspace_id=ws,
                    upload_id=u.id,
                    render_ref=ref,
                    state=state,
                    created_at=now + timedelta(minutes=minutes),
                    result=stamp or {"checks": {}},
                )
            )

        checked(old, "a", "passed")
        checked(old, "a", "passed", minutes=2)
        await db.flush()
        assert await cut_reviews.record(db, ws, old.id, "a", "team-angel", "accepted")
        assert (await cut_reviews.summary(db, ws, "team-angel"))["reviewed"] == 0
        old.render_ref = "new-revision"
        checked(
            old,
            "new-revision",
            "passed",
            {"generated_cut": {"release": cut_reviews.TRIAL_RELEASE, "first": False}},
            3,
        )
        await db.flush()
        assert await cut_reviews.record(db, ws, old.id, "new-revision", "team-angel", "accepted")
        assert (await cut_reviews.summary(db, ws, "team-angel"))["reviewed"] == 0
        # An internal fixing pass was never the delivered preview. The first completed
        # QC run on the repaired render is one new-generation first cut.
        new = await upload("b")
        checked(new, "b", "fixing", STAMP)
        new.render_ref = "first-complete"
        checked(new, "first-complete", "fixed", STAMP, 1)
        await db.flush()
        assert await cut_reviews.record(db, ws, new.id, "first-complete", "team-angel", "accepted")
        trial = await cut_reviews.summary(db, ws, "team-angel")
        assert (trial["reviewed"], trial["accepted"]) == (1, 1)


@pytest.mark.asyncio
async def test_qc_records_only_the_stamp_of_the_exact_file(
    editorial_sessionmaker, tmp_path, monkeypatch
):
    from sqlalchemy import select

    from tce.api.routers import production

    ws = uuid.uuid4()
    monkeypatch.setattr(production, "session_factory", lambda: editorial_sessionmaker)
    edited = tmp_path / "video.mp4"
    edited.write_bytes(b"candidate file")
    async with editorial_sessionmaker() as db:
        obj = RecordingUpload(
            workspace_id=ws,
            candidate_id=uuid.uuid4(),
            original_filename="clip.mp4",
            storage_path="src",
            sha256="d" * 64,
            status="edited",
            edited_path=str(edited),
            render_ref="r",
        )
        db.add(obj)
        await db.commit()
        uid = obj.id
    verdict = {"state": "passed", "line": "Checked.", "checks": {}}
    for tag in ["missing", "wrong", "r"]:
        if tag != "missing":
            stat = edited.stat()
            production._write_render_sidecar(
                edited,
                {
                    "render_ref": tag,
                    "file_size": stat.st_size,
                    "file_mtime_ns": stat.st_mtime_ns,
                    **STAMP,
                },
            )
        await production._qc_record(uid, ws, verdict, final=True)
    async with editorial_sessionmaker() as db:
        rows = (
            (await db.execute(select(RenderCheck).where(RenderCheck.upload_id == uid)))
            .scalars()
            .all()
        )
        assert len(rows) == 3
        assert sum(row.result.get("generated_cut") == STAMP["generated_cut"] for row in rows) == 1
