"""A first cut the meaning check blocked: the card says it in one plain sentence, offers
Jennifer and two taps, and the voice tool and the taps settle it (T-13809, 18-Oct).

Synthetic recording and plan only; the render is the real ffmpeg on generated tone bursts."""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_jennifer_flow import (  # noqa: F401  (fixtures)
    auth, client, needs_ffmpeg, prod, recording, seed, settle, spoken, wired,
)
from tce.editorial import library

SAID = "Few clicks came in, no leads."
SCRIPT = "A few clicks came in."
ISSUE = {
    "kind": "negation_differs_from_script",
    "detail": f'Kept take at 0:02 ("{SAID}") and script phrase 5 ("{SCRIPT}") differ on negation',
    "kept_index": 1,
}


def held_plan() -> dict:
    return {
        "keep": [[0.9, 4.5]],
        "dropped": [],
        "units": [
            {"index": 0, "start": 1.0, "end": 1.9, "text": "Hello there.", "kept": True, "reason": None},
            {"index": 1, "start": 2.0, "end": 4.4, "text": SAID, "kept": True, "reason": None},
        ],
        "meaning_check": {"status": "blocked", "issues": [ISSUE], "notes": []},
        "stats": {"kept_seconds": 3.6},
        "timing": {"summary": "x"},
    }


async def held(wired, tmp_path):
    src = recording(tmp_path / "held.wav", spoken("Hello there. Few clicks came in no leads."))
    ws, uid = await seed(wired["sm"], src, spoken("Hello there. Few clicks came in no leads."))
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
        row.status, row.edit_plan = "needs_review", held_plan()
        row.status_detail = f"Needs review: {ISSUE['detail']}"
        await s.commit()
    return ws, uid


def test_the_sentence_is_plain_not_a_dict():
    said = library.issue_sentence(ISSUE)
    assert said == (
        f'At 0:02 you said "{SAID}" The script says "{SCRIPT}" Keep what you said, or use the script line?'
    )
    assert "{" not in said and "kind" not in said
    assert library.issue_sentence({"kind": "x", "detail": "Plain words."}) == "Plain words."


@needs_ffmpeg
async def test_the_card_offers_jennifer_and_two_taps_and_no_dict(wired, tmp_path):
    ws, uid = await held(wired, tmp_path)
    async with wired["sm"]() as s:
        [item] = (await library.list_library(s, ws))["items"]
    keys = [a["key"] for a in item["actions"]]
    assert "talk_hold" in keys and "keep_mine" in keys and "use_script" in keys and "talk_edit" not in keys
    assert item["issues"] == [library.issue_sentence(ISSUE)]
    assert item["meaning_hold"]["can_use_script"] is True


@needs_ffmpeg
async def test_keep_mine_renders_the_plan_as_planned(wired, client, tmp_path):
    ws, uid = await held(wired, tmp_path)
    r = await client.post(f"/api/v1/production/uploads/{uid}/meaning-hold", headers=auth(ws), json={"choice": "keep_mine"})
    assert r.status_code == 202, r.text
    await settle()
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    assert row.status in ("edited", "checking", "needs_review") and row.edited_path
    assert row.edit_plan["meaning_check"]["status"] == "ok"
    assert row.edit_plan["meaning_check"]["settled"]["choice"] == "keep_mine"
    assert wired["renders"] and wired["renders"][0] == [[0.9, 4.5]]
    again = await client.post(f"/api/v1/production/uploads/{uid}/meaning-hold", headers=auth(ws), json={"choice": "keep_mine"})
    assert again.status_code == 409


@needs_ffmpeg
async def test_use_script_cuts_the_line_that_differs(wired, client, tmp_path):
    ws, uid = await held(wired, tmp_path)
    r = await client.post(f"/api/v1/production/uploads/{uid}/meaning-hold", headers=auth(ws), json={"choice": "use_script"})
    assert r.status_code == 202, r.text
    await settle()
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
    assert row.edit_plan["keep"] == [[0.9, 1.9]]
    assert row.edit_plan["meaning_check"]["settled"]["choice"] == "use_script"
    assert [u["kept"] for u in row.edit_plan["units"]] == [True, False]
    assert wired["renders"][0] == [[0.9, 1.9]]


@needs_ffmpeg
async def test_the_talk_lookup_carries_the_hold_and_a_video_with_no_hold_is_refused(wired, client, tmp_path):
    ws, uid = await held(wired, tmp_path)
    t = await client.get(f"/api/v1/production/recordings/{uid}/talk", headers=auth(ws))
    assert t.status_code == 200 and t.json()["meaning_hold"]["sentence"].startswith("At 0:02 you said")
    async with wired["sm"]() as s:
        row = await prod._load(s, uid, ws)
        row.status = "edited"
        await s.commit()
    r = await client.post(f"/api/v1/production/uploads/{uid}/meaning-hold", headers=auth(ws), json={"choice": "keep_mine"})
    assert r.status_code == 409


def test_the_page_wires_the_taps_and_the_header_call():
    js = (Path(library.__file__).parents[1] / "api" / "workspace.js").read_text(encoding="utf-8")
    assert 'data-settle-hold="' in js and '"settle-hold"' in js and "/meaning-hold" in js
    assert 'route.name === "talk" && route.id' in js and '"video:" + route.id' in js
