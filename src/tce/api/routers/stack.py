"""Post stack endpoints - curated publish-ready queue."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.post_package import PostPackage
from tce.models.post_stack import PostStackEntry

logger = structlog.get_logger()

router = APIRouter(prefix="/stack", tags=["stack"])


class AddToStackRequest(BaseModel):
    post_package_id: str
    operator_notes: str | None = None


class ReorderRequest(BaseModel):
    entries: list[dict[str, Any]]  # [{"id": "uuid", "position": 0}, ...]


@router.get("/")
async def list_stack(
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all posts in the publish stack, ordered by position."""
    result = await db.execute(
        select(PostStackEntry).order_by(PostStackEntry.position)
    )
    entries = result.scalars().all()

    out = []
    for e in entries:
        pkg = await db.get(PostPackage, e.post_package_id)
        entry_data: dict[str, Any] = {
            "id": str(e.id),
            "post_package_id": str(e.post_package_id),
            "position": e.position,
            "scheduled_date": str(e.scheduled_date) if e.scheduled_date else None,
            "status": e.status,
            "operator_notes": e.operator_notes,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        if pkg:
            entry_data["fb_preview"] = (pkg.facebook_post or "")[:120]
            entry_data["li_preview"] = (pkg.linkedin_post or "")[:120]
            entry_data["cta_keyword"] = pkg.cta_keyword
            entry_data["approval_status"] = pkg.approval_status
            entry_data["has_images"] = bool(pkg.image_prompts)
        out.append(entry_data)

    return out


@router.post("/add")
async def add_to_stack(
    request: AddToStackRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add an approved package to the publish stack."""
    pkg_id = uuid.UUID(request.post_package_id)

    # Verify package exists
    pkg = await db.get(PostPackage, pkg_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    # Check if already in stack
    existing = await db.execute(
        select(PostStackEntry).where(PostStackEntry.post_package_id == pkg_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Package already in stack")

    # Get next position
    max_pos_result = await db.execute(
        select(PostStackEntry.position).order_by(PostStackEntry.position.desc()).limit(1)
    )
    max_pos = max_pos_result.scalar_one_or_none() or 0
    next_pos = max_pos + 1

    entry = PostStackEntry(
        post_package_id=pkg_id,
        position=next_pos,
        operator_notes=request.operator_notes,
    )
    db.add(entry)
    await db.commit()

    return {
        "id": str(entry.id),
        "position": next_pos,
        "status": "queued",
    }


@router.delete("/{entry_id}")
async def remove_from_stack(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Remove a package from the stack."""
    entry = await db.get(PostStackEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Stack entry not found")

    await db.delete(entry)
    await db.commit()
    return {"status": "removed"}


@router.patch("/reorder")
async def reorder_stack(
    request: ReorderRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Reorder stack entries by updating positions."""
    for item in request.entries:
        entry = await db.get(PostStackEntry, uuid.UUID(item["id"]))
        if entry:
            entry.position = item["position"]

    await db.commit()
    return {"status": "reordered"}
