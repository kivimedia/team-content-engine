"""Give a test packet's openings their whole scripts (T-24293).

A pick now uses the whole script written for the chosen opening. Tests about
something else (a verdict, a version, an undo) give every opening the script it
had before, under its own first line, so they keep testing what they tested.
The rewrite itself is tested in test_hook_whole_script.py.
"""

from __future__ import annotations

from sqlalchemy import select

from tce.editorial import hook_scripts
from tce.models.editorial import RecordingPacket


async def fill_hook_scripts(sm, ws, *, packet_id=None, candidate_id=None) -> None:
    async with sm() as s:
        query = select(RecordingPacket).where(RecordingPacket.workspace_id == ws)
        if packet_id is not None:
            query = query.where(RecordingPacket.id == packet_id)
        else:
            query = query.where(
                RecordingPacket.candidate_id == candidate_id,
                RecordingPacket.status != "superseded",
            ).order_by(RecordingPacket.version.desc())
        row = (await s.execute(query)).scalars().first()
        current = hook_scripts.script_of(row)
        options = []
        for option in row.hook_options or []:
            item = dict(option)
            phrases = list(current["script_phrases"])
            if phrases:
                phrases[0] = str(item.get("text") or "")
            if item.get("id") == row.selected_hook_id:
                phrases = list(current["script_phrases"])
            item["script"] = {
                **current,
                "script_phrases": phrases,
                "payoff_phrase_id": item.get("payoff_phrase_id"),
            }
            options.append(item)
        row.hook_options = options
        await s.commit()
