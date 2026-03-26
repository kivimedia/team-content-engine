"""Onboarding endpoints (PRD Section 43.6)."""

from typing import Any

from fastapi import APIRouter

from tce.services.onboarding import OnboardingService

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/quickstart")
async def quickstart() -> list[dict[str, Any]]:
    """7-step quickstart guide for new operators."""
    return OnboardingService.get_quickstart()


@router.get("/glossary")
async def glossary() -> dict[str, str]:
    """Definitions of system-specific terms."""
    return OnboardingService.get_glossary()


@router.get("/troubleshooting")
async def troubleshooting() -> list[dict[str, Any]]:
    """Common issues and how to resolve them."""
    return OnboardingService.get_troubleshooting()


@router.get("/roles")
async def roles() -> dict[str, list[str]]:
    """What the operator handles vs what the system does."""
    return OnboardingService.get_role_documentation()


@router.get("/full")
async def full_onboarding() -> dict[str, Any]:
    """Complete onboarding package."""
    return OnboardingService.get_full_onboarding()
