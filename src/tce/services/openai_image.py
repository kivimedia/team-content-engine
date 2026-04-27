"""OpenAI image generation backend.

Wraps the OpenAI Images API (gpt-image-2 / gpt-image-1) so the rest of the
pipeline can dispatch to it the same way it dispatches to fal.ai.
"""

from __future__ import annotations

import base64
import time
import uuid
from typing import Any

import httpx
import structlog

from tce.settings import settings

logger = structlog.get_logger()


# Map our generic aspect ratios to OpenAI's `size` parameter. The Images API
# accepts a fixed set of sizes; we round our internal ratios to the nearest
# supported value. "auto" lets OpenAI choose, which is fine when the prompt
# itself implies aspect ratio.
_SIZE_MAP = {
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "4:3": "1536x1024",
    "3:4": "1024x1536",
    "4:5": "1024x1536",
    "5:4": "1536x1024",
    "1:1": "1024x1024",
    "square": "1024x1024",
}


# OpenAI image API rejects certain quality values per model. gpt-image-* takes
# "low" | "medium" | "high" | "auto"; DALL-E 3 takes "standard" | "hd".
_DEFAULT_QUALITY = "high"


# Approximate cost per image at "high" quality (USD). Used for budget tracking;
# OpenAI's actual pricing depends on size + quality. Keep conservative.
_COST_ESTIMATES = {
    "gpt-image-2": 0.19,
    "gpt-image-1": 0.19,
    "dall-e-3": 0.08,
}


class OpenAIImageService:
    """Generate images via OpenAI's Images API."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.openai_api_key
        self.base_url = "https://api.openai.com/v1/images/generations"

    @staticmethod
    def supports(model: str) -> bool:
        """True if this provider should handle the given model id."""
        m = (model or "").lower()
        return m.startswith("gpt-image") or m.startswith("dall-e")

    async def generate_image(
        self,
        prompt_text: str,
        negative_prompt: str | None = None,
        aspect_ratio: str | None = None,
        model: str = "gpt-image-2",
    ) -> dict[str, Any]:
        if not self.api_key:
            logger.warning("openai_image.no_api_key")
            return {
                "status": "skipped",
                "reason": "No OpenAI API key configured",
                "prompt_text": prompt_text,
                "provider": "openai",
            }

        # OpenAI doesn't take a negative_prompt parameter; fold it into the
        # main prompt as an explicit "avoid:" clause so the model still sees it.
        full_prompt = prompt_text
        if negative_prompt:
            full_prompt = f"{prompt_text}\n\nAvoid: {negative_prompt}"

        size = _SIZE_MAP.get((aspect_ratio or "").lower(), "auto") if aspect_ratio else "auto"

        payload: dict[str, Any] = {
            "model": model,
            "prompt": full_prompt,
            "n": 1,
            "size": size,
        }
        # gpt-image-* supports quality + output_format; DALL-E 3 ignores them.
        if model.lower().startswith("gpt-image"):
            payload["quality"] = _DEFAULT_QUALITY
            payload["output_format"] = "png"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(self.base_url, json=payload, headers=headers)
            if response.status_code != 200:
                logger.error(
                    "openai_image.http_error",
                    status=response.status_code,
                    body=response.text[:500],
                    model=model,
                )
            response.raise_for_status()
            result = response.json()
        elapsed = time.monotonic() - start

        # gpt-image-* returns base64 by default; DALL-E 3 returns a URL.
        data = (result.get("data") or [{}])[0]
        image_url = data.get("url")
        b64 = data.get("b64_json")

        # Persist to S3 if configured. For b64, decode + upload; for URL, fetch + re-upload.
        # Falls back to a data URL when no storage is configured so the
        # dashboard can still display the image.
        s3_path = None
        try:
            from tce.services.storage import StorageService

            storage = StorageService()
            if storage.configured:
                key = f"images/{uuid.uuid4().hex}.png"
                if b64:
                    res = await storage.upload(
                        key, base64.b64decode(b64), content_type="image/png"
                    )
                elif image_url:
                    res = await storage.upload_from_url(image_url, key)
                else:
                    res = None
                if res and res.get("status") == "uploaded":
                    s3_path = res.get("url")
                    logger.info("openai_image.s3_persisted", key=key, model=model)
        except Exception:
            logger.exception("openai_image.s3_upload_failed")

        final_url = s3_path or image_url
        if not final_url and b64:
            final_url = f"data:image/png;base64,{b64}"

        return {
            "status": "generated",
            "image_url": final_url,
            "image_s3_path": s3_path,
            "fal_model_used": model,  # legacy field name; UI reads image_model_used too
            "image_model_used": model,
            "provider": "openai",
            "fal_request_id": None,
            "generation_time_seconds": round(elapsed, 2),
            "generation_cost_usd": _COST_ESTIMATES.get(model.lower(), 0.10),
            "prompt_text": prompt_text,
            "negative_prompt": negative_prompt,
        }
