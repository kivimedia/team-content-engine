"""Fetching: parse what vendors actually ship, and never confuse quiet with broken."""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
import pytest
from sqlalchemy import select

from tce.models.news import NewsFeed, NewsItem
from tce.news.feeds import (
    BLOCKED_HOSTS,
    FAILURES_BEFORE_ALARM,
    fetch_feed,
    health_lines,
    is_blocked_host,
    parse_feed,
    record_items,
    strip_markup,
)

WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
NOW = datetime(2026, 9, 21, 12, 0, 0)

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Vendor releases</title>
  <entry>
    <id>tag:vendor,2026:release/9.1.0</id>
    <title>9.1.0 changes call forwarding defaults</title>
    <link rel="alternate" href="https://vendor.example/releases/9.1.0"/>
    <updated>2026-09-20T08:00:00Z</updated>
    <summary>&lt;p&gt;A new &lt;b&gt;parameter&lt;/b&gt; controls fallback.&lt;/p&gt;</summary>
  </entry>
</feed>
"""

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Changelog</title>
  <item>
    <title>Pricing moves to per message</title>
    <link>https://vendor.example/changelog/pricing</link>
    <guid>changelog-pricing-2026-09</guid>
    <pubDate>Sat, 20 Sep 2026 09:30:00 GMT</pubDate>
    <description>Conversation pricing is retired.</description>
  </item>
</channel></rss>
"""

JSON_FEED = """
{"items": [
  {"id": "rel-45", "title": "v4.5.0", "url": "https://vendor.example/r/45",
   "date_published": "2026-09-19T10:00:00Z", "content_text": "Adds prompt caching for tools."}
]}
"""


def _feed(**kw) -> NewsFeed:
    defaults = dict(
        id=uuid.uuid4(),
        workspace_id=WS,
        name="Vendor changelog",
        url="https://vendor.example/feed.xml",
        kind="atom",
        tier="1a",
        enabled=True,
        consecutive_failures=0,
        items_seen_total=0,
    )
    defaults.update(kw)
    return NewsFeed(**defaults)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_atom_entry_is_parsed_with_markup_stripped():
    items = parse_feed("atom", ATOM)
    assert len(items) == 1
    item = items[0]
    assert item.title == "9.1.0 changes call forwarding defaults"
    assert item.url == "https://vendor.example/releases/9.1.0"
    assert item.external_id == "tag:vendor,2026:release/9.1.0"
    assert item.published_at == datetime(2026, 9, 20, 8, 0, 0)
    assert "<b>" not in (item.summary or "")
    assert "parameter" in (item.summary or "")


def test_rss_item_is_parsed_including_its_rfc822_date():
    items = parse_feed("rss", RSS)
    assert len(items) == 1
    assert items[0].external_id == "changelog-pricing-2026-09"
    assert items[0].published_at == datetime(2026, 9, 20, 9, 30, 0)


def test_json_feed_is_parsed():
    items = parse_feed("json", JSON_FEED)
    assert len(items) == 1
    assert items[0].title == "v4.5.0"
    assert "prompt caching" in (items[0].summary or "")


def test_unparseable_body_raises_rather_than_returning_nothing():
    """Silently returning [] would read as 'the vendor shipped nothing today'."""
    with pytest.raises(ValueError):
        parse_feed("atom", "<not xml")
    with pytest.raises(ValueError):
        parse_feed("json", "{nope")


def test_strip_markup_collapses_whitespace():
    assert strip_markup("<p>a  <b>b</b>\n c</p>") == "a b c"
    assert strip_markup(None) == ""


# ---------------------------------------------------------------------------
# The blocklist: the old failure's sources, gone by name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", sorted(BLOCKED_HOSTS))
def test_popularity_feeds_are_blocked_by_name(host):
    assert is_blocked_host(f"https://{host}/feed")
    assert is_blocked_host(f"https://www.{host}/feed")
    assert is_blocked_host(f"https://blog.{host}/rss")


def test_the_retired_scouts_own_sources_are_in_the_blocklist():
    assert "techcrunch.com" in BLOCKED_HOSTS
    assert "venturebeat.com" in BLOCKED_HOSTS


def test_a_vendor_changelog_is_not_blocked():
    assert not is_blocked_host("https://vendor.example/feed.xml")
    assert not is_blocked_host("")


@pytest.mark.asyncio
async def test_a_blocked_feed_is_never_even_fetched():
    called = False

    def handler(request):  # pragma: no cover - must not run
        nonlocal called
        called = True
        return httpx.Response(200, text=ATOM)

    feed = _feed(url="https://techcrunch.com/feed")
    async with _client(handler) as client:
        outcome = await fetch_feed(client, feed, now=NOW)
    assert not called
    assert outcome.status == "failed"
    assert "trend scout" in (outcome.error or "")


# ---------------------------------------------------------------------------
# Conditional fetching and health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_successful_fetch_stores_the_validators():
    def handler(request):
        return httpx.Response(
            200,
            text=ATOM,
            headers={"etag": 'W/"abc"', "last-modified": "Sat, 20 Sep 2026 08:00:00 GMT"},
        )

    feed = _feed()
    async with _client(handler) as client:
        outcome = await fetch_feed(client, feed, now=NOW)

    assert outcome.status == "ok"
    assert len(outcome.items) == 1
    assert feed.last_etag == 'W/"abc"'
    assert feed.last_modified == "Sat, 20 Sep 2026 08:00:00 GMT"
    assert feed.consecutive_failures == 0
    assert feed.items_seen_total == 1


@pytest.mark.asyncio
async def test_a_quiet_feed_costs_a_304_and_sends_its_validators():
    seen: dict[str, str] = {}

    def handler(request):
        seen.update({k.lower(): v for k, v in request.headers.items()})
        return httpx.Response(304)

    feed = _feed(last_etag='W/"abc"', last_modified="Sat, 20 Sep 2026 08:00:00 GMT")
    async with _client(handler) as client:
        outcome = await fetch_feed(client, feed, now=NOW)

    assert seen["if-none-match"] == 'W/"abc"'
    assert seen["if-modified-since"] == "Sat, 20 Sep 2026 08:00:00 GMT"
    assert outcome.status == "unchanged"
    assert outcome.ok
    assert outcome.items == []


@pytest.mark.asyncio
async def test_a_dead_feed_is_recorded_as_failing_not_as_empty():
    """The trap: quiet and broken must not look the same."""

    def handler(request):
        return httpx.Response(404)

    feed = _feed(consecutive_failures=1)
    async with _client(handler) as client:
        outcome = await fetch_feed(client, feed, now=NOW)

    assert outcome.status == "failed"
    assert not outcome.ok
    assert feed.consecutive_failures == 2
    assert feed.last_status == "failed"
    assert "404" in (feed.last_error or "")


@pytest.mark.asyncio
async def test_a_recovering_feed_clears_its_failure_count():
    def handler(request):
        return httpx.Response(200, text=ATOM)

    feed = _feed(consecutive_failures=5, last_error="HTTP 500")
    async with _client(handler) as client:
        await fetch_feed(client, feed, now=NOW)
    assert feed.consecutive_failures == 0
    assert feed.last_error is None


@pytest.mark.asyncio
async def test_unparseable_content_counts_as_a_failure():
    def handler(request):
        return httpx.Response(200, text="<not xml")

    feed = _feed()
    async with _client(handler) as client:
        outcome = await fetch_feed(client, feed, now=NOW)
    assert outcome.status == "failed"
    assert feed.last_status == "unparseable"
    assert feed.consecutive_failures == 1


def test_health_names_the_feeds_that_are_down():
    down = _feed(name="Dead vendor", consecutive_failures=FAILURES_BEFORE_ALARM,
                 last_error="HTTP 500")
    flaky = _feed(name="Flaky vendor", consecutive_failures=1)
    fine = _feed(name="Healthy vendor", consecutive_failures=0)

    lines = health_lines([fine, flaky, down])
    assert any(line.startswith("DOWN  Dead vendor") for line in lines)
    assert any("flaky Flaky vendor" in line for line in lines)
    assert not any("Healthy vendor" in line for line in lines)


def test_health_is_silent_when_everything_is_fine():
    assert health_lines([_feed(name="a"), _feed(name="b")]) == []


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_items_are_stored_once_however_often_the_feed_is_read(editorial_session):
    feed = _feed()
    editorial_session.add(feed)
    await editorial_session.flush()

    items = parse_feed("atom", ATOM)
    created, known = await record_items(editorial_session, WS, feed, items, now=NOW)
    assert len(created) == 1 and known == 0

    created2, known2 = await record_items(editorial_session, WS, feed, items, now=NOW)
    assert created2 == [] and known2 == 1

    rows = (
        (await editorial_session.execute(select(NewsItem).where(NewsItem.workspace_id == WS)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].matched is False, "an item is unmatched until the matcher says otherwise"
    assert rows[0].source_tier == "1a"


@pytest.mark.asyncio
async def test_recording_nothing_is_not_an_error(editorial_session):
    feed = _feed()
    editorial_session.add(feed)
    await editorial_session.flush()
    created, known = await record_items(editorial_session, WS, feed, [], now=NOW)
    assert created == [] and known == 0
