"""Matan's news anchors (5-Oct): a performer workspace matches the event industry and
mentalism, never Ziv's vendors; owner workspaces build exactly what they built before.
Synthetic data only.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tce.editorial import idea_lane
from tce.editorial import status as job_status
from tce.models.editorial import EvidenceSource
from tce.news.anchors import build_anchor_index
from tce.news.matcher import match_item
from tce.settings import settings

MATAN = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
OWNERS = (
    uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f"),
    uuid.UUID("30c13a7e-432f-4c3a-bade-52483262d793"),
)
NOW = datetime(2026, 10, 5, 12, 0, 0)

ZIV_VENDOR_SETTINGS = SimpleNamespace(
    model_fields={"twilio_api_key": None, "vercel_access_token": None, "zoho_api_key": None,
                  "writer_model": None},
    writer_model="claude-opus-5",
)


@pytest.fixture
def lanes_on(monkeypatch):
    monkeypatch.setattr(settings, "workspace_lane_profiles", f"{MATAN}:performer", raising=False)


@pytest.fixture
def lanes_off(monkeypatch):
    monkeypatch.setattr(settings, "workspace_lane_profiles", "", raising=False)


async def _commit(session, ws, repo="kivimedia/km-florist-receptionist"):
    session.add(EvidenceSource(
        workspace_id=ws, source_kind="github_commit_group", external_id=f"g-{uuid.uuid4()}",
        title="commits", occurred_at=NOW - timedelta(days=3), version_hash="c" * 64,
        fetch_status="ok", payload_private={"repo": repo}, meta={},
    ))
    await session.flush()


async def _build(session, ws, **kw):
    _r, anchors = await build_anchor_index(
        session, ws, settings_obj=ZIV_VENDOR_SETTINGS, dry_run=True, now=NOW, **kw
    )
    return anchors


def _rows(anchors):
    return [(a.kind, a.term, a.origin_kind, a.origin_ref, a.weight) for a in anchors]


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------


async def test_matan_gets_performer_anchors_and_none_of_zivs_vendors(editorial_session, lanes_on):
    await _commit(editorial_session, MATAN)
    anchors = await _build(editorial_session, MATAN)
    terms = {a.normalized for a in anchors}
    for wanted in ("mentalism", "bar mitzvah", "corporate event", "team building",
                   "penn teller", "trade show", "immersive experience", "hanukkah", "purim",
                   "בר מצווה", "מנטליסט"):
        assert wanted in terms, f"{wanted} missing from Matan's anchors"
    for banned in ("twilio", "vercel", "zoho", "claude opus 5", "km florist receptionist",
                   "prompt caching", "whatsapp business"):
        assert banned not in terms, f"Ziv's {banned} leaked into Matan's anchors"
    assert {a.kind for a in anchors} <= {"client_solution", "problem_pattern"}
    assert all(a.origin_ref == "news-anchors-performer.md" for a in anchors)


@pytest.mark.parametrize("owner", OWNERS)
async def test_owner_index_is_identical_with_profiles_on(editorial_session, monkeypatch, owner):
    await _commit(editorial_session, owner)
    monkeypatch.setattr(settings, "workspace_lane_profiles", "", raising=False)
    before = _rows(await _build(editorial_session, owner))
    monkeypatch.setattr(settings, "workspace_lane_profiles", f"{MATAN}:performer", raising=False)
    after = _rows(await _build(editorial_session, owner))
    assert after == before
    terms = {r[1] for r in after}
    assert {"twilio", "prompt caching", "km-florist-receptionist"} <= terms
    assert "mentalism" not in terms


async def test_an_explicit_curated_path_still_wins_for_matan(editorial_session, lanes_on, tmp_path):
    f = tmp_path / "x.md"
    f.write_text("## client_solution\n- escape rooms\n", encoding="utf-8")
    anchors = await _build(editorial_session, MATAN, curated_path=f)
    assert [a.term for a in anchors] == ["escape rooms"]


# ---------------------------------------------------------------------------
# The matcher on his feeds' real shapes
# ---------------------------------------------------------------------------

RELEVANT = [
    ("How Mentalist Oz Pearlman Keeps a Corporate Crowd on the Edge of Their Seats", ""),
    ("10 Team Building Ideas Planners Are Booking for Q4", ""),
    ("Bar Mitzvah Trends: Interactive Entertainment Replaces the DJ Set", ""),
    ("Immersive Experience Opens in London With Live Actors", "An immersive experience..."),
    ("Penn & Teller Return to Las Vegas", ""),
    ("Trade Show Booths Lean on Brand Activations", ""),
]
JUNK = [
    ("Six Flags Magic Mountain unveils solar carport", "The park adds a solar carport."),
    ("Cuddly starry night Totoro and other Ghibli blankets", "Keep cozy."),
    ("37 Cute Pumpkin Nails for Fall 2026", ""),
    ("Recipe Friday: Potato Cannoli", ""),
    ("Aquarium welcomes 7 baby African penguins", ""),
    ("The magic of autumn decor in three rooms", ""),
]


async def _matan_anchors(editorial_session):
    return [SimpleNamespace(id=None, kind=a.kind, term=a.term, normalized_term=a.normalized,
                            weight=a.weight) for a in await _build(editorial_session, MATAN)]


async def test_event_industry_items_match_for_matan(editorial_session, lanes_on):
    anchors = await _matan_anchors(editorial_session)
    for title, summary in RELEVANT:
        res = match_item(title=title, summary=summary, anchors=anchors)
        assert res.matched, f"{title!r}: {res.why()}"


async def test_junk_never_matches_for_matan(editorial_session, lanes_on):
    anchors = await _matan_anchors(editorial_session)
    for title, summary in JUNK:
        res = match_item(title=title, summary=summary, anchors=anchors)
        assert not res.matched, f"{title!r} matched: {res.why()}"


# ---------------------------------------------------------------------------
# "research 3 clip ideas"
# ---------------------------------------------------------------------------


def test_research_kinds_know_the_three_lanes():
    for k in ("trend_reaction", "magic_clip", "behind_scenes"):
        assert k in idea_lane.KINDS
    assert idea_lane.KIND_SOURCES["magic_clip"] == ("curated_clip",)
    assert idea_lane.KIND_SOURCES["behind_scenes"] == ("story_seed",)
    # owner kinds untouched
    assert idea_lane.KIND_SOURCES["coaching"] == ("fathom_meeting",)
    assert idea_lane.KIND_SOURCES["build"] == ("github_commit_group",)


def test_kinds_for_a_workspace(lanes_on):
    assert idea_lane.kinds_for(OWNERS[0]) == ("any", "news", "coaching", "build")
    assert set(idea_lane.kinds_for(MATAN)) >= {"any", "trend_reaction", "magic_clip",
                                               "behind_scenes"}


async def _src(sm, ws, kind, age_days):
    async with sm() as s:
        src = EvidenceSource(
            workspace_id=ws, source_kind=kind, external_id=f"{kind}-{uuid.uuid4()}",
            title=f"{kind} item", occurred_at=idea_lane._now() - timedelta(days=age_days),
            version_hash="d" * 64, fetch_status="ok", payload_private={}, meta={},
        )
        s.add(src)
        await s.commit()
        # created_at is the window's column; age it the same way
        src.created_at = idea_lane._now() - timedelta(days=age_days)
        await s.commit()
        return src.id


async def test_three_clip_ideas_read_his_curated_clips_even_old_ones(
    editorial_sessionmaker, monkeypatch, lanes_on
):
    from tce.editorial import selector

    clip = await _src(editorial_sessionmaker, MATAN, "curated_clip", 90)
    await _src(editorial_sessionmaker, MATAN, "story_seed", 1)
    seen: dict = {}

    async def fake_select(sm, w, week, **kw):
        seen.update(kw)
        return SimpleNamespace(status="complete", detail="", rejected=[], candidates=[
            {"id": str(uuid.uuid4()), "title": "קליפ 1"}])

    monkeypatch.setattr(selector, "select_candidates", fake_select)
    run_id = uuid.uuid4()
    job_status.start(MATAN, idea_lane.KIND_RESEARCH, str(run_id), "Starting")
    await idea_lane.run_idea_research(editorial_sessionmaker, MATAN, run_id, topic=None,
                                      count=3, kind="magic_clip")
    run = job_status.get(MATAN, idea_lane.KIND_RESEARCH, str(run_id))
    assert run["state"] == "done", run
    assert seen["source_ids"] == [clip], "clip ideas read clips, evergreen, not seeds"
    assert seen["max_candidates"] == 3
    assert "clips" in run["said"]


async def test_trend_reaction_without_topic_seeds_from_his_profile(
    editorial_sessionmaker, lanes_on
):
    queries: list[str] = []

    class Search:
        api_key = "k"

        async def search(self, query, count=10, freshness=None, *, raise_errors=False):
            queries.append(query)
            return []

    run_id = uuid.uuid4()
    job_status.start(MATAN, idea_lane.KIND_RESEARCH, str(run_id), "Starting")
    await idea_lane.run_idea_research(editorial_sessionmaker, MATAN, run_id, topic=None,
                                      count=3, kind="trend_reaction", search=Search())
    run = job_status.get(MATAN, idea_lane.KIND_RESEARCH, str(run_id))
    assert run["state"] == "done", run
    assert queries, "no search ran: he has no calls or commits, the profile seeds it"
    assert "found nothing to start from" not in run["said"]


async def test_owner_asking_for_a_lane_kind_reads_nothing_new(editorial_sessionmaker, lanes_on):
    """An owner never has lane kinds; asking for one falls back to his 'any'."""
    run_id = uuid.uuid4()
    ws = OWNERS[0]
    job_status.start(ws, idea_lane.KIND_RESEARCH, str(run_id), "Starting")

    class NoKey:
        api_key = ""

    await idea_lane.run_idea_research(editorial_sessionmaker, ws, run_id, topic="x",
                                      count=3, kind="magic_clip", search=NoKey())
    run = job_status.get(ws, idea_lane.KIND_RESEARCH, str(run_id))
    assert "no search key" in run["said"], run


# Review 5-Oct: "israel" / "tel aviv" as one-hit anchors pulled war and politics
# headlines into a mentalist's trend lane. A place name alone is never a match.
WAR_AND_POLITICS = [
    ("Israeli airstrike hits Gaza as ceasefire talks stall", "Israel's military said..."),
    ("Rockets fired at Tel Aviv overnight", "Sirens sounded across central Israel."),
    ("Israel election: coalition talks collapse", "The Knesset votes next week."),
]


async def test_war_and_politics_never_match_for_matan(editorial_session, lanes_on):
    anchors = await _matan_anchors(editorial_session)
    for title, summary in WAR_AND_POLITICS:
        res = match_item(title=title, summary=summary, anchors=anchors)
        assert not res.matched, f"{title!r} matched: {res.why()}"


async def test_israeli_event_news_still_matches_for_matan(editorial_session, lanes_on):
    anchors = await _matan_anchors(editorial_session)
    res = match_item(title="Tel Aviv corporate events go immersive this Hanukkah",
                     summary="Israeli companies book interactive entertainment.", anchors=anchors)
    assert res.matched, res.why()


# A holiday name alone is a recipe or a news story; his season is the holiday
# TOGETHER with the entertainment around it.
HOLIDAY_JUNK = [
    ("The best Hanukkah latke recipe for crispy edges", "Grate the potatoes and squeeze them dry."),
    ("Purim costume ideas for toddlers", "Simple DIY costumes from things at home."),
    ("Chanukah candle lighting times 2026", "Light the first candle after sunset."),
]


async def test_holiday_name_alone_never_matches_for_matan(editorial_session, lanes_on):
    anchors = await _matan_anchors(editorial_session)
    for title, summary in HOLIDAY_JUNK:
        res = match_item(title=title, summary=summary, anchors=anchors)
        assert not res.matched, f"{title!r} matched: {res.why()}"


async def test_holiday_season_entertainment_matches_for_matan(editorial_session, lanes_on):
    anchors = await _matan_anchors(editorial_session)
    res = match_item(title="Purim parties bring back the performer",
                     summary="Hosts plan the holiday early this year.", anchors=anchors)
    assert res.matched, res.why()
