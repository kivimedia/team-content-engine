"""Schemas for Notification."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class NotificationCreate(BaseModel):
    notification_type: str
    title: str
    message: str
    severity: str = "info"
    channel: str = "in_app"
    data: dict[str, Any] | None = None


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    notification_type: str
    title: str
    message: str
    severity: str
    channel: str
    read: bool
    dismissed: bool
    data: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
