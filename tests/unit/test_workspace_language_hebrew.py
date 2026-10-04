"""Per-workspace language (4-Oct): a Hebrew client workspace (Matan) gets Hebrew ASR,
right-to-left captions in a Hebrew font, Hebrew prompts and Hebrew-aware auto-edit.
Every owner workspace, and every workspace when TCE_WORKSPACE_LANGUAGES is empty,
behaves exactly as before. Synthetic data.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from tce.db import workspace_filter
from tce.db.workspace_filter import set_workspace_context
from tce.settings import settings


def workspace_language(*a):
    return workspace_filter.workspace_language(*a)

HE_WS = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
OWNER_WS = uuid.UUID("30c13a7e-432f-4c3a-bade-52483262d793")


@pytest.fixture
def hebrew_on(monkeypatch):
    monkeypatch.setattr(settings, "workspace_languages", f"{HE_WS}:he", raising=False)
    yield
    set_workspace_context(None)


@pytest.fixture
def unset(monkeypatch):
    monkeypatch.setattr(settings, "workspace_languages", "", raising=False)


# ---------------------------------------------------------------- 1. the setting


def test_every_workspace_is_english_when_the_setting_is_empty(unset):
    assert workspace_language(HE_WS) == "en"
    assert workspace_language(OWNER_WS) == "en"
    assert workspace_language(None) == "en"


def test_the_setting_names_the_hebrew_workspace_only(hebrew_on):
    assert workspace_language(HE_WS) == "he"
    assert workspace_language(str(HE_WS)) == "he"
    assert workspace_language(OWNER_WS) == "en"
    set_workspace_context(HE_WS)
    assert workspace_language() == "he"


def test_bad_entries_are_ignored(monkeypatch):
    monkeypatch.setattr(settings, "workspace_languages", f"nope:he, {HE_WS}:xx ,{OWNER_WS}", raising=False)
    assert workspace_filter.workspace_languages() == {}
    assert workspace_language(HE_WS) == "en"


# ---------------------------------------------------------------- 2. ASR


def test_qc_listen_asks_for_hebrew_only_in_the_hebrew_workspace(hebrew_on, monkeypatch, tmp_path):
    from tce.api.routers import production as prod

    asked: list = []

    async def fake_clip(path, a, b, **kw):
        asked.append(kw.get("language", "MISSING"))
        return {"words": [{"word": "שלום", "start": 0.0, "end": 0.4}]}

    monkeypatch.setattr(prod.settings, "production_qc_listen", True, raising=False)
    monkeypatch.setattr(prod.settings, "production_transcribe_ws_url", "ws://x", raising=False)
    monkeypatch.setattr(prod.settings, "production_transcribe_language", "", raising=False)
    monkeypatch.setattr(prod.media, "transcribe_clip", fake_clip)
    asyncio.run(prod._qc_listen(tmp_path / "x.mp4", 1.0, ws=HE_WS))
    asyncio.run(prod._qc_listen(tmp_path / "x.mp4", 1.0, ws=OWNER_WS))
    asyncio.run(prod._qc_listen(tmp_path / "x.mp4", 1.0))
    assert asked == ["he", None, None]


def test_first_transcription_is_asked_in_hebrew_for_the_hebrew_workspace(hebrew_on, monkeypatch):
    from tce.api.routers import production as prod

    asked: dict = {}

    class Row:
        storage_path, duration_s = "/nowhere.mp4", 3.0

    class Ctx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *a):
            return False

    async def load(s, upload_id, ws):
        return Row()

    async def transcribe_local(path, **kw):
        asked[kw.get("language", "MISSING")] = True
        raise RuntimeError("stop here")

    async def status(*a, **k):
        return None

    monkeypatch.setattr(prod.settings, "production_transcribe_language", "", raising=False)
    monkeypatch.setattr(prod, "session_factory", lambda: (lambda: Ctx()))
    monkeypatch.setattr(prod, "_load", load)
    monkeypatch.setattr(prod, "_set_status", status)
    monkeypatch.setattr(prod.media, "transcribe_local", transcribe_local)
    asyncio.run(prod._run_transcription(uuid.uuid4(), HE_WS, "a"))
    asyncio.run(prod._run_transcription(uuid.uuid4(), OWNER_WS, "b"))
    assert asked == {"he": True, None: True}


def test_second_listen_treats_a_hebrew_workspace_as_hebrew(hebrew_on):
    from tce.api.routers import production as prod

    hebrew = [{"text": "שלום"}, {"text": "לכולם"}]
    english = [{"text": "hello"}, {"text": "everyone"}]
    assert prod._main_language(HE_WS, hebrew) == "he"
    assert prod._main_language(OWNER_WS, english) == "en"
    assert prod._main_language(OWNER_WS, hebrew) == "other"  # as before
    assert prod._clip_language(HE_WS) == {"language": "he"}
    assert prod._clip_language(OWNER_WS) == {}


def test_a_hebrew_stretch_heard_again_is_never_tagged_as_another_language():
    from tce.production import relisten

    words = [{"text": t, "start_s": i * 0.4, "end_s": i * 0.4 + 0.3, "precision": "word"}
             for i, t in enumerate("אני רוצה לספר לכם משהו".split())]
    wins = [relisten.Window(0.0, 2.0, 0, len(words) - 1, ["test"], [(0, 4)])]
    heard = [{"words": [], "language": "he", "language_probability": 0.99} for _ in wins]
    out, _report = relisten.merge(words, wins, heard, main_language="he")
    assert not any(w.get("lang") for w in out)


# ---------------------------------------------------------------- 3. captions

pytest.importorskip("PIL")


def timed(text: str, start: float, step: float = 0.3) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start": round(t, 3), "end": round(t + step - 0.05, 3)})
        t += step
    return out


def test_hebrew_words_are_drawable_only_with_the_hebrew_font():
    from tce.production import wordbox

    words = timed("שלום לכולם, מה שלומכם?", 0.0)
    assert not wordbox.usable(words)  # the English path still falls back, as before
    assert wordbox.usable(words, language="he")
    assert wordbox.usable(timed("AI זה 2026", 0.0), language="he")
    assert wordbox.font_path("he").name.startswith("Heebo")
    assert wordbox.font_path("he").exists()
    assert wordbox.font_path("en") == wordbox.FONT_PATH


def test_hebrew_fillers_leave_the_captions_only_in_the_hebrew_workspace():
    from tce.production import wordbox

    words = timed("אה אז אממ ככה", 0.0)
    assert [w["text"] for p in wordbox.pages(words, language="he") for w in p.words] == ["אז", "ככה"]
    assert len([w for p in wordbox.pages(words) for w in p.words]) == 4


def test_a_hebrew_line_is_laid_out_right_to_left():
    from tce.production import wordbox

    page = wordbox.pages(timed("אני רוצה לספר", 0.0), language="he")[0]
    layout = wordbox._Layout(1080, 1920, language="he")
    _size, placed = layout.place(page)
    xs = [x for x, _y, _w in placed if _y == placed[0][1]]
    assert xs == sorted(xs, reverse=True)  # the first word said is the rightmost


def test_the_english_layout_is_unchanged():
    from tce.production import wordbox

    page = wordbox.pages(timed("We had to jump through", 0.0))[0]
    a = wordbox._Layout(1080, 1920).place(page)
    b = wordbox._Layout(1080, 1920, language="en").place(page)
    assert a == b
    xs = [x for x, y, _w in a[1] if y == a[1][0][1]]
    assert xs == sorted(xs)


def test_a_hebrew_caption_band_draws(tmp_path):
    from PIL import Image

    from tce.production import wordbox

    pages = wordbox.pages(timed("שלום לכולם, מה שלומכם?", 0.0), language="he")
    band = wordbox.render_band(pages, 1080, 1920, tmp_path, 3.0, language="he")
    pngs = sorted(Path(tmp_path).glob("p0000-w*.png"))
    assert band["states"] >= 2 and pngs
    img = Image.open(pngs[0])
    assert img.getbbox() is not None  # something was drawn


# ---------------------------------------------------------------- 4. prompts


def _req(ws, system="You write posts.", version="v1"):
    from tce.llm import LLMRequest

    return LLMRequest(job_type="t", agent_name="a", messages=[{"role": "user", "content": "x"}],
                      system=system, prompt_version=version, workspace_id=ws)


def test_every_prompt_in_the_hebrew_workspace_asks_for_spoken_israeli_hebrew(hebrew_on):
    from tce.llm.provider import localize_request

    req = localize_request(_req(HE_WS))
    assert "Israeli Hebrew" in req.system and req.system.startswith("You write posts.")
    assert req.prompt_version == "v1.he"
    again = localize_request(req)  # a replayed job is not suffixed twice
    assert again.system == req.system and again.prompt_version == req.prompt_version


def test_owner_prompts_are_byte_for_byte_unchanged(hebrew_on, monkeypatch):
    from tce.llm.provider import localize_request

    for ws in (OWNER_WS, None):
        req = _req(ws)
        assert localize_request(req) is req
    monkeypatch.setattr(settings, "workspace_languages", "", raising=False)
    req = _req(HE_WS)
    assert localize_request(req) is req


def test_the_queue_stores_the_hebrew_prompt(hebrew_on):
    import inspect

    from tce.llm import queue

    assert "localize_request" in inspect.getsource(queue.enqueue)


def test_jennifer_review_in_hebrew_drops_the_english_only_rules():
    from tce.production import autoedit, qc

    en = autoedit.review_system(["Maple"])
    assert en == autoedit.review_system(["Maple"], language="en")
    assert "speaks English with an Israeli accent" in en and "NOT ENGLISH" in en
    he = autoedit.review_system(["Maple"], language="he")
    assert "English with an Israeli accent" not in he and "NOT ENGLISH" not in he
    assert "Hebrew" in he
    en_q = qc.asides_system(["Maple"])
    assert en_q == qc.asides_system(["Maple"], language="en")
    he_q = qc.asides_system(["Maple"], language="he")
    assert "English with an Israeli accent" not in he_q and "Hebrew" in he_q


def test_review_request_follows_the_workspace_language():
    from tce.api.routers import production as prod

    words = [{"text": "שלום", "start_s": 0.0, "end_s": 0.3, "precision": "word"}]
    _p, system_he = prod._review_request(words, "", language="he")
    _p, system_en = prod._review_request(words, "")
    assert "NOT ENGLISH" not in system_he and "NOT ENGLISH" in system_en


# ---------------------------------------------------------------- 5. auto-edit


def said(text: str, start: float, step: float = 0.3) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start_s": round(t, 3), "end_s": round(t + step - 0.05, 3),
                    "precision": "word"})
        t += step
    return out


def test_hebrew_fillers_are_cut_only_in_the_hebrew_workspace():
    from tce.production.retakes import plan_edit

    words = said("אז אה אנחנו מתחילים.", 0.0)
    he = plan_edit(words, [], language="he")
    en = plan_edit(words, [])
    assert he["stats"]["fillers"] == 1 and "אה" not in he["kept_text"]
    assert en["stats"]["fillers"] == 0


def test_a_hebrew_retake_keeps_the_complete_take():
    from tce.production.retakes import plan_edit

    words = said("אני רוצה לספר לכם על", 0.0) + said("אני רוצה לספר לכם על הלקוח החדש שלי.", 4.0)
    plan = plan_edit(words, [], language="he")
    assert plan["kept_text"] == "אני רוצה לספר לכם על הלקוח החדש שלי."


def test_common_hebrew_words_are_not_content():
    from tce.production import retakes

    with retakes.language_scope("he"):
        assert retakes.lost_content_words("לא אז כן רק עוד אבל", "") == []
    assert retakes.lost_content_words("לא אז כן רק עוד אבל", "") != []  # English path as before
