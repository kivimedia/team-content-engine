"""Agent talks, contract C4.1 (4-Oct): archive or edit, his choice after Stop.

A recording is never sent into editing without his choice. The finish carries
"edit": true or false (missing is true, for a caller from before the choice). False
keeps the video archived: no edit, no check by Jennifer, not in Still to do, listed
under Archived in the Library with "Edit this now", which starts the normal edit and
takes it out of Archived. A second finish keeps the first choice and says so. Same
routes and test app as test_agent_talks.py; synthetic data only.
"""

from __future__ import annotations

import uuid

import pytest

from tce.api.routers import agent_talks as talk_routes
from tce.editorial import library
from tce.editorial import today as today_service
from tce.models.editorial import RecordingUpload
from tce.models.recording_session import AgentTalk
from tests.unit.test_agent_talks import (  # noqa: F401 - the fixtures are used by name
    AUTH,
    BASE,
    TRANSCRIPT,
    WS,
    _new_talk,
    _record,
    _send,
    client,
    needs_ffmpeg,
    spawned,
)

pytestmark = needs_ffmpeg


async def _finished_talk(client, tmp_path, call_id: str, **finish) -> tuple[str, dict]:
    data = _record(tmp_path / f"{call_id}.webm", "webm", seconds=2.0)
    talk = await _new_talk(client, call_id=call_id)
    await _send(client, talk, data, shuffle=False)
    r = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={"transcript": TRANSCRIPT, **finish})
    assert r.status_code == 200, r.text
    return talk, r.json()


async def _upload(sm, upload_id: str) -> RecordingUpload:
    async with sm() as s:
        return await s.get(RecordingUpload, uuid.UUID(upload_id))


async def _library(sm, filter_key: str) -> list[dict]:
    async with sm() as s:
        return (await library.list_library(s, WS, filter_key=filter_key))["items"]


# ---------------------------------------------------------------------------
# The finish


async def test_finish_with_edit_false_archives_the_video_and_starts_no_edit(
    client, editorial_sessionmaker, tmp_path, spawned
):
    talk, body = await _finished_talk(client, tmp_path, "call-archive", edit=False)
    assert body["edit"] is False and body["archived"] is True
    assert body["edit_started"] is False and body["status"] == "uploaded"
    assert spawned == []  # no edit, so no render and no check by Jennifer either
    upload = await _upload(editorial_sessionmaker, body["upload_id"])
    assert upload.archived_at is not None and upload.status == "uploaded"
    assert upload.source == "agent_talk" and not upload.edited_path
    assert "Archived as you chose" in upload.status_detail
    assert "Jennifer starts the edit" not in upload.status_detail
    async with editorial_sessionmaker() as s:
        row = await s.get(AgentTalk, uuid.UUID(talk))
    assert row.status == "finished" and row.join_meta["edit"] is False
    assert "archived, not edited" in row.status_detail


@pytest.mark.parametrize("finish", [{"edit": True}, {}], ids=["edit-true", "edit-missing"])
async def test_finish_with_edit_true_or_missing_edits_as_before(
    client, editorial_sessionmaker, tmp_path, spawned, finish
):
    _talk, body = await _finished_talk(client, tmp_path, "call-edit", **finish)
    assert body["edit"] is True and body["archived"] is False and body["edit_started"] is True
    assert [c.__name__ for c in spawned] == ["auto_edit"]
    upload = await _upload(editorial_sessionmaker, body["upload_id"])
    assert upload.archived_at is None and "Jennifer starts the edit now" in upload.status_detail


async def test_a_second_finish_keeps_the_first_choice_and_says_so(client, editorial_sessionmaker, tmp_path, spawned):
    talk, first = await _finished_talk(client, tmp_path, "call-twice", edit=False)
    again = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={"edit": True})
    assert again.status_code == 200
    got = again.json()
    assert got["upload_id"] == first["upload_id"] and got["already_finished"] is True
    assert got["edit"] is False and got["archived"] is True and got["edit_started"] is False
    assert got["choice_kept"] is True
    assert "first choice stands: archive it without an edit" in got["note"]
    assert "nothing changed" in got["note"]
    assert spawned == []
    assert (await _upload(editorial_sessionmaker, first["upload_id"])).archived_at is not None
    # The same choice again is no conflict.
    same = (await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={"edit": False})).json()
    assert same["choice_kept"] is False and same["edit"] is False

    # The other way round: edited first, a later "archive" does not pull it back.
    talk2, first2 = await _finished_talk(client, tmp_path, "call-twice-b", edit=True)
    later = (await client.post(f"{BASE}/{talk2}/finish", headers=AUTH, json={"edit": False})).json()
    assert later["edit"] is True and later["archived"] is False and later["choice_kept"] is True
    assert "first choice stands: send it to be edited" in later["note"]
    assert [c.__name__ for c in spawned] == ["auto_edit"]  # only the first finish's edit


# ---------------------------------------------------------------------------
# The Library's Archived list and Edit this now


async def test_an_archived_talk_is_listed_under_archived_and_not_in_the_to_do_views(
    client, editorial_sessionmaker, tmp_path
):
    _talk, body = await _finished_talk(client, tmp_path, "call-listed", edit=False)
    upload_id = body["upload_id"]
    archived = await _library(editorial_sessionmaker, "archived")
    card = next(i for i in archived if i["upload_id"] == upload_id)
    # The agent, the date and the length, in plain words.
    assert card["title"] == "Talk with Atlas, 3 Oct" and card["agent"] == "Atlas"
    assert card["recorded_at"] and card["duration_s"] and abs(card["duration_s"] - 2.0) < 0.5
    assert card["archived"] is True
    assert card["state_sentence"] == library.ARCHIVED_UNEDITED
    keys = [a["key"] for a in card["actions"]]
    assert keys[0] == "edit_now"
    assert card["actions"][0]["label"] == "Edit this now"
    for view in ("todo", "uploading", "all"):
        assert upload_id not in [i["upload_id"] for i in await _library(editorial_sessionmaker, view)], view
    async with editorial_sessionmaker() as s:
        today = await today_service.build(s, WS)
    assert upload_id not in repr(today)
    # The upload's own JSON says it is archived.
    got = (await client.get(f"/api/v1/production/uploads/{upload_id}", headers=AUTH)).json()
    assert got["archived"] is True


async def test_edit_this_now_starts_the_edit_and_takes_it_out_of_archived(
    client, editorial_sessionmaker, tmp_path, spawned
):
    _talk, body = await _finished_talk(client, tmp_path, "call-edit-now", edit=False)
    upload_id = body["upload_id"]
    assert spawned == []
    r = await client.post(f"/api/v1/production/uploads/{upload_id}/auto-edit", headers=AUTH)
    assert r.status_code == 202, r.text
    got = r.json()
    assert got["archived"] is False and got["status"] == "proofreading"
    assert got["status_detail"].startswith("Taken out of Archived. Editing it now: transcribing first")
    assert [c.__name__ for c in spawned] == ["auto_edit"]
    upload = await _upload(editorial_sessionmaker, upload_id)
    assert upload.archived_at is None and upload.status == "proofreading"
    assert upload_id not in [i["upload_id"] for i in await _library(editorial_sessionmaker, "archived")]
    todo = await _library(editorial_sessionmaker, "todo")
    card = next(i for i in todo if i["upload_id"] == upload_id)
    assert "edit_now" not in [a["key"] for a in card["actions"]]
    assert card["state_sentence"] == got["status_detail"]


async def test_an_archived_video_that_was_edited_before_offers_no_edit_this_now(
    client, editorial_sessionmaker, tmp_path
):
    """The Library's own Archive button on an edited video: it has its edit, so the
    Archived list offers watching it, not a first edit."""
    _talk, body = await _finished_talk(client, tmp_path, "call-edited", edit=True)
    async with editorial_sessionmaker() as s:
        upload = await s.get(RecordingUpload, uuid.UUID(body["upload_id"]))
        upload.edited_path = upload.storage_path
        upload.status = "edited"
        await s.commit()
        await library.set_archived(s, WS, upload.id, True)
        await s.commit()
    card = next(i for i in await _library(editorial_sessionmaker, "archived") if i["upload_id"] == body["upload_id"])
    assert "edit_now" not in [a["key"] for a in card["actions"]]
    assert card["state_sentence"] != library.ARCHIVED_UNEDITED


def test_the_backstop_and_the_page_use_plain_words():
    for text in (talk_routes.ARCHIVED_BY_CHOICE, talk_routes.ARCHIVED_BY_BACKSTOP, library.ARCHIVED_UNEDITED):
        assert "—" not in text and "–" not in text and "--" not in text
        assert "Edit this now" in text
