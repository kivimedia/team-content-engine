"""LLM queue states surface as explicit HTTP responses, not hangs or 500 traces."""

from datetime import UTC, datetime

from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient

from tce.api.app import create_app
from tce.llm import LLMPolicyError, LLMUnavailable


async def test_waiting_capacity_is_a_clean_503_with_retry_time():
    app = create_app()
    router = APIRouter()

    @router.get("/_llm_wait")
    async def _wait():
        raise LLMUnavailable(
            "waiting_capacity", "usage limit", retry_at=datetime(2026, 9, 16, 18, tzinfo=UTC)
        )

    @router.get("/_llm_policy")
    async def _policy():
        raise LLMPolicyError("batch API is disabled")

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/_llm_wait")
        assert r.status_code == 503
        assert r.json()["llm_status"] == "waiting_capacity"
        assert r.json()["retry_at"].startswith("2026-09-16T18:00")
        p = await client.get("/_llm_policy")
        assert p.status_code == 500 and "policy" in p.json()["detail"]
