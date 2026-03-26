"""Orchestrator chatbot endpoint (PRD Section 44)."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.services.chatbot import ChatbotService

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    context: dict[str, Any] = {}


class ChatResponse(BaseModel):
    response: str
    intent: str
    data: dict[str, Any] | list | None = None
    success: bool = True
    action: str | None = None


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Send a message to the orchestrator chatbot."""
    service = ChatbotService(db)
    return await service.handle_message(request.message, request.context)
