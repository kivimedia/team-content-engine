"""Image generation pipeline.

Dispatches to OpenAI (gpt-image-2 / gpt-image-1) or fal.ai based on the
configured default_image_model. The default is OpenAI; fal.ai stays available
for prompts the creative_director marks as photoreal/cinematic.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from tce.services.openai_image import OpenAIImageService
from tce.settings import settings

logger = structlog.get_logger()

# fal.ai fallback model. OpenAI gpt-image-2 is the default per
# settings.default_image_model.
DEFAULT_FAL_MODEL = "fal-ai/flux-pro/v1.1"
DEFAULT_IMAGE_SIZE = "landscape_16_9"

# Map common aspect ratios to fal.ai image_size values
ASPECT_RATIO_MAP = {
    "16:9": "landscape_16_9",
    "9:16": "portrait_16_9",
    "4:3": "landscape_4_3",
    "3:4": "portrait_4_3",
    "1:1": "square_hd",
    "4:5": "portrait_4_3",
    "5:4": "landscape_4_3",
    "square": "square_hd",
}

# PRD Section 41.5: Platform crop guidance
PLATFORM_CROPS = {
    "facebook_link": "landscape_16_9",
    "facebook_square": "square_hd",
    "facebook_portrait": "portrait_4_3",
    "linkedin_link": "landscape_16_9",
    "linkedin_square": "square_hd",
    "linkedin_article": "landscape_16_9",
}


class ImageGenerationService:
    """Generates images via fal.ai from Creative Director prompts."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.fal_api_key
        self.base_url = "https://fal.run"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        reraise=True,
    )
    async def generate_image(
        self,
        prompt_text: str,
        negative_prompt: str | None = None,
        aspect_ratio: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Generate a single image from a prompt.

        Routes to OpenAI for gpt-image-* / dall-e-* models; falls through to
        fal.ai for everything else. The default comes from
        settings.default_image_model (gpt-image-2).

        Returns dict with image_url, generation_time, cost, etc.
        """
        # Resolve which model to actually call. Caller can pin a model;
        # otherwise we use the configured default.
        resolved_model = model or settings.default_image_model or DEFAULT_FAL_MODEL

        # Route to OpenAI when the model id matches their image families.
        if OpenAIImageService.supports(resolved_model):
            openai_svc = OpenAIImageService()
            return await openai_svc.generate_image(
                prompt_text=prompt_text,
                negative_prompt=negative_prompt,
                aspect_ratio=aspect_ratio,
                model=resolved_model,
            )

        # fal.ai path
        if not self.api_key:
            logger.warning("image_gen.no_api_key")
            return {
                "status": "skipped",
                "reason": "No fal.ai API key configured",
                "prompt_text": prompt_text,
                "provider": "fal_ai",
            }

        start = time.monotonic()

        # Map aspect ratio to fal.ai image_size value
        image_size = DEFAULT_IMAGE_SIZE
        if aspect_ratio:
            image_size = ASPECT_RATIO_MAP.get(
                aspect_ratio,
                ASPECT_RATIO_MAP.get(aspect_ratio.lower(), DEFAULT_IMAGE_SIZE),
            )

        payload: dict[str, Any] = {
            "prompt": prompt_text,
            "image_size": image_size,
            "num_images": 1,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        headers = {
            "Authorization": f"Key {self.api_key}",
            "Content-Type": "application/json",
        }

        # Caller's resolved_model only routes to fal here; honor it but fall
        # back to the historical Flux Pro default if the resolved id isn't a
        # fal.ai model (e.g. an unknown string).
        fal_model = resolved_model if resolved_model.startswith("fal-ai/") else DEFAULT_FAL_MODEL

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.base_url}/{fal_model}",
                json=payload,
                headers=headers,
            )
            if response.status_code != 200:
                logger.error(
                    "image_gen.http_error",
                    status=response.status_code,
                    body=response.text[:500],
                    model=fal_model,
                    prompt=prompt_text[:100],
                )
            response.raise_for_status()
            result = response.json()

        elapsed = time.monotonic() - start

        # Extract image URL from fal.ai response
        images = result.get("images", [])
        image_url = images[0].get("url") if images else None

        # GAP-04: Persist image to S3 if storage is configured
        s3_path = None
        if image_url:
            try:
                from tce.services.storage import StorageService

                storage = StorageService()
                if storage.configured:
                    import uuid as _uuid

                    key = f"images/{_uuid.uuid4().hex}.png"
                    res = await storage.upload_from_url(image_url, key)
                    if res and res.get("status") == "uploaded":
                        s3_path = res.get("url")
                        logger.info("image_gen.s3_persisted", key=key)
            except Exception:
                logger.exception("image_gen.s3_upload_failed")

        return {
            "status": "generated",
            "image_url": s3_path or image_url,
            "image_s3_path": s3_path,
            "fal_model_used": fal_model,
            "image_model_used": fal_model,
            "provider": "fal_ai",
            "fal_request_id": result.get("request_id"),
            "generation_time_seconds": round(elapsed, 2),
            "generation_cost_usd": 0.03,  # Flux Pro at ~$0.03/image
            "prompt_text": prompt_text,
            "negative_prompt": negative_prompt,
        }

    async def generate_batch(self, prompts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Generate images for a batch of prompts (typically 3 per post).

        Runs all calls concurrently. With OpenAI gpt-image-2 at ~60s per
        image, the difference between serial (3*60=180s) and parallel
        (max=~60s) is the difference between "this is broken" and "fine".
        """
        import asyncio

        async def _one(prompt: dict[str, Any]) -> dict[str, Any]:
            try:
                return await self.generate_image(
                    prompt_text=prompt.get(
                        "prompt_text",
                        prompt.get("detailed_prompt", ""),
                    ),
                    negative_prompt=prompt.get("negative_prompt"),
                    aspect_ratio=prompt.get("aspect_ratio"),
                )
            except Exception as e:
                logger.exception(
                    "image_gen.failed",
                    prompt=prompt.get("prompt_name"),
                )
                return {
                    "status": "failed",
                    "error": str(e),
                    "prompt_text": prompt.get("prompt_text", ""),
                }

        return await asyncio.gather(*(_one(p) for p in prompts))

    @staticmethod
    def get_platform_crops() -> dict[str, str]:
        """Get available platform crop presets."""
        return PLATFORM_CROPS.copy()
