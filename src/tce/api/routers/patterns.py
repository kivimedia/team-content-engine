"""Pattern template endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.pattern_template import PatternTemplate
from tce.schemas.pattern_template import PatternTemplateCreate, PatternTemplateRead

router = APIRouter(prefix="/patterns", tags=["patterns"])


@router.post("/templates", response_model=PatternTemplateRead)
async def create_template(
    data: PatternTemplateCreate,
    db: AsyncSession = Depends(get_db),
) -> PatternTemplate:
    template = PatternTemplate(**data.model_dump())
    db.add(template)
    await db.flush()
    return template


@router.get("/templates", response_model=list[PatternTemplateRead])
async def list_templates(
    family: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[PatternTemplate]:
    query = select(PatternTemplate).order_by(PatternTemplate.template_family)
    if family:
        query = query.where(PatternTemplate.template_family == family)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/templates/{template_id}", response_model=PatternTemplateRead)
async def get_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PatternTemplate:
    template = await db.get(PatternTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template
