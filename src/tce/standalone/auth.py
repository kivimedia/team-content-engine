"""Session and scoped-token authentication for the standalone app."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.db.workspace_filter import get_workspace_context, set_workspace_context
from tce.standalone.models import (
    StandaloneAccount,
    StandaloneAPIToken,
    StandaloneMembership,
    StandaloneSession,
    StandaloneWorkspace,
)

SESSION_HOURS = 24
SESSION_COOKIE = "tce_client_session"
CSRF_COOKIE = "tce_client_csrf"
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(48)


def _utc(value: datetime) -> datetime:
    """SQLite drops offsets; Postgres retains them."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def hash_password(password: str) -> str:
    if len(password) < 16:
        raise ValueError("Password must be at least 16 characters")
    salt = secrets.token_bytes(24)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256" or int(iterations) < 600_000:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Principal:
    account_id: uuid.UUID
    workspace_id: uuid.UUID
    email: str
    role: str
    scopes: frozenset[str]
    token_id: uuid.UUID | None = None


async def _account_membership(
    db: AsyncSession, account_id: uuid.UUID, workspace_id: uuid.UUID
) -> tuple[StandaloneAccount, StandaloneMembership, StandaloneWorkspace]:
    account = await db.get(StandaloneAccount, account_id)
    membership = (
        await db.execute(
            select(StandaloneMembership).where(
                StandaloneMembership.account_id == account_id,
                StandaloneMembership.workspace_id == workspace_id,
                StandaloneMembership.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    workspace = await db.get(StandaloneWorkspace, workspace_id)
    if (
        account is None
        or account.disabled_at is not None
        or account.email_verified_at is None
        or membership is None
        or workspace is None
        or not workspace.active
    ):
        raise HTTPException(status_code=401, detail="Account access is unavailable")
    return account, membership, workspace


async def current_principal(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AsyncGenerator[Principal, None]:
    authorization = request.headers.get("authorization", "")
    cookie = request.cookies.get(SESSION_COOKIE)
    if authorization and cookie:
        raise HTTPException(status_code=401, detail="Choose one authentication method")
    now = datetime.now(UTC)
    if authorization.startswith("Bearer "):
        raw = authorization[7:]
        row = (
            await db.execute(
                select(StandaloneAPIToken).where(StandaloneAPIToken.token_hash == token_hash(raw))
            )
        ).scalar_one_or_none()
        if row is None or row.revoked_at or (row.expires_at and _utc(row.expires_at) <= now):
            raise HTTPException(status_code=401, detail="Invalid API token")
        account, membership, _ = await _account_membership(db, row.account_id, row.workspace_id)
        principal = Principal(
            account.id,
            row.workspace_id,
            account.email,
            membership.role,
            frozenset(row.scopes or []),
            row.id,
        )
    elif cookie:
        row = (
            await db.execute(
                select(StandaloneSession).where(StandaloneSession.token_hash == token_hash(cookie))
            )
        ).scalar_one_or_none()
        if row is None or row.revoked_at or _utc(row.expires_at) <= now:
            raise HTTPException(status_code=401, detail="Session expired")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get("x-tce-csrf", "")
            if not csrf or not hmac.compare_digest(token_hash(csrf), row.csrf_hash):
                raise HTTPException(status_code=403, detail="CSRF token required")
        account, membership, _ = await _account_membership(db, row.account_id, row.workspace_id)
        principal = Principal(
            account.id,
            row.workspace_id,
            account.email,
            membership.role,
            frozenset({"read", "write", "record", "export", "deliver", "tokens"}),
        )
    else:
        raise HTTPException(status_code=401, detail="Sign in required")

    claimed = request.headers.get("x-workspace-id")
    if claimed and claimed != str(principal.workspace_id):
        raise HTTPException(status_code=403, detail="Another workspace is not available")
    prior_workspace = get_workspace_context()
    set_workspace_context(principal.workspace_id)
    try:
        yield principal
    finally:
        set_workspace_context(prior_workspace)


def require_scope(scope: str):
    async def check(principal: Principal = Depends(current_principal)) -> Principal:
        if scope not in principal.scopes:
            raise HTTPException(status_code=403, detail=f"Scope {scope} required")
        return principal

    return check


async def sign_in(
    db: AsyncSession, email: str, password: str, workspace_slug: str
) -> tuple[StandaloneSession, str, str, Principal]:
    generic = HTTPException(status_code=401, detail="Email, password or workspace is incorrect")
    account = (
        await db.execute(
            select(StandaloneAccount).where(StandaloneAccount.email == email.strip().lower())
        )
    ).scalar_one_or_none()
    # Perform a real hash even for unknown users to reduce timing differences.
    dummy = "pbkdf2_sha256$600000$" + "0" * 48 + "$" + "0" * 64
    valid = verify_password(password, account.password_hash if account else dummy)
    now = datetime.now(UTC)
    if account is None or not valid:
        if account is not None:
            account.failed_logins += 1
            if account.failed_logins >= MAX_FAILED_LOGINS:
                account.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                account.failed_logins = 0
            await db.commit()
        raise generic
    if account.locked_until and _utc(account.locked_until) > now:
        raise HTTPException(status_code=429, detail="Try again later")
    workspace = (
        await db.execute(
            select(StandaloneWorkspace).where(StandaloneWorkspace.slug == workspace_slug)
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise generic
    _, membership, _ = await _account_membership(db, account.id, workspace.id)
    account.failed_logins = 0
    account.locked_until = None
    secret, csrf = new_token(), new_token()
    session = StandaloneSession(
        workspace_id=workspace.id,
        account_id=account.id,
        token_hash=token_hash(secret),
        csrf_hash=token_hash(csrf),
        expires_at=now + timedelta(hours=SESSION_HOURS),
    )
    db.add(session)
    await db.flush()
    principal = Principal(
        account.id,
        workspace.id,
        account.email,
        membership.role,
        frozenset({"read", "write", "record", "export", "deliver", "tokens"}),
    )
    return session, secret, csrf, principal


def set_session_cookies(response, secret: str, csrf: str) -> None:
    secure = os.getenv("TCE_STANDALONE_INSECURE_DEV_COOKIES") != "1"
    response.set_cookie(
        SESSION_COOKIE,
        secret,
        httponly=True,
        secure=secure,
        samesite="strict",
        max_age=SESSION_HOURS * 3600,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=False,
        secure=secure,
        samesite="strict",
        max_age=SESSION_HOURS * 3600,
        path="/",
    )
