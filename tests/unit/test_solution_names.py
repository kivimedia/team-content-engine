"""A product label needs proof and explicit permission to be public."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from tce.editorial import solution_names

OWNER = uuid4()
CLIENT = uuid4()
MOMENT = "11111111-1111-1111-1111-111111111111"


def candidate(*, workspace_id=OWNER, citations=None, title="The follow-up distinction",
              gates=None):
    return SimpleNamespace(
        workspace_id=workspace_id,
        citations_private=citations or [],
        title=title,
        news_item_id=None,
        gates=gates or {},
    )


def commit_citation(repo, *, moment_id=MOMENT, flags=None):
    return {
        "moment_id": moment_id,
        "source_kind": "github_commit_group",
        "source_title": "Private commit group",
        "sensitivity_flags": flags or [],
        "code_refs": [{"repo": repo, "sha": "1" * 40, "path": "src/timer.py"}],
    }


def test_verified_owner_build_has_separate_label_proof_and_title_suggestion(monkeypatch):
    monkeypatch.setattr(solution_names, "owner_policy", lambda ws: ws == OWNER)
    item = candidate(citations=[commit_citation("kivimedia/kmhub")],
                     gates={"_solution_central": True})
    label = solution_names.solution_label_for_candidate(item)
    assert label == {
        "name": "KM Hub",
        "public_url": "https://hub.kivimedia.co",
        "evidence": {"source_kind": "github_commit_group", "moment_id": MOMENT},
    }
    assert solution_names.proposed_solution_title(item) == {
        "title": "KM Hub: The follow-up distinction",
        "solution": label,
    }
    assert item.title == "The follow-up distinction"
    lesson_first = candidate(citations=[commit_citation("kivimedia/kmhub")])
    assert solution_names.solution_label_for_candidate(lesson_first)["name"] == "KM Hub"
    assert solution_names.proposed_solution_title(lesson_first) is None


def test_repo_slug_private_context_or_second_repo_cannot_become_public_label(monkeypatch):
    monkeypatch.setattr(solution_names, "owner_policy", lambda ws: ws == OWNER)
    private = candidate(citations=[commit_citation("kivimedia/private-coach")])
    assert solution_names.solution_label_for_candidate(private) is None
    client = candidate(workspace_id=CLIENT, citations=[commit_citation("kivimedia/kmhub")])
    assert solution_names.solution_label_for_candidate(client) is None
    sensitive = candidate(citations=[commit_citation("kivimedia/kmhub", flags=["client_identity"])])
    label = solution_names.solution_label_for_candidate(sensitive)
    assert label == {
        "name": "KM Hub",
        "public_url": "https://hub.kivimedia.co",
        "evidence": {"source_kind": "github_commit_group", "moment_id": MOMENT},
    }
    assert "Private commit group" not in str(label)
    assert "client_identity" not in str(label)
    mixed = candidate(citations=[
        commit_citation("kivimedia/kmhub"),
        commit_citation("kivimedia/boards", moment_id="22222222-2222-2222-2222-222222222222"),
    ])
    assert solution_names.solution_label_for_candidate(mixed) is None


def test_only_exact_primary_news_article_gets_a_product_label(monkeypatch):
    monkeypatch.setattr(solution_names, "owner_policy", lambda ws: ws == OWNER)
    url = ("https://workspaceupdates.googleblog.com/2026/10/"
           "publish-interactive-apps-from-gemini-app-to-Google-Sites.html")
    item = candidate(
        title="Your next coaching resource could do something",
        citations=[{"moment_id": MOMENT, "source_kind": "news_item", "url_private": url}],
    )
    label = solution_names.solution_label_for_candidate(item)
    assert label["name"] == "Google Sites"
    assert label["evidence"] == {"source_kind": "news_item", "moment_id": MOMENT,
                                 "primary_url": url}
    assert solution_names.proposed_solution_title(item)["title"] == (
        "Google Sites: build an interactive coaching diagnostic"
    )
    for unsafe in (url + "?token=x", url.replace("googleblog.com", "googleblog.com.evil.test")):
        item.citations_private[0]["url_private"] = unsafe
        assert solution_names.solution_label_for_candidate(item) is None


def test_verified_gemini_article_accepts_its_exact_legacy_http_source(monkeypatch):
    monkeypatch.setattr(solution_names, "owner_policy", lambda ws: ws == OWNER)
    stored = ("http://workspaceupdates.googleblog.com/2026/10/"
              "an-easier-way-to-customize-how-gemini-works-for-you.html")
    canonical = stored.replace("http://", "https://", 1)
    item = candidate(citations=[
        {"moment_id": MOMENT, "source_kind": "news_item", "url_private": stored}
    ])
    label = solution_names.solution_label_for_candidate(item)
    assert label["name"] == "Gemini app"
    assert label["public_url"] == canonical
    assert label["evidence"]["primary_url"] == stored
    assert solution_names.proposed_solution_title(item)["title"] == (
        "Gemini app: keep repeatable instructions and connected apps in one place"
    )
    item.citations_private[0]["url_private"] = stored + "?key=secret"
    assert solution_names.solution_label_for_candidate(item) is None


def test_other_verified_google_articles_accept_their_exact_stored_http_urls(monkeypatch):
    monkeypatch.setattr(solution_names, "owner_policy", lambda ws: ws == OWNER)
    for canonical, (name, _) in solution_names.PUBLIC_NEWS_ARTICLES.items():
        if not canonical.startswith("https://workspaceupdates.googleblog.com/"):
            continue
        stored = canonical.replace("https://", "http://", 1)
        item = candidate(citations=[
            {"moment_id": MOMENT, "source_kind": "news_item", "url_private": stored}
        ])
        label = solution_names.solution_label_for_candidate(item)
        assert label is not None and label["name"] == name
        assert label["public_url"] == canonical
        item.citations_private[0]["url_private"] = stored + "?private=x"
        assert solution_names.solution_label_for_candidate(item) is None

