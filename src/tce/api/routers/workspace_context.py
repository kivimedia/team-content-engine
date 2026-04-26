"""Per-workspace context CRUD: strategy, portfolio, trend focus.

Lets kmboards (or any other tenant frontend) push tenant-specific overrides
into TCE so the planner pipeline produces tenant-shaped output. When no row
exists for a workspace, agents fall back to the global file defaults.

All routes scope on `workspace_id` (UUID path param). The kmboards
worker-tce sends `X-Workspace-Id` header on pipeline calls; this router
trusts the path param so kmboards onboarding can write before any pipeline
run exists. Add auth via `verify_service_auth` if/when this becomes a
public-facing surface.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.workspace_context import (
    WorkspacePortfolio,
    WorkspaceStrategy,
    WorkspaceTrendFocus,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/workspace-context", tags=["workspace-context"])


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


@router.get("/{workspace_id}/strategy")
async def get_workspace_strategy(
    workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    result = await db.execute(
        select(WorkspaceStrategy).where(WorkspaceStrategy.workspace_id == workspace_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return {"workspace_id": str(workspace_id), "markdown": None, "label": None}
    return {
        "workspace_id": str(workspace_id),
        "markdown": row.markdown,
        "label": row.label,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.put("/{workspace_id}/strategy")
async def put_workspace_strategy(
    workspace_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    markdown = (payload.get("markdown") or "").strip()
    if not markdown:
        raise HTTPException(status_code=400, detail="markdown is required")
    label = payload.get("label")

    result = await db.execute(
        select(WorkspaceStrategy).where(WorkspaceStrategy.workspace_id == workspace_id)
    )
    row = result.scalar_one_or_none()
    if row:
        row.markdown = markdown
        if label is not None:
            row.label = label
    else:
        row = WorkspaceStrategy(workspace_id=workspace_id, markdown=markdown, label=label)
        db.add(row)
    await db.commit()
    logger.info("workspace_context.strategy_saved", workspace_id=str(workspace_id), chars=len(markdown))
    return {"status": "saved", "workspace_id": str(workspace_id)}


@router.delete("/{workspace_id}/strategy")
async def delete_workspace_strategy(
    workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    result = await db.execute(
        select(WorkspaceStrategy).where(WorkspaceStrategy.workspace_id == workspace_id)
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return {"status": "deleted", "workspace_id": str(workspace_id)}


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


@router.get("/{workspace_id}/portfolio")
async def get_workspace_portfolio(
    workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    result = await db.execute(
        select(WorkspacePortfolio).where(WorkspacePortfolio.workspace_id == workspace_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return {"workspace_id": str(workspace_id), "markdown": None, "label": None, "source_url": None}
    return {
        "workspace_id": str(workspace_id),
        "markdown": row.markdown,
        "label": row.label,
        "source_url": row.source_url,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.put("/{workspace_id}/portfolio")
async def put_workspace_portfolio(
    workspace_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    markdown = (payload.get("markdown") or "").strip()
    if not markdown:
        raise HTTPException(status_code=400, detail="markdown is required")
    label = payload.get("label")
    source_url = payload.get("source_url")

    result = await db.execute(
        select(WorkspacePortfolio).where(WorkspacePortfolio.workspace_id == workspace_id)
    )
    row = result.scalar_one_or_none()
    if row:
        row.markdown = markdown
        if label is not None:
            row.label = label
        if source_url is not None:
            row.source_url = source_url
    else:
        row = WorkspacePortfolio(
            workspace_id=workspace_id, markdown=markdown, label=label, source_url=source_url
        )
        db.add(row)
    await db.commit()
    logger.info("workspace_context.portfolio_saved", workspace_id=str(workspace_id), chars=len(markdown))
    return {"status": "saved", "workspace_id": str(workspace_id)}


@router.delete("/{workspace_id}/portfolio")
async def delete_workspace_portfolio(
    workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    result = await db.execute(
        select(WorkspacePortfolio).where(WorkspacePortfolio.workspace_id == workspace_id)
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return {"status": "deleted", "workspace_id": str(workspace_id)}


# ---------------------------------------------------------------------------
# Trend focus
# ---------------------------------------------------------------------------


@router.get("/{workspace_id}/trend-focus")
async def get_workspace_trend_focus(
    workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    result = await db.execute(
        select(WorkspaceTrendFocus).where(WorkspaceTrendFocus.workspace_id == workspace_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return {"workspace_id": str(workspace_id), "queries": None, "label": None}
    return {
        "workspace_id": str(workspace_id),
        "queries": row.queries,
        "label": row.label,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.put("/{workspace_id}/trend-focus")
async def put_workspace_trend_focus(
    workspace_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    queries = payload.get("queries")
    if not isinstance(queries, dict):
        raise HTTPException(
            status_code=400,
            detail="queries must be an object with source_queries / topical_queries arrays",
        )
    source_q = queries.get("source_queries") or []
    topical_q = queries.get("topical_queries") or []
    if not isinstance(source_q, list) or not isinstance(topical_q, list):
        raise HTTPException(status_code=400, detail="source_queries and topical_queries must be arrays")
    if not source_q and not topical_q:
        raise HTTPException(status_code=400, detail="provide at least one query in either array")
    label = payload.get("label")

    normalized = {
        "source_queries": [str(q) for q in source_q if q],
        "topical_queries": [str(q) for q in topical_q if q],
    }

    result = await db.execute(
        select(WorkspaceTrendFocus).where(WorkspaceTrendFocus.workspace_id == workspace_id)
    )
    row = result.scalar_one_or_none()
    if row:
        row.queries = normalized
        if label is not None:
            row.label = label
    else:
        row = WorkspaceTrendFocus(workspace_id=workspace_id, queries=normalized, label=label)
        db.add(row)
    await db.commit()
    logger.info(
        "workspace_context.trend_focus_saved",
        workspace_id=str(workspace_id),
        sources=len(normalized["source_queries"]),
        topicals=len(normalized["topical_queries"]),
    )
    return {"status": "saved", "workspace_id": str(workspace_id)}


@router.delete("/{workspace_id}/trend-focus")
async def delete_workspace_trend_focus(
    workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    result = await db.execute(
        select(WorkspaceTrendFocus).where(WorkspaceTrendFocus.workspace_id == workspace_id)
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return {"status": "deleted", "workspace_id": str(workspace_id)}


# ---------------------------------------------------------------------------
# Combined view (handy for onboarding UI)
# ---------------------------------------------------------------------------


@router.get("/{workspace_id}")
async def get_workspace_context_summary(
    workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Return all 3 override states for a workspace in one call."""
    strategy = (
        await db.execute(
            select(WorkspaceStrategy).where(WorkspaceStrategy.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    portfolio = (
        await db.execute(
            select(WorkspacePortfolio).where(WorkspacePortfolio.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    trend_focus = (
        await db.execute(
            select(WorkspaceTrendFocus).where(WorkspaceTrendFocus.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    return {
        "workspace_id": str(workspace_id),
        "strategy": {
            "configured": strategy is not None,
            "label": strategy.label if strategy else None,
            "chars": len(strategy.markdown) if strategy else 0,
        },
        "portfolio": {
            "configured": portfolio is not None,
            "label": portfolio.label if portfolio else None,
            "chars": len(portfolio.markdown) if portfolio else 0,
            "source_url": portfolio.source_url if portfolio else None,
        },
        "trend_focus": {
            "configured": trend_focus is not None,
            "label": trend_focus.label if trend_focus else None,
            "source_query_count": len((trend_focus.queries or {}).get("source_queries", []))
            if trend_focus
            else 0,
            "topical_query_count": len((trend_focus.queries or {}).get("topical_queries", []))
            if trend_focus
            else 0,
        },
    }
