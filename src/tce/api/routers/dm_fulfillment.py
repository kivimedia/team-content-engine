"""DM fulfillment log endpoints (PRD Section 24.4)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.dm_fulfillment import DMFulfillmentLog
from tce.schemas.dm_fulfillment import (
    DMFulfillmentCreate,
    DMFulfillmentRead,
    DMFulfillmentUpdate,
)

router = APIRouter(prefix="/dm-fulfillment", tags=["dm-fulfillment"])


@router.get("/", response_model=list[DMFulfillmentRead])
async def list_logs(
    status: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[DMFulfillmentLog]:
    query = select(DMFulfillmentLog).order_by(
        DMFulfillmentLog.created_at.desc()
    )
    if status:
        query = query.where(DMFulfillmentLog.status == status)
    if keyword:
        query = query.where(DMFulfillmentLog.cta_keyword == keyword)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/", response_model=DMFulfillmentRead)
async def create_log(
    data: DMFulfillmentCreate,
    db: AsyncSession = Depends(get_db),
) -> DMFulfillmentLog:
    log = DMFulfillmentLog(**data.model_dump())
    db.add(log)
    await db.flush()
    return log


@router.get("/{log_id}", response_model=DMFulfillmentRead)
async def get_log(
    log_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> DMFulfillmentLog:
    log = await db.get(DMFulfillmentLog, log_id)
    if not log:
        raise HTTPException(404, "Log not found")
    return log


@router.patch("/{log_id}", response_model=DMFulfillmentRead)
async def update_log(
    log_id: uuid.UUID,
    data: DMFulfillmentUpdate,
    db: AsyncSession = Depends(get_db),
) -> DMFulfillmentLog:
    log = await db.get(DMFulfillmentLog, log_id)
    if not log:
        raise HTTPException(404, "Log not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(log, key, value)
    await db.flush()
    return log


@router.get("/pending/count")
async def pending_count(
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import func

    result = await db.execute(
        select(func.count())
        .select_from(DMFulfillmentLog)
        .where(DMFulfillmentLog.status == "pending")
    )
    return {"pending": result.scalar_one()}
