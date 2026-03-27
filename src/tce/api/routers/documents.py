"""Document and corpus management endpoints."""

import asyncio
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.post_example import PostExample
from tce.models.source_document import SourceDocument
from tce.schemas.post_example import PostExampleRead
from tce.schemas.source_document import SourceDocumentRead
from tce.services.document_ingest import DocumentIngestService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=SourceDocumentRead)
async def upload_document(
    file: UploadFile,
    auto_analyze: bool = False,
    db: AsyncSession = Depends(get_db),
) -> SourceDocument:
    """Upload a DOCX corpus file for parsing."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".docx", ".txt"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    # Save uploaded file temporarily
    with NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    service = DocumentIngestService(db)
    if suffix == ".docx":
        result = await service.ingest_docx(tmp_path, file.filename)
    else:
        text_content = content.decode("utf-8")
        result = await service.ingest_text(text_content, file.filename)

    # Clean up temp file
    Path(tmp_path).unlink(missing_ok=True)

    # Commit the document record now so it persists even if background analysis fails
    await db.commit()

    doc = await db.get(SourceDocument, uuid.UUID(result["document_id"]))
    if not doc:
        raise HTTPException(status_code=500, detail="Document creation failed")

    # Optionally trigger corpus ingestion pipeline
    if auto_analyze and result.get("document_text"):
        from tce.orchestrator.engine import PipelineOrchestrator
        from tce.orchestrator.workflows import WORKFLOWS
        from tce.settings import settings

        async def _run_analysis():
            from tce.db.session import async_session

            async with async_session() as analysis_db:
                orchestrator = PipelineOrchestrator(
                    steps=WORKFLOWS["corpus_ingestion"],
                    db=analysis_db,
                    settings=settings,
                )
                await orchestrator.run({
                    "document_text": result["document_text"],
                    "document_id": result["document_id"],
                })
                await analysis_db.commit()

        asyncio.create_task(_run_analysis())

    return doc


@router.get("/", response_model=list[SourceDocumentRead])
async def list_documents(db: AsyncSession = Depends(get_db)) -> list[SourceDocument]:
    result = await db.execute(
        select(SourceDocument).order_by(SourceDocument.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{document_id}", response_model=SourceDocumentRead)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SourceDocument:
    doc = await db.get(SourceDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{document_id}/examples", response_model=list[PostExampleRead])
async def get_document_examples(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[PostExample]:
    result = await db.execute(
        select(PostExample)
        .where(PostExample.document_id == document_id)
        .order_by(PostExample.final_score.desc().nulls_last())
    )
    return list(result.scalars().all())
