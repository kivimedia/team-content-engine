"""A spoken pick of an opening brings its whole script too (T-24293). Synthetic data."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from tce.editorial import packets as packets_mod
from tce.editorial import status as job_status
from tce.llm import LLMUnavailable
from tce.models.editorial import RecordingPacket
from tests.unit.test_editorial_voice_agent import (  # noqa: F401
    add_candidate,
    add_packet,
    change,
    client,
    headers,
)

H2_SCRIPT = {
    "bullets": ["Nobody checks.", "Check it.", "Then trust it."],
    "script_phrases": ["Nobody checks the result.", "So I check it for them.", "Then trust it."],
    "beats": [],
    "payoff_phrase_id": "p002",
}


async def versions(sm, cid):
    async with sm() as s:
        rows = (
            await s.execute(
                select(RecordingPacket)
                .where(RecordingPacket.candidate_id == cid)
                .order_by(RecordingPacket.version)
            )
        ).scalars().all()
    return list(rows)


async def test_a_spoken_pick_takes_the_whole_script_and_undo_puts_it_back(
    client, editorial_sessionmaker  # noqa: F811
):
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    pid = await add_packet(editorial_sessionmaker, ws, cid)
    async with editorial_sessionmaker() as s:
        row = await s.get(RecordingPacket, pid)
        h1, h2 = (dict(o) for o in row.hook_options)
        h1["script"] = {
            "bullets": list(row.bullets), "script_phrases": list(row.script_phrases),
            "beats": [], "payoff_phrase_id": "p1",
        }
        h2["script"] = H2_SCRIPT
        row.hook_options = [h1, h2]
        await s.commit()

    response = await change(
        client, ws, cid, "script",
        [{"op": "choose_hook", "after": "2", "expect": "Nobody checks the result."}],
    )
    assert response.status_code == 200, response.text
    rows = await versions(editorial_sessionmaker, cid)
    assert rows[-1].script_phrases == H2_SCRIPT["script_phrases"]
    assert rows[-1].bullets == H2_SCRIPT["bullets"]

    undone = await client.post(
        f"/api/v1/editorial/change-sets/{response.json()['change_set_id']}/undo",
        json={"by": "voice"},
        headers=headers(ws),
    )
    assert undone.status_code == 200, undone.text
    rows = await versions(editorial_sessionmaker, cid)
    assert rows[-1].script_phrases == ["Your AI said done. Was it?", "Line two.", "Line three."]
    assert rows[-1].bullets == ["First point.", "Second point.", "Third point."]


async def test_a_spoken_pick_with_no_script_starts_the_writer_and_changes_nothing(
    client, editorial_sessionmaker, monkeypatch  # noqa: F811
):
    asked = []

    async def complete(request, **_kw):
        asked.append(request.job_type)
        raise LLMUnavailable("timeout", "still queued", job_id=uuid.uuid4())

    monkeypatch.setattr(packets_mod._llm, "complete", complete)
    ws = uuid.uuid4()
    cid = await add_candidate(editorial_sessionmaker, ws, "Scripted idea")
    pid = await add_packet(editorial_sessionmaker, ws, cid)

    response = await change(
        client, ws, cid, "script",
        [{"op": "choose_hook", "after": "2", "expect": "Nobody checks the result."}],
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "hook_script_writing"
    assert "switches by itself" in detail["message"]
    # The writer was started for that packet, and nothing was written yet.
    assert job_status.get(ws, "choose_hook", str(pid)) is not None
    assert asked and set(asked) == {"recording_packet_hook_scripts"}
    assert [r.version for r in await versions(editorial_sessionmaker, cid)] == [1]
