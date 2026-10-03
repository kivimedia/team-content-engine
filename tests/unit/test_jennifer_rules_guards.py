"""Jennifer's rules under stress (3-Oct review of DECIDED 8).

A deleted rule is never applied, not even by a job that read it before he deleted it;
a long list of rules never blows up a prompt, and the page says which rules are past
the cap; what the distilling job decided is always recorded with its reason. Same
fixtures as test_jennifer_rules.py; synthetic data only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from tce.api.routers import production as prod
from tce.editorial import editor_rules, library
from tce.llm import LLMUnavailable
from tce.models.editorial_workspace import EditingRequest
from tce.models.jennifer import EditorRule
from tce.production import autoedit, qc
from tce.production import rules as rule_text
from tests.unit.test_jennifer_rules import (  # noqa: F401 - the fixtures are used by name
    SPOKEN,
    auth,
    client,
    seed,
    settle,
    typed_request,
    wired,
    words,
)

DOG_RULE = "Cut every call to the dogs."
# "Maple come here." are words 6 to 8 of SPOKEN.
CUT_THE_DOG = {"removals": [{"first": 6, "last": 8, "heard": "Maple come here.", "kind": "aside",
                             "kept_from": -1, "why": "calling the dog (R1)"}], "corrections": []}


def _waiting(_prompt):
    raise LLMUnavailable("timeout", "the worker is away")


async def _add(sm, ws, text: str) -> uuid.UUID:
    async with sm() as s:
        rule = await editor_rules.add_rule(s, ws, text, upload_id=None, note_id=None)
        await s.commit()
        return rule.id


async def _delete(sm, ws, rule_id) -> None:
    async with sm() as s:
        await editor_rules.deactivate(s, ws, rule_id)
        await s.commit()


async def _row(sm, ws, uid):
    async with sm() as s:
        return await prod._load(s, uid, ws)


# ---------------------------------------------------------------------------
# Every new route needs the private key


async def test_every_new_jennifer_route_needs_the_private_key(client):
    uid, rid, ws = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for method, url in (
        ("post", f"/api/v1/production/uploads/{uid}/check"),
        ("post", f"/api/v1/production/uploads/{uid}/check/release"),
        ("get", "/api/v1/production/editor-rules"),
        ("delete", f"/api/v1/production/editor-rules/{rid}"),
    ):
        for headers in ({"X-Workspace-Id": str(ws)}, {"Authorization": "Bearer not-the-key", "X-Workspace-Id": str(ws)}):
            r = await getattr(client, method)(url, headers=headers)
            assert r.status_code == 401, (method, url, r.status_code)


# ---------------------------------------------------------------------------
# A deleted rule is never applied


async def test_a_waiting_review_that_read_a_rule_he_deleted_is_asked_again_without_it(wired):
    sm = wired["sm"]
    ws, uid = await seed(sm)
    rule_id = await _add(sm, ws, DOG_RULE)
    wired["answers"][autoedit.REVIEW_JOB] = _waiting
    assert await prod._review(uid, ws, wait_timeout_s=1) == "waiting"
    review = (await _row(sm, ws, uid)).edit_plan["review"]
    assert review["state"] == "waiting" and review["rules"] == [[str(rule_id), DOG_RULE]]
    old_key = review["key"]

    await _delete(sm, ws, rule_id)
    # The answer that comes back follows the rule he deleted.
    wired["answers"][autoedit.REVIEW_JOB] = CUT_THE_DOG
    wired["asked"].clear()
    await prod._await_review(uid, ws)

    asked = [a for a in wired["asked"] if a["kind"] == autoedit.REVIEW_JOB]
    assert asked, "the review was asked again"
    # Without the guard the waiter asks with the rules it saved, the deleted one among them.
    assert all(DOG_RULE not in a["system"] for a in asked), "a deleted rule never reaches the review"
    assert prod._review_key(uid, asked[-1]["prompt"], asked[-1]["system"]) != old_key
    review = (await _row(sm, ws, uid)).edit_plan["review"]
    assert review["state"] == "done" and "rules_used" not in review
    async with sm() as s:
        rule = await s.get(EditorRule, rule_id)
    assert rule.times_applied == 0 and rule.applied_uploads == []


async def test_a_rule_deleted_while_the_first_review_reads_is_never_applied(wired, monkeypatch):
    sm = wired["sm"]
    ws, uid = await seed(sm)
    rule_id = await _add(sm, ws, DOG_RULE)
    real = editor_rules.prompt_rules
    calls = {"n": 0}

    async def deleted_after_the_first_read(s, w):
        calls["n"] += 1
        if calls["n"] == 1:
            return await real(s, w)
        return []  # he deleted it while the review was being read

    monkeypatch.setattr(prod.editor_rules, "prompt_rules", deleted_after_the_first_read)
    wired["answers"][autoedit.REVIEW_JOB] = CUT_THE_DOG
    assert await prod._review(uid, ws, wait_timeout_s=1) == "waiting"
    row = await _row(sm, ws, uid)
    review = row.edit_plan["review"]
    # The answer was not used: no removal from it, and the waiter asks again.
    assert review["state"] == "waiting" and "removals" not in review
    assert review["detail"] == "a rule it read was deleted while it read"
    assert row.status_detail.startswith("You deleted one of Jennifer's rules while she was reading")
    async with sm() as s:
        assert (await s.get(EditorRule, rule_id)).times_applied == 0


async def test_her_check_does_not_use_a_reading_that_read_a_rule_he_deleted(wired):
    sm = wired["sm"]
    ws, uid = await seed(sm)
    w = words(SPOKEN)
    kept = qc.kept_on_edit(
        [{"index": i, "text": x["text"], "start": x["start_s"], "end": x["end_s"]} for i, x in enumerate(w)],
        [[0.0, 20.0]],
    )
    wired["answers"][qc.ASIDES_JOB] = {"asides": [{"first": 6, "last": 8, "heard": "Maple come here.",
                                                   "why": "calling the dog (R1)"}]}
    gone = [[str(uuid.uuid4()), DOG_RULE]]  # asked with a rule that is not in force any more
    found = await prod._qc_asides(uid, ws, kept, "Topic: x", None, gone)
    assert found["state"] == "skipped" and "deleted" in found["why"]
    # The same reading with a rule still in force is used.
    rule_id = await _add(sm, ws, DOG_RULE)
    found = await prod._qc_asides(uid, ws, kept, "Topic: x", None, [[str(rule_id), DOG_RULE]])
    assert found["state"] == "fail" and found["problems"][0]["fix"]["cut"]


async def test_a_deleted_rule_is_never_counted_as_applied(wired):
    sm = wired["sm"]
    ws, uid = await seed(sm)
    rule_id = await _add(sm, ws, DOG_RULE)
    await _delete(sm, ws, rule_id)
    async with sm() as s:
        assert await editor_rules.mark_applied(s, ws, [str(rule_id)], uid) == 0
        await s.commit()
        assert (await s.get(EditorRule, rule_id)).times_applied == 0


# ---------------------------------------------------------------------------
# A long list of rules never blows up a prompt


def _long_rules(n: int) -> list[str]:
    return [f"Rule {i:02d}: keep the cut tight around every pause he takes while walking the dogs here." for i in range(n)]


async def test_every_prompt_that_lists_her_rules_is_capped_and_the_page_says_which_are_past_it(wired, client):
    sm = wired["sm"]
    ws, uid = await seed(sm)
    texts = _long_rules(60)
    for t in texts:
        await _add(sm, ws, t)
    async with sm() as s:
        in_force = await editor_rules.prompt_rules(s, ws)
    assert len(in_force) == 60
    written = editor_rules.in_block(in_force)
    assert 0 < len(written) < 60 and written[-1][1] == texts[-1]  # the newest are kept
    oldest = texts[0]

    # The review and her check.
    _prompt, system = prod._review_request(words(SPOKEN), "T", None, in_force)
    block = editor_rules.block(in_force)[0]
    assert len(block) <= rule_text.MAX_RULES_BLOCK_CHARS and oldest not in system

    # The distilling job.
    wired["answers"][autoedit.EDIT_REQUEST_JOB] = {
        "reply": "Cut it.", "needs_you": False, "corrections": [], "cut": [{"first": 6, "last": 8}],
        "restore": [], "hold": [],
    }
    wired["answers"][rule_text.DISTILL_JOB] = {"notes": [
        {"note": 1, "kind": "rule", "rule": "Cut any aside to the dogs.", "covered_by": 0, "why": "about the dogs"},
    ]}
    rid = await typed_request(sm, ws, uid, "always cut me calling the dogs")
    await prod.run_edit_request(rid, ws)
    await settle()
    distill = next(a for a in wired["asked"] if a["kind"] == rule_text.DISTILL_JOB)
    assert oldest not in distill["prompt"] and texts[-1] in distill["prompt"]
    assert distill["prompt"].count("\nR") <= len(written)

    # Her voice seat.
    async with sm() as s:
        seat = await library.learned_rules_text(s, ws)
    assert oldest not in seat and len(seat) <= rule_text.MAX_RULES_BLOCK_CHARS + 200

    # The page lists every rule and says which ones she is not using right now.
    body = (await client.get("/api/v1/production/editor-rules", headers=auth(ws))).json()
    by_text = {r["text"]: r for r in body["rules"]}
    assert body["total"] == 61 and by_text[oldest]["in_use"] is False
    assert by_text["Cut any aside to the dogs."]["in_use"] is True
    assert body["in_use"] < body["total"]


def test_the_rules_page_says_plainly_when_a_rule_is_not_used():
    from pathlib import Path

    js = (Path(__file__).parents[2] / "src/tce/api/workspace.js").read_text(encoding="utf-8")
    assert "r.in_use === false" in js
    assert "Not used right now: Jennifer reads only the newest rules that fit" in js


# ---------------------------------------------------------------------------
# What the distilling job decided is recorded, with its reason


async def test_a_rule_records_why_it_is_a_rule_and_a_this_video_note_why_it_is_not(wired):
    sm = wired["sm"]
    ws, uid = await seed(sm)
    wired["answers"][autoedit.EDIT_REQUEST_JOB] = {
        "reply": "Cut it.", "needs_you": False, "corrections": [], "cut": [{"first": 6, "last": 8}],
        "restore": [], "hold": [],
    }
    wired["answers"][rule_text.DISTILL_JOB] = {"notes": [
        {"note": 1, "kind": "rule", "rule": "Cut every call to the dogs.", "covered_by": 0,
         "why": "about the dogs, not this line"},
    ]}
    rid = await typed_request(sm, ws, uid, "always cut me calling the dogs")
    await prod.run_edit_request(rid, ws)
    await settle()
    async with sm() as s:
        req = await s.get(EditingRequest, rid)
        rules = (await s.execute(select(EditorRule).where(EditorRule.workspace_id == ws))).scalars().all()
    assert req.result["learned"]["state"] == "rule" and req.result["learned"]["why"] == "about the dogs, not this line"
    assert [r.text for r in rules] == ["Cut every call to the dogs."]
