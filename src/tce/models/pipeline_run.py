"""PipelineRun model - persists pipeline execution history."""

import uuid
from datetime import datetime

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(unique=True, default=uuid.uuid4)
    workflow: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="running")
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    step_results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    step_errors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    external_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
    )
