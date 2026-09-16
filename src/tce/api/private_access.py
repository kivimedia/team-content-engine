"""Fail-closed access for private evidence, editorial, production and LLM-job routes.

Legacy TCE routes are open and tolerate a missing workspace. These routes carry
raw transcripts, commit diffs and client context, so they:

1. refuse to serve at all unless TCE_PRIVATE_ACCESS_KEY is configured (503),
2. require that key, either as `Authorization: Bearer <key>` (workers, KMHub)
   or `X-TCE-Editor-Key: <key>` (injected by the authenticated reverse proxy
   in front of the dashboard), compared in constant time,
3. resolve a NON-NULL workspace: X-Workspace-Id header, else
   TCE_EDITOR_DEFAULT_WORKSPACE_ID, else 400.

Queries in these routers must filter `Model.workspace_id == workspace_id`
explicitly. Never rely on the global filter, which also returns NULL rows.
"""

from __future__ import annotations

import hmac
import uuid

from fastapi import Header, HTTPException

from tce.db.workspace_filter import set_workspace_context
from tce.settings import settings


def _key_matches(candidate: str | None) -> bool:
    expected = settings.private_access_key.get_secret_value()
    if not expected or not candidate:
        return False
    return hmac.compare_digest(candidate.encode(), expected.encode())


async def require_private_access(
    authorization: str | None = Header(None),
    x_tce_editor_key: str | None = Header(None),
) -> None:
    if not settings.private_access_key.get_secret_value():
        raise HTTPException(status_code=503, detail="Private access is not configured")
    bearer = None
    if authorization and authorization.startswith("Bearer "):
        bearer = authorization[len("Bearer ") :]
    if _key_matches(bearer) or _key_matches(x_tce_editor_key):
        return
    raise HTTPException(status_code=401, detail="Private access key required")


async def require_private_workspace(
    authorization: str | None = Header(None),
    x_tce_editor_key: str | None = Header(None),
    x_workspace_id: str | None = Header(None),
) -> uuid.UUID:
    await require_private_access(authorization, x_tce_editor_key)
    raw = x_workspace_id or settings.editor_default_workspace_id
    if not raw:
        raise HTTPException(status_code=400, detail="Workspace is required")
    try:
        ws = uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace id") from exc
    set_workspace_context(ws)
    return ws
