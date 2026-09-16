"""Document ingestion service - parses uploaded files into SourceDocument records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import docx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.source_document import SourceDocument

logger = structlog.get_logger()


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

        # GAP-02: Extract and OCR embedded images
        image_texts = await self._extract_images_ocr(doc)
        if image_texts:
            full_text += "\n\n## OCR from Embedded Images\n\n" + "\n\n".join(image_texts)

        # Count pages (approximate from paragraph count)
        approx_pages = max(1, len(paragraphs) // 20)

        # GAP-04: Upload source DOCX to S3 if configured
        s3_path = None
        try:
            from tce.services.storage import StorageService

            storage = StorageService()
            if storage.configured:
                import uuid as _uuid

                key = f"corpus/{_uuid.uuid4().hex}/{file_name}"
                with open(file_path, "rb") as f:
                    s3_path = await storage.upload(
                        f.read(),
                        key,
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                logger.info("ingest.s3_uploaded", key=key)
        except Exception:
            logger.exception("ingest.s3_upload_failed")

        # Create source document record
        source_doc = SourceDocument(
            file_name=file_name,
            file_type="docx",
            language="he",  # Hebrew corpus default
            pages=approx_pages,
            extracted_text=full_text,
            ingested_at=datetime.now(UTC),
            metadata_={
                "paragraph_count": len(paragraphs),
                "char_count": len(full_text),
                "word_count": len(full_text.split()),
                "images_ocr_count": len(image_texts),
                "s3_path": s3_path,
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
            "images_ocr_count": len(image_texts),
        }

    async def _extract_images_ocr(self, doc: docx.Document) -> list[str]:
        """Image OCR is disabled under the subscription-only LLM policy.

        It used a metered vision call per embedded image. The subscription worker
        runs text-only jobs, so embedded images are counted and logged but not
        transcribed; paste the screenshot text into the document to include it.
        """
        skipped = sum(
            1
            for rel in doc.part.rels.values()
            if "image" in rel.reltype and len(rel.target_part.blob) >= 5000
        )
        if skipped:
            logger.info("ocr.disabled_subscription_policy", images_skipped=skipped)
        return []

    async def ingest_text(self, text: str, file_name: str) -> dict[str, Any]:
        """Ingest raw text content."""
        source_doc = SourceDocument(
            file_name=file_name,
            file_type="text",
            language="en",
            extracted_text=text,
            ingested_at=datetime.now(UTC),
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
