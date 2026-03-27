"""DM fulfillment log endpoints (PRD Section 24.4)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
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
    query = select(DMFulfillmentLog).order_by(DMFulfillmentLog.created_at.desc())
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


# --- GAP-03: Facebook Webhook for CTA comment detection ---


@router.get("/webhook/facebook")
async def verify_facebook_webhook(
    request: Request,
) -> Any:
    """Facebook webhook verification (GET).

    Facebook sends hub.mode, hub.verify_token, hub.challenge as query params
    to verify the endpoint before enabling the subscription.
    """
    from tce.db.session import async_session
    from tce.services.cta_fulfillment import CTAFulfillmentService

    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    async with async_session() as db:
        service = CTAFulfillmentService(db)
        result = await service.verify_facebook_webhook(mode, token, challenge)
        if result:
            return PlainTextResponse(result)
    raise HTTPException(403, "Verification failed")


@router.post("/webhook/facebook")
async def handle_facebook_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive Facebook comment notifications and process CTA keywords.

    Facebook sends a POST when a page comment is made. We look for
    comments that match active CTA keywords and fire DMs to the commenter.
    """
    from tce.services.cta_fulfillment import CTAFulfillmentService

    payload = await request.json()
    service = CTAFulfillmentService(db)
    results = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if change.get("field") == "feed" and value.get("item") == "comment":
                result = await service.process_facebook_comment(
                    comment_id=value.get("comment_id", ""),
                    commenter_id=value.get("from", {}).get("id", ""),
                    comment_text=value.get("message", ""),
                    post_id=value.get("post_id", ""),
                )
                results.append(result)

    return {"processed": len(results), "results": results}
