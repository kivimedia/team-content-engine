"""Effective strategy provenance, default doc content, and decoupled planner prompts."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

from tce.agents.story_strategist import SYSTEM_PROMPT as STRATEGIST_SYSTEM
from tce.agents.story_strategist import build_story_prompt_parts
from tce.agents.weekly_planner import SYSTEM_PROMPT as PLANNER_SYSTEM
from tce.agents.weekly_planner import build_planner_prompt_parts, normalize_weekly_plan
from tce.db.base import Base
from tce.models.workspace_context import WorkspaceStrategy
from tce.services import strategy_loader
from tce.services.strategy_loader import REPLACE_MARKER, load_effective_strategy

DOC = Path(strategy_loader._STRATEGY_PATH)


@pytest.fixture
async def strategy_sessionmaker(editorial_sessionmaker):
    engine = editorial_sessionmaker.kw["bind"]
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[Base.metadata.tables["workspace_strategies"]]
            )
        )
    return editorial_sessionmaker


# --- default doc -------------------------------------------------------------


def test_default_doc_carries_settled_decisions():
    text = DOC.read_text(encoding="utf-8").lower()
    for phrase in (
        "coaches first",
        "event-industry business owners second",
        "super coaching",
        "human team and ai team",
        "book a strategy session",
        "never publish prices",
        "5-7 walking bullets",
        "phrase-broken script",
        "facebook and linkedin",
        "90 minutes",
        "one lesson per idea",
        "keep coaching lessons that do not mention ai",
        "built",
        "measured",
        "silence is not approval",
    ):
        assert phrase in text, phrase


def test_default_doc_has_no_money_figures_or_private_markers():
    text = DOC.read_text(encoding="utf-8")
    assert not re.search(r"[$€£₪]\s?\d", text)
    assert not re.search(r"\b\d+\s?[kK]\s?/\s?(mo|month)", text)
    assert "—" not in text and "–" not in text
    assert "api key" not in text.lower() and "api_key" not in text.lower()
    assert "giveaway" not in text.lower().replace("no forced giveaway", "")


def test_voice_patterns_still_load_for_writers():
    strategy_loader.load_voice_patterns.cache_clear()
    voice = strategy_loader.load_voice_patterns()
    assert voice.startswith("## ZIV'S VOICE AND WRITING STYLE")
    assert "### B. Claims & credibility" in voice and "Banned vocabulary" in voice
    assert not re.search(r"[$€£]\s?\d", voice)


# --- provenance --------------------------------------------------------------


async def test_effective_strategy_without_override_is_default_file(strategy_sessionmaker):
    async with strategy_sessionmaker() as s:
        eff = await load_effective_strategy(s, uuid.uuid4())
    assert [src["kind"] for src in eff.sources] == ["file"]
    assert "book a strategy session" in eff.text.lower()
    assert "ZIV'S VOICE" not in eff.text  # positioning only by default


async def test_effective_strategy_extends_with_db_override(strategy_sessionmaker):
    ws = uuid.uuid4()
    async with strategy_sessionmaker() as s:
        s.add(
            WorkspaceStrategy(workspace_id=ws, markdown="Synthetic private context.", label="ctx")
        )
        s.add(WorkspaceStrategy(workspace_id=uuid.uuid4(), markdown="Other tenant context."))
        await s.commit()
        eff = await load_effective_strategy(s, ws)
    kinds = [(src["kind"], src.get("mode")) for src in eff.sources]
    assert kinds == [("file", "default"), ("db_override", "extend")]
    assert eff.sources[1]["label"] == "ctx"
    assert "Synthetic private context." in eff.text and "Other tenant" not in eff.text
    assert eff.text.index("book a strategy session") < eff.text.index("Synthetic private context.")


async def test_effective_strategy_replace_mode(strategy_sessionmaker):
    ws = uuid.uuid4()
    async with strategy_sessionmaker() as s:
        s.add(WorkspaceStrategy(workspace_id=ws, markdown=f"{REPLACE_MARKER}\nTenant strategy."))
        await s.commit()
        eff = await load_effective_strategy(s, ws)
    assert [(x["kind"], x["mode"]) for x in eff.sources] == [("db_override", "replace")]
    assert eff.text == "Tenant strategy."


async def test_effective_strategy_db_error_is_visible(editorial_sessionmaker):
    # workspace_strategies table deliberately missing
    async with editorial_sessionmaker() as s:
        eff = await load_effective_strategy(s, uuid.uuid4())
    assert any(src.get("status") == "error" for src in eff.sources)
    assert "book a strategy session" in eff.text.lower()


def test_legacy_sync_loader_still_works():
    strategy_loader.load_strategy.cache_clear()
    assert "Super Coaching" in strategy_loader.load_strategy()


# --- planner / strategist prompts ----------------------------------------------

_NEWS_REQUIREMENTS = (
    "MUST be based on a trend",
    "last 14 days",
    "RECENCY RULES",
    "Each day's topic MUST match its cadence angle",
    "Design a weekly gift",
    "weekly_guide_keyword",
    "TJ Robertson",
    "Crisis-signal",
)


def test_planner_system_prompt_no_longer_requires_news_or_giveaway():
    for phrase in _NEWS_REQUIREMENTS:
        assert phrase not in PLANNER_SYSTEM, phrase
    assert "strategy session" in PLANNER_SYSTEM.lower()
    assert "optional context" in PLANNER_SYSTEM.lower()
    assert "Do NOT pad" in PLANNER_SYSTEM


def test_planner_prompt_uses_evidence_candidates_as_primary_pool():
    cands = [{"candidate_id": "c1", "title": "Synthetic idea", "lesson": "l"}]
    parts = build_planner_prompt_parts(
        evidence_candidates=cands,
        trends=[{"headline": "Synthetic trend"}],
        strategy_text="STRATEGY TEXT",
    )
    joined = "\n".join(parts)
    assert parts[0].startswith("EVIDENCE-BACKED IDEAS (primary pool")
    assert joined.index("Synthetic idea") < joined.index("Synthetic trend")
    assert "OPTIONAL TREND CONTEXT" in joined
    for phrase in ("CURRENT AI LANDSCAPE", "Emotional Trigger Test", "$", "300+ clients"):
        assert phrase not in joined, phrase


def test_planner_prompt_without_trends_or_candidates_is_valid():
    joined = "\n".join(build_planner_prompt_parts(strategy_text="S"))
    assert "none available" in joined and "TREND" not in joined


def test_normalize_plan_does_not_invent_guide_or_keyword():
    plan = normalize_weekly_plan({"days": [{"day_of_week": 0, "options": [{"topic": "t"}]}]})
    assert plan["guide_options"] == [] and plan["cta_keyword"] == ""
    assert plan["cta"]["type"] == "strategy_session"
    assert plan["days"][0]["options"][0]["cta_goal"] == "strategy_session"


def test_strategist_prompt_no_longer_forces_cadence_or_guide_cta():
    for phrase in _NEWS_REQUIREMENTS:
        assert phrase not in STRATEGIST_SYSTEM, phrase
    assert '"strategy_session"' in STRATEGIST_SYSTEM
    parts = build_story_prompt_parts(
        {"day_of_week": 0, "trend_brief": {"trends": [{"headline": "Synthetic trend"}]}},
        strategy_text="S",
        evidence_candidates=[{"candidate_id": "c1", "title": "Synthetic idea"}],
    )
    joined = "\n".join(parts)
    assert "Today is" not in joined and "Today's cadence slot" not in joined
    assert "OPTIONAL TREND CONTEXT" in joined and "EVIDENCE-BACKED IDEAS" in joined
    assert "300+ clients" not in joined and "$" not in joined


def test_strategist_operator_topic_still_wins():
    parts = build_story_prompt_parts({"topic": "Synthetic operator topic"}, strategy_text="S")
    assert parts[0].startswith("OPERATOR-ASSIGNED TOPIC")
