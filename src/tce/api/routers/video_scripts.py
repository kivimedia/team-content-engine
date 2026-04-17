"""CRUD routes for Video Studio scripts (walking + talking-head).

Unified list endpoint so the Video Studio "Library" pill can show both
walking_video_scripts and video_lead_scripts in one feed. Detail + status
updates are type-aware via the `kind` path segment.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.video_lead_script import VideoLeadScript
from tce.models.walking_video_script import WalkingVideoScript

router = APIRouter(prefix="/video-scripts", tags=["video-scripts"])


class ScriptStatusUpdate(BaseModel):
    status: str  # draft | approved | recorded | edited | published | rejected
    video_file_path: str | None = None  # set when marking recorded


def _walking_to_card(row: WalkingVideoScript) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": "walking",
        "title": row.title,
        "hook": row.hook,
        "status": row.status,
        "topic": row.topic,
        "word_count": row.word_count,
        "estimated_duration_seconds": row.estimated_duration_seconds,
        "duration_target_seconds": row.duration_target_seconds,
        "niche": row.niche,
        "hook_formula": row.hook_formula,
        "format_label": row.format_label,
        "creator_profile_id": str(row.creator_profile_id) if row.creator_profile_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _talking_to_card(row: VideoLeadScript) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": "talking_head",
        "title": row.title,
        "hook": row.hook,
        "status": row.status,
        "topic": row.topic,
        "word_count": row.word_count,
        "estimated_duration_seconds": int((row.estimated_duration_minutes or 0) * 60) or None,
        "duration_target_seconds": None,
        "niche": row.niche,
        "hook_formula": None,
        "format_label": "talking_head",
        "creator_profile_id": None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
async def list_video_scripts(
    kind: str | None = None,  # "walking" | "talking_head" | None (both)
    status: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List scripts from both tables. kind filters the source table."""
    limit = max(1, min(limit, 500))
    cards: list[dict[str, Any]] = []

    if kind in (None, "walking"):
        q = select(WalkingVideoScript).order_by(WalkingVideoScript.created_at.desc()).limit(limit)
        if status:
            q = q.where(WalkingVideoScript.status == status)
        result = await db.execute(q)
        cards.extend(_walking_to_card(r) for r in result.scalars().all())

    if kind in (None, "talking_head"):
        q = select(VideoLeadScript).order_by(VideoLeadScript.created_at.desc()).limit(limit)
        if status:
            q = q.where(VideoLeadScript.status == status)
        result = await db.execute(q)
        cards.extend(_talking_to_card(r) for r in result.scalars().all())

    cards.sort(key=lambda c: c.get("created_at") or "", reverse=True)
    return cards[:limit]


@router.get("/walking/{script_id}")
async def get_walking_script(
    script_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(WalkingVideoScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Walking-video script not found")
    return {
        **_walking_to_card(row),
        "full_script": row.full_script,
        "shot_notes": row.shot_notes or {},
        "cutsense_prompt": row.cutsense_prompt,
        "thesis": row.thesis,
        "target_audience": row.target_audience,
        "seo_description": row.seo_description,
        "tags": row.tags or [],
        "repurpose": row.repurpose or {},
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        "video_file_path": row.video_file_path,
        "pipeline_run_id": str(row.pipeline_run_id) if row.pipeline_run_id else None,
    }


@router.get("/talking_head/{script_id}")
async def get_talking_head_script(
    script_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(VideoLeadScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Talking-head script not found")
    return {
        **_talking_to_card(row),
        "full_script": row.full_script,
        "sections": row.sections or [],
        "title_pattern": row.title_pattern,
        "target_audience": row.target_audience,
        "key_takeaway": row.key_takeaway,
        "seo_description": row.seo_description,
        "tags": row.tags or [],
        "blog_repurpose_outline": row.blog_repurpose_outline,
        "pipeline_run_id": str(row.pipeline_run_id) if row.pipeline_run_id else None,
    }


@router.patch("/walking/{script_id}")
async def update_walking_script(
    script_id: uuid.UUID,
    data: ScriptStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(WalkingVideoScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Walking-video script not found")
    valid = {"draft", "approved", "recorded", "edited", "published", "rejected"}
    if data.status not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid status; must be one of {sorted(valid)}")
    row.status = data.status
    if data.status == "recorded":
        row.recorded_at = datetime.utcnow()
        if data.video_file_path:
            row.video_file_path = data.video_file_path
    await db.commit()
    await db.refresh(row)
    return _walking_to_card(row)


@router.patch("/talking_head/{script_id}")
async def update_talking_head_script(
    script_id: uuid.UUID,
    data: ScriptStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(VideoLeadScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Talking-head script not found")
    valid = {"draft", "approved", "recorded", "repurposed", "rejected"}
    if data.status not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid status; must be one of {sorted(valid)}")
    row.status = data.status
    await db.commit()
    await db.refresh(row)
    return _talking_to_card(row)
