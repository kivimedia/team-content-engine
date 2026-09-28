"""TCE edits by itself, end to end with a fake subscription answer. Synthetic data.

The subscription call and the ffmpeg render are replaced; everything between -
statuses, proofread record, overrides, the request's state - is the real code.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from tce.api.routers import production as prod
from tce.llm import LLMUnavailable
from tce.llm.provider import LLMResult
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import EditingRequest
from tce.production import autoedit


def words(text: str, start: float = 0.0, step: float = 0.5) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start_s": t, "end_s": t + step - 0.1, "precision": "word"})
        t += step
    return out


SPOKEN = "Getting them back is really smart. Not after you've finished your service. Call them."


@pytest.fixture
def wired(monkeypatch, editorial_sessionmaker):
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    monkeypatch.setattr(prod.settings, "production_auto_edit", True)
    asked: list[tuple[str, str]] = []
    answers: dict[str, dict] = {}

    async def fake_ask(kind, prompt, system, schema, ws, key, **_opts):
        asked.append((kind, prompt))
        answer = answers.get(kind)
        if callable(answer):
            answer = answer()
        if answer is None:
            raise LLMUnavailable("no_worker", "no worker in tests")
        if isinstance(answer, LLMUnavailable):
            raise answer
        return LLMResult(job_id=uuid.uuid4(), text="", structured=answer, model="claude-opus-5-5")

    async def fake_render(upload_id, ws, attempt, mode):
        async with editorial_sessionmaker() as s:
            row = await prod._load(s, upload_id, ws)
            row.status = "edited"
            row.edited_path = "/tmp/edited.mp4"
            row.status_detail = f"rendered {len(row.edit_plan['keep'])} ranges"
            await s.commit()

    monkeypatch.setattr(prod, "_ask", fake_ask)
    monkeypatch.setattr(prod, "_run_render", fake_render)
    return {"sm": editorial_sessionmaker, "asked": asked, "answers": answers}


async def seed(sm, *, planned: bool) -> tuple[uuid.UUID, uuid.UUID]:
    ws = uuid.uuid4()
    async with sm() as s:
        cand = TopicCandidate(
            workspace_id=ws, week_start=datetime(2026, 9, 21), moment_ids=["m"],
            title="Put the follow-up call in the deal", lesson="l", audience="a",
            public_angle="p", gates={}, status="recorded",
        )
        s.add(cand)
        await s.flush()
        up = RecordingUpload(
            workspace_id=ws, candidate_id=cand.id, original_filename="walk.mp4",
            storage_path="/tmp/walk.mp4", sha256=uuid.uuid4().hex * 2, status="transcribed",
            transcript=words(SPOKEN), duration_s=8.0,
        )
        s.add(up)
        await s.commit()
        if planned:
            await prod._compute_plan(s, ws, up)
            up.status, up.edited_path = "edited", "/tmp/edited.mp4"
            await s.commit()
        return ws, up.id


async def test_a_finished_walk_is_proofread_cut_and_rendered_with_no_clicks(wired):
    ws, uid = await seed(wired["sm"], planned=False)
    wired["answers"][autoedit.REVIEW_JOB] = {
        "removals": [],
        "corrections": [
            {"first": 6, "last": 7, "heard": "Not after", "replacement": "After", "why": "flips his point"}
        ],
    }
    await prod.auto_edit(uid, ws)
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    text = " ".join(w["text"] for w in row.transcript)
    assert "Not after" not in text and "smart. After you've" in text
    assert row.status == "edited"
    assert row.edit_plan["proofread"][0]["heard"] == "Not after"
    assert row.edit_plan["review"]["state"] == "done"
    assert prod.AUTO_MARK not in (row.job_ids or [])
    # The review saw his script context and ran on the subscription job type.
    kind, prompt = wired["asked"][0]
    assert kind == autoedit.REVIEW_JOB and "Put the follow-up call in the deal" in prompt


async def test_no_worker_still_edits_without_touching_a_word(wired):
    ws, uid = await seed(wired["sm"], planned=False)
    await prod.auto_edit(uid, ws)  # no answer registered: the queue has no worker
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    assert row.status == "edited"
    assert " ".join(w["text"] for w in row.transcript) == SPOKEN
    assert row.edit_plan["review"]["state"] == "unavailable"
    assert row.edit_plan["decided_by"] == "rules"


WALK = (
    "Selling is where the coaching starts. Hey, Maple Rain, boy! Which means the call "
    "is the first step of the change. Which means the call is the first step in the change. "
    "It is not a detour."
)


async def seed_walk(sm) -> tuple[uuid.UUID, uuid.UUID]:
    ws, uid = await seed(sm, planned=False)
    async with sm() as s:
        row = await prod._load(s, uid, ws)
        row.transcript = words(WALK)
        row.duration_s = row.transcript[-1]["end_s"] + 0.5
        await s.commit()
    return ws, uid


def review_of_walk() -> dict:
    w = WALK.split()
    first_take = w.index("Which")
    second_take = first_take + 1 + w[first_take + 1 :].index("Which")
    return {
        "removals": [
            {"first": 6, "last": 9, "heard": "Hey, Maple Rain, boy!", "kind": "aside",
             "kept_from": -1, "why": "calling the dogs"},
            {"first": first_take, "last": second_take - 1,
             "heard": " ".join(w[first_take:second_take]), "kind": "retake",
             "kept_from": second_take, "why": "said again, complete"},
            # A removal that misquotes its words is refused.
            {"first": 0, "last": 1, "heard": "Buying is", "kind": "junk", "kept_from": -1, "why": "x"},
        ],
        "corrections": [],
    }


async def test_the_review_takes_out_what_it_quotes_and_the_card_lists_it(wired):
    from tce.editorial import library

    ws, uid = await seed_walk(wired["sm"])
    wired["answers"][autoedit.REVIEW_JOB] = review_of_walk()
    await prod.auto_edit(uid, ws)
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
        items = (await library.list_library(s, ws))["items"]
    plan = row.edit_plan
    assert row.status == "edited" and plan["decided_by"] == "editor_review"
    assert "Maple" not in plan["kept_text"]
    assert plan["kept_text"].count("Which means") == 1
    assert "first step in the change" in plan["kept_text"]
    assert plan["kept_text"].startswith("Selling is where")  # the misquoted removal did nothing
    reasons = {r["reason"] for r in plan["removed"]}
    assert reasons == {"aside", "retake"}
    # Kept words never sit inside a cut: the captions follow the edit.
    for w in plan["words"]:
        assert any(s <= (w["start"] + w["end"]) / 2 <= e for s, e in plan["keep"]), w
    card = next(i for i in items if i["upload_id"] == str(uid))
    assert [r["reason"] for r in card["removed"]] == ["aside", "retake"]
    assert any(a["key"] == "edit_again" for a in card["actions"])


async def test_a_late_review_re_edits_by_itself(wired, monkeypatch):
    spawned: list = []
    monkeypatch.setattr(prod, "_spawn", lambda coro: spawned.append(coro))
    ws, uid = await seed_walk(wired["sm"])
    calls = {"n": 0}

    def answer():
        calls["n"] += 1
        return LLMUnavailable("timeout", "still queued") if calls["n"] == 1 else review_of_walk()

    wired["answers"][autoedit.REVIEW_JOB] = answer
    await prod.auto_edit(uid, ws)
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    assert row.status == "edited"  # it went out on the rules
    assert row.edit_plan["review"]["state"] == "waiting"
    assert row.edit_plan["decided_by"] == "rules"
    waiters = [c for c in spawned if c.__name__ == "_await_review"]
    assert len(waiters) == 1  # and a waiter is watching for the review
    for c in spawned:
        if c not in waiters:
            c.close()  # the post drafting is not under test here
    await waiters[0]
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    assert row.edit_plan["review"]["state"] == "done"
    assert row.edit_plan["decided_by"] == "editor_review"
    assert "Maple" not in row.edit_plan["kept_text"]


async def test_a_review_that_would_cut_most_of_the_video_is_not_used(wired):
    ws, uid = await seed_walk(wired["sm"])
    n = len(WALK.split())
    wired["answers"][autoedit.REVIEW_JOB] = {
        "removals": [{"first": 0, "last": n - 3, "heard": " ".join(WALK.split()[: n - 2]),
                      "kind": "junk", "kept_from": -1, "why": "?"}],
        "corrections": [],
    }
    await prod.auto_edit(uid, ws)
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    assert row.status == "edited"
    assert row.edit_plan["review"]["state"] == "rules"
    assert row.edit_plan["decided_by"] == "rules"
    assert "Selling is where the coaching starts." in row.edit_plan["kept_text"]


async def test_a_request_is_carried_out_and_marked_done(wired):
    ws, uid = await seed(wired["sm"], planned=True)
    async with wired["sm"]() as s:
        req = EditingRequest(workspace_id=ws, upload_id=uid, scope="whole",
                             request="I never said not, and drop the last bit", state="open")
        s.add(req)
        await s.commit()
    wired["answers"][autoedit.EDIT_REQUEST_JOB] = {
        "reply": "Removed the 'Not' and cut 'Call them.'",
        "needs_you": False,
        "question": "",
        "corrections": [{"first": 6, "last": 7, "heard": "Not after", "replacement": "After", "why": ""}],
        "cut": [{"first": 12, "last": 13}],
        "restore": [],
    }
    await prod.run_edit_request(req.id, ws)
    async with wired["sm"]() as s:
        req = await s.get(EditingRequest, req.id)
        row = await prod._load(s, uid, ws)
    assert req.state == "done", req.result
    assert req.result["corrections"] == [{"heard": "Not after", "replacement": "After"}]
    assert "Not after" not in " ".join(w["text"] for w in row.transcript)
    # The cut persists as an override and the words are gone from the edit.
    assert row.edit_plan["overrides"]["cut"]
    last = row.transcript[-1]
    assert all(not (s <= last["start_s"] <= e) for s, e in row.edit_plan["keep"])
    # A later re-plan (e.g. the plan button) keeps the cut.
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
        await prod._compute_plan(s, ws, row)
        assert row.edit_plan["overrides"]["cut"]
        assert all(not (s0 <= last["start_s"] <= e0) for s0, e0 in row.edit_plan["keep"])


async def test_an_unclear_request_comes_back_as_one_question(wired):
    ws, uid = await seed(wired["sm"], planned=True)
    async with wired["sm"]() as s:
        req = EditingRequest(workspace_id=ws, upload_id=uid, scope="whole",
                             request="make it pop", state="open")
        s.add(req)
        await s.commit()
    wired["answers"][autoedit.EDIT_REQUEST_JOB] = {
        "reply": "", "needs_you": True, "question": "Pop how - music, faster cuts, or a hook?",
        "corrections": [], "cut": [], "restore": [],
    }
    await prod.run_edit_request(req.id, ws)
    async with wired["sm"]() as s:
        req = await s.get(EditingRequest, req.id)
    assert req.state == "needs_you" and "music" in req.result["question"]
