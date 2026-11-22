"""Choosing an opening brings the whole script written for it (T-24293). Synthetic data.

22-Nov-2026: he picked the third opening and line two did not follow from it,
because a pick swapped only the first spoken line. Now every opening carries
its own whole script (points, lines, beats); a pick uses it, writes it first
when it is missing, and never changes the opening when it cannot.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from tce.editorial import hook_scripts
from tce.editorial import packets as packets_mod
from tce.editorial import status as job_status
from tce.llm import LLMUnavailable
from tce.models.editorial import RecordingPacket
from tests.unit.test_recording_hook_choice import AUTH, client, script_for, seed_v2  # noqa: F401


def option(packet: dict, hook_id: str) -> dict:
    return next(h for h in packet["hook_options"] if h["id"] == hook_id)


class FakeResult:
    def __init__(self, data):
        self.structured = data
        self.text = ""
        self.job_id = uuid.uuid4()


def fake_writer(monkeypatch, *, instant: bool = False, bad: bool = False, unavailable=None):
    """The subscription writer: returns a script for every opening it is asked for.

    Like the real queue, a call that does not wait (wait_timeout_s=0) gets nothing
    back unless the job already finished (`instant`).
    """
    calls: list = []

    async def complete(request, *, wait_timeout_s=None, **_kw):
        calls.append({"request": request, "wait": wait_timeout_s})
        if unavailable is not None:
            raise unavailable
        if wait_timeout_s == 0 and not instant:
            raise LLMUnavailable("timeout", "still queued", job_id=uuid.uuid4())
        content = request.messages[0]["content"]
        wanted = content.split("THE OPENINGS TO WRITE A WHOLE SCRIPT FOR:\n", 1)[1]
        import json

        listed = json.loads(wanted.split("\n\nEVIDENCE", 1)[0])
        scripts = []
        for item in listed:
            entry = script_for(item["text"], item["hook_id"].replace("-", " "))
            if bad:
                entry["script_phrases"][2] = "Comment GUIDE below and I will send it."
            scripts.append({"hook_id": item["hook_id"], **entry})
        return FakeResult({"scripts": scripts})

    monkeypatch.setattr(packets_mod._llm, "complete", complete)
    return calls


async def give_scripts(sessionmaker, packet_id) -> None:
    """Write every opening's whole script onto the version, as the early write does."""
    async with sessionmaker() as s:
        row = await s.get(RecordingPacket, packet_id)
        options = []
        for o in row.hook_options:
            item = dict(o)
            if item["id"] == row.selected_hook_id:
                item["script"] = {**hook_scripts.script_of(row), "payoff_phrase_id": item["payoff_phrase_id"]}
            else:
                item["script"] = script_for(item["text"], item["id"].replace("-", " "))
            options.append(item)
        row.hook_options = options
        await s.commit()


async def test_repro_line_two_follows_the_chosen_opening(client, editorial_sessionmaker):  # noqa: F811
    """The 22-Nov case: opening 2 chosen, and line two must follow from it."""
    cand, original = await seed_v2(editorial_sessionmaker, scripts=False)
    await give_scripts(editorial_sessionmaker, original.id)
    old_line_two = original.script_phrases[1]

    r = await client.post(
        f"/api/v1/editorial/packets/{original.id}/choose-hook",
        json={"hook_id": "hook-2"},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    new = r.json()
    wanted = script_for(option(new, "hook-2")["text"], "hook 2")
    assert new["script_phrases"] == wanted["script_phrases"]
    assert new["script_phrases"][1] != old_line_two
    assert new["bullets"] == wanted["bullets"]
    assert [b["start_phrase_id"] for b in new["beats"]] == [
        b["start_phrase_id"] for b in wanted["beats"]
    ]
    # The posts are kept: they adapt the lesson for text, not the spoken opening.
    assert new["facebook_post"] == original.facebook_post
    # The opening left keeps its own words, so going back gives exactly them.
    back = await client.post(
        f"/api/v1/editorial/packets/{new['id']}/choose-hook",
        json={"hook_id": "hook-1"},
        headers=AUTH,
    )
    assert back.status_code == 200, back.text
    assert back.json()["script_phrases"] == list(original.script_phrases)
    assert back.json()["bullets"] == list(original.bullets)


async def test_a_missing_script_is_written_before_the_opening_changes(
    client, editorial_sessionmaker, monkeypatch  # noqa: F811
):
    cand, original = await seed_v2(editorial_sessionmaker, scripts=False)
    calls = fake_writer(monkeypatch)

    r = await client.post(
        f"/api/v1/editorial/packets/{original.id}/choose-hook",
        json={"hook_id": "hook-3"},
        headers=AUTH,
    )
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "writing"
    status = (
        await client.get(r.json()["status_url"].replace("/api/v1", "/api/v1"), headers=AUTH)
    ).json()
    assert status["state"] == "done", status
    new = status["result"]["packet"]
    assert new["selected_hook_id"] == "hook-3"
    assert new["script_phrases"] == script_for(option(new, "hook-3")["text"], "hook 3")["script_phrases"]
    # One job wrote both missing openings; the next pick is instant.
    assert all(c["request"].job_type == hook_scripts.JOB_TYPE for c in calls)
    queue = (await client.get("/api/v1/production/recording-queue", headers=AUTH)).json()
    assert queue["ideas"][0]["packet_id"] == new["id"]
    again = await client.post(
        f"/api/v1/editorial/packets/{new['id']}/choose-hook",
        json={"hook_id": "hook-2"},
        headers=AUTH,
    )
    assert again.status_code == 200, again.text
    assert again.json()["script_phrases"][0] == option(new, "hook-2")["text"]
    assert again.json()["script_phrases"][1] == "Here is the hook 2 part people skip."


async def test_a_finished_early_write_makes_the_pick_instant(
    client, editorial_sessionmaker, monkeypatch  # noqa: F811
):
    cand, original = await seed_v2(editorial_sessionmaker, scripts=False)
    fake_writer(monkeypatch, instant=True)
    r = await client.post(
        f"/api/v1/editorial/packets/{original.id}/choose-hook",
        json={"hook_id": "hook-2"},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    assert r.json()["script_phrases"][1] == "Here is the hook 2 part people skip."


async def test_no_capacity_says_so_and_changes_nothing(
    client, editorial_sessionmaker, monkeypatch  # noqa: F811
):
    cand, original = await seed_v2(editorial_sessionmaker, scripts=False)
    calls = fake_writer(monkeypatch)

    async def parked(_session, **_kw):
        return datetime(2026, 11, 23, 17, 0)

    monkeypatch.setattr(job_status, "capacity_park", parked)
    r = await client.post(
        f"/api/v1/editorial/packets/{original.id}/choose-hook",
        json={"hook_id": "hook-2"},
        headers=AUTH,
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "Claude limit" in detail and "not changed" in detail and "matches its first line" in detail
    assert calls == []
    versions = (
        await client.get(f"/api/v1/editorial/candidates/{cand.id}/packets", headers=AUTH)
    ).json()["packets"]
    assert [p["version"] for p in versions] == [1]


async def test_writer_limit_hit_while_writing_leaves_the_opening(
    client, editorial_sessionmaker, monkeypatch  # noqa: F811
):
    cand, original = await seed_v2(editorial_sessionmaker, scripts=False)
    fake_writer(
        monkeypatch,
        unavailable=LLMUnavailable(
            "waiting_capacity", "limit", retry_at=datetime.now() + timedelta(hours=30)
        ),
    )
    r = await client.post(
        f"/api/v1/editorial/packets/{original.id}/choose-hook",
        json={"hook_id": "hook-2"},
        headers=AUTH,
    )
    assert r.status_code == 409, r.text
    assert "not changed" in r.json()["detail"]
    versions = (
        await client.get(f"/api/v1/editorial/candidates/{cand.id}/packets", headers=AUTH)
    ).json()["packets"]
    assert [p["version"] for p in versions] == [1]


async def test_a_script_that_breaks_the_rules_is_never_used(
    client, editorial_sessionmaker, monkeypatch  # noqa: F811
):
    cand, original = await seed_v2(editorial_sessionmaker, scripts=False)
    fake_writer(monkeypatch, bad=True)
    r = await client.post(
        f"/api/v1/editorial/packets/{original.id}/choose-hook",
        json={"hook_id": "hook-2"},
        headers=AUTH,
    )
    assert r.status_code == 202, r.text
    status = (await client.get(r.json()["status_url"], headers=AUTH)).json()
    assert status["state"] == "failed"
    assert "not changed" in status["detail"]
    versions = (
        await client.get(f"/api/v1/editorial/candidates/{cand.id}/packets", headers=AUTH)
    ).json()["packets"]
    assert [p["version"] for p in versions] == [1]


def test_an_edit_makes_the_other_scripts_stale():
    base = {
        "bullets": ["a", "b"],
        "script_phrases": ["Open one.", "Two.", "Three."],
        "beats": [],
    }
    options = [
        {"id": "h1", "text": "Open one.", "payoff_phrase_id": "p002", "script": dict(base)},
        {"id": "h2", "text": "Open two.", "payoff_phrase_id": "p002",
         "script": {**base, "script_phrases": ["Open two.", "Follows two.", "Three."]}},
    ]
    assert hook_scripts.ready_script(options, "h1", base, "h2")["script_phrases"][1] == "Follows two."
    edited = {**base, "script_phrases": ["Open one.", "Two, fixed.", "Three."]}
    # Written from the words before the edit: not used, written again first.
    assert hook_scripts.ready_script(options, "h1", edited, "h2") is None
    assert hook_scripts.missing_hooks(options, "h1", edited) == ["h2"]
    assert hook_scripts.missing_hooks(options, "h1", base) == []
    # A stored script whose first line is not its opening is never used.
    options[1]["script"]["script_phrases"][0] = "Something else."
    assert hook_scripts.ready_script(options, "h1", base, "h2") is None


@pytest.mark.parametrize("count", [7, 3])
def test_payoff_lines_stay_inside_the_script_in_use(count):
    target = {"script_phrases": [f"l{n}" for n in range(count)], "bullets": [], "beats": []}
    options = [
        {"id": "h1", "text": "l0", "payoff_phrase_id": "p006"},
        {"id": "h2", "text": "l0", "payoff_phrase_id": "p002"},
    ]
    out = hook_scripts.switch_options(options, "h1", target, "h2", {**target, "payoff_phrase_id": "p002"})
    for item in out:
        assert int(item["payoff_phrase_id"][1:]) <= count
