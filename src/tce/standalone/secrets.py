"""Workspace-bound provider credentials with authenticated encryption."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import UTC, datetime

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.standalone.auth import Principal, current_principal, require_scope
from tce.standalone.models import StandaloneSecret

router = APIRouter(prefix="/api/secrets", dependencies=[Depends(current_principal)])
KINDS = frozenset({"openai_live", "anthropic_api", "fathom", "github"})


def _cipher() -> AESGCM:
    raw = os.environ.get("TCE_STANDALONE_ENCRYPTION_KEY", "")
    try:
        key = base64.b64decode(raw, validate=True)
    except ValueError:
        key = b""
    if len(key) != 32:
        raise HTTPException(status_code=503, detail="Credential vault is not configured")
    return AESGCM(key)


def _aad(workspace_id, kind: str) -> bytes:
    return f"tce-standalone:{workspace_id}:{kind}".encode()


def encrypt(value: str, workspace_id, kind: str) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + _cipher().encrypt(nonce, value.encode(), _aad(workspace_id, kind))


def decrypt(value: bytes, workspace_id, kind: str) -> str:
    try:
        return _cipher().decrypt(value[:12], value[12:], _aad(workspace_id, kind)).decode()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Credential cannot be opened") from exc


class SecretWrite(BaseModel):
    value: str = Field(min_length=8, max_length=1000)


async def _verify(kind: str, value: str) -> bool:
    """Read-only provider probe. Never transmit a secret to a different provider."""
    if kind not in {"openai_live", "anthropic_api"}:
        return False
    if kind == "openai_live":
        url = "https://api.openai.com/v1/models"
        headers = {"Authorization": f"Bearer {value}"}
    else:
        url = "https://api.anthropic.com/v1/models"
        headers = {"x-api-key": value, "anthropic-version": "2023-06-01"}
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.get(url, headers=headers)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


@router.get("")
async def list_secrets(
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(StandaloneSecret).where(StandaloneSecret.workspace_id == principal.workspace_id)
        )
    ).scalars()
    return [
        {"kind": row.kind, "fingerprint": row.fingerprint, "verified": bool(row.verified_at)}
        for row in rows
    ]


@router.put("/{kind}")
async def put_secret(
    kind: str,
    body: SecretWrite,
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail="Connection type not found")
    value = body.value.strip()
    verified = await _verify(kind, value)
    row = (
        await db.execute(
            select(StandaloneSecret).where(
                StandaloneSecret.workspace_id == principal.workspace_id,
                StandaloneSecret.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = StandaloneSecret(workspace_id=principal.workspace_id, kind=kind)
        db.add(row)
    row.encrypted_value = encrypt(value, principal.workspace_id, kind)
    row.fingerprint = hashlib.sha256(value.encode()).hexdigest()[:12]
    row.verified_at = datetime.now(UTC) if verified else None
    return {"kind": kind, "fingerprint": row.fingerprint, "verified": verified}


@router.delete("/{kind}")
async def delete_secret(
    kind: str,
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(StandaloneSecret).where(
                StandaloneSecret.workspace_id == principal.workspace_id,
                StandaloneSecret.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    await db.delete(row)
    return {"ok": True}
