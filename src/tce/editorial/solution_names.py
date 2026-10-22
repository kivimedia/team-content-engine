"""Owner-only, evidence-backed names to display beside editorial ideas.

A GitHub repo slug, commit text, transcript, or model answer never grants
permission to name a solution publicly. Add a name here only after its owner
has identified it as public, or after checking the exact official news article.
The functions compute display suggestions and do not change saved editorial copy.
"""

from __future__ import annotations

import re
from typing import Any

from tce.editorial.news_rules import owner_policy

# These are the owner's expressly public solution identities, with their
# repository associations. A repository may contain private client work, so
# only the verified public product name, URL, and opaque moment ID may leave
# this module. Sensitivity flags on the excerpt do not revoke the independently
# verified public identity of a single exact repository.
# No repo slug outside this list may become a label by title-casing it.
PUBLIC_BUILD_SOLUTIONS: dict[str, tuple[str, str | None]] = {
    "kivimedia/kmhub": ("KM Hub", "https://hub.kivimedia.co"),
    "kivimedia/boards": ("KMboards", "https://kmboards.co"),
    "kivimedia/clara": ("Clara", "https://clara-ebon-ten.vercel.app"),
    "kivimedia/km-florist-receptionist": (
        "Bloomline", "https://km-florist-receptionist.vercel.app"
    ),
    "kivimedia/kmbot": ("KM Bot", None),
    "kivimedia/karaoke-madness": ("Karaoke Madness", None),
}


# An official primary article and the specific product it announces. Exact
# clean URLs avoid turning a vendor home page, a lookalike host, or a tokenized
# URL into verification. Add future entries only after checking their article.
PUBLIC_NEWS_ARTICLES: dict[str, tuple[str, str]] = {
    (
        "https://workspaceupdates.googleblog.com/2026/10/"
        "publish-interactive-apps-from-gemini-app-to-Google-Sites.html"
    ): (
        "Google Sites", "Google Sites: build an interactive coaching diagnostic"
    ),
    (
        "https://workspaceupdates.googleblog.com/2026/10/"
        "follow-through-on-your-meeting-tasks-with-meeting-recaps-in-Google-Chat.html"
    ): (
        "Google Meet and Chat", "Google Meet and Chat: turn meeting recaps into owned tasks"
    ),
    (
        "https://workspaceupdates.googleblog.com/2026/10/"
        "gemini-in-google-sheets-is-now-available-on-iOS-devices.html"
    ): (
        "Gemini in Google Sheets", "Gemini in Google Sheets: check enquiries from your iPhone"
    ),
    "https://www.anthropic.com/claude-haiku-5-5": (
        "Claude Haiku 5.5", "Claude Haiku 5.5: give a faster model one narrow job"
    ),
    (
        "https://workspaceupdates.googleblog.com/2026/10/"
        "an-easier-way-to-customize-how-gemini-works-for-you.html"
    ): (
        "Gemini app", "Gemini app: keep repeatable instructions and connected apps in one place"
    ),
}

# The stored Google citations use the original http addresses. Each alias is
# derived only from an exact curated official article above. Display https.
PUBLIC_ARTICLE_SOURCE_ALIASES = {
    url.replace("https://", "http://", 1): url
    for url in PUBLIC_NEWS_ARTICLES
    if url.startswith("https://workspaceupdates.googleblog.com/")
}


def _get(record: Any, key: str) -> Any:
    return record.get(key) if isinstance(record, dict) else getattr(record, key, None)


def verified_solution_for_repo(repo: Any) -> tuple[str, str | None] | None:
    """Return only an explicitly approved public solution for an exact repo id."""
    if not isinstance(repo, str):
        return None
    return PUBLIC_BUILD_SOLUTIONS.get(repo.strip().casefold())


def _commit_label(citations: list[dict[str, Any]]) -> dict[str, Any] | None:
    commits = [c for c in citations if c.get("source_kind") == "github_commit_group"]
    if not commits:
        return None
    repos: set[str] = set()
    first_id = None
    for citation in commits:
        refs = citation.get("code_refs")
        if not isinstance(refs, list) or not refs:
            return None
        for ref in refs:
            if not isinstance(ref, dict):
                return None
            repo, sha, path = ref.get("repo"), ref.get("sha"), ref.get("path")
            if not (isinstance(repo, str) and isinstance(sha, str)
                    and re.fullmatch(r"[0-9a-f]{7,40}", sha, re.I)
                    and isinstance(path, str) and path.strip()):
                return None
            repos.add(repo.casefold())
        first_id = first_id or str(citation.get("moment_id") or "")
    if len(repos) != 1 or not first_id:
        return None
    approved = verified_solution_for_repo(next(iter(repos)))
    if approved is None:
        return None
    name, public_url = approved
    return {
        "name": name,
        "public_url": public_url,
        "evidence": {"source_kind": "github_commit_group", "moment_id": first_id},
    }


def _news_label(citations: list[dict[str, Any]]) -> dict[str, Any] | None:
    articles = [c for c in citations if c.get("source_kind") == "news_item"]
    if len(articles) != 1:
        return None
    citation = articles[0]
    url = citation.get("url_private")
    if not isinstance(url, str):
        return None
    canonical = PUBLIC_ARTICLE_SOURCE_ALIASES.get(url, url)
    if canonical not in PUBLIC_NEWS_ARTICLES:
        return None
    moment_id = str(citation.get("moment_id") or "")
    if not moment_id:
        return None
    name, _ = PUBLIC_NEWS_ARTICLES[canonical]
    return {
        "name": name,
        "public_url": canonical,
        "evidence": {"source_kind": "news_item", "moment_id": moment_id, "primary_url": url},
    }


def solution_label_for_candidate(candidate: Any) -> dict[str, Any] | None:
    """A public-safe name backed by this owner's cited source, if unambiguous."""
    if not owner_policy(_get(candidate, "workspace_id")):
        return None
    citations = _get(candidate, "citations_private") or []
    if not isinstance(citations, list) or not all(isinstance(c, dict) for c in citations):
        return None
    news = _news_label(citations)
    if news:
        return news
    # A meeting-led idea supported by code may mention the build, but the code
    # does not by itself establish which solution the idea is about.
    gates = _get(candidate, "gates") or {}
    primary_kind = gates.get("_primary_source_kind") if isinstance(gates, dict) else None
    if primary_kind not in (None, "github_commit_group"):
        return None
    if primary_kind is None and any(c.get("source_kind") == "fathom_meeting" for c in citations):
        return None
    return _commit_label(citations)


def proposed_solution_title(candidate: Any) -> dict[str, Any] | None:
    """Reviewable title suggestion; the saved title is never rewritten here."""
    solution = solution_label_for_candidate(candidate)
    old_title = str(_get(candidate, "title") or "").strip()
    if not solution or not old_title:
        return None
    name = solution["name"]
    if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", old_title, re.I):
        return None
    article = solution["public_url"] if solution["evidence"]["source_kind"] == "news_item" else None
    if not article:
        gates = _get(candidate, "gates") or {}
        if not isinstance(gates, dict) or gates.get("_solution_central") is not True:
            return None
    new_title = (PUBLIC_NEWS_ARTICLES[article][1] if article else f"{name}: {old_title}")[:300]
    if new_title == old_title:
        return None
    return {"title": new_title, "solution": solution}

