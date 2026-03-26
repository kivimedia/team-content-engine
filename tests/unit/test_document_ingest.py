"""Tests for DocumentIngestService."""

from tce.services.document_ingest import DocumentIngestService


def test_service_exists():
    assert DocumentIngestService is not None


def test_has_ingest_methods():
    import asyncio

    assert hasattr(DocumentIngestService, "ingest_docx")
    assert asyncio.iscoroutinefunction(
        DocumentIngestService.ingest_docx
    )
    assert hasattr(DocumentIngestService, "ingest_text")
    assert asyncio.iscoroutinefunction(
        DocumentIngestService.ingest_text
    )
