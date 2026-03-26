"""Audit log model (PRD Section 25, 26).

Tracks all significant system actions for auditability.
"""

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    # Who
    actor: Mapped[str] = mapped_column(String(100))  # operator / system / agent_name
    actor_type: Mapped[str] = mapped_column(String(20))  # user / system / agent

    # What (approve / reject / publish / override / etc.)
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Details
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Context
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
