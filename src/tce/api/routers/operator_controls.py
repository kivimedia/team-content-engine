"""Operator control endpoints (PRD Section 4.4)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.services.operator_controls import OperatorControlService

router = APIRouter(prefix="/controls", tags=["operator-controls"])


class TemplateActionRequest(BaseModel):
    template_name: str
    reason: str = ""


class WeightRequest(BaseModel):
    creator_name: str
    weight: float


class PlatformFlagRequest(BaseModel):
    platform: str
    enabled: bool


class SourceActionRequest(BaseModel):
    document_id: str
    reason: str = ""


@router.post("/templates/lock")
async def lock_template(
    request: TemplateActionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = OperatorControlService(db)
    result = await service.lock_template(request.template_name, request.reason)
    if not result:
        raise HTTPException(404, "Template not found")
    return result


@router.post("/templates/unlock")
async def unlock_template(
    request: TemplateActionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = OperatorControlService(db)
    result = await service.unlock_template(request.template_name)
    if not result:
        raise HTTPException(404, "Template not found")
    return result


@router.post("/templates/ban")
async def ban_template(
    request: TemplateActionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = OperatorControlService(db)
    result = await service.ban_template(request.template_name, request.reason)
    if not result:
        raise HTTPException(404, "Template not found")
    return result


@router.post("/sources/approve")
async def approve_source(
    request: SourceActionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = OperatorControlService(db)
    result = await service.approve_source(request.document_id)
    if not result:
        raise HTTPException(404, "Document not found")
    return result


@router.post("/sources/reject")
async def reject_source(
    request: SourceActionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = OperatorControlService(db)
    result = await service.reject_source(request.document_id, request.reason)
    if not result:
        raise HTTPException(404, "Document not found")
    return result


@router.post("/weights")
async def set_weight(
    request: WeightRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = OperatorControlService(db)
    result = await service.set_influence_weight(request.creator_name, request.weight)
    if not result:
        raise HTTPException(404, "Creator not found")
    return result


@router.get("/platforms")
async def get_platform_flags() -> dict[str, bool]:
    return OperatorControlService.get_platform_flags()


@router.post("/platforms")
async def set_platform_flag(
    request: PlatformFlagRequest,
) -> dict[str, Any]:
    return OperatorControlService.set_platform_flag(request.platform, request.enabled)
