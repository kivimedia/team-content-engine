"""Creator and founder voice profile endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.creator_profile import CreatorProfile
from tce.models.founder_voice_profile import FounderVoiceProfile
from tce.schemas.creator_profile import (
    CreatorProfileCreate,
    CreatorProfileRead,
    CreatorProfileUpdate,
)
from tce.schemas.founder_voice_profile import FounderVoiceProfileCreate, FounderVoiceProfileRead

router = APIRouter(prefix="/profiles", tags=["profiles"])


# Creator profiles
@router.post("/creators", response_model=CreatorProfileRead)
async def create_creator(
    data: CreatorProfileCreate,
    db: AsyncSession = Depends(get_db),
) -> CreatorProfile:
    profile = CreatorProfile(**data.model_dump())
    db.add(profile)
    await db.flush()
    return profile


@router.get("/creators", response_model=list[CreatorProfileRead])
async def list_creators(db: AsyncSession = Depends(get_db)) -> list[CreatorProfile]:
    result = await db.execute(select(CreatorProfile).order_by(CreatorProfile.creator_name))
    return list(result.scalars().all())


@router.get("/creators/{creator_id}", response_model=CreatorProfileRead)
async def get_creator(
    creator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CreatorProfile:
    profile = await db.get(CreatorProfile, creator_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Creator not found")
    return profile


@router.patch("/creators/{creator_id}", response_model=CreatorProfileRead)
async def update_creator(
    creator_id: uuid.UUID,
    data: CreatorProfileUpdate,
    db: AsyncSession = Depends(get_db),
) -> CreatorProfile:
    profile = await db.get(CreatorProfile, creator_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Creator not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    await db.flush()
    return profile


# Founder voice profiles
@router.post("/founder-voice", response_model=FounderVoiceProfileRead)
async def create_founder_voice(
    data: FounderVoiceProfileCreate,
    db: AsyncSession = Depends(get_db),
) -> FounderVoiceProfile:
    profile = FounderVoiceProfile(**data.model_dump())
    db.add(profile)
    await db.flush()
    return profile


@router.get("/founder-voice", response_model=list[FounderVoiceProfileRead])
async def list_founder_voices(db: AsyncSession = Depends(get_db)) -> list[FounderVoiceProfile]:
    result = await db.execute(select(FounderVoiceProfile))
    return list(result.scalars().all())
