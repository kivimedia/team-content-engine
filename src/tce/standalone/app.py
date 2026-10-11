"""Private standalone entry point. Legacy owner routes are never mounted here."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.standalone.auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    Principal,
    current_principal,
    hash_password,
    new_token,
    require_scope,
    set_session_cookies,
    sign_in,
    token_hash,
)
from tce.standalone.models import (
    StandaloneAccount,
    StandaloneAPIToken,
    StandaloneConfigRevision,
    StandaloneInvite,
    StandaloneOnboardingDraft,
    StandaloneSession,
    StandaloneWorkspace,
)


class LoginBody(BaseModel):
    email: str
    password: str
    workspace: str


class AcceptInviteBody(BaseModel):
    token: str = Field(min_length=30, max_length=200)
    password: str = Field(min_length=16, max_length=200)


class SourceLane(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(max_length=40)
    filter: str = Field(default="", max_length=4000)
    comments: str = Field(default="", max_length=4000)
    locator: str = Field(default="", max_length=1000)
    enabled: bool = True

    @field_validator("kind")
    @classmethod
    def valid_kind(cls, value: str) -> str:
        if value not in {
            "fathom",
            "commits",
            "ai_news",
            "book",
            "research",
            "course",
            "upload",
            "custom",
        }:
            raise ValueError("Unsupported source kind")
        return value


class RoutineConfig(BaseModel):
    enabled: bool = False
    weekday: int = Field(default=0, ge=0, le=6)
    local_time: str = "09:00"

    @field_validator("local_time")
    @classmethod
    def valid_local_time(cls, value: str) -> str:
        if (
            len(value) != 5
            or value[2] != ":"
            or not (value[:2] + value[3:]).isdigit()
            or int(value[:2]) > 23
            or int(value[3:]) > 59
        ):
            raise ValueError("Choose a local time as HH:MM")
        return value


class ClientConfig(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    timezone: str = Field(default="UTC", max_length=100)
    audience: str = Field(default="", max_length=4000)
    focus: str = Field(default="", max_length=4000)
    voice_notes: str = Field(default="", max_length=8000)
    avoid: str = Field(default="", max_length=4000)
    source_lanes: list[SourceLane] = Field(min_length=3, max_length=3)
    brain_mode: str = "unconfigured"
    brain_model: str = Field(default="claude-sonnet-5", max_length=100)
    routine: RoutineConfig = Field(default_factory=RoutineConfig)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Choose a valid IANA timezone") from exc
        return value

    @field_validator("brain_mode")
    @classmethod
    def valid_brain_mode(cls, value: str) -> str:
        if value not in {"unconfigured", "claude_code", "anthropic_api"}:
            raise ValueError("Choose a supported reasoning connection")
        return value


class ConfigWrite(BaseModel):
    expected_revision: int = Field(ge=0)
    config: ClientConfig


class OnboardingDraftWrite(BaseModel):
    step: int = Field(ge=0, le=6)
    config: ClientConfig


class ConfigRestore(BaseModel):
    expected_revision: int = Field(ge=1)
    restore_revision: int = Field(ge=1)


class TokenCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=6)
    days: int = Field(default=30, ge=1, le=90)


DEFAULT_LANES = [
    {"name": "Source 1", "kind": "custom", "filter": "", "comments": "", "enabled": False},
    {"name": "Source 2", "kind": "custom", "filter": "", "comments": "", "enabled": False},
    {"name": "Source 3", "kind": "custom", "filter": "", "comments": "", "enabled": False},
]
TOKEN_SCOPES = frozenset({"read", "write", "record", "export", "deliver", "worker"})

auth = APIRouter(prefix="/auth")
api = APIRouter(prefix="/api", dependencies=[Depends(current_principal)])


@auth.post("/login")
async def login(body: LoginBody, response: Response, db: AsyncSession = Depends(get_db)):
    _, secret, csrf, principal = await sign_in(db, body.email, body.password, body.workspace)
    set_session_cookies(response, secret, csrf)
    return {
        "email": principal.email,
        "workspace_id": str(principal.workspace_id),
        "role": principal.role,
    }


@auth.post("/accept-invite")
async def accept_invite(
    body: AcceptInviteBody, response: Response, db: AsyncSession = Depends(get_db)
):
    invite = (
        await db.execute(
            select(StandaloneInvite)
            .where(StandaloneInvite.token_hash == token_hash(body.token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if (
        invite is None
        or invite.consumed_at is not None
        or invite.expires_at.replace(tzinfo=UTC) <= now
    ):
        raise HTTPException(status_code=400, detail="Invitation expired or already used")
    account = await db.get(StandaloneAccount, invite.account_id)
    workspace = await db.get(StandaloneWorkspace, invite.workspace_id)
    if account is None or workspace is None or not workspace.active:
        raise HTTPException(status_code=400, detail="Invitation is unavailable")
    account.password_hash = hash_password(body.password)
    account.email_verified_at = now
    invite.consumed_at = now
    _, secret, csrf, principal = await sign_in(db, account.email, body.password, workspace.slug)
    set_session_cookies(response, secret, csrf)
    return {"email": principal.email, "workspace": workspace.slug}


@auth.post("/logout")
async def logout(
    response: Response,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(StandaloneSession).where(
            StandaloneSession.account_id == principal.account_id,
            StandaloneSession.workspace_id == principal.workspace_id,
            StandaloneSession.revoked_at.is_(None),
        )
    )
    for row in rows.scalars():
        row.revoked_at = datetime.now(UTC)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@auth.get("/me")
async def me(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
):
    result = {
        "email": principal.email,
        "workspace_id": str(principal.workspace_id),
        "role": principal.role,
        "scopes": sorted(principal.scopes),
    }
    if principal.token_id:
        token = await db.get(StandaloneAPIToken, principal.token_id)
        expires = token.expires_at if token else None
        result["token_expires_at"] = (
            (
                expires.replace(tzinfo=UTC) if expires.tzinfo is None else expires.astimezone(UTC)
            ).isoformat()
            if expires
            else None
        )
    return result


async def latest_config(db: AsyncSession, ws: uuid.UUID) -> StandaloneConfigRevision | None:
    return (
        await db.execute(
            select(StandaloneConfigRevision)
            .where(StandaloneConfigRevision.workspace_id == ws)
            .order_by(StandaloneConfigRevision.revision.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@api.get("/config")
async def get_config(
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    row = await latest_config(db, principal.workspace_id)
    if row:
        return {"revision": row.revision, "config": row.content, "onboarded": True}
    workspace = await db.get(StandaloneWorkspace, principal.workspace_id)
    return {
        "revision": 0,
        "onboarded": False,
        "config": ClientConfig(
            display_name=workspace.name,
            timezone=workspace.timezone,
            source_lanes=DEFAULT_LANES,
        ).model_dump(),
    }


@api.get("/onboarding/draft")
async def get_onboarding_draft(
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(select(StandaloneOnboardingDraft).where(
            StandaloneOnboardingDraft.workspace_id == principal.workspace_id
        ))
    ).scalar_one_or_none()
    if row is None:
        return {"step": 0, "config": (await get_config(principal, db))["config"]}
    from tce.standalone.secrets import decrypt

    return {"step": row.step, "config": json.loads(decrypt(
        row.encrypted_payload, principal.workspace_id, "onboarding-draft"
    ))}


@api.put("/onboarding/draft")
async def put_onboarding_draft(
    body: OnboardingDraftWrite,
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    from tce.standalone.secrets import encrypt

    row = (
        await db.execute(select(StandaloneOnboardingDraft).where(
            StandaloneOnboardingDraft.workspace_id == principal.workspace_id
        ))
    ).scalar_one_or_none()
    if row is None:
        row = StandaloneOnboardingDraft(workspace_id=principal.workspace_id)
        db.add(row)
    row.step = body.step
    row.encrypted_payload = encrypt(
        json.dumps(body.config.model_dump()), principal.workspace_id, "onboarding-draft"
    )
    return {"step": row.step, "saved": True}


@api.put("/config")
async def put_config(
    body: ConfigWrite,
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    row = await latest_config(db, principal.workspace_id)
    actual = row.revision if row else 0
    if body.expected_revision != actual:
        raise HTTPException(
            status_code=409,
            detail={"message": "Settings changed. Review the latest version.", "revision": actual},
        )
    workspace = await db.get(StandaloneWorkspace, principal.workspace_id)
    workspace.name = body.config.display_name
    workspace.timezone = body.config.timezone
    next_row = StandaloneConfigRevision(
        workspace_id=principal.workspace_id,
        revision=actual + 1,
        content=body.config.model_dump(),
        actor_id=principal.account_id,
        reason="onboarding" if actual == 0 else "settings",
    )
    db.add(next_row)
    draft = (
        await db.execute(select(StandaloneOnboardingDraft).where(
            StandaloneOnboardingDraft.workspace_id == principal.workspace_id
        ))
    ).scalar_one_or_none()
    if draft:
        await db.delete(draft)
    await db.flush()
    return {"revision": next_row.revision, "config": next_row.content}


@api.get("/config/history")
async def config_history(
    principal: Principal = Depends(require_scope("read")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(StandaloneConfigRevision)
            .where(StandaloneConfigRevision.workspace_id == principal.workspace_id)
            .order_by(StandaloneConfigRevision.revision.desc())
        )
    ).scalars()
    return [{"revision": r.revision, "reason": r.reason, "created_at": r.created_at} for r in rows]


@api.post("/config/restore")
async def restore_config(
    body: ConfigRestore,
    principal: Principal = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    latest = await latest_config(db, principal.workspace_id)
    if latest is None or latest.revision != body.expected_revision:
        raise HTTPException(status_code=409, detail="Review the latest settings first")
    old = (
        await db.execute(
            select(StandaloneConfigRevision).where(
                StandaloneConfigRevision.workspace_id == principal.workspace_id,
                StandaloneConfigRevision.revision == body.restore_revision,
            )
        )
    ).scalar_one_or_none()
    if old is None:
        raise HTTPException(status_code=404, detail="Version not found")
    restored = ClientConfig.model_validate(old.content)
    workspace = await db.get(StandaloneWorkspace, principal.workspace_id)
    workspace.name, workspace.timezone = restored.display_name, restored.timezone
    db.add(
        StandaloneConfigRevision(
            workspace_id=principal.workspace_id,
            revision=latest.revision + 1,
            content=restored.model_dump(),
            actor_id=principal.account_id,
            reason="restore",
        )
    )
    return {"revision": latest.revision + 1, "config": restored.model_dump()}


@api.post("/tokens")
async def create_token(
    body: TokenCreate,
    principal: Principal = Depends(require_scope("tokens")),
    db: AsyncSession = Depends(get_db),
):
    scopes = set(body.scopes)
    if not scopes <= TOKEN_SCOPES:
        raise HTTPException(status_code=422, detail="Unsupported token scope")
    raw = new_token()
    row = StandaloneAPIToken(
        workspace_id=principal.workspace_id,
        account_id=principal.account_id,
        label=body.label,
        scopes=sorted(scopes),
        token_hash=token_hash(raw),
        expires_at=datetime.now(UTC) + timedelta(days=body.days),
    )
    db.add(row)
    await db.flush()
    return {"id": str(row.id), "token": raw, "scopes": row.scopes, "expires_at": row.expires_at}


@api.get("/tokens")
async def list_tokens(
    principal: Principal = Depends(require_scope("tokens")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(StandaloneAPIToken).where(
                StandaloneAPIToken.workspace_id == principal.workspace_id,
                StandaloneAPIToken.account_id == principal.account_id,
                StandaloneAPIToken.revoked_at.is_(None),
            )
        )
    ).scalars()
    return [
        {"id": str(r.id), "label": r.label, "scopes": r.scopes, "expires_at": r.expires_at}
        for r in rows
    ]


@api.delete("/tokens/{token_id}")
async def revoke_token(
    token_id: uuid.UUID,
    principal: Principal = Depends(require_scope("tokens")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(StandaloneAPIToken).where(
                StandaloneAPIToken.id == token_id,
                StandaloneAPIToken.workspace_id == principal.workspace_id,
                StandaloneAPIToken.account_id == principal.account_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Token not found")
    row.revoked_at = datetime.now(UTC)
    return {"ok": True}


@asynccontextmanager
async def client_lifespan(app: FastAPI):
    for name in (
        "TCE_DATABASE_URL",
        "TCE_STANDALONE_STORAGE_DIR",
        "TCE_STANDALONE_ENCRYPTION_KEY",
    ):
        if not os.environ.get(name):
            raise RuntimeError(f"Standalone client configuration is missing {name}")
    yield


def create_standalone_app() -> FastAPI:
    from tce.standalone.delivery import router as delivery_router
    from tce.standalone.jobs import router as jobs_router
    from tce.standalone.live import router as live_router
    from tce.standalone.materials import router as materials_router
    from tce.standalone.recording import router as recording_router
    from tce.standalone.routine import router as routine_router
    from tce.standalone.secrets import router as secrets_router
    from tce.standalone.workflow import router as workflow_router

    app = FastAPI(
        title="TCE for clients",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=client_lifespan,
    )

    @app.middleware("http")
    async def browser_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; media-src 'self' blob:; "
            "connect-src 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.url.path.startswith(("/api/", "/auth/")) or request.url.path in {
            "/app",
            "/",
            "/guide",
        }:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz", include_in_schema=False)
    async def healthz(db: AsyncSession = Depends(get_db)):
        await db.execute(select(1))
        return {"status": "ok"}

    app.include_router(auth)
    app.include_router(api)
    app.include_router(materials_router)
    app.include_router(delivery_router)
    app.include_router(live_router)
    app.include_router(jobs_router)
    app.include_router(recording_router)
    app.include_router(routine_router)
    app.include_router(secrets_router)
    app.include_router(workflow_router)
    web_root = Path(__file__).with_name("web")
    app.mount("/static", StaticFiles(directory=web_root), name="standalone-static")
    asset_version = hashlib.sha256(
        (web_root / "app.css").read_bytes() + (web_root / "app.js").read_bytes()
    ).hexdigest()[:12]
    frontend_html = (web_root / "index.html").read_text(encoding="utf-8")
    frontend_html = frontend_html.replace(
        "/static/app.css", f"/static/app.css?v={asset_version}"
    ).replace("/static/app.js", f"/static/app.js?v={asset_version}")

    @app.get("/app", include_in_schema=False)
    async def frontend():
        return HTMLResponse(frontend_html)

    @app.get("/", include_in_schema=False)
    async def home():
        return HTMLResponse(frontend_html)

    @app.get("/guide", include_in_schema=False)
    async def client_guide():
        return HTMLResponse((web_root / "guide.html").read_text(encoding="utf-8"))

    return app


app = create_standalone_app()
