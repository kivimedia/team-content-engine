"""Shared FastAPI dependencies."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.services.cost_tracker import CostTracker
from tce.services.prompt_manager import PromptManager
from tce.settings import Settings, settings


async def get_settings() -> Settings:
    return settings


async def get_cost_tracker(db: AsyncSession = None) -> AsyncGenerator[CostTracker, None]:  # type: ignore[assignment]
    """Yield a CostTracker. Use with Depends(get_db) for the session."""
    # This is composed in route handlers with the db dependency
    pass


async def get_prompt_manager(db: AsyncSession = None) -> AsyncGenerator[PromptManager, None]:  # type: ignore[assignment]
    pass
