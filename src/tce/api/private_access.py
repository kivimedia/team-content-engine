"""Fail-closed access for private evidence, editorial, production and LLM-job routes.

Legacy TCE routes are open and tolerate a missing workspace. These routes carry
raw transcripts, commit diffs and client context, so they:

1. refuse to serve at all unless TCE_PRIVATE_ACCESS_KEY is configured (503),
2. require that key, either as `Authorization: Bearer <key>` (workers, KMHub)
   or `X-TCE-Editor-Key: <key>` (injected by the authenticated reverse proxy
   in front of the dashboard), compared in constant time,
3. resolve a NON-NULL workspace. Bearer callers: X-Workspace-Id header, else
   TCE_EDITOR_DEFAULT_WORKSPACE_ID, else 400. Proxy editors: always the
   configured editor workspace; a different header is 403.

Scoped editors (5-Oct, a client's own login): TCE_EDITOR_WORKSPACE_KEYS maps
further editor keys to ONE workspace each (`<key>:<workspace uuid>,...`). The
proxy injects that key for that client's Basic Auth user. A scoped key:

- works only as X-TCE-Editor-Key, never as a Bearer service key,
- is bound to its workspace; any other X-Workspace-Id is 403,
- is refused on routes that are not workspace scoped (LLM jobs: 403),
- and, through `ScopedEditorGuard`, reaches only the editorial workspace pages
  and the workspace-scoped /production, /editorial and /content-runs APIs. Every
  legacy open route (which would read NULL-workspace owner rows) is 403.

The owner's key and every owner request behave exactly as before.

Queries in these routers must filter `Model.workspace_id == workspace_id`
explicitly. Never rely on the global filter, which also returns NULL rows.
"""

from __future__ import annotations

import hmac
import json
import uuid

from fastapi import Header, HTTPException

from tce.db.workspace_filter import set_workspace_context
from tce.settings import settings


def _key_matches(candidate: str | None) -> bool:
    expected = settings.private_access_key.get_secret_value()
    if not expected or not candidate:
        return False
    return hmac.compare_digest(candidate.encode(), expected.encode())


def scoped_editor_keys() -> list[tuple[str, uuid.UUID]]:
    """TCE_EDITOR_WORKSPACE_KEYS parsed. Bad entries, short keys and a key equal to
    the owner key are skipped (the owner key always stays the owner's)."""
    raw = settings.editor_workspace_keys.get_secret_value() if settings.editor_workspace_keys else ""
    owner = settings.private_access_key.get_secret_value()
    out: list[tuple[str, uuid.UUID]] = []
    for part in (raw or "").split(","):
        key, sep, ws_text = part.strip().rpartition(":")
        key = key.strip()
        if not sep or len(key) < 16 or key == owner:
            continue
        try:
            out.append((key, uuid.UUID(ws_text.strip())))
        except ValueError:
            continue
    return out


def scoped_editor_workspace(candidate: str | None) -> uuid.UUID | None:
    """The workspace a scoped editor key is bound to, or None. Constant time per key."""
    if not candidate:
        return None
    found: uuid.UUID | None = None
    for key, ws in scoped_editor_keys():
        if hmac.compare_digest(candidate.encode(), key.encode()):
            found = ws
    return found


def _authenticate(
    authorization: str | None, x_tce_editor_key: str | None
) -> tuple[str, uuid.UUID | None]:
    """("service", None) for the Bearer key, ("editor", None) for the owner's proxy
    key, ("scoped", ws) for a client's proxy key; raise otherwise."""
    if not settings.private_access_key.get_secret_value():
        raise HTTPException(status_code=503, detail="Private access is not configured")
    if authorization and authorization.startswith("Bearer "):
        if _key_matches(authorization[len("Bearer ") :]):
            return "service", None
    if _key_matches(x_tce_editor_key):
        return "editor", None
    scoped = scoped_editor_workspace(x_tce_editor_key)
    if scoped is not None:
        return "scoped", scoped
    raise HTTPException(status_code=401, detail="Private access key required")


async def require_private_access(
    authorization: str | None = Header(None),
    x_tce_editor_key: str | None = Header(None),
) -> None:
    principal, _ = _authenticate(authorization, x_tce_editor_key)
    if principal == "scoped":
        # These routes are not workspace scoped, so a client login never reaches them.
        raise HTTPException(status_code=403, detail="Not available for this login")


def _parse_workspace(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace id") from exc


async def require_private_workspace(
    authorization: str | None = Header(None),
    x_tce_editor_key: str | None = Header(None),
    x_workspace_id: str | None = Header(None),
) -> uuid.UUID:
    """Service callers (Bearer) choose a workspace with X-Workspace-Id.

    Browser editors authenticate through the proxy, which cannot vouch for a
    header the browser sends, so they are bound to the configured editor
    workspace (the owner) or to their key's workspace (a scoped client login):
    a different X-Workspace-Id is refused.
    """
    principal, scoped_ws = _authenticate(authorization, x_tce_editor_key)
    default = settings.editor_default_workspace_id
    if principal == "scoped":
        ws = scoped_ws
        if x_workspace_id and _parse_workspace(x_workspace_id) != ws:
            raise HTTPException(status_code=403, detail="Editor cannot select another workspace")
    elif principal == "editor":
        if not default:
            raise HTTPException(status_code=400, detail="Editor workspace is not configured")
        ws = _parse_workspace(default)
        if x_workspace_id and _parse_workspace(x_workspace_id) != ws:
            raise HTTPException(status_code=403, detail="Editor cannot select another workspace")
    else:
        raw = x_workspace_id or default
        if not raw:
            raise HTTPException(status_code=400, detail="Workspace is required")
        ws = _parse_workspace(raw)
    set_workspace_context(ws)
    return ws


def refuse_lane_workspace(ws: uuid.UUID | None, what: str, what_he: str | None = None) -> None:
    """409 for a workspace with idea lanes (a client, Matan) on an action that runs on
    the owner's own accounts: posting through the schedule-* skills (his social
    accounts) and the Google export (his Drive, shared with his team). Owner workspaces
    have no lane profile, so for them this returns and nothing changes.

    The one guard (5-Oct, the persona and login reviews merged). Writing a lane
    workspace's script and posts is NOT refused: packets.build_packet sends it to its
    own writer (editorial.lane_packets) and draft_posts to its own Hebrew post writer.
    A Hebrew workspace reads the refusal in Hebrew (`what_he`)."""
    from tce.editorial.lane_profile import profile_for

    if profile_for(ws) is None:
        return
    from tce.db.workspace_filter import workspace_language

    if what_he and workspace_language(ws) == "he":
        detail = (
            f"{what_he} לא זמין כאן: זה רץ על החשבונות של בעל המערכת. את הסרטון מורידים "
            "ואת הפוסט מעתיקים מהכרטיס בספרייה, ומפרסמים מהחשבונות שלך."
        )
    else:
        detail = (
            f"{what} is not available in this workspace: it runs on the owner's own "
            "accounts and voice"
        )
    raise HTTPException(status_code=409, detail=detail)

# --- The scoped-editor fence (pure ASGI, so ContextVars are untouched) ----------

# Pages and assets of the editorial workspace and the recording studio. Exact
# paths, plus the workspace's own sub-pages below.
SCOPED_PAGE_PATHS = frozenset({
    "/", "/record", "/today", "/topics", "/week", "/library", "/settings",
    "/workspace.css", "/workspace.js", "/workspace-sw.js", "/workspace.webmanifest",
    "/talk-voice.js", "/talk-voice.css", "/recording.css", "/recording.js",
    "/i18n-he.js", "/i18n-he.css",
})
SCOPED_PAGE_PREFIXES = ("/topics/", "/scripts/", "/library/")
# Every route under these is workspace scoped (tests/unit/test_scoped_editor_access.py
# walks the real app and fails if one is not).
SCOPED_API_PREFIXES = ("/api/v1/production/", "/api/v1/editorial/", "/api/v1/content-runs")


def scoped_path_allowed(path: str) -> bool:
    if path in SCOPED_PAGE_PATHS or path.startswith(SCOPED_PAGE_PREFIXES):
        return True
    return path.startswith(SCOPED_API_PREFIXES)


class ScopedEditorGuard:
    """Keeps a scoped editor inside its workspace on EVERY route, open ones included.

    Requests without a scoped key pass through untouched, byte for byte.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        keys: list[str] = []
        given_ws = None
        for name, value in scope.get("headers") or []:
            lname = name.lower()
            if lname == b"x-tce-editor-key":
                keys.append(value.decode("latin-1"))
            elif lname == b"x-workspace-id":
                given_ws = value.decode("latin-1")
        if not keys or not scoped_editor_keys():
            return await self.app(scope, receive, send)
        if len(keys) > 1:
            # Review 5-Oct: the app's Header() reads the first value; reading only one
            # here let [scoped key, junk] past the fence. Any scoped key among several
            # is refused outright.
            if any(scoped_editor_workspace(k) is not None for k in keys):
                return await _deny(send, "Not available for this login")
            return await self.app(scope, receive, send)
        key = keys[0]
        if _key_matches(key):
            return await self.app(scope, receive, send)
        ws = scoped_editor_workspace(key)
        if ws is None:
            return await self.app(scope, receive, send)
        if not scoped_path_allowed(scope.get("path") or ""):
            return await _deny(send, "Not available for this login")
        if given_ws is not None:
            try:
                if uuid.UUID(given_ws.strip()) != ws:
                    return await _deny(send, "Editor cannot select another workspace")
            except ValueError:
                return await _deny(send, "Editor cannot select another workspace")
        headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"x-workspace-id"]
        headers.append((b"x-workspace-id", str(ws).encode()))
        scope = dict(scope, headers=headers)
        scope.setdefault("state", {})
        scope["state"]["scoped_workspace_id"] = ws
        return await self.app(scope, receive, send)


async def _deny(send, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start",
        "status": 403,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})
