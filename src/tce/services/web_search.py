"""Web search service - Brave Search API integration (PRD Sections 37.2, 49.7)."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from tce.settings import settings

logger = structlog.get_logger()

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class WebSearchService:
    """Performs web searches via Brave Search API for Trend Scout and Research Agent."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.search_api_key

    async def search(
        self,
        query: str,
        count: int = 10,
        freshness: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search the web and return structured results.

        Args:
            query: Search query string.
            count: Number of results (max 20).
            freshness: Optional filter - "pd" (past day), "pw" (past week), "pm" (past month).

        Returns:
            List of dicts with title, url, description, age fields.
        """
        if not self.api_key:
            logger.warning("web_search.no_api_key", query=query)
            return []

        params: dict[str, Any] = {"q": query, "count": min(count, 20)}
        if freshness:
            params["freshness"] = freshness

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(BRAVE_SEARCH_URL, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            results = []
            for item in data.get("web", {}).get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                    "age": item.get("age", ""),
                    "extra_snippets": item.get("extra_snippets", []),
                })
            logger.info("web_search.ok", query=query, result_count=len(results))
            return results

        except httpx.HTTPStatusError as e:
            logger.error("web_search.http_error", status=e.response.status_code, query=query)
            return []
        except Exception:
            logger.exception("web_search.failed", query=query)
            return []

    async def search_news(self, query: str, count: int = 10) -> list[dict[str, Any]]:
        """Search for recent news (past week)."""
        return await self.search(query, count=count, freshness="pw")

    async def search_fresh(self, query: str, count: int = 10) -> list[dict[str, Any]]:
        """Search for very recent content (past day)."""
        return await self.search(query, count=count, freshness="pd")
