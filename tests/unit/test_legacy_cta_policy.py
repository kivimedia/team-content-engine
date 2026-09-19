"""Legacy daily and repo-driven writers honor the workspace strategy's call to action.

The default coaching strategy has one CTA (a strategy session): no forced comment keyword,
DM flow or giveaway, and a private repository is evidence, never a public link. A tenant
whose own strategy (replace mode) asks for something else keeps it. Synthetic only.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from tce.agents import platform_writer
from tce.agents.copy_polisher import CopyPolisher
from tce.agents.cta_agent import CTAAgent
from tce.agents.platform_writer import FacebookWriter, LinkedInWriter
from tce.agents.repo_storyteller import RepoStoryteller
from tce.db.base import Base
from tce.models.workspace_context import WorkspaceStrategy
from tce.services.strategy_loader import REPLACE_MARKER

REPO_URL = "https://github.com/example-org/synthetic-private-tool"
SHA = "abc1234"


def repo_context(**over) -> dict:
    ctx = {
        "_source": "repo",
        "angle": "new_features",
        "repo_url": REPO_URL,
        "repo_brief": {
            "repo_url": REPO_URL,
            "slug": "example-org/synthetic-private-tool",
            "summary": "Routes new inquiries to the right person within minutes.",
            "feature_highlights": [
                {"title": "Inquiry triage", "commit_sha": SHA, "why_interesting": "no lost leads"}
            ],
            "bug_fixes": [],
            "code_snippets": [{"path": "src/triage.py", "snippet": "def triage(): pass"}],
        },
        "repo_citations": [{"label": "Feature: triage", "commit_sha": SHA, "why_cite": "proof"}],
        "story_brief": {"topic": "Answer inquiries fast", "thesis": "Speed wins trust"},
        "research_brief": {},
    }
    ctx.update(over)
    return ctx


def make(agent_cls, db=None, reply: dict | None = None):
    agent = agent_cls(db=db, settings=None, cost_tracker=None, prompt_manager=None)
    calls: list[dict] = []

    async def fake_call_llm(**kw):
        calls.append(kw)
        text = json.dumps(reply if reply is not None else {})
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

    agent._call_llm = fake_call_llm
    return agent, calls


def prompt_of(calls) -> str:
    return "\n".join(m["content"] for m in calls[0]["messages"]) + "\n" + (calls[0]["system"] or "")


@pytest.fixture(autouse=True)
def _no_voice_critic(monkeypatch):
    monkeypatch.setattr(platform_writer, "load_voice_patterns", lambda: "")


@pytest.fixture
async def strategy_db(editorial_sessionmaker):
    engine = editorial_sessionmaker.kw["bind"]
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[Base.metadata.tables["workspace_strategies"]]
            )
        )
    async with editorial_sessionmaker() as s:
        yield s


async def add_strategy(session, markdown: str) -> uuid.UUID:
    ws = uuid.uuid4()
    session.add(WorkspaceStrategy(workspace_id=ws, markdown=markdown, label="synthetic"))
    await session.commit()
    return ws


def assert_strategy_session_only(prompt: str) -> None:
    low = prompt.lower()
    assert "book a strategy session" in low
    # the legacy forced-keyword instructions are gone (the prohibition may name them)
    assert "cta line must end with: comment" not in low
    assert "weekly cta keyword" not in low and "cta keyword to weave in" not in low
    assert "do not use the 'comment keyword' pattern for this post - the cta is the repo" not in low


def assert_no_repo_exposure(prompt: str) -> None:
    for leak in (REPO_URL, "synthetic-private-tool", SHA, "src/triage.py", "Code's open"):
        assert leak not in prompt, leak
    assert "star the repo" not in prompt.lower()


# --- default (Ziv) strategy ------------------------------------------------------


async def test_daily_facebook_writer_uses_strategy_session_not_keyword():
    writer, calls = make(FacebookWriter, reply={"facebook_post": "p"})
    await writer.run({"story_brief": {"thesis": "t"}, "research_brief": {}})
    assert_strategy_session_only(prompt_of(calls))


async def test_daily_linkedin_writer_uses_strategy_session():
    writer, calls = make(LinkedInWriter, reply={"linkedin_post": "p"})
    await writer.run({"story_brief": {"thesis": "t"}, "research_brief": {}})
    assert_strategy_session_only(prompt_of(calls))


@pytest.mark.parametrize("cls", [FacebookWriter, LinkedInWriter])
async def test_repo_writers_keep_private_repo_out_and_teach_the_lesson(cls):
    writer, calls = make(cls, reply={"facebook_post": "p", "linkedin_post": "p"})
    await writer.run(repo_context())
    prompt = prompt_of(calls)
    assert_no_repo_exposure(prompt)
    assert_strategy_session_only(prompt)
    assert "owner-level decision or lesson" in prompt
    assert "Inquiry triage" in prompt  # the evidence itself still grounds the post


async def test_cta_agent_default_is_strategy_session_without_llm_or_keyword():
    agent, calls = make(CTAAgent)
    out = (await agent.run({"weekly_theme": "sales follow-up"}))["cta_package"]
    assert calls == []
    assert out["cta_type"] == "strategy_session"
    assert "strategy session" in out["fb_cta_line"] and "strategy session" in out["li_cta_line"]
    # legacy keys kept for KMHub / pipeline consumers
    for key in ("weekly_keyword", "secondary_keyword", "dm_flow", "fulfillment_checklist"):
        assert key in out
    assert out["weekly_keyword"] is None and out["dm_flow"] is None


async def test_cta_agent_repo_run_does_not_publish_repo_link():
    agent, calls = make(CTAAgent)
    out = (await agent.run(repo_context()))["cta_package"]
    assert calls == [] and out["cta_type"] == "strategy_session"
    assert REPO_URL not in json.dumps(out) and "repo_url" not in out


async def test_operator_keyword_without_a_real_guide_is_not_forced():
    agent, calls = make(CTAAgent)
    out = (await agent.run({"weekly_keyword": "guide"}))["cta_package"]
    assert out["cta_type"] == "strategy_session" and calls == []
    assert "no guide exists" in " ".join(out["policy"]["notes"])

    writer, wcalls = make(FacebookWriter, reply={"facebook_post": "p"})
    await writer.run({"weekly_keyword": "guide", "story_brief": {}, "research_brief": {}})
    assert_strategy_session_only(prompt_of(wcalls))


async def test_extend_override_keeps_strategy_session(strategy_db):
    ws = await add_strategy(strategy_db, "Private business context. Comment keyword funnels work.")
    writer, calls = make(FacebookWriter, db=strategy_db, reply={"facebook_post": "p"})
    await writer.run({"workspace_id": str(ws), "story_brief": {}, "research_brief": {}})
    assert_strategy_session_only(prompt_of(calls))


async def test_repo_storyteller_prompt_is_lesson_first_and_private():
    agent, calls = make(RepoStoryteller, reply={"story_brief": {"topic": "t", "thesis": "t"}})
    await agent.run(repo_context())
    prompt = prompt_of(calls)
    assert REPO_URL not in prompt and "synthetic-private-tool" not in prompt
    assert "strategy session" in prompt
    assert "I shipped" not in prompt
    assert "EVIDENCE for a lesson" in prompt


async def test_copy_polisher_does_not_weave_a_keyword_by_default():
    agent, calls = make(CopyPolisher, reply={"facebook_draft": {}, "linkedin_draft": {}})
    await agent.run({"raw_copy": "Some synthetic copy.", "weekly_keyword": "guide"})
    prompt = prompt_of(calls)
    assert "CTA keyword to weave in" not in prompt
    assert "book a strategy session" in prompt.lower()


# --- tenants with their own (replace-mode) strategy ------------------------------


async def test_tenant_strategy_with_keyword_funnel_is_preserved(strategy_db):
    ws = await add_strategy(
        strategy_db,
        f"{REPLACE_MARKER}\nOur CTA: comment keyword funnels. Offer a free guide weekly.",
    )
    ctx = {"workspace_id": str(ws), "weekly_keyword": "plan", "story_brief": {}}
    writer, calls = make(FacebookWriter, db=strategy_db, reply={"facebook_post": "p"})
    await writer.run(ctx | {"research_brief": {}})
    assert 'Comment "plan" and I\'ll send it to you.' in prompt_of(calls)

    agent, acalls = make(
        CTAAgent, db=strategy_db, reply={"weekly_keyword": "plan", "fb_cta_line": "x"}
    )
    out = (await agent.run(ctx | {"guide_title": "Synthetic plan"}))["cta_package"]
    assert len(acalls) == 1 and out["weekly_keyword"] == "plan"
    assert out["policy"]["mode"] == "workspace_defined"


async def test_tenant_strategy_without_keyword_is_followed_not_overwritten(strategy_db):
    ws = await add_strategy(
        strategy_db, f"{REPLACE_MARKER}\nCall to action: join our monthly open house."
    )
    ctx = {"workspace_id": str(ws), "story_brief": {}, "research_brief": {}}
    writer, calls = make(LinkedInWriter, db=strategy_db, reply={"linkedin_post": "p"})
    await writer.run(ctx)
    prompt = prompt_of(calls)
    assert "join our monthly open house" in prompt
    assert "book a strategy session" not in prompt.lower()

    agent, acalls = make(CTAAgent, db=strategy_db)
    out = (await agent.run(ctx))["cta_package"]
    assert out["cta_type"] == "workspace_defined" and acalls == []


async def test_tenant_public_repo_link_only_when_explicitly_public(strategy_db):
    ws = await add_strategy(strategy_db, f"{REPLACE_MARKER}\nWe publish open source tools.")
    private = repo_context(workspace_id=str(ws))
    writer, calls = make(FacebookWriter, db=strategy_db, reply={"facebook_post": "p"})
    await writer.run(private)
    assert_no_repo_exposure(prompt_of(calls))

    public = repo_context(workspace_id=str(ws))
    public["repo_brief"]["visibility"] = "public"
    writer, calls = make(FacebookWriter, db=strategy_db, reply={"facebook_post": "p"})
    await writer.run(public)
    assert f"MUST be the repo URL on its own line: {REPO_URL}" in prompt_of(calls)
    agent, _ = make(CTAAgent, db=strategy_db)
    out = (await agent.run(public))["cta_package"]
    assert out["cta_type"] == "repo_link" and out["repo_url"] == REPO_URL
