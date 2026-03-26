"""Admin endpoints — seeding, maintenance, agent config."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.services.seed import seed_database

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/seed")
async def trigger_seed(db: AsyncSession = Depends(get_db)) -> dict:
    """Manually seed the database with default data. Idempotent."""
    counts = await seed_database(db)
    return {"status": "ok", "seeded": counts}


@router.get("/agents")
async def list_agents() -> list[dict[str, Any]]:
    """List all registered agents and their current model assignments."""
    from tce.agents.registry import _registry

    agents = []
    for name, cls in sorted(_registry.items()):
        agents.append({
            "name": name,
            "model": cls.default_model,
            "class": cls.__name__,
        })
    return agents


class AgentModelUpdate(BaseModel):
    model: str


@router.patch("/agents/{agent_name}/model")
async def update_agent_model(agent_name: str, data: AgentModelUpdate) -> dict[str, str]:
    """Change the LLM model for an agent at runtime (no restart needed)."""
    from tce.agents.registry import _registry

    ALLOWED_MODELS = {
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
    }
    if data.model not in ALLOWED_MODELS:
        from fastapi import HTTPException
        raise HTTPException(400, f"Invalid model. Allowed: {sorted(ALLOWED_MODELS)}")

    if agent_name not in _registry:
        from fastapi import HTTPException
        raise HTTPException(404, f"Agent '{agent_name}' not found")

    old_model = _registry[agent_name].default_model
    _registry[agent_name].default_model = data.model
    return {"agent": agent_name, "old_model": old_model, "new_model": data.model}
