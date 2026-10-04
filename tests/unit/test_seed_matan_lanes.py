"""scripts/seed_matan_lanes.py: the data is valid, safe and idempotent; a sample week
is built offline from the seeded lanes (fake LLM, in-memory SQLite, no live DB).
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

import tce.llm
from tce.editorial import lane_profile, lane_seeds, lineup, selector
from tce.llm import LLMResult
from tce.models.editorial import EvidenceMoment, TopicCandidate
from tce.settings import settings

ROOT = Path(__file__).resolve().parents[2]
MATAN = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")


def _load():
    spec = importlib.util.spec_from_file_location(
        "seed_matan_lanes", ROOT / "scripts" / "seed_matan_lanes.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seed = _load()


def test_data_validates_and_has_enough_of_each_lane():
    seed.validate_all()
    assert len(seed.CLIPS) >= 20 and len(seed.STORY_SEEDS) >= 20 and len(seed.FEEDS) >= 8
    assert len({c[4] for c in seed.CLIPS}) == len(seed.CLIPS)
    assert all(c[4].startswith("https://www.youtube.com/watch?v=") for c in seed.CLIPS)
    assert seed.STRATEGY_MD.startswith("<!-- tce-strategy: replace -->")


def test_no_method_words_and_seeds_are_questions():
    for clip in seed.CLIPS:
        assert not lane_profile._METHOD_REVEAL.search(clip[5]), clip[0]
    for key, question in seed.STORY_SEEDS:
        assert question.rstrip().endswith("?"), key
        assert not lane_profile._INVENTED_MEMORY.search(question), key


def test_dry_run_is_the_default_and_writes_nothing(capsys, monkeypatch):
    import asyncio
    import sys

    called = []
    monkeypatch.setattr(seed, "apply", lambda ws: called.append(ws))
    monkeypatch.setattr(sys, "argv", ["seed_matan_lanes.py"])
    assert asyncio.run(seed.main()) == 0
    out = capsys.readouterr().out
    assert "dry run: nothing written" in out and not called
    assert "schedule/weekly-content" in out and str(MATAN) in out


async def test_lane_items_are_idempotent(editorial_session):
    items = seed.lane_items()
    first = await lane_seeds.seed_lane_items(editorial_session, MATAN, items, author="t")
    await editorial_session.commit()
    second = await lane_seeds.seed_lane_items(editorial_session, MATAN, items, author="t")
    assert first["written"] == len(items) and second["unchanged"] == len(items)
    assert second["written"] == second["revised"] == second["retired"] == 0
    third = await lane_seeds.seed_lane_items(editorial_session, MATAN, items[1:], author="t")
    assert third["retired"] == 1
    active = (await editorial_session.execute(select(EvidenceMoment).where(
        EvidenceMoment.workspace_id == MATAN, EvidenceMoment.status == "active"))).scalars().all()
    assert len(active) == len(items) - 1
    assert all(m.extraction_job_id is None for m in active)


async def test_sample_week_offline(editorial_sessionmaker, monkeypatch, capsys):
    """One sample week for Matan from the seeded lanes. The 'model' here is a fake that
    turns every offered seed into an idea of its lane, so this proves the plumbing (pool,
    lanes, gates, mix, lineup lanes), not the wording a real run would produce."""
    monkeypatch.setattr(settings, "workspace_lane_profiles", f"{MATAN}:performer", raising=False)
    async with editorial_sessionmaker() as s:
        await lane_seeds.seed_lane_items(s, MATAN, seed.lane_items(), author="t")
        await s.commit()
        moments = {
            str(m.id): m
            for m in (await s.execute(select(EvidenceMoment))).scalars()
        }
    p = lane_profile.PROFILES["performer"]

    async def fake_complete(req, *, wait_timeout_s=None, requeue_failed=False):
        prompt = req.messages[0]["content"]
        cands = []
        for mid, m in moments.items():
            if mid not in prompt:
                continue
            lane = "magic_clip" if m.claim_type == "demonstrated" else "behind_scenes"
            cands.append({
                "moment_ids": [mid], "lane": lane, "title": m.context_private[:80],
                "lesson": m.lesson_summary, "audience": "both", "public_angle": "",
                "gates": {g: {"pass": True, "reason": "sample"} for g in p.gate_names},
                "freshness_role": "evergreen",
                "scores": {"owner_relevance": 4, "useful_lesson": 4, "support_strength": 3},
            })
        return LLMResult(job_id=uuid.uuid4(), text="", model="fake",
                         structured={"candidates": cands, "rejections": []})

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    res = await selector.select_candidates(
        editorial_sessionmaker, MATAN, datetime(2026, 10, 5), max_candidates=10
    )
    assert res.status == "complete", res.detail
    async with editorial_sessionmaker() as s:
        rows = (await s.execute(select(TopicCandidate).where(
            TopicCandidate.status == "proposed").order_by(TopicCandidate.rank))).scalars().all()
    print("\nSAMPLE WEEK (offline, fake model):")
    for r in rows:
        print(f"  {r.rank:2}. [{lineup.LANE_LABELS[lineup.lane_for(r)]}] {r.title}")
    lanes = [lineup.lane_for(r) for r in rows]
    assert len(rows) == 10
    assert lanes.count("magic_clip") >= 3 and lanes.count("behind_scenes") >= 3


def test_seed_has_no_method_reveal_clips_and_weekly_stops_at_ranking(capsys):
    """Review 5-Oct: a clip whose own title says it reveals the trick, a vendor
    upload of a trick product, and a feed that answers 403 are out; the weekly
    schedule never reaches the owner's packet writer."""
    for c in seed.CLIPS:
        assert "fg0CC99hVK8" not in c[4] and "9w7QAr13FP0" not in c[4]
    assert all("japantoday" not in f[1] for f in seed.FEEDS)
    seed.print_live_steps(seed.MATAN_WORKSPACE)
    out = capsys.readouterr().out
    assert '"final_stage":"ranking"' in out and '"final_stage":"exporting"' not in out
