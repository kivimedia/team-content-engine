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

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState

from tce.db.base import Base

# Thread-local (actually coroutine-local) workspace context
_workspace_id_var: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "workspace_id", default=None
)

# Models that should NOT be filtered by workspace_id (global/operational tables)
GLOBAL_TABLES = frozenset({
    "cost_events",
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
    """SQLAlchemy event listener that adds workspace_id filter to SELECT queries."""
    ws_id = _workspace_id_var.get()
    if ws_id is None:
        return

    if not execute_state.is_select:
        return

    # Get the mapper entities being queried
    for mapper in execute_state.all_mappers:
        table_name = mapper.local_table.name
        if table_name in GLOBAL_TABLES:
            continue
        if hasattr(mapper.class_, "workspace_id"):
            execute_state.statement = execute_state.statement.filter(
                mapper.class_.workspace_id == ws_id
            )


def install_workspace_filter(session_factory: object) -> None:
    """Install the workspace filter event listener on a session factory.

    Call this once at app startup.
    """
    event.listen(session_factory, "do_orm_execute", _apply_workspace_filter)
