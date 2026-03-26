"""Shared FastAPI dependencies."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.services.cost_tracker import CostTracker
from tce.services.prompt_manager import PromptManager
from tce.settings import Settings, settings


async def get_settings() -> Settings:
    return settings


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
