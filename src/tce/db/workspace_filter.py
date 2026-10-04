"""Automatic workspace_id filtering for multi-tenant queries.

When a workspace_id is set in the request context, all SELECT queries
on models that have a workspace_id column automatically get filtered.
This is the ORM-level equivalent of Supabase RLS.

Usage:
    # In a FastAPI endpoint:
    @router.get("/packages")
    async def list_packages(
        db: AsyncSession = Depends(get_db),
        workspace_id: uuid.UUID | None = Depends(get_workspace_id),
    ):
        set_workspace_context(workspace_id)
        result = await db.execute(select(PostPackage))
        # ^ automatically filtered by workspace_id if set
"""

from __future__ import annotations

import contextvars
import uuid
from typing import Any

from sqlalchemy import Select, case, event, or_, select
from sqlalchemy.orm import ORMExecuteState

from tce.db.base import Base

# Thread-local (actually coroutine-local) workspace context
_workspace_id_var: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "workspace_id", default=None
)

# Models that should NOT be filtered by workspace_id (global/operational tables)
GLOBAL_TABLES = frozenset({
    "system_versions",
    "prompt_versions",
    "audit_logs",
    "notifications",
})


def set_workspace_context(workspace_id: uuid.UUID | None) -> None:
    """Set the workspace_id for the current request context."""
    _workspace_id_var.set(workspace_id)


def get_workspace_context() -> uuid.UUID | None:
    """Get the current workspace_id from request context."""
    return _workspace_id_var.get()


def _apply_workspace_filter(execute_state: ORMExecuteState) -> None:
    """SQLAlchemy event listener that adds workspace_id filter to SELECT queries.

    For JOIN queries, the filter is applied once per joined model (correct
    behavior - both sides of a JOIN should be workspace-scoped).

    For raw text() queries or func() aggregations without an ORM mapper,
    all_mappers is empty and no filter is applied. These queries must add
    workspace_id filtering manually if needed.
    """
    ws_id = _workspace_id_var.get()
    if ws_id is None:
        return

    if not execute_state.is_select:
        return

    # Track which tables we've already filtered to avoid duplicates
    # (can happen if the same model appears multiple times in a query)
    filtered_tables: set[str] = set()

    for mapper in execute_state.all_mappers:
        table_name = mapper.local_table.name
        if table_name in GLOBAL_TABLES or table_name in filtered_tables:
            continue
        if hasattr(mapper.class_, "workspace_id"):
            filtered_tables.add(table_name)
            # Include legacy rows (workspace_id IS NULL) alongside workspace-scoped rows.
            execute_state.statement = execute_state.statement.filter(
                or_(
                    mapper.class_.workspace_id == ws_id,
                    mapper.class_.workspace_id.is_(None),
                )
            )


def install_workspace_filter(session_class: type | object) -> None:
    """Install the workspace filter event listener on the Session class.

    Call this once at app startup. Pass the Session class (not the session factory).
    """
    from sqlalchemy.orm import Session
    event.listen(Session, "do_orm_execute", _apply_workspace_filter)


# Workspaces that belong to the owner (Ziv / Kivi). A pick made with no workspace
# context may read these and the NULL-workspace legacy rows, never a client's.
_OWNER_WORKSPACE_FALLBACK = "30c13a7e-432f-4c3a-bade-52483262d793"


def _parse_uuids(raw: str) -> set[uuid.UUID]:
    out: set[uuid.UUID] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(uuid.UUID(part))
        except ValueError:
            continue
    return out


def owner_workspace_ids() -> set[uuid.UUID]:
    """TCE_OWNER_WORKSPACE_IDS (comma list), else the editor default + the owner fallback."""
    from tce.settings import settings

    configured = _parse_uuids(getattr(settings, "owner_workspace_ids", "") or "")
    if configured:
        return configured
    return _parse_uuids(
        f"{getattr(settings, 'editor_default_workspace_id', '') or ''},{_OWNER_WORKSPACE_FALLBACK}"
    )


SUPPORTED_LANGUAGES = frozenset({"en", "he"})


def workspace_languages() -> dict[uuid.UUID, str]:
    """TCE_WORKSPACE_LANGUAGES parsed: {workspace: language}. Bad entries are skipped."""
    from tce.settings import settings

    out: dict[uuid.UUID, str] = {}
    for part in (getattr(settings, "workspace_languages", "") or "").split(","):
        ws_text, _, code = part.strip().partition(":")
        code = code.strip().lower()
        if code not in SUPPORTED_LANGUAGES:
            continue
        try:
            out[uuid.UUID(ws_text.strip())] = code
        except ValueError:
            continue
    return out


def workspace_language(workspace_id: uuid.UUID | str | None = None) -> str:
    """The content language of a workspace ("en" unless TCE_WORKSPACE_LANGUAGES says
    otherwise). With no workspace given, the one in the request context."""
    ws = workspace_id if workspace_id is not None else get_workspace_context()
    if ws is None:
        return "en"
    try:
        ws = ws if isinstance(ws, uuid.UUID) else uuid.UUID(str(ws))
    except ValueError:
        return "en"
    return workspace_languages().get(ws, "en")


def workspace_scope_clause(model: Any, workspace_id: uuid.UUID | None = None) -> Any:
    """WHERE clause limiting `model` to the rows a pick may see.

    With a workspace: that workspace's rows plus NULL-workspace (global) rows.
    Without one: NULL-workspace rows plus the owner workspaces - never a client's.
    """
    col = model.workspace_id
    if workspace_id is not None:
        return or_(col == workspace_id, col.is_(None))
    return or_(col.is_(None), col.in_(owner_workspace_ids()))


def scoped_rows(model: Any, *where: Any) -> Select:
    """`select(model)` for listing rows, limited like a pick (see workspace_scope_clause)."""
    return select(model).where(workspace_scope_clause(model, get_workspace_context()), *where)


def scoped_pick(model: Any, *where: Any, newest: bool = True) -> Select:
    """`select(model)` for picking ONE profile-like row, workspace-safe.

    Uses the current workspace context. With a context, a row of that workspace
    wins over a global (NULL) row; within a tier the newest wins. Always LIMIT 1,
    so a name shared across workspaces can never raise MultipleResultsFound.
    """
    ws = get_workspace_context()
    stmt = select(model).where(workspace_scope_clause(model, ws), *where)
    order: list[Any] = []
    if ws is not None:
        order.append(case((model.workspace_id == ws, 0), else_=1))
    if newest:
        order.append(model.created_at.desc())
    order.append(model.id)
    return stmt.order_by(*order).limit(1)
