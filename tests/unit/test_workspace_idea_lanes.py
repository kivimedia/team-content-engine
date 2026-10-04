"""Per-workspace idea lanes (5-Oct): Matan's three lanes, a weekly mix of ten, and
owner workspaces that behave byte-for-byte as before. Synthetic data only.
"""

from __future__ import annotations

import copy
import os
import stat
import subprocess
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

import tce.llm
from tce.editorial import lane_profile, lineup, selector
from tce.llm import LLMResult
from tce.models.editorial import (
    REJECTION_GATES,
    SOURCE_KINDS,
    EvidenceMoment,
    EvidenceSource,
    TopicCandidate,
)
from tce.settings import settings

MATAN = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
OWNER = uuid.UUID("3e8c3f9c-0000-4000-8000-000000000001")
WEEK = datetime(2026, 10, 5)
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lanes_on(monkeypatch):
    monkeypatch.setattr(
        settings, "workspace_lane_profiles", f"{MATAN}:performer", raising=False
    )


@pytest.fixture
def lanes_off(monkeypatch):
    monkeypatch.setattr(settings, "workspace_lane_profiles", "", raising=False)


@pytest.fixture
def fake_llm(monkeypatch):
    state: dict = {"calls": [], "responder": None}

    async def fake_complete(req, *, wait_timeout_s=None, requeue_failed=False):
        state["calls"].append(req)
        data = (
            state["responder"](req)
            if state["responder"]
            else {"candidates": [], "rejections": []}
        )
        return LLMResult(job_id=uuid.uuid4(), text="", structured=data, model="claude-opus-5")

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    return state


async def add(session, ws, kind, *, when=datetime(2026, 9, 1), lesson="x", news_ref=None,
              claim_type="paraphrased"):
    src = EvidenceSource(
        workspace_id=ws,
        source_kind=kind,
        external_id=str(uuid.uuid4()),
        title=f"synthetic {kind}",
        occurred_at=when,
        version_hash="b" * 64,
        fetch_status="ok",
        payload_private={},
    )
    session.add(src)
    await session.flush()
    m = EvidenceMoment(
        workspace_id=ws,
        source_id=src.id,
        source_version_hash="b" * 64,
        excerpt_private="synthetic",
        lesson_summary=lesson,
        claim_type=claim_type,
        speaker="Matan",
        speaker_confidence="high",
        sensitivity_flags=[],
        status="active",
        news_ref=news_ref,
    )
    session.add(m)
    await session.flush()
    return m


def performer_gates() -> dict:
    p = lane_profile.PROFILES["performer"]
    return {g: {"pass": True, "reason": f"synthetic {g}"} for g in p.gate_names}


def cand(ids, lane, **over):
    base = {
        "moment_ids": [str(i) for i in ids],
        "lane": lane,
        "title": "כותרת לדוגמה",
        "lesson": "רעיון לדוגמה",
        "audience": "event_owners",
        "public_angle": "זווית לדוגמה",
        "gates": performer_gates(),
        "freshness_role": "evergreen",
        "scores": {"owner_relevance": 4, "useful_lesson": 4, "support_strength": 3},
    }
    base.update(over)
    return base


# ------------------------------------------------------------- 1. the setting


def test_no_profile_when_setting_is_empty(lanes_off):
    assert lane_profile.profile_for(MATAN) is None
    assert lane_profile.profile_for(OWNER) is None
    assert lane_profile.profile_for(None) is None


def test_setting_names_matan_only(lanes_on):
    p = lane_profile.profile_for(MATAN)
    assert p is not None and p.name == "performer"
    assert [lane.key for lane in p.lanes] == ["trend_reaction", "magic_clip", "behind_scenes"]
    assert p.weekly_target == 10
    assert lane_profile.profile_for(str(MATAN)) is p
    assert lane_profile.profile_for(OWNER) is None


def test_bad_entries_ignored(monkeypatch):
    monkeypatch.setattr(
        settings, "workspace_lane_profiles", f"nope:performer,{MATAN}:unknown", raising=False
    )
    assert lane_profile.profile_for(MATAN) is None


def test_lane_source_kinds_are_known():
    assert "curated_clip" in SOURCE_KINDS and "story_seed" in SOURCE_KINDS


# ---------------------------------------------- 2. owner workspace unchanged


OWNER_SCHEMA_SNAPSHOT = copy.deepcopy(selector.OUTPUT_SCHEMA)


async def test_owner_request_is_byte_identical_with_profiles_configured(
    editorial_sessionmaker, fake_llm, lanes_on
):
    async with editorial_sessionmaker() as s:
        await add(s, OWNER, "fathom_meeting", when=datetime(2026, 10, 6, 10))
        await s.commit()
    res = await selector.select_candidates(editorial_sessionmaker, OWNER, WEEK, max_candidates=10)
    req = fake_llm["calls"][0]
    assert req.system == selector.SYSTEM_PROMPT
    assert req.output_schema == OWNER_SCHEMA_SNAPSHOT
    assert set(req.output_schema["properties"]["candidates"]["items"]["properties"]) == {
        "moment_ids", "title", "lesson", "audience", "reasons_to_care", "public_angle",
        "public_safety_notes", "gates", "freshness_role", "verification_note", "scores",
    }
    assert res.max_candidates == 6  # the owner cap is still 6
    prompt = req.messages[0]["content"]
    assert "Three strong ideas is the usual target" in prompt
    assert "IDEA LANES" not in prompt


def test_owner_enforce_unchanged_signature_defaults():
    # Called the old way (no profile) it uses the owner gates.
    assert selector.enforce_candidates([], [], set()) == ([], [])


# ------------------------------------------------------ 3. Matan's selection


async def test_matan_request_uses_lane_prompt_schema_and_cap(
    editorial_sessionmaker, fake_llm, lanes_on
):
    async with editorial_sessionmaker() as s:
        await add(s, MATAN, "curated_clip")
        await add(s, MATAN, "story_seed")
        await s.commit()
    res = await selector.select_candidates(editorial_sessionmaker, MATAN, WEEK, max_candidates=10)
    req = fake_llm["calls"][0]
    p = lane_profile.PROFILES["performer"]
    assert req.system == p.system_prompt
    items = req.output_schema["properties"]["candidates"]["items"]
    assert set(items["properties"]["gates"]["required"]) == set(p.gate_names)
    assert items["properties"]["lane"]["enum"] == ["trend_reaction", "magic_clip", "behind_scenes"]
    assert "lane" in items["required"]
    assert res.max_candidates == 10
    prompt = req.messages[0]["content"]
    assert "IDEA LANES" in prompt and "magic_clip" in prompt
    # evergreen lane seeds are offered even though they are older than the week
    assert res.pool_size == 2


def test_lane_rules_in_code(lanes_on):
    p = lane_profile.PROFILES["performer"]

    class _Src:
        def __init__(self, kind):
            self.id = uuid.uuid4()
            self.source_kind = kind
            self.title = kind
            self.occurred_at = datetime(2026, 9, 1)
            self.url_private = None

    class _M:
        def __init__(self, i):
            self.id = i
            self.claim_type = "paraphrased"
            self.speaker_confidence = "high"
            self.translation_label = None
            self.language_uncertain = False
            self.sensitivity_flags = []
            self.span_start_s = self.span_end_s = None
            self.code_refs = None
            self.speaker = "Matan"
            self.excerpt_private = "x"
            self.news_ref = {}

    def pm(kind):
        i = uuid.uuid4()
        return selector.PoolMoment(_M(i), _Src(kind), False)

    clip, seed = pm("curated_clip"), pm("story_seed")
    news, fact = pm("news_item"), pm("standing_fact")
    pool = [clip, seed, news, fact]
    ids = {x.id for x in pool}
    raws = [
        cand([clip.id], "magic_clip"),                       # ok
        cand([seed.id], "magic_clip"),                       # wrong evidence for lane B
        cand([seed.id], "behind_scenes",
             lesson="בחתונה אחת הופעתי מול 300 איש וכולם צרחו"),  # invented memory
        cand([seed.id], "behind_scenes",
             lesson="מה הרגשת בפעם הראשונה שמישהו שאל אותך אם אתה באמת קורא מחשבות?"),  # ok
        cand([news.id], "trend_reaction"),                   # news only: no anchor
        cand([news.id, fact.id], "trend_reaction"),          # ok
        cand([clip.id], "magic_clip", lesson="הסוד של הטריק הוא כרטיס כפול"),  # method
        cand([clip.id], "no_such_lane"),
        cand([clip.id, seed.id], "magic_clip"),              # two lanes in one idea
    ]
    acc, rej = selector.enforce_candidates(raws, pool, ids, profile=p)
    assert [c["lane"] for c in acc] == ["magic_clip", "behind_scenes", "trend_reaction"]
    codes = [r["code"] for r in rej]
    from tce.editorial import news_rules

    assert codes == [
        "lane_evidence", "invented_memory", news_rules.CODE_NEEDS_ANCHOR, "method_revealed",
        "unknown_lane", "lane_evidence",
    ]
    assert all(set(c["gates"]) == set(p.gate_names) for c in acc)


def test_fill_lane_mix_takes_four_three_three_then_best_rest(lanes_on):
    p = lane_profile.PROFILES["performer"]

    def c(lane, score):
        return {"lane": lane, "rank_score": score, "moment_ids": [str(uuid.uuid4())],
                "title": f"{lane}{score}", "lesson": "", "public_angle": "", "audience": "both"}

    cands = [c("trend_reaction", 0.9 - i / 100) for i in range(6)]
    cands += [c("magic_clip", 0.5 - i / 100) for i in range(6)]
    cands += [c("behind_scenes", 0.4 - i / 100) for i in range(6)]
    kept, cut = lane_profile.fill_lane_mix(cands, p, 10)
    lanes = [k["lane"] for k in kept]
    assert len(kept) == 10 and len(cut) == 8
    assert lanes.count("trend_reaction") == 4
    assert lanes.count("magic_clip") == 3 and lanes.count("behind_scenes") == 3

    # a thin lane is filled by the best remaining ideas, never padded
    thin = [c("trend_reaction", 0.9 - i / 100) for i in range(8)] + [c("magic_clip", 0.3)]
    kept, cut = lane_profile.fill_lane_mix(thin, p, 10)
    assert len(kept) == 9 and not cut
    lanes = [k["lane"] for k in kept]
    assert lanes.count("magic_clip") == 1 and lanes.count("trend_reaction") == 8


async def test_matan_week_saves_a_lane_mix_of_ten(editorial_sessionmaker, fake_llm, lanes_on):
    async with editorial_sessionmaker() as s:
        clips = [await add(s, MATAN, "curated_clip", lesson=f"clip {i}") for i in range(12)]
        seeds = [await add(s, MATAN, "story_seed", lesson=f"seed {i}") for i in range(12)]
        await s.commit()

    def responder(req):
        prompt = req.messages[0]["content"]
        out = []
        for m in clips + seeds:
            if str(m.id) in prompt:
                lane = "magic_clip" if m in clips else "behind_scenes"
                out.append(cand([m.id], lane, title=f"{lane} {m.lesson_summary}",
                                lesson=f"מה אתה חושב על {m.lesson_summary}?"))
        return {"candidates": out, "rejections": []}

    fake_llm["responder"] = responder
    res = await selector.select_candidates(editorial_sessionmaker, MATAN, WEEK, max_candidates=10)
    assert res.status == "complete", res.detail
    assert len(res.candidates) == 10
    async with editorial_sessionmaker() as s:
        stmt = select(TopicCandidate).where(
            TopicCandidate.workspace_id == MATAN, TopicCandidate.status == "proposed"
        )
        rows = (await s.execute(stmt)).scalars().all()
    lanes = [lineup.lane_for(r) for r in rows]
    # no trend evidence this week: B and C fill the ten, both represented
    assert set(lanes) == {"magic_clip", "behind_scenes"}
    assert lanes.count("magic_clip") >= 3 and lanes.count("behind_scenes") >= 3


async def test_lane_reserve_rotates_and_skips_recently_used(editorial_session, lanes_on):
    s = editorial_session
    p = lane_profile.PROFILES["performer"]
    clips = [await add(s, MATAN, "curated_clip", lesson=f"c{i}") for i in range(20)]
    used = clips[0]
    s.add(TopicCandidate(
        workspace_id=MATAN, week_start=WEEK - timedelta(days=7), moment_ids=[str(used.id)],
        title="t", lesson="l", audience="both", public_angle="a", gates={}, status="selected",
        citations_private=[], origin="selector", freshness_role="evergreen",
        reasons_to_care=[], created_at=WEEK, updated_at=WEEK,
    ))
    await s.commit()
    plan = await selector.collect_pool(s, MATAN, WEEK, profile=p)
    ids = {pm.id for pm in plan.moments}
    assert str(used.id) not in ids
    assert len(ids) == p.reserve_per_lane
    other = await selector.collect_pool(s, MATAN, WEEK + timedelta(days=7), profile=p)
    assert {pm.id for pm in other.moments} != ids  # rotates week to week
    # once the reuse window has passed, the used clip is eligible again
    eligible_later = selector.lane_reserve_used_since(
        WEEK + timedelta(days=7 * (p.reuse_after_weeks + 2)), p
    )
    assert eligible_later > WEEK - timedelta(days=7)


# ------------------------------------------------------------ 4. lineup lanes


def test_lane_for_owner_unchanged_and_matan_lanes(lanes_on):
    owner = TopicCandidate(workspace_id=OWNER, freshness_role="evergreen", audience="coaches",
                           citations_private=[{"source_kind": "fathom_meeting"}])
    assert lineup.lane_for(owner) == "coaching"
    for kind, lane in (("curated_clip", "magic_clip"), ("story_seed", "behind_scenes"),
                       ("news_item", "trend_reaction")):
        c = TopicCandidate(workspace_id=MATAN, freshness_role="news" if kind == "news_item"
                           else "evergreen", audience="both",
                           citations_private=[{"source_kind": kind}])
        assert lineup.lane_for(c) == lane
        assert lane in lineup.LANE_LABELS


def test_week_run_asks_matan_for_the_weekly_target(lanes_on):
    from types import SimpleNamespace

    from tce.api.routers.content_runs import _max_candidates_for

    week = SimpleNamespace(workspace_id=MATAN, scope_kind="week", maximum_candidate_count=6)
    assert _max_candidates_for(week, []) == 10
    assert _max_candidates_for(SimpleNamespace(**{**week.__dict__, "workspace_id": OWNER}), []) == 6
    assert _max_candidates_for(week, [uuid.uuid4()]) == 6


def test_collectors_skip_meetings_and_repos_for_matan(lanes_on):
    assert lane_profile.collects(OWNER) == {"fathom": True, "github": True}
    assert lane_profile.collects(MATAN) == {"fathom": False, "github": False}


# ------------------------------------------------------- 5. the tick script


def _run_tick(tmp_path: Path, env_lines: list[str]) -> list[str]:
    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(["TCE_PRIVATE_ACCESS_KEY=k", *env_lines]) + "\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "calls.txt"
    curl = bindir / "curl"
    curl.write_text(
        "#!/bin/bash\n"
        f'for a in "$@"; do case "$a" in X-Workspace-Id:*) echo "$a" >> {calls};; esac; done\n'
        'out=""; prev=""; for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
        'echo \'{"status":"ok","occurrences":[]}\' > "$out"; printf 200\n'
    )
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "TCE_ENV_FILE": str(env_file),
        "TCE_TICK_LOG": str(tmp_path / "tick.log"),
    }
    subprocess.run(["bash", str(ROOT / "scripts" / "tce-schedule-tick.sh")], env=env, check=True)
    return calls.read_text().split("\n")[:-1]


def test_tick_default_is_the_editor_workspace_only(tmp_path):
    got = _run_tick(tmp_path, [f"TCE_EDITOR_DEFAULT_WORKSPACE_ID={OWNER}"])
    assert got == [f"X-Workspace-Id: {OWNER}"]


def test_tick_loops_the_schedule_workspaces(tmp_path):
    got = _run_tick(tmp_path, [
        f"TCE_EDITOR_DEFAULT_WORKSPACE_ID={OWNER}",
        f"TCE_SCHEDULE_WORKSPACES={OWNER},{MATAN}",
    ])
    assert got == [f"X-Workspace-Id: {OWNER}", f"X-Workspace-Id: {MATAN}"]
    log = (tmp_path / "tick.log").read_text()
    assert log.count("http=200") == 2 and str(MATAN)[:8] in log


# ------------------------------------------------------- 6. idea lane language


def test_spoken_idea_moment_uses_workspace_language(monkeypatch):
    src = (ROOT / "src" / "tce" / "editorial" / "idea_lane.py").read_text()
    assert 'language="en"' not in src
    assert "workspace_language(" in src


def test_owner_gates_constant_untouched():
    assert REJECTION_GATES == (
        "small_service_business",
        "coach_or_event_owner_relevance",
        "concrete_supported_substance",
        "connects_to_ziv_work",
    )
