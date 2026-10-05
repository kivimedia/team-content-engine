"""Ziv's decisions of 5-Oct for Matan's workspace (feat/matan-tce-integrated).

1. Five ideas offered per lane each week (15), cap 15, the lanes weighted equally.
2. At least five videos recorded a week: the performer default and the seed are 5, and
   the week never caps him at 5 when he records more.
3. Publishing is his own: he downloads the finished video and copies the post text.
   TCE writes his posts with HIS writer, never posts or exports for him, and every
   refusal shown to him is Hebrew. (The screens: test_matan_post_card_screens.py.)
4. His week-1 feedback is in the performer lane guidance, and a gadget-tech trend that
   is not about a live performer is rejected in code.
5. The Genii feed (trick reviews) is out of his trend lane seed, and --apply retires it.
6. His login has no microphone and no "Back to KM BOT" link (both leave his fence).

Synthetic keys and an in-memory database; the live database is never touched.
"""

from __future__ import annotations

import importlib.util
import io
import re
import uuid
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tce.settings import settings

ROOT = Path(__file__).resolve().parents[2]
MATAN = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
ZIV_WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
ZIV_WS_2 = uuid.UUID("30c13a7e-432f-4c3a-bade-52483262d793")
OWNER_KEY = "owner-key-" + uuid.uuid4().hex
MATAN_KEY = "matan-key-" + uuid.uuid4().hex
HEBREW = re.compile(r"[֐-׿]")


@pytest.fixture
def lanes(monkeypatch):
    monkeypatch.setattr(settings, "workspace_lane_profiles", f"{MATAN}:performer", raising=False)
    monkeypatch.setattr(settings, "workspace_languages", f"{MATAN}:he", raising=False)
    monkeypatch.setattr(settings, "owner_workspace_ids", "", raising=False)
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(ZIV_WS), raising=False)


def _seed_module():
    spec = importlib.util.spec_from_file_location("seed_matan_lanes", ROOT / "scripts" / "seed_matan_lanes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ 1. five per lane


def test_the_performer_week_offers_five_ideas_in_every_lane():
    from tce.editorial.lane_profile import PERFORMER

    assert {lane.key: lane.target for lane in PERFORMER.lanes} == {
        "trend_reaction": 5, "magic_clip": 5, "behind_scenes": 5,
    }
    assert PERFORMER.max_candidates == 15 and PERFORMER.weekly_target == 15


def test_a_full_week_keeps_five_of_each_lane():
    from tce.editorial.lane_profile import PERFORMER, fill_lane_mix

    cands = [
        {"lane": lane, "rank_score": score, "title": f"{lane}-{i}"}
        for lane, score in (("trend_reaction", 0.9), ("magic_clip", 0.5), ("behind_scenes", 0.7))
        for i in range(8)
    ]
    kept, cut = fill_lane_mix(cands, PERFORMER, PERFORMER.max_candidates)
    counts = {}
    for c in kept:
        counts[c["lane"]] = counts.get(c["lane"], 0) + 1
    assert counts == {"trend_reaction": 5, "magic_clip": 5, "behind_scenes": 5}
    assert len(cut) == 9


def test_his_whole_week_run_asks_for_fifteen_and_the_owner_cap_stays_six(lanes):
    from tce.api.routers.content_runs import _max_candidates_for
    from tce.editorial.selector import MAX_CANDIDATES_CAP

    run = SimpleNamespace(workspace_id=MATAN, scope_kind="window", maximum_candidate_count=6)
    assert _max_candidates_for(run, []) == 15
    owner = SimpleNamespace(workspace_id=ZIV_WS, scope_kind="window", maximum_candidate_count=6)
    assert _max_candidates_for(owner, []) == 6
    assert MAX_CANDIDATES_CAP == 6


# ------------------------------------------------------------------ 2. five a week, never capped


def test_the_seed_and_the_performer_default_are_five_videos_a_week():
    from tce.editorial.lane_profile import PERFORMER

    assert _seed_module().VIDEOS_PER_WEEK == 5
    assert PERFORMER.videos_per_week == 5


async def test_his_week_defaults_to_five_and_the_owners_to_three(editorial_session, lanes):
    from tce.editorial import lineup

    assert await lineup.videos_per_week(editorial_session, MATAN) == 5
    assert await lineup.videos_per_week(editorial_session, ZIV_WS) == lineup.DEFAULT_PRIMARY_SLOTS == 3


async def test_recording_more_than_five_is_never_capped(editorial_session, lanes):
    from tce.editorial import lineup
    from tce.models.editorial import TopicCandidate

    await lineup.set_videos_per_week(editorial_session, MATAN, 5)
    week = await lineup.ensure_lineup(editorial_session, MATAN, lineup.week_start_for(None))
    assert week.primary_slots == 5
    for i in range(7):
        cand = TopicCandidate(
            workspace_id=MATAN, week_start=week.week_start, moment_ids=["m"], title=f"רעיון {i}",
            lesson="l", audience="a", public_angle="p", gates={}, status="selected",
        )
        editorial_session.add(cand)
        await editorial_session.flush()
        item = await lineup.add_topic(editorial_session, MATAN, week, cand, slot="primary")
        assert item.slot == "primary"
    data = await lineup.lineup_to_json(editorial_session, MATAN, week)
    assert len(data["primary"]) == 7 and data["over_by"] == 2


# ------------------------------------------------------------------ 3. his posts, by his hand


@pytest.fixture
def app_client(monkeypatch, lanes, editorial_sessionmaker):
    from tce.api.app import create_app
    from tce.api.routers import editorial as editorial_router
    from tce.api.routers import production as prod
    from tce.db.session import get_db

    monkeypatch.setattr(settings, "private_access_key", SecretStr(OWNER_KEY))
    monkeypatch.setattr(settings, "editor_workspace_keys", SecretStr(f"{MATAN_KEY}:{MATAN}"))
    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    app = create_app()

    async def _db():
        async with editorial_sessionmaker() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: editorial_sessionmaker
    return TestClient(app, raise_server_exceptions=False)


HIS = {"X-TCE-Editor-Key": MATAN_KEY}
ANY = str(uuid.uuid4())


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (f"/api/v1/production/uploads/{ANY}/publishing/publish", {"platforms": ["instagram"]}),
        (f"/api/v1/production/packets/{ANY}/export", None),
    ],
)
def test_posting_and_export_are_refused_to_him_in_hebrew(app_client, path, body):
    r = app_client.post(path, headers=HIS, **({"json": body} if body else {}))
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert HEBREW.search(detail) and "owner" not in detail.lower(), detail


def test_his_script_button_reaches_his_own_lane_writer(app_client):
    # Not refused as owner-only: the route goes on to look the idea up (and
    # build_packet sends a lane workspace to editorial.lane_packets).
    r = app_client.post(f"/api/v1/editorial/candidates/{ANY}/packet", headers=HIS)
    assert r.status_code == 404, r.text


def test_writing_his_posts_is_allowed_through_his_writer(app_client):
    r = app_client.post(f"/api/v1/production/uploads/{ANY}/publishing/draft", headers=HIS)
    # Not the owner-only 409: the route looks the video up.
    assert r.status_code == 404, r.text


async def _edited_upload(sm, ws=MATAN):
    from tce.models.editorial import RecordingUpload, TopicCandidate

    async with sm() as s:
        cand = TopicCandidate(workspace_id=ws, week_start=datetime(2026, 10, 5), moment_ids=["m"], title="קסם",
                              lesson="l", audience="a", public_angle="p", gates={}, status="recorded")
        s.add(cand)
        await s.flush()
        up = RecordingUpload(workspace_id=ws, candidate_id=cand.id, original_filename="w.mp4",
                             storage_path="/tmp/w.mp4", sha256=uuid.uuid4().hex * 2, status="edited",
                             edited_path="/tmp/w-edited.mp4",
                             transcript=[{"text": "שלום", "start_s": 0.0, "end_s": 0.5, "precision": "word"}],
                             edit_plan={"keep": [[0.0, 1.0]]})
        s.add(up)
        await s.commit()
        return up.id


async def test_a_lane_workspace_with_no_voice_of_its_own_never_gets_the_owner_writer(
    editorial_sessionmaker, monkeypatch, lanes
):
    from tce.api.routers import production as prod

    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)

    async def no_persona(ws, db=None):
        return None

    async def never(*a, **k):
        raise AssertionError("the owner's post writer must never run for a lane workspace")

    monkeypatch.setattr(prod, "_persona", no_persona)
    monkeypatch.setattr(prod, "_ask", never)
    uid = await _edited_upload(editorial_sessionmaker)
    await prod.draft_posts(uid, MATAN)
    async with editorial_sessionmaker() as s:
        assert await prod._publications(s, MATAN, uid) == {}


def test_a_finished_edit_starts_his_own_post_writer(lanes, monkeypatch):
    from tce.api.routers import production as prod

    spawned = []

    def fake_spawn(coro):
        spawned.append(coro)
        coro.close()

    monkeypatch.setattr(prod, "_spawn", fake_spawn)
    for ws in (MATAN, ZIV_WS, ZIV_WS_2):
        prod.start_draft_posts(uuid.uuid4(), ws)
    assert len(spawned) == 3


async def test_his_library_says_he_posts_by_hand_in_hebrew_and_the_owners_does_not(editorial_session, lanes):
    from tce.editorial import library

    his = await library.list_library(editorial_session, MATAN)
    assert HEBREW.search(his["post_by_hand"]), his
    for ws in (ZIV_WS, ZIV_WS_2):
        assert "post_by_hand" not in await library.list_library(editorial_session, ws)


def test_his_refusal_text_is_hebrew_and_an_english_lane_workspace_keeps_english(lanes, monkeypatch):
    from fastapi import HTTPException

    from tce.api.private_access import refuse_lane_workspace

    with pytest.raises(HTTPException) as he:
        refuse_lane_workspace(MATAN, "Posting", "פרסום")
    assert he.value.status_code == 409 and HEBREW.search(he.value.detail)
    monkeypatch.setattr(settings, "workspace_languages", "", raising=False)
    with pytest.raises(HTTPException) as en:
        refuse_lane_workspace(MATAN, "Posting", "פרסום")
    assert "owner" in en.value.detail.lower() and not HEBREW.search(en.value.detail)
    for ws in (ZIV_WS, ZIV_WS_2, None):
        assert refuse_lane_workspace(ws, "Posting", "פרסום") is None


# ------------------------------------------------------------------ 4. his week-1 feedback


def test_the_performer_guidance_carries_his_week_one_picks():
    from tce.editorial.lane_profile import PERFORMER

    text = PERFORMER.system_prompt + " ".join(lane.guidance for lane in PERFORMER.lanes)
    for must in (
        "behind_scenes is his strongest lane",
        "audience participation",
        "small, intimate events",
        "gadget",
        "not about a live performer",
        "psychological-manipulation stunt",
        "Derren Brown",
    ):
        assert must in text, must


@pytest.mark.parametrize(
    "title",
    [
        "רובוט שמצייר את האורחים",
        "הרובוטים מגיעים לחתונות",
        "AI sketch robot is the new wedding favour",
        "אפליקציית בינה מלאכותית שמחליפה את הצלם",
        "Drone light shows replace fireworks at weddings",
    ],
)
def test_a_gadget_tech_trend_is_rejected(title):
    from tce.editorial.lane_profile import PERFORMER, lane_check

    raw = {"lane": "trend_reaction", "title": title, "lesson": "טרנד חדש", "public_angle": "מה אני חושב"}
    got = lane_check(PERFORMER, raw, ["news_item", "standing_fact"])
    assert got is not None and got[1] == "gadget_tech_trend", (title, got)
    assert got[0] == "relevant_to_israeli_events_or_mentalism"


@pytest.mark.parametrize(
    "title",
    [
        "הקהל כבר לא רוצה לשבת ולראות",
        "אירועים קטנים, קסם קרוב",
        "מנטליסט מול בינה מלאכותית: מי קורא מחשבות טוב יותר?",
    ],
)
def test_participation_intimate_and_performer_trends_pass(title):
    from tce.editorial.lane_profile import PERFORMER, lane_check

    raw = {"lane": "trend_reaction", "title": title, "lesson": "הקהל רוצה להשתתף", "public_angle": "מה אני חושב"}
    assert lane_check(PERFORMER, raw, ["news_item", "standing_fact"]) is None


def test_the_gadget_gate_is_only_for_the_trend_lane():
    from tce.editorial.lane_profile import PERFORMER, lane_check

    raw = {"lane": "magic_clip", "title": "רובוט קוסם בטלוויזיה", "lesson": "l", "public_angle": "p"}
    assert lane_check(PERFORMER, raw, ["curated_clip"]) is None


# ------------------------------------------------------------------ 5. no Genii


def test_genii_is_out_of_his_trend_seed_and_apply_retires_it():
    seed = _seed_module()
    urls = [url for _n, url, *_ in seed.FEEDS]
    assert not any("geniimagazine" in u for u in urls)
    genii = SimpleNamespace(url="https://geniimagazine.com/feed/", name="Genii Magazine (magic)", enabled=True)
    other = SimpleNamespace(url="https://www.bizbash.com/rss.xml", name="BizBash (US events)", enabled=True)
    assert seed.retire_feeds({genii.url: genii, other.url: other}) == ["Genii Magazine (magic)"]
    assert genii.enabled is False and other.enabled is True
    assert seed.retire_feeds({genii.url: genii}) == []  # already off: nothing to do


def test_his_weekly_schedule_goes_to_drafting():
    seed = _seed_module()
    out = io.StringIO()
    with redirect_stdout(out):
        seed.print_live_steps(str(MATAN))
    weekly = next(line for line in out.getvalue().splitlines() if "weekly-content" in line)
    assert '"final_stage":"drafting"' in weekly


# ------------------------------------------------------------------ 6. no mic, no KM BOT link


@pytest.fixture
def pages(monkeypatch):
    from fastapi import FastAPI

    from tce.api import dashboard
    from tce.api.private_access import ScopedEditorGuard

    monkeypatch.setattr(settings, "private_access_key", SecretStr(OWNER_KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(ZIV_WS))
    monkeypatch.setattr(settings, "editor_workspace_keys", SecretStr(f"{MATAN_KEY}:{MATAN}"))

    async def enabled():
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)
    app = FastAPI()
    app.include_router(dashboard.router)
    app.add_middleware(ScopedEditorGuard)
    return TestClient(app)


@pytest.mark.parametrize("language", ["he", "en"])
@pytest.mark.parametrize("path", ["/record", "/today", "/library"])
def test_his_login_hides_the_microphone_and_the_km_bot_link(pages, monkeypatch, path, language):
    monkeypatch.setattr(settings, "workspace_languages", f"{MATAN}:{language}" if language == "he" else "")
    html = pages.get(path, headers=HIS).text
    hide = re.search(r"<style id=\"tce-scoped\">([^<]*)</style>", html)
    assert hide, html[:400]
    for sel in (".kmbot-link", "#talkHeader", "#talkFab"):
        assert sel in hide.group(1)
    assert "window.TCE_SCOPED = true" in html
