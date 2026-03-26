"""Schemas for QAScorecard."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class QAScorecardCreate(BaseModel):
    package_id: uuid.UUID
    dimension_scores: dict[str, int | float]
    model_justifications: dict[str, str] | None = None


class QAScorecardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    package_id: uuid.UUID
    dimension_scores: dict
    composite_score: float | None
    pass_status: str
    model_justifications: dict | None
    operator_overrides: dict | None
    final_verdict: str
    scored_by: str
    created_at: datetime
    updated_at: datetime
