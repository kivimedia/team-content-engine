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

import tce.llm
from tce.api.routers import editorial as editorial_router
from tce.editorial import packets as packet_service
from tce.editorial import status as job_status
from tce.llm import LLMResult, LLMUnavailable
from tce.models.editorial import RecordingPacket
from tests.unit.test_editorial_packets import good_output
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

    async def record(sm, ws, cid, resume_job_id=None, **kwargs):
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


MOMENT = "11111111-1111-1111-1111-111111111111"


async def undo_rewrite(client, ws, cid, rewrite_id):
    return await client.post(
        f"/api/v1/editorial/candidates/{cid}/script/undo-rewrite",
        json={"rewrite_id": rewrite_id, "by": "voice"},
        headers=headers(ws),
    )


async def test_a_rewrite_keeps_the_script_it_replaced_when_it_is_saved_edits_included(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea", moment_ids=[MOMENT])
    pid = await add_packet(editorial_sessionmaker, ws, cid)
    during = {}

    async def slow_writer(request, *, wait_timeout_s=None):
        # While the new script is written he asks for an edit by voice, and types
        # one on the phone.
        during["voice"] = await change(
            client,
            ws,
            cid,
            "script",
            [{"field": "bullets.0", "after": "VOICE EDIT", "expect": "First point."}],
        )
        typed = await client.post(
            "/api/v1/editorial/change-sets",
            json={
                "target_type": "packet",
                "target_id": str(pid),
                "operations": [{"op": "set_field", "field": "bullets.0", "after": "PHONE EDIT"}],
                "summary": "Typed on the phone",
                "origin": "quick_action",
            },
            headers=headers(ws),
        )
        assert typed.status_code == 200, typed.text
        applied = await client.post(
            f"/api/v1/editorial/change-sets/{typed.json()['id']}/apply", headers=headers(ws)
        )
        assert applied.status_code == 200, applied.text
        during["typed"] = typed.json()["id"]
        return LLMResult(job_id=uuid.uuid4(), text="", structured=good_output(), model="m")

    monkeypatch.setattr(tce.llm, "complete", slow_writer)
    started = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": True, "by": "voice"},
        headers=headers(ws),
    )
    assert started.status_code == 200, started.text
    rewrite_id = started.json()["rewrite_id"]

    # The voice edit was refused, with the reason, rather than written and lost.
    assert during["voice"].status_code == 409, during["voice"].text
    assert during["voice"].json()["detail"]["code"] == "still_writing"

    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["points"][0] == good_output()["bullets"][0]

    # Listed with the voice changes, under the id the start answered with.
    items = (await client.get("/api/v1/editorial/voice/activity", headers=headers(ws))).json()[
        "items"
    ]
    entry = next(i for i in items if i["id"] == rewrite_id)
    assert entry["is_undo"] is False and entry["can_undo"] is True
    assert "new script" in " ".join(entry["lines"]).lower()

    back = await undo_rewrite(client, ws, cid, rewrite_id)
    assert back.status_code == 200, back.text
    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["points"][0] == "PHONE EDIT", "the script it really replaced, edit included"

    # The text from before that edit is one more undo away.
    typed_back = await undo(client, ws, during["typed"])
    assert typed_back.status_code == 200, typed_back.text
    script = (await topic(client, ws, "scripted"))["topic"]["script"]
    assert script["points"][0] == "First point."


async def test_undoing_a_rewrite_that_was_never_saved_says_so(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    await add_packet(editorial_sessionmaker, ws, cid)
    response = await undo_rewrite(client, ws, cid, str(uuid.uuid4()))
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "not_saved"
    assert (await topic(client, ws, "scripted"))["topic"]["script"]["version"] == 1


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


# ------------------------------------------------------------ the rewrite's edges


def more_openings(text):
    return {
        "hook_options": [
            {
                "id": "x",
                "text": text,
                "question": "q?",
                "payoff_phrase_id": "p002",
                "moment_ids": [MOMENT],
                "rationale": "r",
            }
        ]
    }


def busy_then_writes():
    """The PC worker is busy the first time (the job waits), then writes the script."""
    calls = []

    async def complete(request, *, wait_timeout_s=None):
        calls.append(1)
        if len(calls) == 1:
            raise LLMUnavailable("waiting_capacity", "the PC worker is busy")
        return LLMResult(job_id=uuid.uuid4(), text="", structured=good_output(), model="m")

    return complete


async def test_undoing_a_rewrite_refuses_when_openings_were_added_since_and_keeps_them(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea", moment_ids=[MOMENT])
    await add_packet(editorial_sessionmaker, ws, cid)

    async def writer(request, *, wait_timeout_s=None):
        if request.job_type == packet_service.MORE_HOOKS_JOB_TYPE:
            return LLMResult(
                job_id=uuid.uuid4(),
                text="",
                structured=more_openings("AN OPENING ADDED ON THE NEW SCRIPT."),
                model="m",
            )
        return LLMResult(job_id=uuid.uuid4(), text="", structured=good_output(), model="m")

    monkeypatch.setattr(tce.llm, "complete", writer)
    started = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": True, "by": "voice"},
        headers=headers(ws),
    )
    rewrite_id = started.json()["rewrite_id"]
    new_packet = (await topic(client, ws, "scripted"))["topic"]["script"]["packet_id"]
    asked = await client.post(
        f"/api/v1/editorial/packets/{new_packet}/more-hooks", headers=headers(ws)
    )
    assert asked.status_code == 202, asked.text
    texts = [h["text"] for h in (await topic(client, ws, "scripted"))["topic"]["script"]["hooks"]]
    assert "AN OPENING ADDED ON THE NEW SCRIPT." in texts

    back = await undo_rewrite(client, ws, cid, rewrite_id)
    assert back.status_code == 409, back.text
    assert back.json()["detail"]["code"] == "changed"
    assert "opening" in back.json()["detail"]["message"].lower()
    after = [h["text"] for h in (await topic(client, ws, "scripted"))["topic"]["script"]["hooks"]]
    assert after == texts, "the openings he asked for after the rewrite are kept"


async def test_more_openings_are_refused_while_a_new_script_is_written_or_waits(
    client, editorial_sessionmaker
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    pid = await add_packet(editorial_sessionmaker, ws, cid)
    more = f"/api/v1/editorial/packets/{pid}/more-hooks"
    job_status.start(ws, "packet", str(cid), "Queued packet")
    try:
        running = await client.post(more, headers=headers(ws))
        job_status.update(ws, "packet", str(cid), state="waiting")
        waiting = await client.post(more, headers=headers(ws))
    finally:
        job_status.update(ws, "packet", str(cid), state="done")
    for response in (running, waiting):
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "still_writing"
        assert "Scripted idea" in response.json()["detail"]["message"]
    assert job_status.get(ws, "more_hooks", str(pid)) is None, "nothing was asked for"


async def test_a_voice_rewrite_that_waited_and_was_finished_by_a_resume_is_still_his_rewrite(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea", moment_ids=[MOMENT])
    await add_packet(editorial_sessionmaker, ws, cid)
    monkeypatch.setattr(tce.llm, "complete", busy_then_writes())
    started = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": True, "by": "voice"},
        headers=headers(ws),
    )
    rewrite_id = started.json()["rewrite_id"]
    assert job_status.get(ws, "packet", str(cid))["state"] == "waiting"
    edited = await change(
        client,
        ws,
        cid,
        "script",
        [{"field": "bullets.0", "after": "VOICE EDIT", "expect": "First point."}],
    )
    assert edited.status_code == 200, edited.text

    # The workspace's button finishes it, and says nothing about who asked.
    resumed = await client.post(f"/api/v1/editorial/candidates/{cid}/packet", headers=headers(ws))
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["rewrite_id"] == rewrite_id, "the rewrite keeps its id on the job"
    assert (await topic(client, ws, "scripted"))["topic"]["script"]["points"][0] == (
        good_output()["bullets"][0]
    )

    back = await undo_rewrite(client, ws, cid, rewrite_id)
    assert back.status_code == 200, back.text
    assert (await topic(client, ws, "scripted"))["topic"]["script"]["points"][0] == "VOICE EDIT"
    assert (await undo(client, ws, edited.json()["change_set_id"])).status_code == 200
    assert (await topic(client, ws, "scripted"))["topic"]["script"]["points"][0] == "First point."


async def test_an_unrecorded_rewrite_whose_script_moved_on_says_so_and_offers_the_version(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea", moment_ids=[MOMENT])
    await add_packet(editorial_sessionmaker, ws, cid)
    monkeypatch.setattr(tce.llm, "complete", busy_then_writes())
    started = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": True, "by": "voice"},
        headers=headers(ws),
    )
    rewrite_id = started.json()["rewrite_id"]
    edited = await change(
        client,
        ws,
        cid,
        "script",
        [{"field": "bullets.0", "after": "VOICE EDIT", "expect": "First point."}],
    )
    assert edited.status_code == 200, edited.text
    # A restart forgets the job; the resume after it cannot know who asked.
    job_status.clear()
    resumed = await client.post(f"/api/v1/editorial/candidates/{cid}/packet", headers=headers(ws))
    assert resumed.status_code == 200, resumed.text
    current = (await topic(client, ws, "scripted"))["topic"]["script"]["version"]

    response = await client.post(
        f"/api/v1/editorial/candidates/{cid}/script/undo-rewrite",
        json={"rewrite_id": rewrite_id, "replaced_version": 1, "by": "voice"},
        headers=headers(ws),
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "replaced_since"
    assert "still the current one" not in detail["message"]
    assert f"version {current}" in detail["message"]
    assert detail["current_version"] == current and detail["previous_version"] == current - 1

    # The version it offers really brings the edited script back.
    restored = await client.post(
        f"/api/v1/editorial/candidates/{cid}/script/restore",
        json={"version": detail["previous_version"], "by": "voice"},
        headers=headers(ws),
    )
    assert restored.status_code == 200, restored.text
    assert (await topic(client, ws, "scripted"))["topic"]["script"]["points"][0] == "VOICE EDIT"
