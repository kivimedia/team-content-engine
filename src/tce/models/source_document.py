"""SourceDocument model — uploaded corpus files (DOCX, PDF, text)."""

import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class SourceDocument(Base):
    __tablename__ = "source_documents"

    file_name: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(20))  # docx, pdf, text, url
    language: Mapped[str] = mapped_column(String(10), default="he")
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    # Relationships
    post_examples: Mapped[list["PostExample"]] = relationship(  # noqa: F821
        back_populates="source_document", cascade="all, delete-orphan"
    )
