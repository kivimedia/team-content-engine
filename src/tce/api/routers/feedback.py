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


@router.get("/insights")
async def get_learning_insights(db: AsyncSession = Depends(get_db)) -> dict:
    """Get latest learning loop results and system version history."""
    from tce.models.pipeline_run import PipelineRun
    from tce.models.system_version import SystemVersion

    # Latest learning loop pipeline runs
    runs_result = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.workflow == "weekly_learning")
        .order_by(PipelineRun.started_at.desc())
        .limit(5)
    )
    runs = runs_result.scalars().all()

    # System version history
    versions_result = await db.execute(
        select(SystemVersion).order_by(SystemVersion.created_at.desc()).limit(20)
    )
    versions = versions_result.scalars().all()

    # Recent feedback summary
    feedback_result = await db.execute(
        select(OperatorFeedback).order_by(OperatorFeedback.created_at.desc()).limit(20)
    )
    recent_feedback = feedback_result.scalars().all()

    tag_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for fb in recent_feedback:
        action_counts[fb.action_taken] = action_counts.get(fb.action_taken, 0) + 1
        for tag in fb.feedback_tags or []:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return {
        "learning_runs": [
            {
                "run_id": str(r.run_id),
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "recommendations": (r.step_results or {}).get("learning_loop", {}).get("weekly_recommendations", {}),
                "cost_usd": r.total_cost_usd,
            }
            for r in runs
        ],
        "system_versions": [
            {
                "id": str(v.id),
                "corpus_version": v.corpus_version,
                "template_library_version": v.template_library_version,
                "house_voice_version": v.house_voice_version,
                "scoring_config_version": v.scoring_config_version,
                "change_type": v.change_type,
                "change_description": v.change_description,
                "changed_by": v.changed_by,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ],
        "feedback_summary": {
            "total_recent": len(recent_feedback),
            "action_counts": action_counts,
            "tag_frequency": dict(sorted(tag_counts.items(), key=lambda x: -x[1])),
        },
    }
