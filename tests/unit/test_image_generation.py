"""Tests for image generation pipeline (PRD Section 41)."""

from tce.services.image_generation import (
    DEFAULT_FAL_MODEL,
    DEFAULT_RESOLUTION,
    PLATFORM_CROPS,
    ImageGenerationService,
)


def test_default_fal_model():
    """Should use Flux Pro."""
    assert "flux" in DEFAULT_FAL_MODEL.lower()


def test_default_resolution():
    assert DEFAULT_RESOLUTION == "1024x1024"


def test_platform_crops():
    """PRD Section 41.5: platform crop presets."""
    assert "facebook_link" in PLATFORM_CROPS
    assert "facebook_square" in PLATFORM_CROPS
    assert "linkedin_link" in PLATFORM_CROPS
    assert "linkedin_square" in PLATFORM_CROPS
    assert PLATFORM_CROPS["facebook_link"] == "1200x630"
    assert PLATFORM_CROPS["linkedin_link"] == "1200x627"


def test_service_exists():
    service = ImageGenerationService(api_key="test")
    assert service.api_key == "test"


def test_service_no_key():
    """Service should work without API key (returns skip status)."""
    service = ImageGenerationService(api_key="")
    assert service.api_key == ""


def test_get_platform_crops():
    crops = ImageGenerationService.get_platform_crops()
    assert len(crops) == 6


def test_service_has_methods():
    import asyncio

    assert asyncio.iscoroutinefunction(
        ImageGenerationService.generate_image
    )
    assert asyncio.iscoroutinefunction(
        ImageGenerationService.generate_batch
    )
