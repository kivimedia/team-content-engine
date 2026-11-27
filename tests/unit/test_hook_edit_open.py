"""The edit opens with the hook picked for the topic (T-25711). The moments writer is
stubbed; the shots are real (reels.shots_for over synthetic words)."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from tce.hooks import catalog, edit_open, library
from tce.production.creatorz import reels
from tce.settings import settings
from tests.unit.test_creatorz_style import tce_words

WS = uuid.UUID("00000000-0000-4000-8000-0000000257a4")
CID = "22222222-3333-4444-8555-666666666666"
WORDS = tce_words("80% of my clients rebook. Most owners never count who came back. That number is the job.")
KEEP = [[0.95, 3.6], [3.7, 7.6], [7.7, 9.6]]
P1 = {"id": "p1", "file": "p1.png", "note": "the rebook chart", "w": 40, "h": 70}


def shots():
    return reels.shots_for(KEEP, reels.engine_words(WORDS))


def run(coro):
    return asyncio.run(coro)


def writer(answer):
    prompts = []

    async def ask(prompt, system, schema, attempt):
        prompts.append(prompt)
        return {"moments": answer, "punchline": None}

    return ask, prompts


def tag(pick, word):
    return {"type": "tag", "text": "the fix:", "at": {"pick": pick, "word": word}}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path))
    return tmp_path


def test_the_topics_hook_is_found_from_the_newest_week(store):
    lineup = {"primary": [{"candidate_id": CID, "title": "x", "filmed": False}], "reserve": []}
    assert edit_open.hook_on(WS, CID) is None
    run(library.pick(WS, "2026-11-16", "whip-in", lineup))
    run(library.pick(WS, "2026-11-23", "big-number", lineup))
    assert edit_open.hook_on(WS, CID).id == "big-number"
    assert edit_open.hook_on(WS, "someone-else") is None and edit_open.hook_on(WS, None) is None


def test_the_writer_is_told_and_its_opening_is_kept_first():
    s = shots()
    first_line = s[0]["pick"]
    card = {"type": "card_stat", "text": "80%", "label": "clients rebook", "at": {"pick": first_line, "word": "80%"}}
    ask, prompts = writer([tag(s[1]["pick"], "Most"), card])
    got = run(reels.get_moments(s, "en", ask, hook=catalog.BY_ID["big-number"]))
    assert "visual hook “Big number”" in prompts[0] and "card_stat" in prompts[0].split("visual hook")[1]
    assert got["moments"][0]["type"] == "card_stat" and got["moments"][0]["text"] == "80%"
    assert got["opening"] == "Opens with Big number."


def test_big_number_is_put_in_by_rule_when_the_writer_forgets():
    s = shots()
    ask, _ = writer([tag(s[1]["pick"], "Most")])
    got = run(reels.get_moments(s, "en", ask, hook=catalog.BY_ID["big-number"]))
    first = got["moments"][0]
    assert first["type"] == "card_stat" and first["text"] == "80%" and first["at"]["pick"] == s[0]["pick"]
    assert got["opening"] == "Opens with Big number: 80%."


def test_whip_is_put_in_at_the_first_line():
    s = shots()
    ask, _ = writer([tag(s[1]["pick"], "Most")])
    got = run(reels.get_moments(s, "en", ask, hook=catalog.BY_ID["whip-in"]))
    assert got["moments"][0] == {"type": "whip", "at": {"pick": s[0]["pick"], "at": "start"}}
    assert got["opening"] == "Opens with Whip into the first line."


def test_proof_pop_uses_the_first_picture_and_says_so_without_one():
    s = shots()
    ask, prompts = writer([tag(s[1]["pick"], "Most")])
    got = run(reels.get_moments(s, "en", ask, pictures=[P1], hook=catalog.BY_ID["proof-pop"]))
    assert got["moments"][0]["type"] == "insert" and got["moments"][0]["picture"] == "p1"
    ask, prompts = writer([tag(s[1]["pick"], "Most")])
    got = run(reels.get_moments(s, "en", ask, hook=catalog.BY_ID["proof-pop"]))
    assert got["moments"][0]["type"] == "tag" and "no picture is attached" in got["opening"]
    assert "visual hook" not in prompts[0]


def test_no_number_said_early_goes_on_without_it():
    words = tce_words("Most owners never count who came back. That number is the job.")
    s = reels.shots_for([[0.95, 4.6], [4.7, 7.6]], reels.engine_words(words))
    ask, _ = writer([tag(s[0]["pick"], "Most")])
    got = run(reels.get_moments(s, "en", ask, hook=catalog.BY_ID["big-number"]))
    assert got["moments"][0]["type"] == "tag"
    assert got["opening"] == "The edit could not open with Big number: no number is said in the opening lines."


def test_a_hook_the_editor_cannot_draw_yet_is_named():
    s = shots()
    ask, prompts = writer([tag(s[1]["pick"], "Most")])
    got = run(reels.get_moments(s, "en", ask, hook=catalog.BY_ID["split-screen"]))
    assert "visual hook" not in prompts[0]
    assert got["opening"] == "The hook \u201cSplit screen: before and after\u201d is not drawn by the editor yet, so this edit opens without it."


def test_no_hook_changes_nothing():
    s = shots()
    ask, prompts = writer([tag(s[1]["pick"], "Most")])
    got = run(reels.get_moments(s, "en", ask))
    assert "opening" not in got and "visual hook" not in prompts[0]


def test_the_render_wires_the_hook():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "src/tce/api/routers/production.py").read_text(encoding="utf-8")
    assert "edit_open.hook_on(ws, candidate_id)" in src and "hook=hook" in src
    assert 'key = f"{key}-{hook.id}"' in src and "chosen_style is None" in src
    # T-25834: a hook the editor draws, or a trend format, asks for the Creatorz edit
    assert "(hook is not None and hook.id in edit_open.DRAWN) or fmt is not None" in src
