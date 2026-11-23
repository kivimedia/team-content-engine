"""The Book answers his taps with the chapter itself (23-Nov, wait-less item B9, part 1).

After a layout word, a write ask or an approve the page used to fetch the chapter again.
Each of those answers now carries the chapter exactly as GET /book/chapters/{n} draws it
(additive: every refusal is unchanged), so the page redraws from the answer. The
layout-first hold (423) and the narration budget (409 device_voice) refuse exactly as
before. Same app, record and fixtures as test_book.py; synthetic text only.
"""

from __future__ import annotations

from tests.unit.test_book import (  # noqa: F401 - the fixtures are used by name
    OWNER,
    api,
    editor,
    held,
)

HELD_WORDS = "Episode 12 is held: its layout has to be approved and the chapter written from it first"


def _get(api, n: int) -> dict:
    r = api.get(f"/api/v1/book/chapters/{n}", headers=OWNER)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_layout_word_and_a_write_ask_answer_with_the_chapter_as_the_get_draws_it(api, held):
    note = api.post("/api/v1/book/chapters/12/layout", headers=OWNER, json={"action": "note", "note": "Coaching first"})
    assert note.status_code == 200, note.text
    assert note.json()["chapter"] == _get(api, 12)
    assert note.json()["chapter"]["layout_notes"][-1]["text"] == "Coaching first"
    approve = api.post("/api/v1/book/chapters/12/layout", headers=OWNER, json={"action": "approve"}).json()
    # What the answer said before is still there, and the chapter beside it.
    assert approve["phase"] == "approved_unwritten" and approve["action"] == "approve"
    assert approve["chapter"] == _get(api, 12)
    assert approve["chapter"]["layout_status"] == "approved" and approve["chapter"]["phase"] == "approved_unwritten"
    # The held draft's text stays on the server in the answer too.
    assert approve["chapter"]["paragraphs"] == [] and approve["chapter"]["held_paragraphs"] == 2
    write = api.post("/api/v1/book/chapters/12/write", headers=OWNER, json={}).json()
    assert write["already"] is False and write["write_requested_at"]
    assert write["chapter"] == _get(api, 12) and write["chapter"]["write_requested_at"] == write["write_requested_at"]


def test_an_approve_answers_with_the_chapter_and_its_new_phase(api, editor):
    r = api.post("/api/v1/book/chapters/12/status", headers=OWNER, json={"status": "approved"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved" and body["status_words"] == "Approved" and body["at"]
    assert body["chapter"] == _get(api, 12)
    assert body["chapter"]["status"] == "approved" and body["chapter"]["phase"] == "approved"
    back = api.post("/api/v1/book/chapters/12/status", headers=OWNER, json={"status": "in_review"}).json()
    assert back["chapter"]["status"] == "in_review" and back["chapter"]["phase"] == "ready"


def test_the_refusals_are_the_ones_they_always_were(api, held, monkeypatch):
    # Nothing written for a refused tap, and no chapter in a refusal.
    r = api.post("/api/v1/book/chapters/12/write", headers=OWNER, json={})
    assert r.status_code == 422 and "chapter" not in r.json()
    r = api.post("/api/v1/book/chapters/12/status", headers=OWNER, json={"status": "approved"})
    assert r.status_code == 422 and "chapter" not in r.json()
    assert api.post("/api/v1/book/chapters/99/layout", headers=OWNER, json={"action": "approve"}).status_code == 404
    api.post("/api/v1/book/chapters/12/layout", headers=OWNER, json={"action": "approve"})
    # The layout-first hold: still 423, in the same words, after the tap.
    held_audio = api.get("/api/v1/book/chapters/12/audio/0", headers=OWNER)
    assert held_audio.status_code == 423 and held_audio.json()["detail"] == HELD_WORDS
    # The narration budget: still 409 with device_voice, nothing bought.
    called = []

    class Boom:
        def __init__(self, *a, **k):
            called.append(1)

    monkeypatch.setattr("tce.services.tts.TTSService", Boom)
    budget = api.get("/api/v1/book/chapters/1/audio/0", headers=OWNER)
    assert budget.status_code == 409 and budget.json()["device_voice"] is True
    assert budget.json()["detail"] == "Narration is not switched on yet, so this device reads it aloud."
    assert called == []
