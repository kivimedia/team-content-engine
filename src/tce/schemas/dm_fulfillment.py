"""Schemas for DMFulfillmentLog."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DMFulfillmentCreate(BaseModel):
    package_id: uuid.UUID | None = None
    cta_keyword: str
    promised_asset: str | None = None
    platform: str
    commenter_id: str | None = None
    comment_text: str | None = None


class DMFulfillmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    package_id: uuid.UUID | None
    cta_keyword: str
    promised_asset: str | None
    platform: str
    commenter_id: str | None
    comment_text: str | None
    dm_sent: bool
    dm_content: str | None
    delivery_method: str | None
    status: str
    failure_reason: str | None
    whatsapp_joined: bool
    consent_given: bool
    opted_out: bool
    created_at: datetime
    updated_at: datetime


class DMFulfillmentUpdate(BaseModel):
    dm_sent: bool | None = None
    dm_content: str | None = None
    delivery_method: str | None = None
    status: str | None = None
    failure_reason: str | None = None
    whatsapp_joined: bool | None = None
    consent_given: bool | None = None
    opted_out: bool | None = None
