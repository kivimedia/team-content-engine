"""Shared FastAPI dependencies."""

import uuid

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.db.workspace_filter import set_workspace_context
from tce.services.cost_tracker import CostTracker
from tce.services.prompt_manager import PromptManager
from tce.settings import Settings, settings


async def get_settings() -> Settings:
    return settings


async def get_workspace_id(
    x_workspace_id: str | None = Header(None),
) -> uuid.UUID | None:
    """Extract workspace_id from the X-Workspace-Id header and set the
    ContextVar for automatic query filtering.

    This runs as a FastAPI dependency (same task as the route handler),
    which guarantees ContextVar propagation. Do NOT use middleware for
    this - Starlette's BaseHTTPMiddleware breaks ContextVar propagation.

    Returns None for legacy single-tenant requests (no header).
    When present, all queries and writes are scoped to this workspace.
    """
    if x_workspace_id is None:
        set_workspace_context(None)
        return None
    try:
        ws_id = uuid.UUID(x_workspace_id)
        set_workspace_context(ws_id)
        return ws_id
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Workspace-Id header")


async def verify_service_auth(
    authorization: str | None = Header(None),
) -> None:
    """Verify service-to-service auth when service_key is configured.

    If TCE_SERVICE_KEY is empty, auth is disabled (development mode).
    """
    if not settings.service_key:
        return
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    expected = f"Bearer {settings.service_key}"
    if authorization != expected:
        raise HTTPException(status_code=403, detail="Invalid service key")


async def get_cost_tracker(
    db: AsyncSession = Depends(get_db),
) -> CostTracker:
    """Provide a CostTracker bound to the current DB session."""
    return CostTracker(db)


async def get_prompt_manager(
    db: AsyncSession = Depends(get_db),
) -> PromptManager:
    """Provide a PromptManager bound to the current DB session."""
    return PromptManager(db)
