"""CostEvent model — per-agent per-run cost tracking (PRD Section 36)."""

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class CostEvent(Base):
    __tablename__ = "cost_events"

    run_id: Mapped[uuid.UUID] = mapped_column()
    date: Mapped[date] = mapped_column(Date)
    agent_name: Mapped[str] = mapped_column(String(100))

    # Model info
    model_used: Mapped[str] = mapped_column(String(200))
    model_version: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Token usage
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    extended_thinking_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # Cost
    computed_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    wall_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Optimization flags
    batch_api_used: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_cache_hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Reference
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
