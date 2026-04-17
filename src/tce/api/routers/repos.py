"""Tracked repos CRUD + on-demand scan endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.repo_brief import RepoBrief
from tce.models.tracked_repo import TrackedRepo
from tce.schemas.repo import (
    RepoBriefRead,
    RepoScanRequest,
    TrackedRepoCreate,
    TrackedRepoRead,
    TrackedRepoUpdate,
)
from tce.services.repo_service import RepoService, parse_github_url

logger = structlog.get_logger()

router = APIRouter(prefix="/repos", tags=["repos"])


@router.post("/tracked", response_model=TrackedRepoRead)
async def add_tracked_repo(
    data: TrackedRepoCreate,
    db: AsyncSession = Depends(get_db),
) -> TrackedRepo:
    """Register a new tracked repo. Slug is derived from the URL."""
    try:
        owner, name = parse_github_url(data.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    slug = f"{owner}-{name}".lower()

    # Upsert by slug within workspace.
    existing = (
        await db.execute(select(TrackedRepo).where(TrackedRepo.slug == slug).limit(1))
    ).scalar_one_or_none()
    if existing:
        # Update fields the user is explicitly setting.
        if data.display_name is not None:
            existing.display_name = data.display_name
        if data.default_branch is not None:
            existing.default_branch = data.default_branch
        if data.tags is not None:
            existing.tags = data.tags
        if data.blocked_topics is not None:
            existing.blocked_topics = data.blocked_topics
        existing.include_examples_in_posts = data.include_examples_in_posts
        existing.is_public = data.is_public
        existing.is_archived = False
        await db.flush()
        return existing

    repo = TrackedRepo(
        repo_url=data.repo_url.strip(),
        slug=slug,
        display_name=data.display_name or name,
        default_branch=data.default_branch or "main",
        tags=data.tags,
        blocked_topics=data.blocked_topics,
        include_examples_in_posts=data.include_examples_in_posts,
        is_public=data.is_public,
    )
    db.add(repo)
    await db.flush()
    return repo


@router.get("/tracked", response_model=list[TrackedRepoRead])
async def list_tracked_repos(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[TrackedRepo]:
    stmt = select(TrackedRepo).order_by(
        TrackedRepo.priority_score.desc(),
        TrackedRepo.last_commit_at.desc().nulls_last(),
        TrackedRepo.created_at.desc(),
    )
    if not include_archived:
        stmt = stmt.where(TrackedRepo.is_archived.is_(False))
    return list((await db.execute(stmt)).scalars().all())


@router.patch("/tracked/{repo_id}", response_model=TrackedRepoRead)
async def update_tracked_repo(
    repo_id: uuid.UUID,
    data: TrackedRepoUpdate,
    db: AsyncSession = Depends(get_db),
) -> TrackedRepo:
    repo = await db.get(TrackedRepo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Tracked repo not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(repo, field, value)
    await db.flush()
    return repo


@router.delete("/tracked/{repo_id}")
async def delete_tracked_repo(
    repo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repo = await db.get(TrackedRepo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Tracked repo not found")
    await db.delete(repo)
    await db.flush()
    return {"deleted": str(repo_id)}


@router.post("/tracked/{repo_id}/scan", response_model=RepoBriefRead)
async def scan_repo(
    repo_id: uuid.UUID,
    data: RepoScanRequest,
    db: AsyncSession = Depends(get_db),
) -> RepoBrief:
    """Run repo_scout against this repo and return the fresh RepoBrief.

    No pipeline - just refresh the cached analysis. Useful as a "Sync now" button.
    """
    repo = await db.get(TrackedRepo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Tracked repo not found")

    # Run repo_scout inline so the caller gets the brief synchronously
    from tce.agents.repo_scout import RepoScout
    from tce.services.cost_tracker import CostTracker
    from tce.services.prompt_manager import PromptManager
    from tce.settings import settings

    run_id = uuid.uuid4()
    tracker = CostTracker(db)
    prompts = PromptManager(db)
    scout = RepoScout(
        db=db,
        settings=settings,
        cost_tracker=tracker,
        prompt_manager=prompts,
        run_id=run_id,
    )
    try:
        await scout.run(
            {
                "tracked_repo_id": repo.id,
                "angle": data.angle,
                "force_refresh": data.force_refresh,
            }
        )
    except Exception as exc:
        logger.exception("repos.scan_failed", repo_id=str(repo_id))
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}")

    await db.flush()

    # Return the fresh brief for (repo, angle, head)
    repo = await db.get(TrackedRepo, repo_id)  # reload with updated SHA
    stmt = (
        select(RepoBrief)
        .where(
            RepoBrief.tracked_repo_id == repo.id,
            RepoBrief.angle == data.angle,
        )
        .order_by(RepoBrief.analyzed_at.desc().nulls_last())
        .limit(1)
    )
    brief = (await db.execute(stmt)).scalar_one_or_none()
    if not brief:
        raise HTTPException(status_code=500, detail="Scan produced no brief")
    return brief


@router.get("/tracked/{repo_id}/briefs", response_model=list[RepoBriefRead])
async def list_briefs(
    repo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[RepoBrief]:
    stmt = (
        select(RepoBrief)
        .where(RepoBrief.tracked_repo_id == repo_id)
        .order_by(RepoBrief.analyzed_at.desc().nulls_last())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.get("/remote-head")
async def remote_head(
    repo_url: str,
    branch: str = "main",
) -> dict[str, str | None]:
    """Ask origin for the current HEAD SHA without touching the DB. Debug helper."""
    from tce.models.tracked_repo import TrackedRepo as _TR

    service = RepoService()
    fake = _TR(repo_url=repo_url, slug="probe", default_branch=branch)
    sha = await service.remote_head_sha(fake)
    return {"repo_url": repo_url, "branch": branch, "sha": sha}
