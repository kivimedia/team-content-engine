"""Owner idea origin stays distinct from subject, status and AI-news mix."""

from __future__ import annotations

from types import SimpleNamespace

from tce.editorial import news_rules, solution_names
from tce.editorial.inbox import _matches, _row_to_json
from tce.editorial.lineup import (
    _item_to_json,
    source_category,
    source_category_label,
    source_tags,
    news_kind,
)
from tests.unit.test_topic_source_tags import CALL, COMMIT, NEWS, SPOKEN, cand


def owner(monkeypatch):
    monkeypatch.setattr(news_rules, "owner_policy", lambda ws: True)
    monkeypatch.setattr(solution_names, "owner_policy", lambda ws: True)


def test_commit_origin_keeps_build_category_even_for_a_coaching_lesson(monkeypatch):
    owner(monkeypatch)
    idea = cand([COMMIT])
    idea.title = "A no and a not now need different follow-up"
    assert source_category(idea) == "builds"
    assert source_category_label(idea) == "From my builds"
    assert source_tags(idea) == ["Code"]
    assert _matches("builds", idea, None)
    assert _matches("code", idea, None)  # bookmarked URL
    assert not _matches("calls", idea, None)
    row = _row_to_json(idea, {}, None, 0)
    assert row["source_category"] == "builds"
    assert row["source_category_label"] == "From my builds"


def test_news_with_a_commit_anchor_counts_once_as_news(monkeypatch):
    owner(monkeypatch)
    idea = cand([NEWS, COMMIT], role="news")
    assert source_category(idea) == "news"
    assert news_kind(idea) == "unknown"
    assert source_tags(idea)[0] == "News to classify"
    assert _matches("news", idea, None)
    assert not _matches("builds", idea, None)


def test_ordinary_software_news_is_news_but_not_ai(monkeypatch):
    owner(monkeypatch)
    idea = cand([NEWS], role="news")
    idea.gates = {"_news_category": "software"}
    assert source_category(idea) == "news"
    assert news_kind(idea) == "software"
    assert _matches("news", idea, None)
    assert not _matches("builds", idea, None)
    assert _row_to_json(idea, {}, None, 0)["news_kind"] == "software"


def test_known_legacy_dubsado_changelog_is_ordinary_software_news(monkeypatch):
    owner(monkeypatch)
    announcement = {
        "source_kind": "news_item",
        "url_private": "https://updates.dubsado.com/159130-changelog-october-5-2026",
    }
    idea = cand([announcement], role="news")
    assert news_kind(idea) == "software"
    assert source_category(idea) == "news"
    assert source_tags(idea) == ["Software news"]
    assert _matches("news", idea, None)


def test_owner_topic_and_week_share_verified_solution_suggestion(monkeypatch):
    owner(monkeypatch)
    article = {
        "source_kind": "news_item",
        "moment_id": "verified-moment",
        "url_private": "https://www.anthropic.com/claude-haiku-5-5",
    }
    idea = cand([article], role="news")
    idea.title = "A faster model does not need to do every job"
    idea.gates = {"_news_category": "ai"}
    topic = _row_to_json(idea, {}, None, 0)
    item = SimpleNamespace(candidate_id=idea.id, rank=1, slot="primary", lane="ai_news",
                           reason="Timely", status="planned")
    week = _item_to_json(item, idea, None)
    for row in (topic, week):
        assert row["source_category_label"] == "From the news"
        assert row["solution_label"] == "Claude Haiku 5.5"
        assert row["solution_url"] == "https://www.anthropic.com/claude-haiku-5-5"
        assert row["suggested_title"] == "Claude Haiku 5.5: give a faster model one narrow job"
        assert row["news_kind"] == "ai"


def test_call_mentioning_software_remains_call(monkeypatch):
    owner(monkeypatch)
    idea = cand([CALL])
    idea.title = "A client asked about the Google Sites app"
    assert source_category(idea) == "calls"
    assert _matches("calls", idea, None)
    assert not _matches("builds", idea, None)


def test_ambiguous_origins_are_not_guessed_and_explicit_origin_resolves_them(monkeypatch):
    owner(monkeypatch)
    idea = cand([CALL, COMMIT])
    assert source_category(idea) is None
    assert _matches("all", idea, None)
    assert not _matches("calls", idea, None)
    assert not _matches("builds", idea, None)
    idea.gates = {"_primary_source_kind": "github_commit_group"}
    assert source_category(idea) == "builds"
    assert _matches("builds", idea, None)
    assert not _matches("calls", idea, None)


def test_personal_ideas_remain_in_all_with_honest_label(monkeypatch):
    owner(monkeypatch)
    idea = cand([SPOKEN])
    assert source_category(idea) is None
    assert _matches("all", idea, None)
    assert source_tags(idea) == ["Your idea"]


def test_status_is_separate_from_category(monkeypatch):
    owner(monkeypatch)
    idea = cand([COMMIT])
    assert _matches("all", idea, SimpleNamespace(decision="later"))
    assert _matches("builds", idea, SimpleNamespace(decision="later"))
    assert _matches("builds", idea, SimpleNamespace(decision="away"))
    assert _matches("builds", idea, SimpleNamespace(decision="this_week"))
    assert not _matches("best", idea, SimpleNamespace(decision="later"))


def test_client_keeps_existing_subject_based_code_filter(monkeypatch):
    monkeypatch.setattr(news_rules, "owner_policy", lambda ws: False)
    idea = cand([COMMIT])
    idea.title = "A no and a not now need different follow-up"
    assert source_category(idea) is None
    assert source_tags(idea) == []
    assert not _matches("code", idea, None)
    assert "source_category" not in _row_to_json(idea, {}, None, 0)
    assert "solution_label" not in _row_to_json(idea, {}, None, 0)
