"""Prompt version management endpoints (PRD Section 39)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.schemas.prompt_version import PromptVersionCreate, PromptVersionRead
from tce.services.prompt_manager import PromptManager

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("/{agent_name}", response_model=list[PromptVersionRead])
async def list_prompt_versions(
    agent_name: str,
    db: AsyncSession = Depends(get_db),
) -> list:
    manager = PromptManager(db)
    return await manager.list_versions(agent_name)


@router.get("/{agent_name}/active", response_model=PromptVersionRead | None)
async def get_active_prompt(
    agent_name: str,
    db: AsyncSession = Depends(get_db),
):
    manager = PromptManager(db)
    return await manager.get_active(agent_name)


@router.post("/{agent_name}", response_model=PromptVersionRead)
async def create_prompt_version(
    agent_name: str,
    data: PromptVersionCreate,
    db: AsyncSession = Depends(get_db),
):
    manager = PromptManager(db)
    return await manager.create_version(
        agent_name=agent_name,
        prompt_text=data.prompt_text,
        variables=data.variables,
        model_target=data.model_target,
        created_by=data.created_by,
    )


class RollbackRequest(BaseModel):
    target_version: int


@router.post("/{agent_name}/rollback", response_model=PromptVersionRead)
async def rollback_prompt(
    agent_name: str,
    data: RollbackRequest,
    db: AsyncSession = Depends(get_db),
):
    manager = PromptManager(db)
    result = await manager.rollback(agent_name, data.target_version)
    if not result:
        raise HTTPException(status_code=404, detail=f"Version {data.target_version} not found")
    return result
