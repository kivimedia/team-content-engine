"""Fetch + extract clean text from URLs pasted into Topic/Brief.

Used by the Start-from-Topic endpoint so the pipeline studies the actual page
instead of treating the URL as opaque text.
"""

from __future__ import annotations

import asyncio
import html
import re
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 TCE-LinkStudier/1.0"
)

_TAG_BLOCKS_TO_DROP = ("script", "style", "noscript", "svg", "nav", "footer", "aside", "form", "header")
_BODY_CHAR_CAP = 6000


def extract_urls(text: str) -> list[str]:
    """Return unique URLs preserving first-seen order. Strips trailing punctuation."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in URL_RE.findall(text or ""):
        url = raw.rstrip(".,;:!?”’")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _strip_html(raw_html: str) -> tuple[str, str, str]:
    """Return (title, description, body_text) from raw HTML.

    No external deps — regex + html.unescape. Good enough for blog/landing pages.
    """
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    title = html.unescape(title_match.group(1).strip()) if title_match else ""

    desc = ""
    for pattern in (
        r'<meta[^>]+property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']description["\'][^>]*content=["\']([^"\']+)["\']',
    ):
        m = re.search(pattern, raw_html, re.IGNORECASE)
        if m:
            desc = html.unescape(m.group(1).strip())
            break

    body = raw_html
    for tag in _TAG_BLOCKS_TO_DROP:
        body = re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}>",
            " ",
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.DOTALL)
    body = re.sub(r"<[^>]+>", " ", body)
    body = html.unescape(body)
    body = re.sub(r"\s+", " ", body).strip()

    if len(body) > _BODY_CHAR_CAP:
        body = body[:_BODY_CHAR_CAP].rsplit(" ", 1)[0] + " ..."

    return title, desc, body


async def fetch_url_text(url: str, timeout_s: float = 15.0) -> dict[str, Any]:
    """Fetch one URL and return {url, title, description, body_text, status, error}."""
    result: dict[str, Any] = {
        "url": url,
        "title": "",
        "description": "",
        "body_text": "",
        "status": "ok",
        "error": None,
    }
    try:
        async with httpx.AsyncClient(
            timeout=timeout_s,
            follow_redirects=True,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                result["status"] = "http_error"
                result["error"] = f"HTTP {resp.status_code}"
                return result
            ctype = resp.headers.get("content-type", "")
            if "html" not in ctype and "xml" not in ctype:
                result["status"] = "non_html"
                result["error"] = f"content-type: {ctype}"
                return result
            title, desc, body = _strip_html(resp.text)
            result["title"] = title
            result["description"] = desc
            result["body_text"] = body
            if not body and not title:
                result["status"] = "empty"
                result["error"] = "no extractable text"
    except httpx.TimeoutException:
        result["status"] = "timeout"
        result["error"] = f"timed out after {timeout_s}s"
    except Exception as e:  # noqa: BLE001 — surface any failure to caller
        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def _format_link_block(idx: int, link: dict[str, Any]) -> str:
    parts = [f"REFERENCE LINK {idx}: {link['url']}"]
    if link.get("status") != "ok":
        parts.append(f"STATUS: failed to fetch ({link.get('error') or link.get('status')})")
        return "\n".join(parts)
    if link.get("title"):
        parts.append(f"TITLE: {link['title']}")
    if link.get("description"):
        parts.append(f"DESCRIPTION: {link['description']}")
    if link.get("body_text"):
        parts.append("EXTRACTED CONTENT:")
        parts.append(link["body_text"])
    return "\n".join(parts)


async def resolve_topic_links(topic: str, max_links: int = 3) -> tuple[str, list[dict[str, Any]]]:
    """Detect URLs in `topic`, fetch up to `max_links`, and return enriched topic + metadata.

    The original `topic` text is preserved at the top so any operator prose
    around the URL still flows through. Each fetched link is appended as a
    REFERENCE LINK block that downstream agents (TrendScout, StoryStrategist,
    Research) read via `context["topic"]`.
    """
    urls = extract_urls(topic)[:max_links]
    if not urls:
        return topic, []

    logger.info("url_fetcher.resolving", count=len(urls), urls=urls)
    fetched = await asyncio.gather(*(fetch_url_text(u) for u in urls), return_exceptions=False)

    blocks = [_format_link_block(i + 1, link) for i, link in enumerate(fetched)]
    original = (topic or "").strip()
    enriched = (
        f"{original}\n\n"
        "----- LINK CONTENT (studied by the engine before writing) -----\n"
        + "\n\n".join(blocks)
    )
    return enriched, fetched
