"""Pieces sent two or three at a time (23-Nov, wait-less item B9, part 3).

The Book page and Record without a script now send up to three pieces at once, so they
land in any order. The server keeps each piece under its own number (store_piece names its
file by the number, pieces() reads them back sorted), so the joined video is the same.
Same routes and test app as test_agent_talks.py, a tiny recording made here.
"""

from __future__ import annotations

import asyncio
import uuid

from tce.api.routers import agent_talks as talk_routes
from tce.models.recording_session import AgentTalk
from tce.production import agent_talks
from tests.unit.test_agent_talks import (  # noqa: F401 - the fixtures are used by name
    AUTH,
    BASE,
    _new_talk,
    _record,
    client,
    needs_ffmpeg,
    spawned,
)

pytestmark = needs_ffmpeg


async def test_pieces_land_in_any_order_and_at_once_and_join_by_number(client, editorial_sessionmaker, tmp_path):
    """The pages send two or three pieces at a time (B9 part 3): the server keeps each under
    its own number, so the order they arrive in never changes the video."""
    data = _record(tmp_path / "parallel.webm", "webm", seconds=3.0)
    pieces = [data[i:i + 4000] for i in range(0, len(data), 4000)]
    assert len(pieces) >= 6
    talk = await _new_talk(client, call_id="call-parallel")
    order = list(range(len(pieces)))[::-1]
    for start in range(0, len(order), 3):
        batch = order[start:start + 3]
        answers = await asyncio.gather(*(
            client.put(f"{BASE}/{talk}/chunks/{seq}", headers=AUTH, content=pieces[seq]) for seq in batch))
        assert [a.status_code for a in answers] == [200] * len(batch)
    got = (await client.get(f"{BASE}/{talk}", headers=AUTH)).json()
    assert got["pieces"] == len(pieces) and got["bytes_total"] == len(data)
    async with editorial_sessionmaker() as s:
        folder = talk_routes._folder(await s.get(AgentTalk, uuid.UUID(talk)))
    assert b"".join(p.read_bytes() for _n, p in agent_talks.pieces(folder)) == data
    r = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={})
    assert r.status_code == 200 and r.json()["missing_pieces"] == []
