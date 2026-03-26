"""System versioning (PRD Section 16.3).

Tracks corpus_version, template_library_version, house_voice_version,
and scoring_config_version as a single versioned config record.
"""

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class SystemVersion(Base):
    __tablename__ = "system_versions"

    # Version numbers (auto-incremented per domain)
    corpus_version: Mapped[int] = mapped_column(Integer, default=1)
    template_library_version: Mapped[int] = mapped_column(Integer, default=1)
    house_voice_version: Mapped[int] = mapped_column(Integer, default=1)
    scoring_config_version: Mapped[int] = mapped_column(Integer, default=1)

    # What changed
    change_type: Mapped[str] = mapped_column(String(50))  # corpus/template/voice/scoring
    change_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Snapshot of config at this version
    config_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
