"""Notification endpoints (PRD Section 43.1)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.schemas.notification import NotificationRead
from tce.services.notifications import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/", response_model=list[NotificationRead])
async def list_unread(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list:
    service = NotificationService(db)
    return await service.get_unread(limit)


@router.get("/count")
async def unread_count(
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = NotificationService(db)
    count = await service.get_unread_count()
    return {"unread": count}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = NotificationService(db)
    await service.mark_read(str(notification_id))
    return {"status": "ok"}


@router.post("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = NotificationService(db)
    count = await service.mark_all_read()
    return {"marked_read": count}
