"""Schemas for ImageAsset."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ImageAssetCreate(BaseModel):
    package_id: uuid.UUID
    prompt_text: str
    negative_prompt: str | None = None
    aspect_ratio: str | None = None


class ImageAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    package_id: uuid.UUID
    prompt_text: str
    negative_prompt: str | None
    fal_model_used: str | None
    image_url: str | None
    image_s3_path: str | None
    resolution: str | None
    aspect_ratio: str | None
    generation_cost_usd: float | None
    operator_selected: bool
    created_at: datetime
    updated_at: datetime
