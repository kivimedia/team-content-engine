"""After recording: watch it back, get the captions, open the Doc.

The recorder could take a video and then showed nothing. The file, the captions and
the Google Doc each sat behind a different route, and the original recording had no
route at all - only an edited cut that exists after a render nobody had run.
"""

# ruff: noqa: F811 - a fixture taken as a test parameter shadows its import

from __future__ import annotations

import uuid

import pytest

from tests.unit.test_production_router import (  # noqa: F401,F811 - fixtures
    AUTH,
    OTHER_WS,
    WS,
    _candidate,
    _file,
    _packet,
    _seed,
    client,
)

RECORDED = "/api/v1/production/recorded"


async def record_one(client, sm, *, title="Answer inquiries fast", doc_url=None):
    cand = _candidate(title=title)
    packet = _packet(cand)
    if doc_url:
        packet.google_doc_url = doc_url
        packet.google_doc_id = "doc-" + uuid.uuid4().hex[:8]
    await _seed(sm, cand, packet)
    # Identical bytes across candidates are a 409 by design, so each take differs.
    r = await client.post(
        f"/api/v1/production/candidates/{cand.id}/recording",
        headers=AUTH,
        files=_file(b"synthetic-video-bytes " + title.encode()),
    )
    assert r.status_code == 201, r.text
    return cand, packet, r.json()


async def test_a_recording_comes_back_with_its_video_and_its_doc(client, editorial_sessionmaker):
    cand, _packet_row, upload = await record_one(
        client, editorial_sessionmaker, doc_url="https://docs.google.com/document/d/abc/edit"
    )

    r = await client.get(RECORDED, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    item = body["recordings"][0]
    assert item["title"] == cand.title
    assert item["candidate_id"] == str(cand.id)
    assert item["video_url"] == f"/api/v1/production/uploads/{upload['id']}/video"
    assert item["google_doc_url"] == "https://docs.google.com/document/d/abc/edit"
    assert item["recorded_at"]


async def test_the_video_plays_back(client, editorial_sessionmaker):
    _cand, _p, upload = await record_one(client, editorial_sessionmaker)

    r = await client.get(f"/api/v1/production/uploads/{upload['id']}/video", headers=AUTH)

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/mp4")
    assert r.content.startswith(b"synthetic-video-bytes")


async def test_captions_are_only_offered_once_they_exist(client, editorial_sessionmaker):
    _cand, _p, _upload = await record_one(client, editorial_sessionmaker)

    item = (await client.get(RECORDED, headers=AUTH)).json()["recordings"][0]

    # No transcript yet, so no captions link that would 404 under his finger.
    assert item["captions_srt_url"] is None
    assert item["has_transcript"] is False


async def test_another_workspace_recordings_are_not_listed(client, editorial_sessionmaker):
    await record_one(client, editorial_sessionmaker)

    other = {**AUTH, "X-Workspace-Id": str(OTHER_WS)}
    body = (await client.get(RECORDED, headers=other)).json()

    assert body["count"] == 0


async def test_nothing_recorded_yet_is_an_empty_list_not_an_error(client):
    r = await client.get(RECORDED, headers=AUTH)

    assert r.status_code == 200
    assert r.json() == {"recordings": [], "count": 0}


async def test_newest_first(client, editorial_sessionmaker):
    from datetime import datetime

    from sqlalchemy import select

    from tce.models.editorial import RecordingUpload

    _c1, _p1, first = await record_one(client, editorial_sessionmaker, title="Recorded on Monday")
    _c2, _p2, second = await record_one(client, editorial_sessionmaker, title="Recorded on Friday")
    async with editorial_sessionmaker() as s:
        for upload_id, when in (
            (first["id"], datetime(2026, 9, 14, 9)),
            (second["id"], datetime(2026, 9, 18, 9)),
        ):
            row = (
                await s.execute(
                    select(RecordingUpload).where(RecordingUpload.id == uuid.UUID(upload_id))
                )
            ).scalar_one()
            row.created_at = when
        await s.commit()

    titles = [i["title"] for i in (await client.get(RECORDED, headers=AUTH)).json()["recordings"]]

    assert titles == ["Recorded on Friday", "Recorded on Monday"]


async def test_two_takes_in_the_same_second_keep_a_stable_order(client, editorial_sessionmaker):
    # Identical timestamps used to leave the order to the database, so the list
    # reshuffled itself between refreshes.
    await record_one(client, editorial_sessionmaker, title="One")
    await record_one(client, editorial_sessionmaker, title="Two")

    once = [i["title"] for i in (await client.get(RECORDED, headers=AUTH)).json()["recordings"]]
    twice = [i["title"] for i in (await client.get(RECORDED, headers=AUTH)).json()["recordings"]]

    assert once == twice and len(once) == 2


async def test_a_missing_file_says_so_instead_of_serving_nothing(
    client, editorial_sessionmaker, tmp_path
):
    from sqlalchemy import select

    from tce.models.editorial import RecordingUpload

    _cand, _p, upload = await record_one(client, editorial_sessionmaker)
    async with editorial_sessionmaker() as s:
        row = (
            await s.execute(
                select(RecordingUpload).where(RecordingUpload.id == uuid.UUID(upload["id"]))
            )
        ).scalar_one()
        row.storage_path = str(tmp_path / "gone.mp4")
        await s.commit()

    r = await client.get(f"/api/v1/production/uploads/{upload['id']}/video", headers=AUTH)

    assert r.status_code == 404
    assert "not on this server" in r.json()["detail"]


@pytest.mark.parametrize("limit,expected", [(1, 1), (500, 2)])
async def test_the_limit_is_clamped(client, editorial_sessionmaker, limit, expected):
    await record_one(client, editorial_sessionmaker, title="One")
    await record_one(client, editorial_sessionmaker, title="Two")

    body = (await client.get(f"{RECORDED}?limit={limit}", headers=AUTH)).json()

    assert body["count"] == expected
