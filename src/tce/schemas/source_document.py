"""Schemas for SourceDocument."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SourceDocumentCreate(BaseModel):
    file_name: str
    file_type: str = "docx"
    language: str = "he"
    pages: int | None = None
    notes: str | None = None


class SourceDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    file_type: str
    language: str
    pages: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
