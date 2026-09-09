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


# Creative Director tags each prompt with `best_platform`. Map that to a real
# model id we can dispatch to. Where we don't yet have an API for the requested
# platform (gemini, midjourney), fall back to fal.ai's Flux Pro — historically
# the most reliable diagram-renderer we have a key for, and gpt-image-2 has
# proven to time out on dense diagram prompts (~9 min before failing).
_BEST_PLATFORM_TO_MODEL = {
    "fal_ai": "fal-ai/flux-pro/v1.1",
    "fal": "fal-ai/flux-pro/v1.1",
    "flux": "fal-ai/flux-pro/v1.1",
    "dall_e": "dall-e-3",
    "dalle": "dall-e-3",
    "openai": "gpt-image-2.5-sunburst",
    "gpt_image": "gpt-image-2.5-sunburst",
    "gpt-image-2": "gpt-image-2",
        "gpt-image-2.5-sunburst": "gpt-image-2.5-sunburst",
        "gpt-image-2.5-flare": "gpt-image-2.5-flare",
    # Platforms we don't have direct APIs for. Flux Pro renders text overlays
    # and clean diagrams more reliably than gpt-image-2 within our timeout.
    "gemini": "fal-ai/flux-pro/v1.1",
    "midjourney": "fal-ai/flux-pro/v1.1",
}


def _resolve_model_for(best_platform: str | None) -> str:
    """Map a Creative Director `best_platform` value to a concrete model id.

    Falls through to `settings.default_image_model` (gpt-image-2) when the tag
    is missing or unrecognised — that's the legacy behaviour for prompts that
    don't carry a hint.
    """
    key = (best_platform or "").strip().lower()
    if key in _BEST_PLATFORM_TO_MODEL:
        return _BEST_PLATFORM_TO_MODEL[key]
    return settings.default_image_model or DEFAULT_FAL_MODEL


def _alternate_model_for(model: str) -> str:
    """Pick a different-provider fallback model for cross-provider retry."""
    if model.startswith("fal-ai/"):
        # fal failed — try OpenAI
        return "gpt-image-2.5-sunburst"
    # OpenAI / dall-e failed — try fal.ai
    return DEFAULT_FAL_MODEL


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

    async def generate_with_fallback(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """Generate one image, routing by `best_platform` and falling back to
        the alternate provider on any failure.

        This is the public entry point for both batch generation (called from
        `generate_batch`) and single-image regeneration (called from the
        `/regenerate-image/{idx}` route). Honoring `best_platform` here means
        diagram prompts the Creative Director marks `gemini` go to Flux Pro
        instead of timing out on gpt-image-2.
        """
        return await self._one(prompt)

    async def generate_batch(self, prompts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Generate images for a batch of prompts (typically 3 per post).

        Runs all calls concurrently. With OpenAI gpt-image-2 at ~60s per
        image, the difference between serial (3*60=180s) and parallel
        (max=~60s) is the difference between "this is broken" and "fine".
        """
        import asyncio

        return await asyncio.gather(*(self._one(p) for p in prompts))

    async def _one(self, prompt: dict[str, Any]) -> dict[str, Any]:
        prompt_text = prompt.get(
            "prompt_text",
            prompt.get("detailed_prompt", ""),
        )
        negative = prompt.get("negative_prompt")
        aspect = prompt.get("aspect_ratio")
        primary_model = _resolve_model_for(prompt.get("best_platform"))
        attempted: list[str] = []

        try:
            attempted.append(primary_model)
            result = await self.generate_image(
                prompt_text=prompt_text,
                negative_prompt=negative,
                aspect_ratio=aspect,
                model=primary_model,
            )
            if result.get("status") == "generated":
                result["attempted_providers"] = attempted
                return result
            # generate_image returned a non-generated status (skipped/etc.)
            # -> try the alternate provider before giving up.
            logger.warning(
                "image_gen.primary_non_generated",
                primary=primary_model,
                status=result.get("status"),
                reason=result.get("reason"),
            )
        except Exception as e:
            logger.warning(
                "image_gen.primary_failed",
                primary=primary_model,
                prompt=prompt.get("prompt_name"),
                error=str(e)[:200],
            )

        # Cross-provider fallback. Diagram prompts that time out on
        # gpt-image-2 succeed on Flux Pro within ~30s; photoreal prompts
        # that fail moderation on fal.ai often pass on OpenAI. Trying
        # the other side is cheap and prevents an empty 3rd image slot.
        fallback_model = _alternate_model_for(primary_model)
        try:
            attempted.append(fallback_model)
            logger.info(
                "image_gen.fallback_attempt",
                primary=primary_model,
                fallback=fallback_model,
                prompt=prompt.get("prompt_name"),
            )
            result = await self.generate_image(
                prompt_text=prompt_text,
                negative_prompt=negative,
                aspect_ratio=aspect,
                model=fallback_model,
            )
            if result.get("status") == "generated":
                result["attempted_providers"] = attempted
                result["fallback_used"] = True
                return result
            return {
                "status": "failed",
                "error": (
                    f"both providers returned non-generated: "
                    f"{primary_model}, {fallback_model}->{result.get('status')}"
                ),
                "prompt_text": prompt_text,
                "attempted_providers": attempted,
            }
        except Exception as e:
            logger.exception(
                "image_gen.failed",
                prompt=prompt.get("prompt_name"),
                primary=primary_model,
                fallback=fallback_model,
            )
            return {
                "status": "failed",
                "error": f"both providers failed: {e!s}",
                "prompt_text": prompt_text,
                "attempted_providers": attempted,
            }

    @staticmethod
    def get_platform_crops() -> dict[str, str]:
        """Get available platform crop presets."""
        return PLATFORM_CROPS.copy()
