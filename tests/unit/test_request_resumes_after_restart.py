"""A restart in the middle of a request's render (20-Oct, Angel's top line on a953792f).

Another deploy restarted TCE while the request's re-render ran. On startup the request was
read again from the start; the editor saw its own change already saved, answered "I didn't
need to change anything", and the request was marked done while the video sat in
"rendering" with the old file. Now a request whose change was saved goes straight back to
the render, keeps the reply it already gave, and is done only when the video is.
"""

from __future__ import annotations

import asyncio

import pytest

from tce.api.routers import production as prod
from tce.models.editorial_workspace import EditingRequest
from tce.production import autoedit

from .test_autoedit_flow import seed, wired  # noqa: F401 - the fixture

ANSWER = {
    "reply": "Removed the 'Not'.",
    "needs_you": False,
    "question": "",
    "corrections": [{"first": 6, "last": 7, "heard": "Not after", "replacement": "After", "why": ""}],
    "cut": [],
    "restore": [],
}
SECOND_READ = {  # what the editor says when it reads the note again after its change
    "reply": "I didn't need to change anything: it already says 'After'.",
    "needs_you": False, "question": "", "corrections": [], "cut": [], "restore": [],
}


async def test_a_restart_mid_render_renders_again_and_keeps_the_first_reply(wired, monkeypatch):  # noqa: F811
    ws, uid = await seed(wired["sm"], planned=True)
    async with wired["sm"]() as s:
        req = EditingRequest(workspace_id=ws, upload_id=uid, scope="whole",
                             request="I never said not", state="open")
        s.add(req)
        await s.commit()
    wired["answers"][autoedit.EDIT_REQUEST_JOB] = ANSWER

    renders: list[str] = []
    real_render = prod._run_render

    async def dies(upload_id, ws_, attempt, mode):
        renders.append("killed")
        raise asyncio.CancelledError  # the process went away mid-ffmpeg

    monkeypatch.setattr(prod, "_run_render", dies)
    with pytest.raises(asyncio.CancelledError):
        await prod.run_edit_request(req.id, ws)

    async with wired["sm"]() as s:
        req_row = await s.get(EditingRequest, req.id)
        assert req_row.state == "in_progress"

    # Startup: the request runs again. The editor would now say there is nothing to do.
    wired["answers"][autoedit.EDIT_REQUEST_JOB] = SECOND_READ
    asked_before = len(wired["asked"])

    async def renders_ok(upload_id, ws_, attempt, mode):
        renders.append("ok")
        await real_render(upload_id, ws_, attempt, mode)

    monkeypatch.setattr(prod, "_run_render", renders_ok)
    await prod.run_edit_request(req.id, ws)

    async with wired["sm"]() as s:
        req_row = await s.get(EditingRequest, req.id)
        row = await prod._load(s, uid, ws)
    assert renders == ["killed", "ok"]
    assert row.status == "edited"
    assert req_row.state == "done", req_row.result
    assert req_row.result["reply"] == "Removed the 'Not'."
    assert req_row.result["corrections"] == [{"heard": "Not after", "replacement": "After"}]
    assert len(wired["asked"]) == asked_before  # not read again: the change was already made
