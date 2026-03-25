"""Schemas for CostEvent."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class CostEventCreate(BaseModel):
    run_id: uuid.UUID
    date: date
    agent_name: str
    model_used: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    computed_cost_usd: float = 0.0
    wall_time_seconds: float | None = None
    batch_api_used: bool = False
    prompt_cache_hit_rate: float | None = None
    prompt_id: uuid.UUID | None = None


class CostEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    date: date
    agent_name: str
    model_used: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    computed_cost_usd: float
    wall_time_seconds: float | None
    batch_api_used: bool
    prompt_cache_hit_rate: float | None
    created_at: datetime


class CostSummary(BaseModel):
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    by_agent: dict[str, float]
    by_model: dict[str, float]
    avg_cache_hit_rate: float | None
