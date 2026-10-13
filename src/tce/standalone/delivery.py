"""Explicit send-to-self delivery with a stable idempotency key."""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.standalone.auth import Principal, current_principal, require_scope
from tce.standalone.models import StandaloneDelivery, StandaloneRecording, StandaloneRender
from tce.standalone.recording import _safe_path

router = APIRouter(prefix="/api", dependencies=[Depends(current_principal)])
MAX_ATTACH_BYTES = 25 * 1024 * 1024


class SendBody(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    render_id: uuid.UUID | None = None


def _public(row: StandaloneDelivery) -> dict:
    return {
        "id": str(row.id),
        "recording_id": str(row.upload_id),
        "render_id": str(row.render_id) if row.render_id else None,
        "recipient": row.recipient,
        "status": row.status,
        "attempts": row.attempts,
        "error_code": row.error_code,
        "provider_receipt": row.provider_receipt,
    }


async def _send_provider(payload: dict, idempotency_key: str) -> str:
    key = os.environ.get("TCE_STANDALONE_RESEND_API_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="Email delivery is not configured")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {key}", "Idempotency-Key": idempotency_key},
                json=payload,
            )
        if response.status_code not in {200, 201}:
            raise HTTPException(
                status_code=503, detail=f"Email provider returned HTTP {response.status_code}"
            )
        receipt = str(response.json().get("id") or "")
        if not receipt:
            raise HTTPException(status_code=502, detail="Email provider returned no receipt")
        return receipt
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Email provider is unavailable") from exc


@router.post("/recordings/{recording_id}/send-to-self")
async def send_to_self(
    recording_id: uuid.UUID,
    body: SendBody,
    principal: Principal = Depends(require_scope("deliver")),
    db: AsyncSession = Depends(get_db),
):
    recording = (
        await db.execute(
            select(StandaloneRecording).where(
                StandaloneRecording.id == recording_id,
                StandaloneRecording.workspace_id == principal.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    render = None
    if body.render_id is not None:
        render = (
            await db.execute(
                select(StandaloneRender).where(
                    StandaloneRender.id == body.render_id,
                    StandaloneRender.recording_id == recording_id,
                    StandaloneRender.workspace_id == principal.workspace_id,
                )
            )
        ).scalar_one_or_none()
        if render is None:
            raise HTTPException(status_code=404, detail="Edit version not found")
    elif recording.edited_key:
        render = (
            await db.execute(
                select(StandaloneRender).where(
                    StandaloneRender.workspace_id == principal.workspace_id,
                    StandaloneRender.recording_id == recording_id,
                    StandaloneRender.storage_key == recording.edited_key,
                )
            )
        ).scalar_one_or_none()
        if render is None:
            raise HTTPException(status_code=409, detail="Selected edit is unavailable")
    selected_render_id = render.id if render else None
    existing = (
        await db.execute(
            select(StandaloneDelivery).where(
                StandaloneDelivery.workspace_id == principal.workspace_id,
                StandaloneDelivery.idempotency_key == body.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.upload_id != recording_id or existing.render_id != selected_render_id:
            raise HTTPException(status_code=409, detail="Delivery key belongs to another video")
        return _public(existing)
    sender = os.environ.get("TCE_STANDALONE_FROM_EMAIL", "")
    public_url = os.environ.get("TCE_STANDALONE_PUBLIC_URL", "")
    parsed_url = urlsplit(public_url)
    if (
        not sender
        or parsed_url.scheme != "https"
        or not parsed_url.netloc
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise HTTPException(
            status_code=503, detail="Email sender or public app URL is not configured"
        )
    key = render.storage_key if render else recording.original_key
    path = _safe_path(key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")
    row = StandaloneDelivery(
        workspace_id=principal.workspace_id,
        account_id=principal.account_id,
        upload_id=recording_id,
        render_id=selected_render_id,
        idempotency_key=body.idempotency_key,
        recipient=principal.email,
        status="sending",
        attempts=0,
    )
    db.add(row)
    await db.flush()
    link = f"{public_url.rstrip('/')}/app?recording={recording_id}"
    attached = path.stat().st_size <= MAX_ATTACH_BYTES
    payload = {
        "from": sender,
        "to": [principal.email],
        "subject": "Your TCE video",
        "text": (
            "Your selected video is attached. You can also open your private TCE workspace: " + link
            if attached
            else "Your video is ready. Sign in to your private TCE workspace to download it: "
            + link
        ),
    }
    if attached:
        payload["attachments"] = [
            {
                "filename": f"your-video{path.suffix.lower()}",
                "content": base64.b64encode(path.read_bytes()).decode(),
            }
        ]
    provider_key = f"tce-{principal.workspace_id}-{row.id}"
    for attempt in range(1, 4):
        row.attempts = attempt
        try:
            row.provider_receipt = await _send_provider(payload, provider_key)
            row.status = "sent"
            row.error_code = None
            return _public(row)
        except HTTPException as exc:
            row.error_code = f"provider_{exc.status_code}"
            if attempt < 3:
                await asyncio.sleep(attempt)
    row.status = "failed"
    return _public(row)


@router.get("/deliveries")
async def list_deliveries(
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(StandaloneDelivery)
            .where(
                StandaloneDelivery.workspace_id == principal.workspace_id,
                StandaloneDelivery.account_id == principal.account_id,
            )
            .order_by(StandaloneDelivery.created_at.desc())
        )
    ).scalars()
    return [_public(row) for row in rows]
