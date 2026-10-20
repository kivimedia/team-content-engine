"""A video recorded in the last day and not yet edited sits at the top of Still to do
while it is being edited, and says so (T-14299, 20-Oct)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.unit.test_jennifer_flow import (  # noqa: F401  (fixtures)
    auth, client, needs_ffmpeg, prod, recording, seed, spoken, wired,
)
from tce.editorial import library


@needs_ffmpeg
async def test_a_new_take_sits_above_older_edited_ones(wired, tmp_path):
    text = "Hello there. Few clicks came in no leads."
    ws, old = await seed(wired["sm"], recording(tmp_path / "a.wav", spoken(text)), spoken(text))
    ws2, new = await seed(wired["sm"], recording(tmp_path / "b.wav", spoken(text)), spoken(text))
    async with wired["sm"]() as s:
        row = await prod._load(s, old, ws)
        row.edited_path = str(tmp_path / "a-edit.mp4")
        row.created_at = datetime.now(UTC) - timedelta(days=3)
        fresh = await prod._load(s, new, ws2)
        fresh.workspace_id = ws
        fresh.status = "rendering"
        fresh.created_at = datetime.now(UTC) - timedelta(minutes=30)
        await s.commit()
    async with wired["sm"]() as s:
        items = (await library.list_library(s, ws))["items"]
    ids = [i["upload_id"] for i in items]
    assert ids.index(str(new)) < ids.index(str(old))
    by_id = {i["upload_id"]: i for i in items}
    assert by_id[str(new)]["recent_take"] is True and by_id[str(old)]["recent_take"] is False
