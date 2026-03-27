"""Operator feedback and learning event endpoints (PRD Section 46)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.learning_event import LearningEvent
from tce.models.operator_feedback import OperatorFeedback
from tce.schemas.learning_event import LearningEventCreate, LearningEventRead
from tce.schemas.operator_feedback import OperatorFeedbackCreate, OperatorFeedbackRead

router = APIRouter(prefix="/feedback", tags=["feedback"])


# Operator feedback
@router.post("/", response_model=OperatorFeedbackRead)
async def create_feedback(
    data: OperatorFeedbackCreate,
    db: AsyncSession = Depends(get_db),
) -> OperatorFeedback:
    feedback = OperatorFeedback(**data.model_dump())
    db.add(feedback)
    await db.flush()
    return feedback


@router.get("/", response_model=list[OperatorFeedbackRead])
async def list_feedback(db: AsyncSession = Depends(get_db)) -> list[OperatorFeedback]:
    result = await db.execute(select(OperatorFeedback).order_by(OperatorFeedback.created_at.desc()))
    return list(result.scalars().all())


@router.get("/package/{package_id}", response_model=OperatorFeedbackRead)
async def get_feedback_by_package(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> OperatorFeedback:
    result = await db.execute(
        select(OperatorFeedback).where(OperatorFeedback.package_id == package_id)
    )
    fb = result.scalar_one_or_none()
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return fb


# Learning events
@router.post("/learning", response_model=LearningEventRead)
async def create_learning_event(
    data: LearningEventCreate,
    db: AsyncSession = Depends(get_db),
) -> LearningEvent:
    event = LearningEvent(**data.model_dump())
    db.add(event)
    await db.flush()
    return event


@router.get("/learning", response_model=list[LearningEventRead])
async def list_learning_events(db: AsyncSession = Depends(get_db)) -> list[LearningEvent]:
    result = await db.execute(select(LearningEvent).order_by(LearningEvent.created_at.desc()))
    return list(result.scalars().all())
