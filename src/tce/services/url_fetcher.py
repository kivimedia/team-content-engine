"""Fetch + extract clean text from URLs pasted into Topic/Brief.

Used by the Start-from-Topic endpoint so the pipeline studies the actual page
instead of treating the URL as opaque text.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import re
import socket
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

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

# Sites that answer 403 to the server's address whatever it sends (14-Oct:
# every openai.com article). Only for these, and only on a 403, the page is read
# through a public reader that returns the article as text. The source URL stays
# the site's own.
_READER = "https://r.jina.ai/"
_READER_HOSTS = frozenset({"openai.com"})

# Only announcement pages on primary publishers can resolve a secondary link.
# Do not treat a homepage, a link shortener, or a lookalike domain as evidence.
_PRIMARY_PATHS = {
    "openai.com": ("/index/",),
    "anthropic.com": ("/news/", "/claude-"),
    "deepmind.google": ("/blog/",),
    "blog.google": ("/products/", "/technology/"),
    "workspaceupdates.googleblog.com": ("/20",),
    "developers.googleblog.com": ("/en/",),
    "elevenlabs.io": ("/blog/", "/docs/changelog"),
    "deepgram.com": ("/learn/",),
    "twilio.com": ("/en-us/changelog/", "/en-us/blog/"),
    "updates.dubsado.com": ("/",),
}


def _public_url(url: str, base: str = "") -> str | None:
    """Public HTTP(S) URL without credentials, query strings, or fragments."""
    try:
        parsed = urlsplit(urljoin(base, url))
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except ValueError:
        return None


def is_primary_announcement(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        return bool(
            not parsed.username and not parsed.password
            and parsed.scheme in ("https", "http")
            and any(parsed.path.startswith(p) and len(parsed.path) > len(p)
                    for p in _PRIMARY_PATHS.get(host, ()))
        )
    except ValueError:
        return False


class _PageMetadata(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.published: list[str] = []
        self.times: list[str] = []
        self.links: list[str] = []
        self.jsonld: list[str] = []
        self._json: list[str] | None = None
        self._time: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and (attrs.get("property") or attrs.get("name")) in (
            "article:published_time", "datePublished", "datepublished", "pubdate",
        ):
            self.published.append(attrs.get("content", ""))
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self._json = []
        if tag == "time":
            if attrs.get("datetime"):
                self.times.append(attrs["datetime"])
            self._time = []

    def handle_data(self, data):
        if self._json is not None:
            self._json.append(data)
        if self._time is not None:
            self._time.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._json is not None:
            self.jsonld.append("".join(self._json))
            self._json = None
        if tag == "time" and self._time is not None:
            self.times.append("".join(self._time).strip())
            self._time = None


def _publication_value(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).replace(tzinfo=None)
    except ValueError:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def extract_publication_date(raw_html: str) -> datetime | None:
    """Read publication metadata, never dateModified or the time we fetched it."""
    parser = _PageMetadata()
    parser.feed(raw_html)
    for value in parser.published:
        if parsed := _publication_value(value):
            return parsed

    def dates(node):
        if isinstance(node, dict):
            if "datePublished" in node:
                yield node["datePublished"]
            for value in node.values():
                yield from dates(value)
        elif isinstance(node, list):
            for value in node:
                yield from dates(value)

    for block in parser.jsonld:
        try:
            found = {_publication_value(v) for v in dates(json.loads(block))}
        except (ValueError, TypeError):
            continue
        found.discard(None)
        if len(found) == 1:
            return next(iter(found))
    found = {_publication_value(v) for v in parser.times}
    found.discard(None)
    return next(iter(found)) if len(found) == 1 else None


def _outbound_links(raw_html: str, base: str) -> list[str]:
    parser = _PageMetadata()
    parser.feed(raw_html)
    return list(dict.fromkeys(url for link in parser.links
                              if (url := _public_url(link, base))))[:300]


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


def _reader_host(url: str) -> bool:
    host = (httpx.URL(url).host or "").lower()
    return any(host == h or host.endswith("." + h) for h in _READER_HOSTS)


def _from_reader(text: str) -> tuple[str, str]:
    """(title, body_text) from the reader's "Title: ... Markdown Content:" page."""
    title_match = re.search(r"^Title:\s*(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else ""
    _, marker, content = text.partition("Markdown Content:")
    body = content if marker else text
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", body)
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) > _BODY_CHAR_CAP:
        body = body[:_BODY_CHAR_CAP].rsplit(" ", 1)[0] + " ..."
    return title, body


class UnsafePublicURL(ValueError):
    """A news link would reach a non-public network destination."""


async def _public_target(url: str) -> tuple[httpx.URL, str, str]:
    """Resolve once, validate every address, and pin the actual connection IP.

    Merely checking DNS and then connecting by hostname has a second DNS lookup
    race. The request uses this checked IP while Host and TLS SNI retain the
    original hostname, so certificate verification still checks the real site.
    """
    try:
        parsed = httpx.URL(url)
        host = parsed.host
        default_port = 443 if parsed.scheme == "https" else 80
        if (parsed.scheme not in {"https", "http"} or not host or parsed.userinfo
                or parsed.port not in (None, default_port)):
            raise UnsafePublicURL("Only public HTTP(S) pages on standard ports are allowed.")
        if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal")):
            raise UnsafePublicURL("The page address is not public.")
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            records = await asyncio.wait_for(asyncio.to_thread(
                socket.getaddrinfo, host, default_port, type=socket.SOCK_STREAM,
            ), timeout=5)
            addresses = list(dict.fromkeys(ipaddress.ip_address(row[4][0]) for row in records))
        if not addresses or any(not ip.is_global or ip.is_multicast for ip in addresses):
            raise UnsafePublicURL("The page resolves to a non-public address.")
        return parsed.copy_with(host=str(addresses[0])), parsed.netloc.decode("ascii"), host
    except (httpx.InvalidURL, ValueError) as exc:
        if isinstance(exc, UnsafePublicURL):
            raise
        raise UnsafePublicURL("Invalid public page address.") from exc


async def _get_public(
    client: httpx.AsyncClient, url: str, *, timeout_s: float,
) -> tuple[httpx.Response, str]:
    current = url
    for _ in range(6):
        target, host_header, hostname = await _public_target(current)
        response = await client.get(
            target, headers={"Host": host_header},
            extensions={"sni_hostname": hostname}, follow_redirects=False, timeout=timeout_s,
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response, current
        location = response.headers.get("location")
        if not location:
            return response, current
        current = urljoin(current, location)
    raise UnsafePublicURL("Too many page redirects.")


async def fetch_url_text(
    url: str, timeout_s: float = 15.0, *, public_only: bool = False,
) -> dict[str, Any]:
    """Fetch one URL and return {url, title, description, body_text, status, error}."""
    result: dict[str, Any] = {
        "url": url,
        "title": "",
        "description": "",
        "body_text": "",
        "status": "ok",
        "error": None,
        "published_at": None,
        "outbound_links": [],
        "primary_url": None,
        "source_verified": False,
    }
    try:
        async with httpx.AsyncClient(
            timeout=timeout_s,
            follow_redirects=not public_only,
            # IP origins can be shared by unrelated hostnames. Do not reuse a
            # TLS connection whose certificate was checked for another SNI.
            **({"trust_env": False, "limits": httpx.Limits(max_keepalive_connections=0)}
               if public_only else {}),
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:
            if public_only:
                resp, final_url = await _get_public(client, url, timeout_s=timeout_s)
            else:
                resp = await client.get(url)
                final_url = str(resp.url) if getattr(resp, "url", None) else url
            if resp.status_code == 403 and _reader_host(url):
                if public_only:
                    via, _ = await _get_public(client, _READER + url, timeout_s=max(timeout_s, 40.0))
                else:
                    via = await client.get(_READER + url, timeout=max(timeout_s, 40.0))
                if via.status_code < 400:
                    title, body = _from_reader(via.text)
                    if body:
                        # Reader links retain provenance; its own request time
                        # is never promoted to a publication date.
                        date = re.search(r"^Published Time:\s*(.+)$", via.text, re.MULTILINE)
                        result.update(title=title, body_text=body, via="reader",
                                      published_at=_publication_value(date.group(1)) if date else None,
                                      primary_url=_public_url(url),
                                      source_verified=is_primary_announcement(url),
                                      outbound_links=list(dict.fromkeys(
                                          clean for u in extract_urls(via.text)
                                          if (clean := _public_url(u))))[:300])
                        return result
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
            result["primary_url"] = _public_url(final_url)
            result["source_verified"] = is_primary_announcement(final_url)
            result["published_at"] = extract_publication_date(resp.text)
            result["outbound_links"] = _outbound_links(resp.text, final_url)
            if not body and not title:
                result["status"] = "empty"
                result["error"] = "no extractable text"
    except UnsafePublicURL as exc:
        result["status"] = "unsafe_url"
        result["error"] = str(exc)
    except httpx.TimeoutException:
        result["status"] = "timeout"
        result["error"] = f"timed out after {timeout_s}s"
    except Exception as e:  # noqa: BLE001 — surface any failure to caller
        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"
    return result


async def resolve_primary_announcement(url: str, timeout_s: float = 15.0) -> dict[str, Any]:
    """Follow one unambiguous primary link, and actually fetch it before citing.

    Secondary roundups with multiple official sources remain unresolved. This
    conservative resolution never turns a summary into verified primary text.
    """
    page = await fetch_url_text(url, timeout_s=timeout_s, public_only=True)
    if page.get("status") != "ok" or page.get("source_verified"):
        return page
    candidates = list(dict.fromkeys(
        link for link in page.get("outbound_links", [])
        if is_primary_announcement(link)
    ))
    if len(candidates) != 1:
        return {**page, "status": "primary_unresolved", "source_verified": False,
                "error": f"Expected one primary announcement link; found {len(candidates)}",
                "primary_candidates": candidates[:10]}
    primary = await fetch_url_text(candidates[0], timeout_s=timeout_s, public_only=True)
    if primary.get("status") == "ok" and primary.get("source_verified"):
        return {**primary, "discovery_url": _public_url(url)}
    return {**page, "status": "primary_unresolved", "source_verified": False,
            "error": "Primary announcement could not be fetched and verified",
            "primary_candidates": candidates}


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
