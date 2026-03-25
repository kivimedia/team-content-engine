"""PromptVersion model — versioned agent prompts (PRD Section 39)."""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    agent_name: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer)
    prompt_text: Mapped[str] = mapped_column(Text)

    # Template variables
    variables: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # Model target
    model_target: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # draft/active/retired

    # A/B testing
    ab_test_group: Mapped[str | None] = mapped_column(String(50), nullable=True)
    performance_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Authorship
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
