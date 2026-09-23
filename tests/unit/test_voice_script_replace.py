"""Writing a new script over the one he has: it needs his yes, and it can be put back.

A rewrite replaces the current script, and every edit made to it, when the job
finishes. The voice agent used to start one on "write the script for X" with no
read-back, and nothing could bring the old version back. Now the voice path
must say `replace`, the old version stays in the database as superseded, and
putting it back is an attributed change that is itself undoable.
"""

# ruff: noqa: F811 - a fixture taken as a test parameter shadows its import

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from tce.api.routers import editorial as editorial_router
from tce.editorial import status as job_status
from tce.models.editorial import RecordingPacket
from tests.unit.test_editorial_voice_agent import (
    add_candidate,
    add_packet,
    change,
    headers,
    regenerate,
    topic,
    undo,
)
from tests.unit.test_voice_agent_jobs_and_matching import client  # noqa: F401


@pytest.fixture
def no_writer(monkeypatch):
    """The packet writer is a PC worker job; here it only records that it was asked."""
    asked = []

    async def record(sm, ws, cid, resume_job_id=None):
        asked.append(cid)
        job_status.update(ws, "packet", str(cid), state="done")

    monkeypatch.setattr(editorial_router, "_run_packet", record)
    return asked


async def test_a_new_script_over_an_existing_one_needs_his_yes(
    client, editorial_sessionmaker, no_writer
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)

    refused = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": False, "by": "voice"},
        headers=headers(ws),
    )
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "has_script"
    assert detail["version"] == 1 and detail["status"] == "ready"
    assert no_writer == [], "nothing may be started before he says yes"

    agreed = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": True, "by": "voice"},
        headers=headers(ws),
    )
    assert agreed.status_code == 200, agreed.text
    assert agreed.json()["replaces_version"] == 1
    assert no_writer == [cid]


async def test_the_workspace_button_still_writes_without_a_flag(
    client, editorial_sessionmaker, no_writer
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    response = await client.post(f"/api/v1/editorial/candidates/{cid}/packet", headers=headers(ws))
    assert response.status_code == 200, response.text
    assert no_writer == [cid]


async def test_a_first_script_needs_no_flag(client, editorial_sessionmaker, no_writer):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "New idea")
    response = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": False, "by": "voice"},
        headers=headers(ws),
    )
    assert response.status_code == 200, response.text
    assert response.json()["replaces_version"] is None


NEW_HOOKS = [
    {
        "id": "h1",
        "text": "A brand new first opening.",
        "question": "q",
        "payoff_phrase_id": "p1",
        "moment_ids": ["m"],
        "rationale": "r",
    }
]


async def test_a_replaced_script_can_be_put_back_and_that_can_be_undone(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    # His edits on version 1, then a rewrite that replaced it.
    edited = await change(
        client,
        ws,
        cid,
        "script",
        [{"op": "choose_hook", "after": "2", "expect": "Nobody checks the result."}],
    )
    assert edited.status_code == 200, edited.text
    async with editorial_sessionmaker() as s:
        mine = (
            await s.execute(
                select(RecordingPacket).where(
                    RecordingPacket.candidate_id == cid, RecordingPacket.status != "superseded"
                )
            )
        ).scalar_one()
        mine_version = mine.version
        mine.status = "superseded"
        s.add(
            RecordingPacket(
                workspace_id=ws,
                candidate_id=cid,
                version=mine_version + 1,
                bullets=["New first.", "New second."],
                script_phrases=["A brand new first opening.", "New line two."],
                hook_options=NEW_HOOKS,
                selected_hook_id="h1",
                status="ready",
                citations_private=[],
                public_safety={},
            )
        )
        await s.commit()

    back = await client.post(
        f"/api/v1/editorial/candidates/{cid}/script/restore",
        json={"version": mine_version, "by": "voice"},
        headers=headers(ws),
    )
    assert back.status_code == 200, back.text
    assert back.json()["restored"] is True
    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["version"] == mine_version + 2
    assert script["opening"] == "Nobody checks the result."
    assert script["points"] == ["First point.", "Second point.", "Third point."]
    assert [h["text"] for h in script["hooks"]] == [
        "Your AI said done. Was it?",
        "Nobody checks the result.",
    ]
    assert script["hooks"][1]["chosen"] is True

    # Attributed and listed like any other voice change, and undoable by id.
    items = (await client.get("/api/v1/editorial/voice/activity", headers=headers(ws))).json()[
        "items"
    ]
    entry = next(i for i in items if i["id"] == back.json()["change_set_id"])
    assert entry["can_undo"] is True

    again = await undo(client, ws, back.json()["change_set_id"])
    assert again.status_code == 200, again.text
    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["opening"] == "A brand new first opening."
    assert [h["text"] for h in script["hooks"]] == ["A brand new first opening."]


async def test_putting_back_a_script_while_the_new_one_is_written_is_refused(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    job_status.start(ws, "packet", str(cid), "Queued packet")
    try:
        response = await client.post(
            f"/api/v1/editorial/candidates/{cid}/script/restore",
            json={"version": 1, "by": "voice"},
            headers=headers(ws),
        )
    finally:
        job_status.update(ws, "packet", str(cid), state="done")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "still_writing"


async def test_putting_back_the_current_script_changes_nothing(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    await regenerate(editorial_sessionmaker, ws, cid, NEW_HOOKS)
    response = await client.post(
        f"/api/v1/editorial/candidates/{cid}/script/restore",
        json={"version": 2, "by": "voice"},
        headers=headers(ws),
    )
    assert response.status_code == 200, response.text
    assert response.json()["restored"] is False
    assert (await topic(client, ws, "scripted"))["topic"]["script"]["version"] == 2
