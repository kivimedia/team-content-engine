"""Talk to the editor, step 4 (30-Sep): a sitting's notes in one job, then one render.

Synthetic data. The subscription call (_ask) and the ffmpeg render (_run_render) are
replaced, as in test_autoedit_flow.py; the sitting, the notes, the plan, the gates,
the routes and the settle are the real code.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.editorial import library
from tce.llm import LLMUnavailable
from tce.llm.provider import LLMResult
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import EditingRequest, EditSession
from tce.production import autoedit
from tce.production.retakes import frame_keep
from tce.settings import settings

KEY = "synthetic-test-key"


def words(text: str, start: float = 0.0, step: float = 0.5) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start_s": t, "end_s": t + step - 0.1, "precision": "word"})
        t += step
    return out


# 0 Getting 1 them 2 back 3 is 4 really 5 smart. 6 Not 7 after 8 you've 9 finished
# 10 your 11 service. 12 Call 13 them.
SPOKEN = "Getting them back is really smart. Not after you've finished your service. Call them."
WALK = (
    "Selling is where the coaching starts. Hey, Maple Rain, boy! Which means the call "
    "is the first step of the change. Which means the call is the first step in the change. "
    "It is not a detour."
)


def note(n, *, reply="", needs_you=False, question="", corrections=(), cut=(), restore=(), hold=()):
    return {
        "note": n, "reply": reply, "needs_you": needs_you, "question": question,
        "corrections": list(corrections), "cut": list(cut), "restore": list(restore), "hold": list(hold),
    }


def fix(first, last, heard, replacement):
    return {"first": first, "last": last, "heard": heard, "replacement": replacement, "why": "his note"}


@pytest.fixture
def wired(monkeypatch, editorial_sessionmaker):
    sm = editorial_sessionmaker
    monkeypatch.setattr(prod, "session_factory", lambda: sm)
    monkeypatch.setattr(prod, "TALK_WORKER_RETRY_S", 0.0)
    asked: list[dict] = []
    answers: list = []
    renders: list = []

    async def fake_ask(kind, prompt, system, schema, ws, key, **opts):
        asked.append({"kind": kind, "prompt": prompt, "system": system, "schema": schema, "key": key, **opts})
        answer = answers.pop(0) if answers else LLMUnavailable("failed", "no answer in this test")
        if inspect.iscoroutinefunction(answer):
            answer = await answer()
        elif callable(answer):
            answer = answer()
        if isinstance(answer, BaseException):
            raise answer
        return LLMResult(job_id=uuid.uuid4(), text="", structured=answer, model="claude-opus-5-5")

    async def fake_render(upload_id, ws, attempt, mode):
        renders.append(upload_id)
        async with sm() as s:
            row = await prod._load(s, upload_id, ws)
            row.status = "edited"
            row.edited_path = "/tmp/edited.mp4"
            row.rendered_keep = frame_keep(row.edit_plan["keep"])
            row.render_ref = uuid.uuid4().hex[:16]
            row.status_detail = f"rendered {len(row.edit_plan['keep'])} ranges"
            row.job_ids = prod._with_lease(row.job_ids, None)
            await s.commit()

    monkeypatch.setattr(prod, "_ask", fake_ask)
    monkeypatch.setattr(prod, "_run_render", fake_render)
    return {"sm": sm, "asked": asked, "answers": answers, "renders": renders}


async def seed(sm, tmp_path: Path, text: str = SPOKEN, review: dict | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    """An edited, stamped video. The recording file does not exist: no audio is read."""
    ws = uuid.uuid4()
    w = words(text)
    async with sm() as s:
        cand = TopicCandidate(
            workspace_id=ws, week_start=datetime(2026, 9, 28), moment_ids=["m"],
            title="Call them after the service", lesson="l", audience="a",
            public_angle="p", gates={}, status="recorded",
        )
        s.add(cand)
        await s.flush()
        up = RecordingUpload(
            workspace_id=ws, candidate_id=cand.id, original_filename="walk.mp4",
            storage_path=str(tmp_path / f"missing-{uuid.uuid4().hex[:6]}.mp4"), sha256=uuid.uuid4().hex * 2,
            status="transcribed", transcript=w, duration_s=w[-1]["end_s"] + 0.5,
            edit_plan={"review": review} if review else None,
        )
        s.add(up)
        await s.commit()
        await prod._compute_plan(s, ws, up)
        assert up.status == "planned", up.status_detail
        up.status, up.edited_path = "edited", "/tmp/edited.mp4"
        up.rendered_keep = frame_keep(up.edit_plan["keep"])
        up.render_ref = "0000seedrender00"
        await s.commit()
        return ws, up.id


async def sit(sm, ws, uid, notes, typed: list[str] = ()) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Open a sitting, pin each (edit second, his words, the editor's reading), add typed
    whole-video notes, and say yes to the read-back: the sitting is thinking."""
    async with sm() as s:
        sitting = await library.open_sitting(s, ws, uid)
        ids = []
        for edit_s, heard, understood in notes:
            pinned = await library.pin_note(s, ws, sitting.id, edit_s=edit_s, render_ref=sitting.render_ref)
            await library.update_note(s, ws, sitting.id, pinned.id, heard=heard, understood=understood)
            ids.append(pinned.id)
        for text in typed:
            row = await library.create_edit_request(s, ws, uid, request=text, sitting=sitting)
            ids.append(row.id)
        preview = await library.submit_preview(s, ws, sitting.id)
        await library.submit(s, ws, sitting.id, check=preview["check"])
        await s.commit()
        return sitting.id, ids


async def state_of(sm, ws, uid, sid):
    async with sm() as s:
        row = await prod._load(s, uid, ws)
        sitting = await s.get(EditSession, sid)
        notes = await library.sitting_notes(s, ws, sid)
        return row, sitting, {n.id: n for n in notes}


def kept(row, i: int) -> bool:
    w = row.transcript[i]
    return any(a <= (w["start_s"] + w["end_s"]) / 2 <= b for a, b in row.edit_plan["keep"])


def kept_word(row, text: str) -> bool:
    """Whether the edit keeps the word spelled `text` (a fix can shift the indexes)."""
    return kept(row, next(i for i, w in enumerate(row.transcript) if w["text"] == text))


# ---------------------------------------------------------------- one job, one render


async def test_a_sitting_is_one_opus_call_and_one_render(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    async with sm() as s:
        start = await prod._load(s, uid, ws)
        old_ref, old_words = start.render_ref, [w["text"] for w in start.transcript]
    sid, (n1, n2, n3) = await sit(
        sm, ws, uid,
        [(3.2, "I never said not", "At 0:03 you want the 'Not' gone."), (6.6, "drop the last bit", None)],
        typed=["Make the captions bigger"],
    )
    wired["answers"].append({
        "summary": "Took out the 'Not' and cut 'Call them.'",
        "notes": [
            note(1, reply="Removed the 'Not'.", corrections=[fix(6, 7, "Not after", "After")]),
            note(2, reply="Cut 'Call them.'", cut=[{"first": 12, "last": 13}]),
            note(3, reply="Caption size is set by the caption style, not by the cut."),
        ],
    })
    await prod.run_talk_session(sid, ws)

    asked = wired["asked"]
    assert len(asked) == 1 and asked[0]["kind"] == autoedit.EDIT_BATCH_JOB
    assert asked[0]["schema"] is autoedit.EDIT_BATCH_SCHEMA
    assert asked[0]["max_tokens"] == 1500 + 600 * 3
    assert asked[0]["prompt_version"] == autoedit.EDIT_BATCH_PROMPT_VERSION
    assert asked[0]["system"] == autoedit.edit_batch_system()
    assert asked[0]["key"] == prod.talk_key(sid, asked[0]["prompt"], asked[0]["system"])
    prompt = asked[0]["prompt"]
    assert "Call them after the service" in prompt  # the script context
    assert '[note 1 | 0:03 in the edit | he said "I never said not" | agreed: "At 0:03 you want' in prompt
    assert '[note 2 | 0:06 in the edit | he said "drop the last bit"]' in prompt
    assert '[note 3 | the whole video | he said "Make the captions bigger"]' in prompt
    assert "6:Not <note 1>" in prompt and "13:them. <note 2>" in prompt
    assert "<note 3>" not in prompt

    assert len(wired["renders"]) == 1
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert row.status == "edited" and row.render_ref != old_ref
    text = " ".join(w["text"] for w in row.transcript)
    assert "Not after" not in text and "smart. After you've" in text
    assert row.edit_plan["overrides"]["cut"]
    assert not kept_word(row, "Call") and not kept_word(row, "them.") and kept_word(row, "service.")

    assert sitting.state == "done" and sitting.llm_key == asked[0]["key"]
    assert sitting.render_ref == row.render_ref and sitting.keep_snapshot == row.rendered_keep
    assert sitting.summary == "Took out the 'Not' and cut 'Call them.'"
    assert sitting.result["read_back"].startswith("3 notes: ")
    assert sitting.result["status"] == "New version made from your 3 notes."
    assert [w["text"] for w in sitting.before["transcript"]] == old_words

    assert [notes[i].state for i in (n1, n2, n3)] == ["done", "done", "done"]
    assert notes[n1].result["corrections"] == [{"heard": "Not after", "replacement": "After"}]
    assert notes[n1].result["file"].endswith(f"v={row.render_ref}")
    assert notes[n2].result["cut"] and notes[n2].result["reply"] == "Cut 'Call them.'"
    assert notes[n3].result["changed"] is False and "caption style" in notes[n3].result["reply"]
    assert all(n.resolved_at for n in notes.values())


async def test_a_later_note_wins(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, (n1, n2) = await sit(sm, ws, uid, [(6.6, "cut the last bit", None), (6.7, "no, keep call them", None)])
    wired["answers"].append({
        "summary": "Kept 'Call them.' after all.",
        "notes": [
            note(1, reply="Cut 'Call them.'", cut=[{"first": 12, "last": 13}]),
            note(2, reply="Instead of note 1: 'Call them.' stays.", restore=[{"first": 12, "last": 13}]),
        ],
    })
    await prod.run_talk_session(sid, ws)
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert kept(row, 12) and kept(row, 13)  # the later note's restore lifted the earlier cut
    assert not (row.edit_plan["overrides"].get("cut") or [])
    assert notes[n1].state == notes[n2].state == "done"
    assert len(wired["renders"]) == 1


async def test_an_overlapping_fix_is_reported_on_its_own_note(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, (n1, n2, n3) = await sit(
        sm, ws, uid, [(3.2, "no not", None), (3.6, "you have, not you've", None), (6.6, "drop the end", None)]
    )
    wired["answers"].append({
        "summary": "Two fixes.",
        "notes": [
            note(1, reply="Removed 'Not'.", corrections=[fix(6, 7, "Not after", "After")]),
            note(2, reply="Spelled it out.", corrections=[fix(7, 8, "after you've", "after you have")]),
            note(3, reply="Cut it.", cut=[{"first": 12, "last": 13}],
                 corrections=[fix(6, 6, "Not", "Now")]),
        ],
    })
    await prod.run_talk_session(sid, ws)
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    text = " ".join(w["text"] for w in row.transcript)
    # Note 1's fix stands; the fixes of notes 2 and 3 touched its words and did not land.
    assert "smart. After you've finished" in text and "Now" not in text
    assert notes[n1].state == "done"
    # Every change note 2 made was refused: it asks him, naming the note that got there first.
    assert notes[n2].state == "needs_you"
    assert 'overlaps words note 1 already fixed' in notes[n2].result["question"]
    # Note 3's cut went ahead; its skipped fix is on its own result, not dropped silently.
    assert notes[n3].state == "done" and not kept_word(row, "Call")
    assert any("note 1 already fixed" in s for s in notes[n3].result["skipped"])
    assert sitting.state == "needs_you"
    assert "1 of them needs you" in sitting.result["status"]


async def test_a_note_the_answer_skipped_needs_him(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, (n1, n2, n3) = await sit(
        sm, ws, uid, [(1.0, "louder", None), (3.2, "no not", None), (6.6, "cut the end", None)]
    )
    wired["answers"].append({
        "summary": "Removed 'Not' and cut the end.",
        "notes": [
            note(2, reply="Removed 'Not'.", corrections=[fix(6, 7, "Not after", "After")]),
            note(3, reply="Cut it.", cut=[{"first": 12, "last": 13}]),
            note(9, reply="a note that does not exist", cut=[{"first": 0, "last": 5}]),
        ],
    })
    await prod.run_talk_session(sid, ws)
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert notes[n1].state == "needs_you"
    assert notes[n1].result["question"] == autoedit.MISSED_QUESTION
    assert notes[n2].state == notes[n3].state == "done"
    assert kept(row, 0)  # the answer for a note that was never given changed nothing
    assert sitting.state == "needs_you"


async def test_a_note_that_asks_him_changes_nothing_and_the_others_go_ahead(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, (n1, n2) = await sit(sm, ws, uid, [(1.0, "make it pop", None), (6.6, "cut the end", None)])
    wired["answers"].append({
        "summary": "Cut the end.",
        "notes": [
            note(1, needs_you=True, question="Pop how: faster cuts, or music?", cut=[{"first": 0, "last": 2}]),
            note(2, reply="Cut it.", cut=[{"first": 12, "last": 13}]),
        ],
    })
    await prod.run_talk_session(sid, ws)
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert notes[n1].state == "needs_you" and notes[n1].result["question"] == "Pop how: faster cuts, or music?"
    assert kept(row, 0) and kept(row, 2)  # the question's own cut was not made
    assert notes[n2].state == "done" and not kept(row, 12)
    assert len(wired["renders"]) == 1


async def test_notes_that_change_nothing_do_not_render(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, (n1, n2) = await sit(sm, ws, uid, [(1.0, "is that clipped?", None), (3.2, "it sounds like cou", None)])
    wired["answers"].append({
        "summary": "",
        "notes": [
            note(1, reply="'back' is whole; nothing is clipped there."),
            note(2, reply="Your phone cut the end of that word; the recording never had it."),
        ],
    })
    await prod.run_talk_session(sid, ws)
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert wired["renders"] == []
    assert row.render_ref == "0000seedrender00"
    assert notes[n1].state == notes[n2].state == "done"
    assert sitting.state == "done" and sitting.before is None
    assert sitting.result["status"] == "Nothing in the video needed changing for your 2 notes."
    assert library.undo_refusal(sitting, row)[0] == "nothing"


async def test_a_blocked_meaning_check_keeps_the_edit_he_has_and_the_review(wired, tmp_path):
    # His editor's review removed the first take of a line said twice. A note that puts a
    # "not" into that removed take makes the dropped take say something the kept one
    # does not: the meaning check blocks, and the edit he has stays.
    w = words(WALK)
    heard = " ".join(x["text"] for x in w[10:21])
    removals, _ = autoedit.validate_removals(
        w, [{"first": 10, "last": 20, "heard": heard, "kind": "retake", "kept_from": 21, "why": "again"}]
    )
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path, WALK, review={"state": "done", "removals": removals})
    async with sm() as s:
        start = await prod._load(s, uid, ws)
        old_keep, old_ref = list(start.edit_plan["keep"]), start.render_ref
    sid, (n1,) = await sit(sm, ws, uid, [(4.0, "I said it is not the first step", None)])
    wired["answers"].append({
        "summary": "Added the 'not'.",
        "notes": [note(1, reply="Added 'not'.", corrections=[fix(14, 14, "is", "is not")])],
    })
    await prod.run_talk_session(sid, ws)
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert wired["renders"] == []
    assert row.status == "edited" and row.render_ref == old_ref
    assert row.edit_plan["keep"] == old_keep and row.transcript[14]["text"] == "is"
    # The review is not marked blocked for a change it never asked for: its cuts still count.
    assert row.edit_plan["review"]["state"] == "done"
    assert row.status_detail.startswith("Your notes would make a cut that needs your eyes")
    assert notes[n1].state == "needs_you"
    assert notes[n1].result["question"].startswith("The re-render stopped: Your notes would make a cut")
    assert sitting.state == "needs_you" and sitting.before is None
    assert sitting.result["status"].startswith("The re-render stopped:")


async def test_words_changed_while_it_read_ask_once_more_with_a_new_key(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, (n1,) = await sit(sm, ws, uid, [(3.2, "no not", None)])
    answer = {"summary": "Removed 'Not'.", "notes": [note(1, reply="Removed 'Not'.", corrections=[fix(6, 7, "Not after", "After")])]}

    async def first():
        async with sm() as s:  # a word fix landed from elsewhere while the editor read
            row = await prod._load(s, uid, ws)
            fixed = [dict(x) for x in row.transcript]
            fixed[0]["text"] = "Gettin'"
            row.transcript = fixed
            await s.commit()
        return answer

    wired["answers"].extend([first, answer])
    await prod.run_talk_session(sid, ws)
    asked = wired["asked"]
    assert len(asked) == 2 and asked[0]["key"] != asked[1]["key"]
    assert "0:Gettin'" in asked[1]["prompt"]
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert [x["text"] for x in row.transcript[:1]] == ["Gettin'"] and row.transcript[6]["text"] == "After"
    assert notes[n1].state == "done" and len(wired["renders"]) == 1
    assert sitting.llm_key == asked[1]["key"]


async def test_the_worker_away_says_so_and_the_same_job_is_asked_again(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, (n1,) = await sit(sm, ws, uid, [(6.6, "cut the end", None)])
    seen: list[str] = []

    async def later():
        async with sm() as s:
            seen.append((await s.get(EditSession, sid)).result["status"])
        return {"summary": "Cut it.", "notes": [note(1, reply="Cut it.", cut=[{"first": 12, "last": 13}])]}

    wired["answers"].extend([LLMUnavailable("timeout", "job still queued after 60s"), later])
    await prod.run_talk_session(sid, ws)
    asked = wired["asked"]
    assert len(asked) == 2 and asked[0]["key"] == asked[1]["key"]  # the queued job, not a new one
    assert asked[0]["wait_timeout_s"] == prod.TALK_ASK_WAIT_S and asked[0]["requeue_failed"] is True
    assert seen == ["Waiting for the subscription worker (timeout)"]
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert sitting.state == "done" and notes[n1].state == "done"


async def test_a_failed_job_hands_the_notes_back_unchanged(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, (n1,) = await sit(sm, ws, uid, [(6.6, "cut the end", None)])
    wired["answers"].append(LLMUnavailable("failed", "the worker crashed"))
    await prod.run_talk_session(sid, ws)
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert sitting.state == "open" and sitting.submitted_at is None
    assert sitting.result["status"].startswith("Your editor could not read the notes (failed)")
    assert notes[n1].state == "held" and wired["renders"] == []
    assert kept(row, 12)


def test_the_batch_key_changes_when_the_skill_file_changes(tmp_path, monkeypatch):
    skill = tmp_path / "video_editor.md"
    skill.write_text("Never cut a joke's punchline.", encoding="utf-8")
    monkeypatch.setattr(autoedit, "EDITOR_SKILL_PATH", skill)
    sid, prompt = uuid.uuid4(), "the same notes and transcript"
    first = prod.talk_key(sid, prompt, autoedit.edit_batch_system())
    assert "Never cut a joke's punchline." in autoedit.edit_batch_system()
    assert first == prod.talk_key(sid, prompt, autoedit.edit_batch_system())
    skill.write_text("Never cut a joke's punchline. Keep every 'basically'.", encoding="utf-8")
    second = prod.talk_key(sid, prompt, autoedit.edit_batch_system())
    assert second != first
    assert first.startswith(f"edit-batch:{sid}:") and len(first) <= 128


def test_the_token_budget_grows_with_the_notes_and_stops_at_8000():
    assert prod.talk_tokens(1) == 2100 and prod.talk_tokens(3) == 3300 and prod.talk_tokens(20) == 8000


# ---------------------------------------------------------------- after a restart


async def test_resume_picks_up_a_thinking_sitting(wired, tmp_path, monkeypatch):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, (n1,) = await sit(sm, ws, uid, [(6.6, "cut the end", None)])
    spawned: list = []
    monkeypatch.setattr(prod, "_spawn", lambda coro: spawned.append(coro))
    monkeypatch.setattr(prod.settings, "production_auto_edit", False)  # his tap resumes regardless
    await prod.resume_auto_work()
    mine = [c for c in spawned if c.__name__ == "run_talk_session"]
    for c in spawned:
        if c not in mine:
            c.close()
    assert len(mine) == 1
    wired["answers"].append({"summary": "Cut it.", "notes": [note(1, reply="Cut it.", cut=[{"first": 12, "last": 13}])]})
    await mine[0]
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert sitting.state == "done" and notes[n1].state == "done" and not kept(row, 12)


async def test_resume_of_a_rendering_sitting_renders_once_and_never_asks_again(wired, tmp_path, monkeypatch):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, (n1,) = await sit(sm, ws, uid, [(6.6, "cut the end", None)])
    wired["answers"].append({"summary": "Cut it.", "notes": [note(1, reply="Cut it.", cut=[{"first": 12, "last": 13}])]})
    real = prod._plan_and_render_locked
    crash = {"on": True}

    async def dies_mid_render(*a, **k):
        if crash["on"]:
            raise asyncio.CancelledError()  # the process went away mid-render
        return await real(*a, **k)

    monkeypatch.setattr(prod, "_plan_and_render_locked", dies_mid_render)
    with pytest.raises(asyncio.CancelledError):
        await prod.run_talk_session(sid, ws)
    row, sitting, _ = await state_of(sm, ws, uid, sid)
    assert sitting.state == "rendering" and sitting.before and wired["renders"] == []

    crash["on"] = False
    spawned: list = []
    monkeypatch.setattr(prod, "_spawn", lambda coro: spawned.append(coro))
    await prod.resume_auto_work()
    mine = [c for c in spawned if c.__name__ == "run_talk_session"]
    for c in spawned:
        if c not in mine:
            c.close()
    await mine[0]
    assert len(wired["asked"]) == 1 and len(wired["renders"]) == 1
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert sitting.state == "done" and notes[n1].state == "done" and not kept(row, 12)


# ---------------------------------------------------------------- undo, through the routes


@pytest.fixture
async def client(wired, monkeypatch):
    sm = wired["sm"]
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api/v1")
    app.include_router(workspace_router.production_router, prefix="/api/v1")
    app.include_router(prod.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sm

    async def _db():
        async with sm() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def headers(ws) -> dict:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


async def made(wired, tmp_path):
    """A sitting of two notes made into a new version."""
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    async with sm() as s:
        start = await prod._load(s, uid, ws)
        before_words = [dict(w) for w in start.transcript]
    sid, ids = await sit(sm, ws, uid, [(3.2, "no not", None), (6.6, "cut the end", None)])
    wired["answers"].append({
        "summary": "Removed 'Not' and cut 'Call them.'",
        "notes": [
            note(1, reply="Removed 'Not'.", corrections=[fix(6, 7, "Not after", "After")]),
            note(2, reply="Cut it.", cut=[{"first": 12, "last": 13}]),
        ],
    })
    await prod.run_talk_session(sid, ws)
    return ws, uid, sid, ids, before_words


async def test_undo_puts_back_the_version_from_before_the_notes_with_one_render(wired, client, tmp_path, monkeypatch):
    ws, uid, sid, ids, before_words = await made(wired, tmp_path)
    row, sitting, _ = await state_of(wired["sm"], ws, uid, sid)
    made_ref = row.render_ref
    sheet = (await client.get(f"/api/v1/production/talk/{sid}", headers=headers(ws))).json()
    assert sheet["can_undo"] is True and sheet["video_status"] == "edited"
    preview = (await client.get(f"/api/v1/production/talk/{sid}/undo", headers=headers(ws))).json()
    assert preview["possible"] is True
    assert preview["read_back"] == (
        "Put back the version from before your 2 notes (Removed 'Not' and cut 'Call them.'). One re-render."
    )

    spawned: list = []
    monkeypatch.setattr(prod, "_spawn", lambda coro: spawned.append(coro))
    r = await client.post(f"/api/v1/production/talk/{sid}/undo", headers=headers(ws))
    assert r.status_code == 200, r.text
    assert r.json()["result"]["undo"]["state"] == "queued"
    assert [c.__name__ for c in spawned] == ["run_talk_undo"]
    await spawned[0]

    row, sitting, notes = await state_of(wired["sm"], ws, uid, sid)
    assert row.transcript == before_words and kept(row, 12)
    assert not (row.edit_plan.get("overrides") or {}).get("cut")
    assert len(wired["renders"]) == 2 and row.render_ref != made_ref
    assert sitting.before is None and sitting.result["undo"]["state"] == "done"
    assert sitting.result["undo"]["render_ref"] == row.render_ref
    assert all(n.result.get("undone_at") for n in notes.values())
    again = (await client.get(f"/api/v1/production/talk/{sid}/undo", headers=headers(ws))).json()
    assert again["possible"] is False and again["code"] == "undone"
    assert (await client.post(f"/api/v1/production/talk/{sid}/undo", headers=headers(ws))).status_code == 409


async def test_undo_is_refused_once_the_video_changed_after_the_notes(wired, client, tmp_path, monkeypatch):
    ws, uid, sid, _ids, _ = await made(wired, tmp_path)
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
        fixed = [dict(x) for x in row.transcript]
        fixed[0]["text"] = "Gettin'"  # a later request changed a word
        row.transcript = fixed
        await s.commit()
    spawned: list = []
    monkeypatch.setattr(prod, "_spawn", lambda coro: spawned.append(coro))
    r = await client.post(f"/api/v1/production/talk/{sid}/undo", headers=headers(ws))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "changed"
    assert r.json()["detail"]["message"] == library.UNDO_CHANGED
    assert spawned == [] and len(wired["renders"]) == 1


async def test_undo_is_refused_while_the_video_is_rendering(wired, client, tmp_path):
    ws, uid, sid, _ids, _ = await made(wired, tmp_path)
    async with prod._render_lock(uid):
        r = await client.post(f"/api/v1/production/talk/{sid}/undo", headers=headers(ws))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "busy"


async def test_the_next_batch_reads_earlier_notes_and_what_was_undone(wired, tmp_path):
    ws, uid, sid, _ids, _ = await made(wired, tmp_path)
    async with wired["sm"]() as s:
        for n in await library.sitting_notes(s, ws, sid):
            n.result = {**(n.result or {}), "undone_at": "2026-09-30T20:00:00"}
        await s.commit()
    sid2, _ = await sit(wired["sm"], ws, uid, [(1.0, "louder here", None)])
    wired["answers"].append({"summary": "", "notes": [note(1, reply="Loudness is not an edit.")]})
    await prod.run_talk_session(sid2, ws)
    prompt = wired["asked"][-1]["prompt"]
    assert "Earlier notes on this video, oldest first:" in prompt
    assert "- At 0:03, he said: no not | You answered: Removed 'Not'. | He undid this afterwards" in prompt


# ---------------------------------------------------------------- pure: prompt and apply


LETTERS = words("a b c d e f g h i j k l m n o p q r s t")


def test_the_prompt_has_one_block_a_note_and_a_marker_where_he_paused():
    notes = [
        {"said": "cut the c", "understood": "At 0:01 you want 'c' gone.", "edit_s": 1.2, "source_s": 1.2},
        {"said": "", "understood": "At 0:00 a longer start.", "edit_s": 0.0, "source_s": 0.0},
        {"said": "bigger captions", "understood": "", "edit_s": None, "source_s": None},
        {"said": "check the pause", "understood": "", "where": "0:04 to 0:06 in the edit", "source_s": 4.0},
    ]
    history = [{"request": "it sounds like cou", "reply": "The phone cut it.", "where": "At 0:38"}]
    text = autoedit.edit_batch_prompt(LETTERS, [[0.0, 10.0]], "Topic: letters", notes, history=history)
    assert text.startswith("Topic: letters\n\nEarlier notes on this video, oldest first:\n")
    assert "- At 0:38, he said: it sounds like cou | You answered: The phone cut it." in text
    assert '[note 1 | 0:01 in the edit | he said "cut the c" | agreed: "At 0:01 you want \'c\' gone."]' in text
    assert '[note 2 | 0:00 in the edit | his own words were not caught | agreed: "At 0:00 a longer start."]' in text
    assert '[note 3 | the whole video | he said "bigger captions"]' in text
    assert '[note 4 | 0:04 to 0:06 in the edit | he said "check the pause"]' in text
    # Paused at 1.2 s: "c" (1.0 s) was the last word he heard. At 0.0 s: "a" had just started.
    assert "2:c <note 1>" in text and "0:a <note 2>" in text and "8:i <note 4>" in text
    assert "<note 3>" not in text


def test_a_pause_before_the_first_word_is_marked_before_it():
    later = words("a b c", start=2.0)
    assert autoedit.pin_index(later, 0.5) == -1
    text = autoedit.edit_batch_prompt(later, [[0.0, 4.0]], "ctx", [{"said": "x", "edit_s": 0.5, "source_s": 0.5}])
    assert "<note 1> 0:a" in text


def test_apply_batch_folds_cut_and_restore_in_note_order():
    a = autoedit.apply_batch(LETTERS, None, {"notes": [
        note(1, reply="cut", cut=[{"first": 2, "last": 4}]),
        note(2, reply="back", restore=[{"first": 3, "last": 3}]),
    ], "summary": "s"}, 2)
    assert a["changed"] and a["summary"] == "s"
    cut, restore = a["overrides"]["cut"], a["overrides"]["restore"]
    mid = lambda i: (LETTERS[i]["start_s"] + LETTERS[i]["end_s"]) / 2  # noqa: E731
    assert any(s <= mid(2) <= e for s, e in cut) and any(s <= mid(4) <= e for s, e in cut)
    assert not any(s <= mid(3) <= e for s, e in cut) and any(s <= mid(3) <= e for s, e in restore)

    b = autoedit.apply_batch(LETTERS, None, {"notes": [
        note(1, reply="back", restore=[{"first": 3, "last": 3}]),
        note(2, reply="cut", cut=[{"first": 3, "last": 3}]),
    ]}, 2)
    assert any(s <= mid(3) <= e for s, e in b["overrides"]["cut"])
    assert not any(s <= mid(3) <= e for s, e in b["overrides"]["restore"])


def test_apply_batch_caps_fixes_per_note_not_per_sitting():
    many = [fix(i, i, LETTERS[i]["text"], LETTERS[i]["text"].upper()) for i in range(13)]
    out = autoedit.apply_batch(LETTERS, None, {"notes": [
        note(1, reply="caps", corrections=many),
        note(2, reply="one more", corrections=[fix(15, 15, "p", "P")]),
    ]}, 2)
    texts = [w["text"] for w in out["words"]]
    assert texts[:12] == [t.upper() for t in "abcdefghijkl"] and texts[12] == "m"
    assert texts[15] == "P"  # note 2 has its own 12
    first = out["notes"][0]
    assert len(first["corrections"]) == 12 and "only the first 12 word fixes were used" in first["skipped"]
    assert out["notes"][1]["outcome"] == "change"


def test_apply_batch_says_why_each_note_ended_as_it_did():
    out = autoedit.apply_batch(LETTERS, {"cut": [[9.0, 9.4]], "restore": []}, {"notes": [
        note(1, reply="fixed", corrections=[fix(0, 1, "a b", "ab")]),
        note(2, reply="also", corrections=[fix(1, 1, "b", "bee")]),  # overlaps note 1
        note(3, reply="misquoted", corrections=[fix(5, 5, "x", "y")]),
        note(4, needs_you=True, question="Which one?", cut=[{"first": 6, "last": 6}]),
        note(5, reply="Nothing to change there."),
        note(6),
        note(7, reply="out of range", cut=[{"first": 40, "last": 41}]),
    ]}, 8)
    kinds = [n["outcome"] for n in out["notes"]]
    assert kinds == ["change", "refused", "refused", "question", "answer", "unclear", "refused", "missing"]
    assert 'overlaps words note 1 already fixed' in out["notes"][1]["question"]
    assert 'quoted "x" where the words are "f"' in out["notes"][2]["question"]
    assert out["notes"][3]["question"] == "Which one?"
    assert out["notes"][5]["question"] == autoedit.UNCLEAR_QUESTION
    assert out["notes"][6]["question"].startswith("I could not make this change: a cut that pointed outside")
    assert out["notes"][7]["question"] == autoedit.MISSED_QUESTION
    # Only note 1 changed anything; the earlier cut stays and nothing else was cut.
    assert out["words"][0]["text"] == "ab" and out["words"][1]["text"] == "c"
    assert out["overrides"] == {"cut": [[9.0, 9.4]], "restore": []}


def test_the_single_request_path_still_drops_bad_fixes_silently():
    fixed, applied = autoedit.apply_corrections(
        LETTERS, [fix(0, 1, "a b", "ab"), fix(1, 1, "b", "bee"), fix(5, 5, "x", "y")]
    )
    assert [c["replacement"] for c in applied] == ["ab"] and fixed[0]["text"] == "ab"


def test_the_sitting_says_what_the_video_is_doing_while_it_renders():
    upload = RecordingUpload(
        workspace_id=uuid.uuid4(), original_filename="w.mp4", sha256="0" * 64, status="rendering",
        status_detail="Cutting and burning in your captions", edited_path=None,
    )
    sitting = EditSession(upload_id=uuid.uuid4(), state="rendering", keep_snapshot=[[0.0, 1.0]])
    body = library.sitting_to_json(sitting, [], upload)
    assert body["video_status"] == "rendering" and body["video_step"] == "Cutting and burning in your captions"
    assert body["can_undo"] is False


# ---------------------------------------------------------------- review findings, 1-Oct
#
# A typed request and a sitting on the same video, a note left out at "make it", a
# failed job, a plan that moved, and two undo taps.


def request_answer(*corrections, cut=(), reply="Done."):
    return {
        "reply": reply, "needs_you": False, "question": "", "corrections": list(corrections),
        "cut": list(cut), "restore": [], "hold": [],
    }


async def typed_request(sm, ws, uid, text: str, state: str = "open") -> uuid.UUID:
    """A request typed on the Library card, outside any sitting."""
    async with sm() as s:
        req = EditingRequest(
            workspace_id=ws, upload_id=uid, scope="whole", request=text, state=state, created_by="ziv"
        )
        s.add(req)
        await s.commit()
        return req.id


def held_on(event: asyncio.Event, gate: asyncio.Event, answer: dict):
    """An answer that arrives only when the test lets it: the job is being read meanwhile."""

    async def slow():
        event.set()
        await gate.wait()
        return answer

    return slow


async def test_a_typed_request_while_the_notes_are_being_made_is_refused_not_run(
    wired, client, tmp_path, monkeypatch
):
    ran: list = []
    monkeypatch.setattr(prod, "start_edit_request", lambda rid, ws, **_k: ran.append(rid))
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, _ = await sit(sm, ws, uid, [(3.2, "no not", None)])  # thinking: the batch is on its way
    url = f"/api/v1/production/recordings/{uid}/edit-requests"
    for state in ("thinking", "rendering"):
        async with sm() as s:
            (await s.get(EditSession, sid)).state = state
            await s.commit()
        r = await client.post(url, json={"request": "and make the captions bigger"}, headers=headers(ws))
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == {"code": "notes_being_made", "message": library.NOTES_BEING_MADE}
    assert ran == []
    async with sm() as s:
        assert len(await library.list_edit_requests(s, ws, uid)) == 1  # only the sitting's own note


async def test_a_request_that_read_the_words_before_a_batch_never_undoes_its_fixes(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    rid = await typed_request(sm, ws, uid, "say truly, not really")
    reading, go = asyncio.Event(), asyncio.Event()
    wired["answers"].append(held_on(reading, go, request_answer(fix(4, 4, "really", "truly"))))
    task = asyncio.create_task(prod.run_edit_request(rid, ws))
    await asyncio.wait_for(reading.wait(), 10)

    # A sitting made past the gates (a restart resumed the request while he gave notes):
    # its batch fixes "Not after" and renders while the request is still being read.
    sid, (n1,) = await sit(sm, ws, uid, [(3.2, "no not", None)])
    wired["answers"].append({
        "summary": "Removed 'Not'.",
        "notes": [note(1, reply="Removed 'Not'.", corrections=[fix(6, 7, "Not after", "After")])],
    })
    await prod.run_talk_session(sid, ws)
    wired["answers"].append(request_answer(fix(4, 4, "really", "truly")))
    go.set()
    await asyncio.wait_for(task, 10)

    asked = wired["asked"]
    kinds = [a["kind"] for a in asked]
    assert kinds == [autoedit.EDIT_REQUEST_JOB, autoedit.EDIT_BATCH_JOB, autoedit.EDIT_REQUEST_JOB]
    # The words moved while it read: it read them again, as a new job.
    assert asked[2]["key"] != asked[0]["key"] and "6:After" in asked[2]["prompt"]
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    text = " ".join(w["text"] for w in row.transcript)
    assert "is truly smart. After you've" in text and "Not after" not in text
    assert notes[n1].state == "done" and len(wired["renders"]) == 2
    async with sm() as s:
        req = await s.get(EditingRequest, rid)
    assert req.state == "done" and req.result["corrections"] == [{"heard": "really", "replacement": "truly"}]


async def test_notes_cannot_open_while_a_typed_request_is_being_made_and_it_joins_a_sitting_opened_anyway(
    wired, client, tmp_path
):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    rid = await typed_request(sm, ws, uid, "cut the end")
    reading, go = asyncio.Event(), asyncio.Event()
    wired["answers"].append(held_on(reading, go, request_answer(cut=[{"first": 12, "last": 13}])))
    task = asyncio.create_task(prod.run_edit_request(rid, ws))
    await asyncio.wait_for(reading.wait(), 10)

    r = await client.post(f"/api/v1/production/recordings/{uid}/talk", headers=headers(ws))
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "busy"
    assert r.json()["detail"]["message"] == prod.request_busy_sentence("Reading your request on the subscription")

    # A sheet that was still loaded wakes up and takes notes anyway: when the request's
    # answer lands, it joins those notes instead of re-rendering under his player.
    async with sm() as s:
        sitting = await library.open_sitting(s, ws, uid)
        pinned = await library.pin_note(s, ws, sitting.id, edit_s=1.0, render_ref=sitting.render_ref)
        await library.update_note(s, ws, sitting.id, pinned.id, heard="louder here")
        await s.commit()
        sid = sitting.id
    go.set()
    await asyncio.wait_for(task, 10)
    assert wired["renders"] == []
    async with sm() as s:
        req = await s.get(EditingRequest, rid)
        preview = await library.submit_preview(s, ws, sid)
    assert req.session_id == sid and req.state == "held"
    assert req.result["status"] == prod.REQUEST_JOINED
    assert preview["count"] == 2 and 'the whole video: you said "cut the end"' in preview["read_back"]
    r = await client.post(f"/api/v1/production/recordings/{uid}/talk", headers=headers(ws))
    assert r.status_code == 200 and r.json()["session_id"] == str(sid)


async def test_a_request_resumed_while_he_gives_notes_joins_them_without_asking(wired, client, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    # Parked: the worker was away and the request waits for a restart to carry on.
    rid = await typed_request(sm, ws, uid, "cut the end", state="in_progress")
    body = (await client.post(f"/api/v1/production/recordings/{uid}/talk", headers=headers(ws))).json()
    await prod.run_edit_request(rid, ws)  # the restart resumes it now
    assert wired["asked"] == [] and wired["renders"] == []
    async with sm() as s:
        req = await s.get(EditingRequest, rid)
    assert str(req.session_id) == body["session_id"] and req.state == "held"


async def test_a_request_waits_while_his_notes_are_made_then_reads_the_new_words(wired, tmp_path, monkeypatch):
    # The request looks at the sitting again only when this test says so: the suite's
    # SQLite shares one connection between sessions, so a request polling while the
    # batch writes would roll the batch's writes back (Postgres gives each its own).
    looked, look_again = asyncio.Event(), asyncio.Event()

    async def recheck():
        looked.set()
        await look_again.wait()

    monkeypatch.setattr(prod, "_sitting_recheck", recheck)
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    rid = await typed_request(sm, ws, uid, "say truly, not really", state="in_progress")
    sid, (n1,) = await sit(sm, ws, uid, [(3.2, "no not", None)])
    reading, go = asyncio.Event(), asyncio.Event()
    wired["answers"].append(held_on(reading, go, {
        "summary": "Removed 'Not'.",
        "notes": [note(1, reply="Removed 'Not'.", corrections=[fix(6, 7, "Not after", "After")])],
    }))
    talk = asyncio.create_task(prod.run_talk_session(sid, ws))
    await asyncio.wait_for(reading.wait(), 10)
    request = asyncio.create_task(prod.run_edit_request(rid, ws))
    await asyncio.wait_for(looked.wait(), 10)
    # Its notes are being made: the request asks nothing and changes nothing yet.
    assert [a["kind"] for a in wired["asked"]] == [autoedit.EDIT_BATCH_JOB]
    async with sm() as s:
        assert (await s.get(EditingRequest, rid)).result["status"] == prod.REQUEST_WAITS_FOR_NOTES
    wired["answers"].append(request_answer(fix(4, 4, "really", "truly")))
    go.set()
    await asyncio.wait_for(talk, 10)
    look_again.set()
    await asyncio.wait_for(request, 10)
    assert [a["kind"] for a in wired["asked"]] == [autoedit.EDIT_BATCH_JOB, autoedit.EDIT_REQUEST_JOB]
    assert "6:After" in wired["asked"][1]["prompt"]
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert "is truly smart. After you've" in " ".join(w["text"] for w in row.transcript)
    assert notes[n1].state == "done" and len(wired["renders"]) == 2


async def test_the_batch_reads_the_edit_he_watched_not_a_plan_that_moved(wired, tmp_path):
    # His editor's review cut "Hey, Maple Rain, boy!", but the file on his phone is an
    # uncut render: the words he heard must not reach the editor struck out as cut.
    w = words(WALK)
    removals, _ = autoedit.validate_removals(
        w, [{"first": 6, "last": 9, "heard": "Hey, Maple Rain, boy!", "kind": "aside", "kept_from": -1, "why": "dogs"}]
    )
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path, WALK, review={"state": "done", "removals": removals})
    async with sm() as s:
        up = await prod._load(s, uid, ws)
        assert not kept(up, 8)  # the plan cuts "Rain,"
        up.rendered_keep, up.render_ref = frame_keep([[0.0, up.duration_s]]), "uncutrender00000"
        await s.commit()
    sid, (n1,) = await sit(sm, ws, uid, [(4.1, "take this out", None)])
    wired["answers"].append({"summary": "", "notes": [note(1, reply="Cut 'Hey, Maple Rain, boy!'.",
                                                            cut=[{"first": 6, "last": 9}])]})
    await prod.run_talk_session(sid, ws)
    prompt = wired["asked"][0]["prompt"]
    assert "8:Rain, <note 1>" in prompt and "~~8:Rain,~~" not in prompt
    assert autoedit.PLAN_MOVED_LINE in prompt


async def test_the_batch_prompt_says_nothing_of_a_plan_while_it_is_the_edit_he_watched(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, _ = await sit(sm, ws, uid, [(3.2, "no not", None)])
    wired["answers"].append({"summary": "", "notes": [note(1, reply="Nothing to change.")]})
    await prod.run_talk_session(sid, ws)
    assert autoedit.PLAN_MOVED_LINE not in wired["asked"][0]["prompt"]


async def test_a_failed_job_then_make_it_again_is_a_new_job(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    sid, (n1,) = await sit(sm, ws, uid, [(6.6, "cut the end", None)])
    # The process went away while the job was read: after the restart the same job is asked.
    wired["answers"].append(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await prod.run_talk_session(sid, ws)
    wired["answers"].append(LLMUnavailable("failed", "auth: the worker's login expired"))
    await prod.run_talk_session(sid, ws)
    asked = wired["asked"]
    assert asked[0]["key"] == asked[1]["key"]
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert sitting.state == "open" and notes[n1].state == "held"

    # He fixed the login and taps Make the new version again: a new job, not the failed one.
    async with sm() as s:
        preview = await library.submit_preview(s, ws, sid)
        await library.submit(s, ws, sid, check=preview["check"])
        await s.commit()
    wired["answers"].append({"summary": "Cut it.", "notes": [note(1, reply="Cut it.", cut=[{"first": 12, "last": 13}])]})
    await prod.run_talk_session(sid, ws)
    assert len(asked) == 3 and asked[2]["key"] != asked[1]["key"]
    assert asked[2]["prompt"] == asked[1]["prompt"]  # the same notes, the same words
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert sitting.state == "done" and notes[n1].state == "done" and not kept(row, 12)


async def test_a_note_left_out_at_make_it_is_taken_back_not_stranded(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    async with sm() as s:
        sitting = await library.open_sitting(s, ws, uid)
        spoke = await library.pin_note(s, ws, sitting.id, edit_s=6.6, render_ref=sitting.render_ref)
        await library.update_note(s, ws, sitting.id, spoke.id, heard="cut the end")
        silent = await library.pin_note(s, ws, sitting.id, edit_s=2.0, render_ref=sitting.render_ref)
        preview = await library.submit_preview(s, ws, sitting.id)
        assert preview["left_out"] == [str(silent.id)]
        await library.submit(s, ws, sitting.id, check=preview["check"])
        await s.commit()
        sid = sitting.id
    wired["answers"].append({"summary": "Cut it.", "notes": [note(1, reply="Cut it.", cut=[{"first": 12, "last": 13}])]})
    await prod.run_talk_session(sid, ws)
    row, sitting, notes = await state_of(sm, ws, uid, sid)
    assert sitting.state == "done" and notes[spoke.id].state == "done"
    assert notes[silent.id].state == "rejected"
    assert notes[silent.id].result == {"left_out": library.LEFT_OUT}
    async with sm() as s:
        item = (await library.list_library(s, ws))["items"][0]
    assert item["waiting_notes"] == 0


async def test_notes_being_made_are_not_counted_as_waiting_on_the_card(wired, tmp_path):
    sm = wired["sm"]
    ws, uid = await seed(sm, tmp_path)
    await sit(sm, ws, uid, [(6.6, "cut the end", None)])  # thinking
    async with sm() as s:
        item = (await library.list_library(s, ws))["items"][0]
    assert item["waiting_notes"] == 0


async def test_two_undo_tasks_put_the_version_back_once_and_say_so(wired, tmp_path):
    ws, uid, sid, _ids, before_words = await made(wired, tmp_path)
    async with wired["sm"]() as s:
        await library.start_undo(s, ws, sid)
        await s.commit()
    # A double tap, or the voice tool and a tap: two tasks on the same queued undo.
    await asyncio.gather(prod.run_talk_undo(sid, ws), prod.run_talk_undo(sid, ws))
    row, sitting, _ = await state_of(wired["sm"], ws, uid, sid)
    assert row.transcript == before_words
    assert len(wired["renders"]) == 2  # the batch's, and one for going back
    assert sitting.result["undo"]["state"] == "done"
    assert library.undo_refusal(sitting, row)[0] == "undone"
