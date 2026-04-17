"""Find tracked repos whose recent commits are relevant to a post topic.

Used by research_agent to auto-inject concrete examples from our own repos
into posts that aren't specifically about those repos. Respects per-repo
`include_examples_in_posts` toggle and `blocked_topics` deny-list.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.repo_brief import RepoBrief
from tce.models.tracked_repo import TrackedRepo

logger = structlog.get_logger()

_STOPWORDS = {
    "the", "and", "or", "a", "an", "of", "in", "on", "for", "to", "with",
    "how", "why", "what", "your", "our", "about", "is", "are", "we", "they",
    "this", "that", "these", "those", "from", "by", "it", "you",
}


def _keywords(text: str) -> set[str]:
    """Cheap keyword set from a text blob."""
    if not text:
        return set()
    words = re.findall(r"[a-z0-9\-]{3,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _matches(topic_kws: set[str], repo: TrackedRepo) -> int:
    """Score how well a tracked repo matches the topic keywords."""
    if not topic_kws:
        return 0
    candidates: set[str] = set()
    candidates.update(_keywords(repo.slug.replace("-", " ")))
    if repo.display_name:
        candidates.update(_keywords(repo.display_name))
    if repo.description:
        candidates.update(_keywords(repo.description))
    if repo.language:
        candidates.add(repo.language.lower())
    for t in repo.tags or []:
        candidates.update(_keywords(t))
    return len(topic_kws & candidates)


def _blocked(topic: str, repo: TrackedRepo) -> bool:
    if not repo.blocked_topics:
        return False
    lowered = topic.lower()
    return any(b.lower() in lowered for b in repo.blocked_topics)


async def find_repo_examples(
    db: AsyncSession,
    topic: str,
    thesis: str = "",
    max_examples: int = 3,
) -> list[dict[str, Any]]:
    """Return up to `max_examples` repo examples matching the topic.

    Each example includes a cite-ready snippet (commit sha, title, why_relevant).
    """
    if not topic and not thesis:
        return []

    topic_kws = _keywords(f"{topic} {thesis}")
    if not topic_kws:
        return []

    # Load active, example-enabled repos
    stmt = select(TrackedRepo).where(
        TrackedRepo.is_archived.is_(False),
        TrackedRepo.include_examples_in_posts.is_(True),
    )
    repos = list((await db.execute(stmt)).scalars().all())
    if not repos:
        return []

    # Score + filter
    scored: list[tuple[int, TrackedRepo]] = []
    for repo in repos:
        if _blocked(topic, repo):
            continue
        score = _matches(topic_kws, repo)
        if score <= 0:
            continue
        scored.append((score, repo))
    scored.sort(key=lambda t: t[0], reverse=True)

    examples: list[dict[str, Any]] = []
    for _score, repo in scored[:max_examples]:
        # Prefer the most recent brief; any angle is fine.
        brief_stmt = (
            select(RepoBrief)
            .where(RepoBrief.tracked_repo_id == repo.id)
            .order_by(RepoBrief.analyzed_at.desc().nulls_last())
            .limit(1)
        )
        brief = (await db.execute(brief_stmt)).scalar_one_or_none()

        highlight = None
        if brief:
            feats = brief.feature_highlights or []
            fixes = brief.bug_fixes or []
            if feats:
                highlight = {
                    "kind": "feature",
                    "title": feats[0].get("title", "Recent feature"),
                    "commit_sha": feats[0].get("commit_sha"),
                    "why": feats[0].get("why_interesting"),
                }
            elif fixes:
                highlight = {
                    "kind": "fix",
                    "title": fixes[0].get("title", "Recent fix"),
                    "commit_sha": fixes[0].get("commit_sha"),
                    "why": fixes[0].get("what_broke"),
                }

        examples.append(
            {
                "slug": repo.slug,
                "display_name": repo.display_name or repo.slug,
                "repo_url": repo.repo_url,
                "summary": (brief.summary if brief else repo.description) or "",
                "highlight": highlight,
                "last_commit_sha": repo.last_commit_sha,
                "last_scanned_at": (
                    repo.last_scanned_at.isoformat()
                    if repo.last_scanned_at
                    else None
                ),
            }
        )

    return examples
