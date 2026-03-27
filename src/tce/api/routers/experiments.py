"""A/B experiment endpoints (PRD Section 43.2)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.services.ab_testing import EXPERIMENT_TYPES, ABTestingService

router = APIRouter(prefix="/experiments", tags=["experiments"])

# Module-level service (experiments are in-memory for v1)
_service: ABTestingService | None = None


def _get_service(db: AsyncSession = Depends(get_db)) -> ABTestingService:
    global _service
    if _service is None:
        _service = ABTestingService(db)
    _service.db = db
    return _service


class CreateExperimentRequest(BaseModel):
    experiment_type: str
    variants: list[str] = ["A", "B"]
    min_sample_size: int = 10


@router.post("/")
async def create_experiment(
    request: CreateExperimentRequest,
    service: ABTestingService = Depends(_get_service),
) -> dict[str, Any]:
    if request.experiment_type not in EXPERIMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(f"Invalid type: {request.experiment_type}. Valid: {EXPERIMENT_TYPES}"),
        )
    exp = service.create_experiment(
        experiment_type=request.experiment_type,
        variants=request.variants,
        min_sample_size=request.min_sample_size,
    )
    return exp.to_dict()


@router.get("/")
async def list_experiments(
    service: ABTestingService = Depends(_get_service),
) -> list[dict[str, Any]]:
    return service.list_experiments()


@router.get("/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    service: ABTestingService = Depends(_get_service),
) -> dict[str, Any]:
    exp = service.get_experiment(experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return exp.to_dict()


@router.get("/{experiment_id}/results")
async def get_results(
    experiment_id: str,
    service: ABTestingService = Depends(_get_service),
) -> dict[str, Any]:
    return await service.get_experiment_results(experiment_id)


@router.get("/types/available")
async def available_types() -> dict[str, list[str]]:
    return {"experiment_types": EXPERIMENT_TYPES}
