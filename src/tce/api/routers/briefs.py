"""Brief endpoints — StoryBrief, ResearchBrief, TrendBrief."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.research_brief import ResearchBrief
from tce.models.story_brief import StoryBrief
from tce.models.trend_brief import TrendBrief
from tce.schemas.research_brief import ResearchBriefRead
from tce.schemas.story_brief import StoryBriefRead
from tce.schemas.trend_brief import TrendBriefRead

router = APIRouter(prefix="/briefs", tags=["briefs"])


# Story briefs
@router.get("/stories", response_model=list[StoryBriefRead])
async def list_story_briefs(db: AsyncSession = Depends(get_db)) -> list[StoryBrief]:
    result = await db.execute(select(StoryBrief).order_by(StoryBrief.created_at.desc()))
    return list(result.scalars().all())


@router.get("/stories/{brief_id}", response_model=StoryBriefRead)
async def get_story_brief(
    brief_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> StoryBrief:
    brief = await db.get(StoryBrief, brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail="Story brief not found")
    return brief


# Research briefs
@router.get("/research", response_model=list[ResearchBriefRead])
async def list_research_briefs(db: AsyncSession = Depends(get_db)) -> list[ResearchBrief]:
    result = await db.execute(select(ResearchBrief).order_by(ResearchBrief.created_at.desc()))
    return list(result.scalars().all())


@router.get("/research/{brief_id}", response_model=ResearchBriefRead)
async def get_research_brief(
    brief_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ResearchBrief:
    brief = await db.get(ResearchBrief, brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail="Research brief not found")
    return brief


# Trend briefs
@router.get("/trends", response_model=list[TrendBriefRead])
async def list_trend_briefs(db: AsyncSession = Depends(get_db)) -> list[TrendBrief]:
    result = await db.execute(select(TrendBrief).order_by(TrendBrief.created_at.desc()))
    return list(result.scalars().all())


@router.get("/trends/{brief_id}", response_model=TrendBriefRead)
async def get_trend_brief(
    brief_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> TrendBrief:
    brief = await db.get(TrendBrief, brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail="Trend brief not found")
    return brief
