"""Jennifer's check after a render: fix or hold, end to end (3-Oct).

The render, the level readings and the loudness meter are the real ffmpeg on a generated
recording (tone bursts stand in for words, a faint hum for a pause that survived the cut).
The subscription worker is replaced by a function that answers each job. Synthetic data
only; nothing here reaches a server database or a worker.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.editorial import library, notify
from tce.llm import LLMUnavailable
from tce.llm.provider import LLMResult
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.models.jennifer import EditorRule, RenderCheck
from tce.production import autoedit, qc
from tce.settings import settings

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

KEY = "synthetic-test-key"
BURST = 0.5  # a word: a tone at speech level
HUM = 0.0084  # a pause that is not silent: under the pause level, over the level speech ends at


def recording(path: Path, words: list[tuple[str, float, float]], hums: list[tuple[float, float]] = ()) -> Path:
    """A mono WAV: a tone burst for each word (text, start, end), a faint hum for each
    (start, end) in `hums`, digital silence elsewhere, and a second of silence at the end."""
    terms = [f"{BURST}*sin(2*PI*500*t)*between(t,{s:.3f},{e:.3f})" for _t, s, e in words]
    terms += [f"{HUM}*sin(2*PI*500*t)*between(t,{s:.3f},{e:.3f})" for s, e in hums]
    total = max(e for _t, _s, e in words) + 1.0
    subprocess.run(
        [shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
         f"aevalsrc='{'+'.join(terms)}':s=48000:d={total:.3f}", "-c:a", "pcm_s16le", str(path)],
        check=True, capture_output=True,
    )
    return path


def spoken(text: str, start: float = 1.0, step: float = 0.5, length: float = 0.4) -> list[tuple[str, float, float]]:
    out, t = [], start
    for w in text.split():
        out.append((w, round(t, 3), round(t + length, 3)))
        t += step
    return out


def transcript(words: list[tuple[str, float, float]]) -> list[dict]:
    return [{"text": t, "start_s": s, "end_s": e, "precision": "word"} for t, s, e in words]


# "smart." is followed by three seconds of hum before he goes on: the cut keeps the hum
# (it never drops under the level where speech ends), and the viewer hears a 3 s pause.
GAP_WORDS = spoken("It is smart.") + spoken("Call them.", start=5.4)
GAP_HUM = [(2.4, 5.4)]
# A line to the dog the rules do not catch (no name, no call word): only her reading can.
DOG_WORDS = spoken(
    "It is smart to call them after the work is done. Leave that shoe alone. "
    "Ask them how it went and what they need next."
)
DOG_LINE = {"first": 11, "last": 14, "heard": "Leave that shoe alone."}
KEPT_AFTER_DOG = "It is smart to call them after the work is done. Ask them how it went and what they need next."
# No word here ends on a hiss: a tone has no "s" in it, and the phone-cut check would be right.
CLEAN = "It is smart. Call them after the work today."


@pytest.fixture
def wired(monkeypatch, editorial_sessionmaker):
    """The real pipeline with Jennifer's check ON, a worker that answers from `answers`,
    no recogniser (so the check relies on the level reading), and a count of renders."""
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    monkeypatch.setattr(settings, "production_qc", "fix")
    monkeypatch.setattr(settings, "production_transcribe_ws_url", "")
    asked: list[dict] = []
    answers: dict[str, object] = {qc.ASIDES_JOB: {"asides": []}}

    async def fake_ask(kind, prompt, system, schema, ws, key, **_opts):
        asked.append({"kind": kind, "prompt": prompt, "system": system})
        answer = answers.get(kind)
        if callable(answer):
            answer = answer(prompt)
        if answer is None:
            raise LLMUnavailable("timeout", "no worker in tests")
        return LLMResult(job_id=uuid.uuid4(), text="", structured=answer, model="claude-opus-5-5")

    renders: list[list[list[float]]] = []
    real_render = prod.media.render_edit

    async def counting_render(src, keep, out, **kw):
        renders.append([list(r) for r in keep])
        return await real_render(src, keep, out, **kw)

    monkeypatch.setattr(prod, "_ask", fake_ask)
    monkeypatch.setattr(prod.media, "render_edit", counting_render)
    return {"sm": editorial_sessionmaker, "asked": asked, "answers": answers, "renders": renders}


async def seed(sm, src: Path, words: list[tuple[str, float, float]]) -> tuple[uuid.UUID, uuid.UUID]:
    ws = uuid.uuid4()
    async with sm() as s:
        cand = TopicCandidate(
            workspace_id=ws, week_start=datetime(2026, 9, 28), moment_ids=["m"],
            title="Selling is the first step", lesson="l", audience="a",
            public_angle="p", gates={}, status="recorded",
        )
        s.add(cand)
        await s.flush()
        up = RecordingUpload(
            workspace_id=ws, candidate_id=cand.id, original_filename=src.name,
            storage_path=str(src), sha256=uuid.uuid4().hex * 2, status="transcribed",
            transcript=transcript(words), duration_s=max(e for _t, _s, e in words) + 1.0,
        )
        s.add(up)
        await s.commit()
        return ws, up.id


async def edit(wired, tmp_path, words, hums=()) -> tuple[uuid.UUID, uuid.UUID, RecordingUpload]:
    src = recording(tmp_path / f"walk-{uuid.uuid4().hex[:6]}.wav", words, hums)
    ws, uid = await seed(wired["sm"], src, words)
    row = await prod._plan_and_render(uid, ws)
    return ws, uid, row


async def checks_of(sm, uid) -> list[RenderCheck]:
    async with sm() as s:
        rows = (await s.execute(select(RenderCheck).where(RenderCheck.upload_id == uid))).scalars().all()
    return sorted(rows, key=lambda r: (r.round, r.created_at))


# ------------------------------------------------------------------ pass


@needs_ffmpeg
async def test_a_clean_edit_ends_checked_by_jennifer_with_its_numbers(wired, tmp_path):
    ws, uid, row = await edit(wired, tmp_path, spoken(CLEAN))
    assert row.status == "edited" and len(wired["renders"]) == 1
    found = row.qc
    assert found["state"] == "passed" and found["render_ref"] == row.render_ref
    assert found["line"].startswith("Checked by Jennifer: longest pause ")
    assert "9 of 9 words captioned" in found["line"] and "LUFS" in found["line"]
    assert abs(found["numbers"]["lufs"] - (-14.0)) <= qc.LOUDNESS_TOLERANCE_LU
    assert found["numbers"]["longest_gap_s"] < 1.2
    # The render's own line is back on the row once the check is done, and nothing is marked.
    assert row.status_detail.startswith("Captioned MP4 ready") and prod.QC_MARK not in row.job_ids
    [check] = await checks_of(wired["sm"], uid)
    assert (check.state, check.round, check.render_ref) == ("passed", 0, row.render_ref)
    # One subscription job: the reading for leftover asides, with the words still in the video.
    assert [a["kind"] for a in wired["asked"]] == [qc.ASIDES_JOB]
    assert "0:It 1:is 2:smart." in wired["asked"][0]["prompt"]
    # The card.
    async with wired["sm"]() as s:
        [item] = (await library.list_library(s, ws))["items"]
        api = prod.upload_json(await prod._load(s, uid, ws))
    assert item["qc"]["state"] == "passed" and item["qc"]["label"] == "Checked by Jennifer"
    assert item["status"] == "edited" and api["qc"]["line"] == found["line"]


# ------------------------------------------------------------------ fix


@needs_ffmpeg
async def test_a_gap_is_cut_with_one_rerender_and_a_recheck(wired, tmp_path):
    ws, uid, row = await edit(wired, tmp_path, GAP_WORDS, GAP_HUM)
    assert len(wired["renders"]) == 2, "her fix renders once more, never twice"
    assert row.status == "edited" and row.qc["state"] == "fixed" and row.qc["round"] == 1
    assert row.qc["line"].startswith("Checked by Jennifer, after one fix (cut a ")
    assert "second gap at 0:01" in row.qc["line"]
    assert row.qc["numbers"]["longest_gap_s"] < 1.2
    # The fix is an override, like his own notes: it survives every later re-plan.
    [[a, b]] = row.edit_plan["overrides"]["trim"]
    assert 2.4 < a < 2.8 and 5.1 < b < 5.4
    first, second = wired["renders"]
    length = lambda keep: sum(e - s for s, e in keep)  # noqa: E731
    assert 2.4 < length(first) - length(second) < 3.0
    # Every kept word is still there, with its caption.
    assert [w["text"] for w in row.edit_plan["words"]] == ["It", "is", "smart.", "Call", "them."]
    states = [(c.round, c.state) for c in await checks_of(wired["sm"], uid)]
    assert states == [(0, "fixing"), (1, "fixed")]
    async with wired["sm"]() as s:
        [item] = (await library.list_library(s, ws))["items"]
    assert item["qc"]["label"] == "Checked and fixed by Jennifer" and item["qc"]["fixed"]


@needs_ffmpeg
async def test_a_line_to_the_dog_left_in_is_cut_and_the_rule_she_used_is_counted(wired, tmp_path):
    def reading(prompt: str) -> dict:
        if "11:Leave" not in prompt:
            return {"asides": []}
        return {"asides": [{**DOG_LINE, "why": "talk to the dog (R1)"}]}

    wired["answers"][qc.ASIDES_JOB] = reading
    src = recording(tmp_path / "dog.wav", DOG_WORDS)
    ws, uid = await seed(wired["sm"], src, DOG_WORDS)
    async with wired["sm"]() as s:
        rule = EditorRule(workspace_id=ws, text="Cut any aside to the dogs, even under 2 seconds.", active=True,
                          times_applied=0, applied_uploads=[])
        s.add(rule)
        await s.commit()
        rule_id = rule.id
    row = await prod._plan_and_render(uid, ws)
    assert len(wired["renders"]) == 2 and row.status == "edited" and row.qc["state"] == "fixed"
    assert " ".join(w["text"] for w in row.edit_plan["words"]) == KEPT_AFTER_DOG
    assert row.edit_plan["overrides"]["cut"] == [[6.5, 8.4]]
    assert 'took out "Leave that shoe alone." at 0:05' in row.qc["line"]
    # Her learned rules reached the reading, after the hand-written skill file.
    system = wired["asked"][0]["system"]
    assert "R1. Cut any aside to the dogs, even under 2 seconds." in system
    assert system.index("HIS STANDING RULES") < system.index("RULES YOU LEARNED FROM HIS NOTES")
    async with wired["sm"]() as s:
        rule = await s.get(EditorRule, rule_id)
    assert rule.times_applied == 1 and rule.applied_uploads == [str(uid)]


# ------------------------------------------------------------------ hold


@needs_ffmpeg
async def test_what_is_still_wrong_after_one_fix_holds_the_video_and_never_renders_a_third_time(wired, tmp_path):
    def reading(prompt: str) -> dict:
        if "11:Leave" in prompt:
            return {"asides": [{**DOG_LINE, "why": "talk to the dog"}]}
        return {"asides": [{"first": 15, "last": 19, "heard": "Ask them how it went", "why": "said to someone beside him"}]}

    wired["answers"][qc.ASIDES_JOB] = reading
    ws, uid, row = await edit(wired, tmp_path, DOG_WORDS)
    assert len(wired["renders"]) == 2
    assert row.status == "needs_review" and row.qc["state"] == "held" and row.qc["round"] == 1
    assert row.status_detail == row.qc["line"]
    assert row.qc["line"] == (
        'Jennifer is holding this video: "Ask them how it went" at 0:05 is not said to the viewer '
        "(said to someone beside him) after one fix."
    )
    # Only her first fix was written; the second finding waits for him.
    assert row.edit_plan["overrides"]["cut"] == [[6.5, 8.4]]
    assert [(c.round, c.state) for c in await checks_of(wired["sm"], uid)] == [(0, "fixing"), (1, "held")]


@pytest.fixture
def a_caption_is_lost(monkeypatch):
    """The render's caption data without one word: a defect no cut can fix."""
    real = qc.caption_data

    def without_smart(words, pages, cues):
        data = real(words, pages, cues)
        for cue in data.get("cues") or []:
            cue["text"] = cue["text"].replace("smart. ", "").replace("smart.", "")
        return data

    monkeypatch.setattr(prod.qc, "caption_data", without_smart)


@needs_ffmpeg
async def test_a_caption_that_does_not_match_holds_at_once_with_one_plain_line(wired, tmp_path, a_caption_is_lost):
    ws, uid, row = await edit(wired, tmp_path, spoken("It is smart. Call them."))
    assert len(wired["renders"]) == 1, "nothing a cut can fix: no second render"
    assert row.status == "needs_review" and row.qc["state"] == "held"
    line = 'Jennifer is holding this video: 1 word has no caption: "smart.", the first at 0:01.'
    assert row.status_detail == line and library.qc_hold(row) == line
    # Her hold is not a cut waiting for his eyes: notes can still be made on this video.
    assert library.edit_waits_for_him(row) is None
    assert prod._rendered_since(row, "the-render-before") is True
    async with wired["sm"]() as s:
        [item] = (await library.list_library(s, ws, filter_key="needs_review"))["items"]
        events = await notify.collect_events(s, ws)
    assert item["state_sentence"] == line and item["qc"]["label"] == "Jennifer is holding this"
    keys = [a["key"] for a in item["actions"]]
    assert "release_hold" in keys and "check_again" in keys and "talk_edit" in keys
    held = [e for e in events if e["dedupe_key"].startswith("qc_hold:")]
    assert [e["title"] for e in held] == ["Jennifer is holding a video"]
    assert held[0]["dedupe_key"] == f"qc_hold:{uid}:{row.render_ref}" and line in held[0]["body"]


# ------------------------------------------------------------------ modes and edges


@needs_ffmpeg
async def test_report_mode_measures_and_says_and_changes_nothing(wired, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "production_qc", "report")
    ws, uid, row = await edit(wired, tmp_path, GAP_WORDS, GAP_HUM)
    assert len(wired["renders"]) == 1 and row.status == "edited"
    assert row.qc["state"] == "report"
    assert row.qc["line"].startswith("Jennifer found 1 thing and changed nothing (checking only): a ")
    assert "trim" not in (row.edit_plan.get("overrides") or {})


async def test_a_render_that_cannot_be_read_is_left_as_it_was_and_no_job_is_spent(wired, tmp_path, monkeypatch):
    async def fake_render(src, keep, out, **_kw):
        Path(out).write_bytes(b"edited")
        return Path(out)

    async def fake_size(_src):
        return (1080, 1920)

    monkeypatch.setattr(prod.media, "render_edit", fake_render)
    monkeypatch.setattr(prod.media, "probe_video_size", fake_size)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"synthetic")
    ws, uid = await seed(wired["sm"], src, spoken("It is smart. Call them."))
    row = await prod._plan_and_render(uid, ws)
    assert row.status == "edited" and row.status_detail.startswith("Captioned MP4 ready")
    assert row.qc["state"] == "unchecked" and row.qc["line"] == prod.QC_UNREADABLE
    assert wired["asked"] == [] and prod.QC_MARK not in (row.job_ids or [])
    assert library.qc_json(row)["label"] == "Not checked"


async def test_switched_off_nothing_is_checked(wired, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "production_qc", "off")

    async def fake_render(src, keep, out, **_kw):
        Path(out).write_bytes(b"edited")
        return Path(out)

    async def fake_size(_src):
        return (1080, 1920)

    monkeypatch.setattr(prod.media, "render_edit", fake_render)
    monkeypatch.setattr(prod.media, "probe_video_size", fake_size)
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"synthetic")
    ws, uid = await seed(wired["sm"], src, spoken("It is smart. Call them."))
    row = await prod._plan_and_render(uid, ws)
    assert row.status == "edited" and row.qc is None and await checks_of(wired["sm"], uid) == []


@needs_ffmpeg
async def test_a_worker_that_is_away_leaves_the_asides_unchecked_and_says_so(wired, tmp_path):
    wired["answers"][qc.ASIDES_JOB] = None  # the queue has no worker
    ws, uid, row = await edit(wired, tmp_path, spoken(CLEAN))
    assert row.status == "edited" and row.qc["state"] == "passed"
    assert "Not checked this time: leftover asides" in row.qc["line"]


def test_her_hold_counts_as_a_new_render_and_a_blocked_cut_does_not():
    held = SimpleNamespace(status="needs_review", render_ref="new", edited_path="/x/e.mp4",
                           qc={"state": "held", "render_ref": "new", "line": "Jennifer is holding this video: x."})
    assert prod._rendered_since(held, "old") is True and library.qc_hold(held).endswith("x.")
    # The plan was blocked before any render: the file is the old one.
    blocked = SimpleNamespace(status="needs_review", render_ref="old", edited_path="/x/e.mp4", qc=None)
    assert prod._rendered_since(blocked, "old") is False and library.qc_hold(blocked) is None
    # A hold of an older render is not a hold of the file he has now.
    stale = SimpleNamespace(status="needs_review", render_ref="newer", edited_path="/x/e.mp4",
                            qc={"state": "held", "render_ref": "new", "line": "x"})
    assert library.qc_hold(stale) is None and library.qc_json(stale) is None


# ------------------------------------------------------------------ the routes


@pytest.fixture
async def client(wired, monkeypatch):
    sm = wired["sm"]
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    app = FastAPI()
    app.include_router(workspace_router.production_router, prefix="/api/v1")
    app.include_router(prod.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sm

    async def _db():
        async with sm() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def auth(ws: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


async def settle() -> None:
    while prod._background:
        await asyncio.gather(*list(prod._background), return_exceptions=True)


@needs_ffmpeg
async def test_a_held_video_cannot_be_posted_until_he_lets_it_through(wired, client, tmp_path, a_caption_is_lost):
    ws, uid, row = await edit(wired, tmp_path, spoken("It is smart. Call them."))
    assert row.status == "needs_review"
    refused = await client.post(
        f"/api/v1/production/uploads/{uid}/publishing/publish", headers=auth(ws), json={"platforms": ["youtube"]}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("Jennifer is holding this video: 1 word has no caption")
    released = await client.post(f"/api/v1/production/uploads/{uid}/check/release", headers=auth(ws))
    assert released.status_code == 200
    body = released.json()
    assert body["status"] == "edited" and body["qc"]["state"] == "released"
    assert body["qc"]["line"].startswith("You let this one through. Jennifer had held it: ")
    await settle()
    assert [c.state for c in await checks_of(wired["sm"], uid)] == ["held", "released"]
    # Not held any more: a second release is refused.
    again = await client.post(f"/api/v1/production/uploads/{uid}/check/release", headers=auth(ws))
    assert again.status_code == 409 and again.json()["detail"] == "Jennifer is not holding this video"


@needs_ffmpeg
async def test_he_can_ask_for_a_check_again_and_the_card_says_what_she_is_doing(wired, client, tmp_path):
    ws, uid, row = await edit(wired, tmp_path, spoken(CLEAN))
    assert row.qc["state"] == "passed"
    started = await client.post(f"/api/v1/production/uploads/{uid}/check", headers=auth(ws))
    assert started.status_code == 202
    assert started.json()["status"] == "checking"
    assert started.json()["status_detail"].startswith("Jennifer is checking this edit: ")
    # While she checks, another check is refused with what she is doing.
    busy = await client.post(f"/api/v1/production/uploads/{uid}/check", headers=auth(ws))
    assert busy.status_code == 409 and "Jennifer is checking this edit" in busy.json()["detail"]
    await settle()
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    assert row.status == "edited" and row.qc["state"] == "passed" and prod.QC_MARK not in row.job_ids
    assert len(wired["renders"]) == 1 and len(await checks_of(wired["sm"], uid)) == 2


async def test_a_check_never_marks_ready_a_video_whose_blocked_cut_waits_for_him(wired, client, tmp_path):
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"synthetic")
    edited = tmp_path / "walk-edited.mp4"
    edited.write_bytes(b"edited")
    ws, uid = await seed(wired["sm"], src, spoken("It is smart."))
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
        row.status, row.edited_path = "needs_review", str(edited)
        row.status_detail = "Needs review: the cut would drop a not"
        await s.commit()
        [item] = (await library.list_library(s, ws))["items"]
    assert "check_again" not in [a["key"] for a in item["actions"]]
    r = await client.post(f"/api/v1/production/uploads/{uid}/check", headers=auth(ws))
    assert r.status_code == 409 and "waiting for your eyes" in r.json()["detail"]
    async with wired["sm"]() as s:
        assert (await prod._load(s, uid, ws)).status == "needs_review"


async def test_a_check_is_refused_when_there_is_no_edit(wired, client, tmp_path):
    src = tmp_path / "walk.mp4"
    src.write_bytes(b"synthetic")
    ws, uid = await seed(wired["sm"], src, spoken("It is smart."))
    r = await client.post(f"/api/v1/production/uploads/{uid}/check", headers=auth(ws))
    assert r.status_code == 409 and r.json()["detail"] == "There is no edit of this video to check yet"


def test_the_card_and_the_page_show_her_check():
    root = Path(__file__).parents[2] / "src/tce"
    js = (root / "api/workspace.js").read_text(encoding="utf-8")
    assert "function checkHtml(item)" in js and "html += checkHtml(item);" in js
    assert 'data-check-again="' in js and 'data-release-hold="' in js
    assert '"/check/release"' in js and '"checking"' in js
    assert "checking" in library._LIVE_STATUSES and "checking" in library.LIBRARY_FILTERS["editing"]
    assert autoedit.AGENT_NAME == "video_editor"  # internal names stay; only what he reads says Jennifer
