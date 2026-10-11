"""A client's own Anthropic API connection. No owner key or paid fallback."""

from __future__ import annotations

import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.standalone.models import StandaloneConfigRevision, StandaloneSecret
from tce.standalone.secrets import decrypt


async def client_config(db: AsyncSession, workspace_id: uuid.UUID) -> dict:
    row = (
        await db.execute(
            select(StandaloneConfigRevision)
            .where(StandaloneConfigRevision.workspace_id == workspace_id)
            .order_by(StandaloneConfigRevision.revision.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=409, detail="Complete onboarding first")
    return row.content


async def ask_brain(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    system: str,
    prompt: str,
    *,
    web_search: bool = False,
    max_tokens: int = 2400,
) -> str:
    config = await client_config(db, workspace_id)
    if config.get("brain_mode") != "anthropic_api":
        raise HTTPException(
            status_code=409,
            detail=(
                "Connect a client-owned Anthropic API key for web generation, "
                "or use terminal mode with Claude Code"
            ),
        )
    secret = (
        await db.execute(
            select(StandaloneSecret).where(
                StandaloneSecret.workspace_id == workspace_id,
                StandaloneSecret.kind == "anthropic_api",
            )
        )
    ).scalar_one_or_none()
    if secret is None or secret.verified_at is None:
        raise HTTPException(
            status_code=409, detail="Verify the Anthropic API connection in Settings"
        )
    key = decrypt(secret.encrypted_value, workspace_id, "anthropic_api")
    payload = {
        "model": config.get("brain_model") or "claude-sonnet-5",
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    if web_search:
        payload["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                json=payload,
            )
        if response.status_code != 200:
            raise HTTPException(
                status_code=503,
                detail=f"Client reasoning connection returned HTTP {response.status_code}",
            )
        body = response.json()
        text = "\n".join(
            part.get("text", "")
            for part in body.get("content", [])
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
        if not text:
            raise HTTPException(
                status_code=503, detail="Client reasoning connection returned no text"
            )
        return text
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503, detail="Client reasoning connection is unavailable"
        ) from exc
