"""Document ingestion service — parses uploaded files into SourceDocument records."""

from __future__ import annotations

from typing import Any

import docx
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.source_document import SourceDocument


class DocumentIngestService:
    """Handle document uploads and text extraction."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def ingest_docx(self, file_path: str, file_name: str) -> dict[str, Any]:
        """Parse a DOCX file and create a SourceDocument record."""
        doc = docx.Document(file_path)

        # Extract all text
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        full_text = "\n\n".join(paragraphs)

        # Count pages (approximate from paragraph count)
        approx_pages = max(1, len(paragraphs) // 20)

        # Create source document record
        source_doc = SourceDocument(
            file_name=file_name,
            file_type="docx",
            language="he",  # Hebrew corpus default
            pages=approx_pages,
            metadata_={
                "paragraph_count": len(paragraphs),
                "char_count": len(full_text),
                "word_count": len(full_text.split()),
            },
        )
        self.db.add(source_doc)
        await self.db.flush()

        return {
            "document_id": str(source_doc.id),
            "document_text": full_text,
            "file_name": file_name,
            "paragraph_count": len(paragraphs),
            "approx_pages": approx_pages,
        }

    async def ingest_text(self, text: str, file_name: str) -> dict[str, Any]:
        """Ingest raw text content."""
        source_doc = SourceDocument(
            file_name=file_name,
            file_type="text",
            language="en",
            metadata_={
                "char_count": len(text),
                "word_count": len(text.split()),
            },
        )
        self.db.add(source_doc)
        await self.db.flush()

        return {
            "document_id": str(source_doc.id),
            "document_text": text,
            "file_name": file_name,
        }
