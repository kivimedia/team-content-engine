"""Fetching: changelogs of the things Ziv already runs, plus the frontier feeds.

The feed list is the first place the old failure could return, so it is narrow on
purpose. Roughly eighty percent of it is vendor changelogs for software running
in production for Ziv or a client right now, which means an item from there
arrives with an anchor already attached. The retired `trend_scout` queried
TechCrunch funding and VentureBeat enterprise AI; none of that is reachable from
here, and `BLOCKED_HOSTS` says so out loud.

No search API. Deterministic documents only: Atom, RSS and JSON changelogs
parsed with the standard library, fetched through the same retry helper the
evidence collector uses. That keeps this path free of metered spend entirely,
which the subscription-only policy requires and which is also why the daily run
can be unattended.

Conditional requests mean a quiet feed costs a 304. And a feed that FAILS is
recorded as failing: three consecutive failures surface in health, because "no
news today" and "four feeds are down" must never look the same.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

import httpx
from sqlalchemy import select

from tce.evidence.common import EvidenceHTTPError, request_with_retries
from tce.models.news import NewsFeed, NewsItem

# Hosts that are blocked by name, with the reason kept next to them. These are
# the exact sources trend_scout used; an item can still be DISCOVERED through a
# tier-2 write-up, but the claim must come from the announcement itself.
BLOCKED_HOSTS = frozenset(
    {
        "techcrunch.com",
        "venturebeat.com",
        "theverge.com",
        "news.ycombinator.com",
        "reddit.com",
        "semafor.com",
        "platformer.news",
        "businessinsider.com",
        "cnbc.com",
    }
)

FAILURES_BEFORE_ALARM = 3

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass
class ParsedItem:
    """One entry off a feed, before anything decides whether it matters."""

    external_id: str
    title: str
    url: str
    summary: str | None = None
    published_at: datetime | None = None


@dataclass
class FetchOutcome:
    """What one feed did, in the vocabulary the ledger already uses."""

    feed_id: uuid.UUID | None
    name: str
    status: str  # ok | unchanged | failed
    items: list[ParsedItem] = field(default_factory=list)
    error: str | None = None
    http_status: int | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "unchanged")


def strip_markup(text: str | None) -> str:
    """Feed summaries arrive as HTML. Keep the words, drop the tags."""
    if not text:
        return ""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def host_of(url: str) -> str:
    match = re.match(r"https?://([^/]+)", url or "", re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).lower().removeprefix("www.")


def is_blocked_host(url: str) -> bool:
    """True for the popularity feeds, matching subdomains too."""
    host = host_of(url)
    if not host:
        return False
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        # RFC 822, as RSS uses.
        return parsedate_to_datetime(text).astimezone(UTC).replace(tzinfo=None)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return (
            datetime.fromisoformat(text.replace("Z", "+00:00"))
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
    except ValueError:
        return None


def parse_atom_or_rss(body: str) -> list[ParsedItem]:
    """One parser for both, because the difference is only tag names."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ValueError(f"not valid XML: {exc}") from exc

    items: list[ParsedItem] = []

    for entry in root.findall(".//atom:entry", _NS):
        link = ""
        for candidate in entry.findall("atom:link", _NS):
            if candidate.get("rel", "alternate") == "alternate":
                link = candidate.get("href", "")
                break
        title = (entry.findtext("atom:title", default="", namespaces=_NS) or "").strip()
        summary = entry.findtext("atom:summary", default="", namespaces=_NS) or ""
        if not summary:
            summary = entry.findtext("atom:content", default="", namespaces=_NS) or ""
        entry_id = (entry.findtext("atom:id", default="", namespaces=_NS) or link).strip()
        when = _parse_date(
            entry.findtext("atom:updated", namespaces=_NS)
            or entry.findtext("atom:published", namespaces=_NS)
        )
        if title or link:
            items.append(
                ParsedItem(
                    external_id=entry_id or link or title,
                    title=title,
                    url=link,
                    summary=strip_markup(summary) or None,
                    published_at=when,
                )
            )

    for entry in root.findall(".//item"):
        title = (entry.findtext("title") or "").strip()
        link = (entry.findtext("link") or "").strip()
        guid = (entry.findtext("guid") or link or title).strip()
        summary = entry.findtext("description") or ""
        when = _parse_date(entry.findtext("pubDate"))
        if title or link:
            items.append(
                ParsedItem(
                    external_id=guid,
                    title=title,
                    url=link,
                    summary=strip_markup(summary) or None,
                    published_at=when,
                )
            )

    return items


def parse_json_feed(body: str) -> list[ParsedItem]:
    """JSON Feed, and the loose changelog shapes vendors actually ship."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc

    if isinstance(data, dict):
        entries = data.get("items") or data.get("entries") or data.get("releases") or []
    elif isinstance(data, list):
        entries = data
    else:
        entries = []

    items: list[ParsedItem] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or entry.get("name") or entry.get("tag_name") or "")
        url = str(entry.get("url") or entry.get("html_url") or entry.get("link") or "")
        summary = entry.get("summary") or entry.get("content_text") or entry.get("body") or ""
        external = str(entry.get("id") or entry.get("guid") or url or title)
        when = _parse_date(
            entry.get("date_published")
            or entry.get("published_at")
            or entry.get("created_at")
            or entry.get("date")
        )
        if title or url:
            items.append(
                ParsedItem(
                    external_id=external,
                    title=title.strip(),
                    url=url,
                    summary=strip_markup(str(summary)) or None,
                    published_at=when,
                )
            )
    return items


def parse_feed(kind: str, body: str) -> list[ParsedItem]:
    if kind == "json":
        return parse_json_feed(body)
    return parse_atom_or_rss(body)


async def fetch_feed(
    client: httpx.AsyncClient,
    feed: NewsFeed,
    *,
    now: datetime | None = None,
) -> FetchOutcome:
    """Fetch one feed conditionally and record what happened to it.

    Never raises for an unreachable feed: the outcome is `failed` with the
    reason, because a run that dies on one dead changelog tells you nothing about
    the other twenty.
    """
    now = now or datetime.now(UTC).replace(tzinfo=None)

    if is_blocked_host(feed.url):
        feed.last_status = "blocked_host"
        feed.last_error = (
            "popularity feed, blocked by name: it is what the retired trend scout read"
        )
        return FetchOutcome(feed.id, feed.name, "failed", error=feed.last_error)

    headers: dict[str, str] = {"accept": "application/atom+xml, application/rss+xml, "
                              "application/json;q=0.9, */*;q=0.5"}
    if feed.last_etag:
        headers["if-none-match"] = feed.last_etag
    if feed.last_modified:
        headers["if-modified-since"] = feed.last_modified

    try:
        response = await request_with_retries(client, "GET", feed.url, headers=headers)
    except EvidenceHTTPError as exc:
        feed.consecutive_failures = (feed.consecutive_failures or 0) + 1
        feed.last_status = "failed"
        feed.last_error = str(exc)
        feed.last_fetched_at = now
        return FetchOutcome(feed.id, feed.name, "failed", error=str(exc))

    feed.last_fetched_at = now

    if response.status_code == 304:
        feed.consecutive_failures = 0
        feed.last_status = "unchanged"
        feed.last_error = None
        return FetchOutcome(feed.id, feed.name, "unchanged", http_status=304)

    if response.status_code >= 400:
        feed.consecutive_failures = (feed.consecutive_failures or 0) + 1
        feed.last_status = "failed"
        feed.last_error = f"HTTP {response.status_code}"
        return FetchOutcome(
            feed.id,
            feed.name,
            "failed",
            error=feed.last_error,
            http_status=response.status_code,
        )

    try:
        items = parse_feed(feed.kind, response.text)
    except ValueError as exc:
        feed.consecutive_failures = (feed.consecutive_failures or 0) + 1
        feed.last_status = "unparseable"
        feed.last_error = str(exc)
        return FetchOutcome(feed.id, feed.name, "failed", error=str(exc))

    feed.consecutive_failures = 0
    feed.last_status = "ok"
    feed.last_error = None
    feed.last_etag = response.headers.get("etag") or feed.last_etag
    feed.last_modified = response.headers.get("last-modified") or feed.last_modified
    feed.items_seen_total = (feed.items_seen_total or 0) + len(items)

    return FetchOutcome(
        feed.id, feed.name, "ok", items=items, http_status=response.status_code
    )


async def record_items(
    session: Any,
    workspace_id: uuid.UUID,
    feed: NewsFeed,
    items: list[ParsedItem],
    *,
    now: datetime | None = None,
) -> tuple[list[NewsItem], int]:
    """Store what is new. Returns (new rows, how many were already known).

    Identity is (workspace, feed, external_id), so re-reading a feed every day
    is free and a vendor rewriting a changelog entry in place does not produce a
    duplicate.
    """
    now = now or datetime.now(UTC).replace(tzinfo=None)
    if not items:
        return [], 0

    external_ids = [i.external_id for i in items if i.external_id]
    known = {
        row.external_id
        for row in (
            await session.execute(
                select(NewsItem).where(
                    NewsItem.workspace_id == workspace_id,
                    NewsItem.feed_id == feed.id,
                    NewsItem.external_id.in_(external_ids),
                )
            )
        )
        .scalars()
        .all()
    }

    created: list[NewsItem] = []
    for item in items:
        if not item.external_id or item.external_id in known:
            continue
        known.add(item.external_id)
        row = NewsItem(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            feed_id=feed.id,
            external_id=item.external_id[:400],
            url=(item.url or feed.url)[:1000],
            title=(item.title or "(untitled)")[:600],
            summary=item.summary,
            publisher=feed.name,
            published_at=item.published_at,
            fetched_at=now,
            source_tier=feed.tier,
            matched=False,
        )
        session.add(row)
        created.append(row)

    await session.flush()
    return created, len(items) - len(created)


def health_lines(feeds: list[NewsFeed]) -> list[str]:
    """What `tce_health` prints. An empty day and a broken one must differ.

    This is the trap this stack has hit before: a collector that returns nothing
    because everything is quiet looks exactly like one returning nothing because
    it is broken, and the second one goes unnoticed for weeks.
    """
    lines: list[str] = []
    for feed in sorted(feeds, key=lambda f: (-(f.consecutive_failures or 0), f.name)):
        if (feed.consecutive_failures or 0) >= FAILURES_BEFORE_ALARM:
            lines.append(
                f"DOWN  {feed.name}: {feed.consecutive_failures} failures in a row"
                f" ({feed.last_error or 'no reason recorded'})"
            )
        elif feed.consecutive_failures:
            lines.append(f"flaky {feed.name}: {feed.consecutive_failures} failure(s)")
    return lines
