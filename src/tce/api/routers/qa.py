"""QA scorecard endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.qa_scorecard import QAScorecard
from tce.schemas.qa_scorecard import QAScorecardRead

router = APIRouter(prefix="/qa", tags=["qa"])


@router.get("/scorecards", response_model=list[QAScorecardRead])
async def list_scorecards(db: AsyncSession = Depends(get_db)) -> list[QAScorecard]:
    result = await db.execute(
        select(QAScorecard).order_by(QAScorecard.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/scorecards/{scorecard_id}", response_model=QAScorecardRead)
async def get_scorecard(
    scorecard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> QAScorecard:
    sc = await db.get(QAScorecard, scorecard_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    return sc


@router.get("/scorecards/package/{package_id}", response_model=QAScorecardRead)
async def get_scorecard_by_package(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> QAScorecard:
    result = await db.execute(
        select(QAScorecard).where(QAScorecard.package_id == package_id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        raise HTTPException(status_code=404, detail="Scorecard not found for this package")
    return sc
