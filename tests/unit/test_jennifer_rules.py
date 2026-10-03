"""Jennifer learns from his notes (3-Oct): distillation, the rules table, prompts, the page.

The subscription worker is replaced by a function that answers each job. Synthetic data
only; the database is the suite's in-memory SQLite.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

import tce.models  # noqa: F401 - registers every table on Base.metadata
from tce.api import dashboard
from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as workspace_router
from tce.api.routers import production as prod
from tce.db.base import Base
from tce.db.session import get_db
from tce.editorial import editor_rules, library
from tce.llm import LLMUnavailable
from tce.llm.provider import LLMResult
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import EditingRequest, EditSession
from tce.models.jennifer import EditorRule
from tce.production import autoedit, qc
from tce.production import rules as rule_text
from tce.settings import settings
from tests.editorial_db import TABLE_NAMES

KEY = "synthetic-test-key"
DASHES = ("—", "–", " -- ")


def words(text: str, start: float = 0.0, step: float = 0.5) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start_s": t, "end_s": t + step - 0.1, "precision": "word"})
        t += step
    return out


SPOKEN = "Getting them back is really smart. Maple come here. Call them after the service."


# ------------------------------------------------------------------ distillation (pure)


def test_the_distill_prompt_carries_each_note_and_the_rules_she_has():
    prompt = rule_text.distill_prompt(
        "Topic: Call them after the service",
        [
            {"said": "cut the bit where I call Maple", "understood": "Cut the call to the dog",
             "where": "at 0:38", "reply": "Cut \"Maple come here\"."},
            {"said": "bring back that line", "where": "at 1:02"},
        ],
        ["Cut long pauses to a breath."],
    )
    assert "R1. Cut long pauses to a breath." in prompt
    assert '[note 1 | at 0:38 | he said "cut the bit where I call Maple" | read back as "Cut the call to the dog"' in prompt
    assert '[note 2 | at 1:02 | he said "bring back that line"]' in prompt
    assert "only about this video" in rule_text.DISTILL_SYSTEM.lower()
    assert not any(d in rule_text.DISTILL_SYSTEM + rule_text.RULES_HEADING for d in DASHES)


def test_each_note_becomes_a_rule_or_only_about_this_video_and_says_which():
    answer = {"notes": [
        {"note": 1, "kind": "rule", "rule": "cut any aside to the dogs, even under 2 seconds", "covered_by": 0, "why": "w"},
        {"note": 2, "kind": "this_video", "rule": "", "covered_by": 0, "why": "one line of this video"},
        {"note": 3, "kind": "covered", "rule": "", "covered_by": 1, "why": "already a rule"},
        {"note": 4, "kind": "rule", "rule": "Cut the pause at 0:38.", "covered_by": 0, "why": "w"},
        {"note": 5, "kind": "rule", "rule": "Cut long pauses to a breath", "covered_by": 0, "why": "w"},
    ]}
    got = rule_text.read_distill(answer, 6, ["Cut long pauses to a breath."])
    assert got[0] == {"kind": "rule", "rule": "Cut any aside to the dogs, even under 2 seconds.", "covered_by": None,
                      "why": "w"}
    assert got[1]["kind"] == "this_video"
    assert got[2] == {"kind": "covered", "rule": "Cut long pauses to a breath.", "covered_by": 0, "why": "already a rule"}
    # A "rule" pinned to a time is about this video; a rule she already has is covered.
    assert got[3]["kind"] == "this_video" and got[4]["kind"] == "covered"
    assert got[5]["kind"] == "unread"


def test_a_rule_is_one_plain_sentence():
    assert rule_text.clean_rule("keep the jokes — they work") == "Keep the jokes, they work."
    assert rule_text.clean_rule("  ") is None
    assert rule_text.clean_rule("x" * 300) is None
    assert rule_text.clean_rule("Cut at 1:20") is None


def test_the_rules_block_is_numbered_and_capped_and_the_cap_is_logged(caplog):
    rules = [f"Rule number {i} says something useful about the edit." for i in range(1, 6)]
    block, used = rule_text.rules_block(rules)
    assert block.startswith(rule_text.RULES_HEADING) and "R1. Rule number 1" in block and used == [0, 1, 2, 3, 4]
    logged: list[dict] = []
    real = rule_text.logger.warning
    rule_text.logger.warning = lambda event, **kw: logged.append({"event": event, **kw})  # type: ignore[method-assign]
    try:
        small, used = rule_text.rules_block(rules, max_chars=len(rule_text.RULES_HEADING) + 130)
    finally:
        rule_text.logger.warning = real  # type: ignore[method-assign]
    # The newest rules win, renumbered from R1; the oldest are left out, and it is logged.
    assert used == [3, 4] and "R1. Rule number 4" in small and "Rule number 1 " not in small
    assert logged == [{"event": "editor_rules.cap_hit", "rules": 5, "written": 2, "left_out": 3,
                       "max_chars": len(rule_text.RULES_HEADING) + 130}]
    assert rule_text.rules_block([]) == ("", [])


def test_the_rules_an_answer_names_are_read_from_its_reasons():
    assert rule_text.rules_named(["talk to the dog (R2)", "R1 and (R 3)", "R9"], 3) == [1, 2, 3]
    assert rule_text.rules_named(["nothing here", "R12"], 3) == []


# ------------------------------------------------------------------ rules in the prompts


def test_active_rules_go_into_the_review_after_the_skill_file():
    w = words(SPOKEN)
    prompt, system = prod._review_request(w, "Topic: x", None, [["id-1", "Cut any aside to the dogs."]])
    assert "R1. Cut any aside to the dogs." in system
    assert system.index("HIS STANDING RULES") < system.index("RULES YOU LEARNED FROM HIS NOTES")
    # No rules: the instructions are exactly what they were before 3-Oct.
    _, plain = prod._review_request(w, "Topic: x")
    assert plain == autoedit.review_system(prod.aside_names())
    assert "RULES YOU LEARNED" not in plain


def test_a_rule_learned_while_a_review_waits_does_not_move_its_key():
    w = words(SPOKEN)
    asked = prod._review_key(uuid.uuid4(), *prod._review_request(w, "T", None, [["a", "Rule one."]]))
    again = prod._review_key(uuid.UUID(int=0), *prod._review_request(w, "T", None, [["a", "Rule one."]]))
    assert asked != again  # the key names its video ...
    uid = uuid.uuid4()
    one = prod._review_key(uid, *prod._review_request(w, "T", None, [["a", "Rule one."]]))
    two = prod._review_key(uid, *prod._review_request(w, "T", None, [["a", "Rule one."], ["b", "Rule two."]]))
    assert one != two  # ... and its rules, which is why a waiting review keeps the rules it was asked with


# ------------------------------------------------------------------ learning, end to end


@pytest.fixture
def wired(monkeypatch, editorial_sessionmaker):
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    monkeypatch.setattr(settings, "production_learn_rules", True)
    monkeypatch.setattr(settings, "production_auto_edit", True)
    asked: list[dict] = []
    answers: dict[str, object] = {}

    async def fake_ask(kind, prompt, system, schema, ws, key, **_opts):
        asked.append({"kind": kind, "prompt": prompt, "system": system})
        answer = answers.get(kind)
        if callable(answer):
            answer = answer(prompt)
        if answer is None:
            raise LLMUnavailable("failed", "no worker in tests")
        return LLMResult(job_id=uuid.uuid4(), text="", structured=answer, model="claude-opus-5-5")

    async def fake_render(upload_id, ws, attempt, mode):
        async with editorial_sessionmaker() as s:
            row = await prod._load(s, upload_id, ws)
            row.status, row.edited_path = "edited", "/work/projects/alpha-service/edited.mp4"
            row.render_ref = uuid.uuid4().hex[:16]
            row.rendered_keep = [list(r) for r in row.edit_plan["keep"]]
            await s.commit()

    monkeypatch.setattr(prod, "_ask", fake_ask)
    monkeypatch.setattr(prod, "_run_render", fake_render)
    return {"sm": editorial_sessionmaker, "asked": asked, "answers": answers}


async def seed(sm) -> tuple[uuid.UUID, uuid.UUID]:
    ws = uuid.uuid4()
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
            storage_path="/work/projects/alpha-service/walk.mp4", sha256=uuid.uuid4().hex * 2,
            status="transcribed", transcript=words(SPOKEN), duration_s=12.0,
        )
        s.add(up)
        await s.commit()
        await prod._compute_plan(s, ws, up)
        up.status, up.edited_path = "edited", "/work/projects/alpha-service/edited.mp4"
        await s.commit()
        return ws, up.id


async def settle() -> None:
    while prod._background:
        await asyncio.gather(*list(prod._background), return_exceptions=True)


async def typed_request(sm, ws, uid, text: str) -> uuid.UUID:
    async with sm() as s:
        req = EditingRequest(workspace_id=ws, upload_id=uid, request=text, scope="whole", state="open")
        s.add(req)
        await s.commit()
        return req.id


async def test_a_typed_request_that_was_applied_teaches_a_rule(wired):
    ws, uid = await seed(wired["sm"])
    wired["answers"][autoedit.EDIT_REQUEST_JOB] = {
        "reply": "Cut \"Maple come here.\"", "needs_you": False, "corrections": [],
        "cut": [{"first": 6, "last": 8}], "restore": [], "hold": [],
    }
    wired["answers"][rule_text.DISTILL_JOB] = {"notes": [
        {"note": 1, "kind": "rule", "rule": "Cut any aside to the dogs, even under 2 seconds.", "covered_by": 0,
         "why": "about the dogs, not this line"},
    ]}
    rid = await typed_request(wired["sm"], ws, uid, "always cut me calling the dogs, even short ones")
    await prod.run_edit_request(rid, ws)
    await settle()
    async with wired["sm"]() as s:
        req = await s.get(EditingRequest, rid)
        [rule] = (await s.execute(select(EditorRule).where(EditorRule.workspace_id == ws))).scalars().all()
    assert req.state == "done"
    assert rule.text == "Cut any aside to the dogs, even under 2 seconds."
    assert (rule.source_upload_id, rule.source_note_id, rule.active, rule.times_applied) == (uid, rid, True, 0)
    assert req.result["learned"]["state"] == "rule" and req.result["learned"]["rule_id"] == str(rule.id)
    distill = next(a for a in wired["asked"] if a["kind"] == rule_text.DISTILL_JOB)
    assert 'he said "always cut me calling the dogs, even short ones"' in distill["prompt"]
    assert "Call them after the service" in distill["prompt"]
    # The next video's review is told the rule, after the skill file.
    ws2_review = prod._review_request(words(SPOKEN), "T", None, await _rules(wired["sm"], ws))[1]
    assert "R1. Cut any aside to the dogs, even under 2 seconds." in ws2_review
    # And the asides check of her own QC gets it too.
    block = editor_rules.block(await _rules(wired["sm"], ws))[0]
    assert "R1. Cut any aside to the dogs" in qc.asides_system(["Maple"], skill="S", rules=block)


async def _rules(sm, ws):
    async with sm() as s:
        return await editor_rules.prompt_rules(s, ws)


async def test_a_note_only_about_this_video_teaches_nothing_and_says_so(wired):
    ws, uid = await seed(wired["sm"])
    wired["answers"][autoedit.EDIT_REQUEST_JOB] = {
        "reply": "Cut it.", "needs_you": False, "corrections": [], "cut": [{"first": 6, "last": 8}],
        "restore": [], "hold": [],
    }
    wired["answers"][rule_text.DISTILL_JOB] = {"notes": [
        {"note": 1, "kind": "this_video", "rule": "", "covered_by": 0, "why": "one line of this video"},
    ]}
    rid = await typed_request(wired["sm"], ws, uid, "take out the second sentence")
    await prod.run_edit_request(rid, ws)
    await settle()
    async with wired["sm"]() as s:
        req = await s.get(EditingRequest, rid)
        rules = (await s.execute(select(EditorRule))).scalars().all()
    assert rules == [] and req.result["learned"]["state"] == "this_video"
    assert library.learned_json(req.result["learned"])["line"] == "Jennifer took this as only about this video."


async def test_an_answer_that_changed_nothing_teaches_nothing(wired):
    ws, uid = await seed(wired["sm"])
    wired["answers"][autoedit.EDIT_REQUEST_JOB] = {
        "reply": "The phone cut the end of that word; no cut can bring it back.", "needs_you": False,
        "corrections": [], "cut": [], "restore": [], "hold": [],
    }
    rid = await typed_request(wired["sm"], ws, uid, "the word course sounds cut")
    await prod.run_edit_request(rid, ws)
    await settle()
    assert not [a for a in wired["asked"] if a["kind"] == rule_text.DISTILL_JOB]


async def test_switched_off_no_rule_is_learned(wired, monkeypatch):
    monkeypatch.setattr(settings, "production_learn_rules", False)
    ws, uid = await seed(wired["sm"])
    wired["answers"][autoedit.EDIT_REQUEST_JOB] = {
        "reply": "Cut it.", "needs_you": False, "corrections": [], "cut": [{"first": 6, "last": 8}],
        "restore": [], "hold": [],
    }
    rid = await typed_request(wired["sm"], ws, uid, "cut the dogs always")
    await prod.run_edit_request(rid, ws)
    await settle()
    assert not [a for a in wired["asked"] if a["kind"] == rule_text.DISTILL_JOB]


async def test_the_notes_of_a_sitting_that_changed_the_video_are_learned_from_in_one_job(wired):
    ws, uid = await seed(wired["sm"])
    async with wired["sm"]() as s:
        sitting = EditSession(workspace_id=ws, upload_id=uid, state="rendering", before={"render_ref": "old"},
                              result={"outcomes": []})
        s.add(sitting)
        await s.flush()
        notes = []
        for k, said in enumerate(("always cut the dogs", "this line is fine, bring it back")):
            # In the order he gave them, to the microsecond, as the sheet pins them.
            n = EditingRequest(workspace_id=ws, upload_id=uid, session_id=sitting.id, request=said,
                               scope="moment", start_s=1.0, state="held",
                               created_at=datetime(2026, 10, 3, 9, 0, k))
            s.add(n)
            notes.append(n)
        await s.flush()
        sitting.result = {"outcomes": [
            {"note": 1, "outcome": "change", "reply": "Cut it.", "id": str(notes[0].id)},
            {"note": 2, "outcome": "change", "reply": "Brought it back.", "id": str(notes[1].id)},
        ]}
        row = await prod._load(s, uid, ws)
        row.render_ref = "new"
        await s.commit()
        sid, ids = sitting.id, [n.id for n in notes]
    wired["answers"][rule_text.DISTILL_JOB] = {"notes": [
        {"note": 1, "kind": "rule", "rule": "Cut every call to the dogs.", "covered_by": 0, "why": "w"},
        {"note": 2, "kind": "this_video", "rule": "", "covered_by": 0, "why": "w"},
    ]}
    await prod._settle_talk(sid, ws)
    await settle()
    distills = [a for a in wired["asked"] if a["kind"] == rule_text.DISTILL_JOB]
    assert len(distills) == 1 and "note 2" in distills[0]["prompt"]
    async with wired["sm"]() as s:
        learned = [(await s.get(EditingRequest, i)).result["learned"]["state"] for i in ids]
        [rule] = (await s.execute(select(EditorRule))).scalars().all()
        made = library._notes_made_json(await s.get(EditSession, sid), [await s.get(EditingRequest, i) for i in ids])
    assert learned == ["rule", "this_video"] and rule.source_note_id == ids[0]
    assert made["notes"][0]["learned"]["line"] == "Jennifer learned a rule from this: Cut every call to the dogs."


async def test_a_worker_that_fails_leaves_the_note_unlearned_and_no_rule(wired):
    ws, uid = await seed(wired["sm"])
    rid = await typed_request(wired["sm"], ws, uid, "cut the dogs always")
    async with wired["sm"]() as s:
        req = await s.get(EditingRequest, rid)
        req.state, req.result = "done", {"reply": "Cut."}
        await s.commit()
    await prod.learn_from_notes(ws, uid, [rid])  # no answer registered: the job fails
    async with wired["sm"]() as s:
        req = await s.get(EditingRequest, rid)
        assert (await s.execute(select(EditorRule))).scalars().all() == []
    assert req.result["learned"]["state"] == "unavailable"
    # A note already decided is never asked about twice.
    wired["asked"].clear()
    req_result = dict(req.result)
    async with wired["sm"]() as s:
        req = await s.get(EditingRequest, rid)
        req.result = {**req_result, "learned": {"state": "this_video"}}
        await s.commit()
    await prod.learn_from_notes(ws, uid, [rid])
    assert wired["asked"] == []


async def test_a_review_that_names_a_rule_counts_the_video_once(wired):
    ws, uid = await seed(wired["sm"])
    async with wired["sm"]() as s:
        rule = await editor_rules.add_rule(s, ws, "Cut every call to the dogs.", upload_id=None, note_id=None)
        await s.commit()
        rid = rule.id
    review = {"removals": [{"first": 6, "last": 8, "heard": "Maple come here.", "kind": "aside", "kept_from": -1,
                            "why": "calling the dog (R1)"}], "corrections": []}
    wired["answers"][autoedit.REVIEW_JOB] = review
    await prod._review(uid, ws, wait_timeout_s=1)
    await prod._review(uid, ws, wait_timeout_s=1)  # the same video edited again
    async with wired["sm"]() as s:
        rule = await s.get(EditorRule, rid)
        row = await prod._load(s, uid, ws)
    assert rule.times_applied == 1 and rule.applied_uploads == [str(uid)]
    assert row.edit_plan["review"]["rules_used"] == [str(rid)]
    assert "R1. Cut every call to the dogs." in wired["asked"][0]["system"]


# ------------------------------------------------------------------ the page and Delete


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    app = FastAPI()
    app.include_router(workspace_router.production_router, prefix="/api/v1")
    app.include_router(prod.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: editorial_sessionmaker

    async def _db():
        async with editorial_sessionmaker() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def auth(ws) -> dict:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


async def test_the_rules_page_lists_each_rule_with_its_source_video_and_delete_switches_it_off(
    client, editorial_sessionmaker
):
    sm = editorial_sessionmaker
    ws, other = uuid.uuid4(), uuid.uuid4()
    async with sm() as s:
        cand = TopicCandidate(workspace_id=ws, week_start=datetime(2026, 9, 28), moment_ids=["m"],
                              title="Selling is the first step", lesson="l", audience="a", public_angle="p",
                              gates={}, status="recorded")
        s.add(cand)
        await s.flush()
        up = RecordingUpload(workspace_id=ws, candidate_id=cand.id, original_filename="w.mp4",
                             storage_path="/work/projects/alpha-service/w.mp4", sha256=uuid.uuid4().hex * 2,
                             status="edited", edited_path="/work/projects/alpha-service/e.mp4")
        s.add(up)
        await s.flush()
        note = EditingRequest(workspace_id=ws, upload_id=up.id, request="always cut the dogs", state="done")
        s.add(note)
        await s.flush()
        old = await editor_rules.add_rule(s, ws, "Cut long pauses to a breath.", upload_id=None, note_id=None)
        new = await editor_rules.add_rule(s, ws, "Cut every call to the dogs.", upload_id=up.id, note_id=note.id)
        new.times_applied = 3
        await editor_rules.add_rule(s, other, "Another workspace's rule.", upload_id=None, note_id=None)
        await s.commit()
        upload_id, new_id, old_id = up.id, new.id, old.id
    body = (await client.get("/api/v1/production/editor-rules", headers=auth(ws))).json()
    assert body["total"] == 2
    first = body["rules"][0]  # newest first
    assert first == {
        "id": str(new_id), "text": "Cut every call to the dogs.", "created_at": first["created_at"],
        "times_applied": 3, "source_upload_id": str(upload_id), "source_title": "Selling is the first step",
        "source_has_edit": True, "source_note": "always cut the dogs", "in_use": True,
    }
    assert body["rules"][1]["source_upload_id"] is None and body["rules"][1]["source_title"] is None
    gone = await client.delete(f"/api/v1/production/editor-rules/{new_id}", headers=auth(ws))
    assert gone.status_code == 200 and gone.json()["active"] is False
    after = (await client.get("/api/v1/production/editor-rules", headers=auth(ws))).json()
    assert [r["id"] for r in after["rules"]] == [str(old_id)]
    async with sm() as s:
        row = await s.get(EditorRule, new_id)  # Delete keeps the row
        assert row is not None and row.active is False and row.deactivated_at is not None
        assert [r[1] for r in await editor_rules.prompt_rules(s, ws)] == ["Cut long pauses to a breath."]
    # Another workspace's rule is not his to see or delete.
    foreign = (await client.get("/api/v1/production/editor-rules", headers=auth(other))).json()["rules"][0]["id"]
    assert (await client.delete(f"/api/v1/production/editor-rules/{foreign}", headers=auth(ws))).status_code == 404
    assert (await client.delete(f"/api/v1/production/editor-rules/{uuid.uuid4()}", headers=auth(ws))).status_code == 404


def test_the_rules_page_has_its_own_address_and_draws_each_rule_with_delete():
    js = (Path(__file__).parents[2] / "src/tce/api/workspace.js").read_text(encoding="utf-8")
    assert '{ name: "rules",    pattern: /^\\/library\\/rules\\/?$/,      title: "Jennifer\'s rules" }' in js
    assert 'else if (route.name === "rules") await renderRules();' in js
    assert '"/production/editor-rules/" + encodeURIComponent(ruleId), { method: "DELETE" }' in js
    assert 'data-rule-delete="' in js and "Open the video it came from: " in js
    assert 'data-go="/library/rules">Jennifer\\\'s rules</a>' in js
    paths = {r.path for r in dashboard.router.routes}
    assert "/library/rules" in paths
    # The rules route is matched before the notes sheet's /library/<id>/talk.
    assert js.index('name: "rules"') < js.index('name: "talk"')


def test_her_voice_seat_knows_she_checks_and_learns_and_can_read_her_rules():
    root = Path(__file__).parents[2]
    brief = (root / "deploy/voice-seat/tce-brief.md").read_text(encoding="utf-8")
    seat = (root / "deploy/voice-seat/tce.json").read_text(encoding="utf-8")
    assert "You learn from his notes." in brief and "tce_video_rules" in brief and "tce_video_check" in brief
    assert "Jennifer's rules" in brief
    assert "mcp__tce__tce_video_rules" in seat and "mcp__tce__tce_video_check" in seat
    for text in (brief, seat):
        assert not any(d in text for d in DASHES)


async def test_her_learned_rules_reach_her_voice_seat_after_the_skill_file(editorial_session):
    ws = uuid.uuid4()
    await editor_rules.add_rule(editorial_session, ws, "Cut every call to the dogs.", upload_id=None, note_id=None)
    text = await library.learned_rules_text(editorial_session, ws)
    assert text == "\n\n## Rules you learned from his notes on earlier videos\n- Cut every call to the dogs."
    assert await library.learned_rules_text(editorial_session, uuid.uuid4()) == ""


# ------------------------------------------------------------------ migration 058


VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
MIGRATION = VERSIONS / "058_jennifer_checks_and_rules.py"
NEW_TABLES = ("render_checks", "editor_rules")


def _migration():
    spec = importlib.util.spec_from_file_location("migration_058", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _before_058() -> sa.MetaData:
    md = sa.MetaData()
    for name in TABLE_NAMES:
        if name in NEW_TABLES:
            continue
        table = Base.metadata.tables[name]
        dropped = {"qc"} if name == "recording_uploads" else set()
        links = [
            sa.ForeignKeyConstraint([c.name for c in fk.columns], [e.target_fullname for e in fk.elements],
                                    ondelete=fk.ondelete, name=fk.name)
            for fk in table.foreign_key_constraints
        ]
        sa.Table(name, md, *[c._copy() for c in table.columns if c.name not in dropped], *links)
    return md


def _run(sync_conn, step: str) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        getattr(_migration(), step)()


def _shape(sync_conn) -> dict:
    insp = sa.inspect(sync_conn)
    out: dict = {"tables": set(insp.get_table_names())}
    for name in ("recording_uploads", *NEW_TABLES):
        if name in out["tables"]:
            out[name] = {c["name"] for c in insp.get_columns(name)}
            out[name + ".fks"] = {(tuple(f["constrained_columns"]), f["referred_table"]) for f in insp.get_foreign_keys(name)}
    return out


def test_058_follows_057_and_is_the_only_head():
    module = _migration()
    assert module.revision == "058" and module.down_revision == "057"
    parents = [p.name for p in VERSIONS.glob("*.py") if 'down_revision = "057"' in p.read_text(encoding="utf-8")]
    assert parents == ["058_jennifer_checks_and_rules.py"]


async def test_058_up_and_down_on_the_test_database_matches_the_models():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: _before_058().create_all(c))
            before = await conn.run_sync(_shape)
            assert not set(NEW_TABLES) & before["tables"] and "qc" not in before["recording_uploads"]
            await conn.run_sync(lambda c: _run(c, "upgrade"))
            after = await conn.run_sync(_shape)
            for name in ("recording_uploads", *NEW_TABLES):
                assert after[name] == set(Base.metadata.tables[name].c.keys()), name
            assert (("upload_id",), "recording_uploads") in after["render_checks.fks"]
            assert (("source_upload_id",), "recording_uploads") in after["editor_rules.fks"]
            assert (("source_note_id",), "editing_requests") in after["editor_rules.fks"]
            await conn.run_sync(lambda c: _run(c, "downgrade"))
            undone = await conn.run_sync(_shape)
            assert undone["tables"] == before["tables"] and undone["recording_uploads"] == before["recording_uploads"]
            await conn.run_sync(lambda c: _run(c, "upgrade"))
            assert set(NEW_TABLES) <= (await conn.run_sync(_shape))["tables"]
    finally:
        await engine.dispose()


def test_on_postgres_058_is_additive_sql():
    buf = io.StringIO()
    ctx = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buf})
    with Operations.context(ctx):
        _migration().upgrade()
    sql = " ".join(buf.getvalue().split())
    assert "ALTER TABLE recording_uploads ADD COLUMN qc JSONB" in sql
    assert "CREATE TABLE render_checks" in sql and "CREATE TABLE editor_rules" in sql
    assert "DROP" not in sql.upper()
    assert "TABLE_NAMES" and all(t in TABLE_NAMES for t in NEW_TABLES)
