"""QAScorecard model — 12-dimension quality scoring (PRD Section 45)."""

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class QAScorecard(Base):
    __tablename__ = "qa_scorecards"

    package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("post_packages.id"), unique=True)

    # Scores: dimension_name -> score (1-10)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Composite
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pass_status: Mapped[str] = mapped_column(String(20), default="pending")  # pass/conditional_pass/fail

    # Justifications: dimension_name -> text
    model_justifications: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Operator overrides: dimension_name -> {score, reason}
    operator_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Final
    final_verdict: Mapped[str] = mapped_column(String(20), default="pending")
    scored_by: Mapped[str] = mapped_column(String(20), default="model")  # model/operator/both

    # Relationships
    post_package: Mapped["PostPackage"] = relationship(back_populates="qa_scorecard")  # noqa: F821
