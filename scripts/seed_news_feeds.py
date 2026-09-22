"""Seed the feed registry: changelogs of what Ziv runs, plus the frontier feeds.

The list is narrow on purpose. Roughly eighty percent is vendor changelogs for
software running in production for Ziv or a client right now, which is what lets
an item arrive with an anchor already attached. The retired trend_scout read
TechCrunch funding and VentureBeat enterprise AI; those hosts are blocked by name
in `tce.news.feeds.BLOCKED_HOSTS` and cannot be added here.

Tiers:
  1a  a vendor whose changelog describes something he actually runs. Citable.
  1b  frontier releases. Citable. Kept to a handful on purpose.
  2   discovery only: may point at a primary source, may never BE one.

Usage:
    PYTHONPATH=src python scripts/seed_news_feeds.py --check     # verify, write nothing
    PYTHONPATH=src python scripts/seed_news_feeds.py --dry-run
    PYTHONPATH=src python scripts/seed_news_feeds.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

import httpx
from sqlalchemy import select

from tce.models.news import NewsFeed
from tce.news.feeds import is_blocked_host

# (name, url, kind, tier, vendor)
FEEDS: list[tuple[str, str, str, str, str | None]] = [
    # --- 1a: his own stack -------------------------------------------------
    ("Claude Code releases", "https://github.com/anthropics/claude-code/releases.atom",
     "atom", "1a", "anthropic"),
    ("MCP specification releases",
     "https://github.com/modelcontextprotocol/modelcontextprotocol/releases.atom",
     "atom", "1a", "model context protocol"),
    ("Supabase releases", "https://github.com/supabase/supabase/releases.atom",
     "atom", "1a", "supabase"),
    ("Next.js releases", "https://github.com/vercel/next.js/releases.atom",
     "atom", "1a", "vercel"),
    ("Twilio Python SDK releases", "https://github.com/twilio/twilio-python/releases.atom",
     "atom", "1a", "twilio"),
    ("Stripe Python SDK releases", "https://github.com/stripe/stripe-python/releases.atom",
     "atom", "1a", "stripe"),
    ("OpenAI Python SDK releases", "https://github.com/openai/openai-python/releases.atom",
     "atom", "1a", "openai"),
    ("Anthropic Python SDK releases",
     "https://github.com/anthropics/anthropic-sdk-python/releases.atom",
     "atom", "1a", "anthropic"),
    ("Deepgram SDK releases", "https://github.com/deepgram/deepgram-python-sdk/releases.atom",
     "atom", "1a", "deepgram"),
    ("ElevenLabs SDK releases", "https://github.com/elevenlabs/elevenlabs-python/releases.atom",
     "atom", "1a", "elevenlabs"),
    ("FastAPI releases", "https://github.com/fastapi/fastapi/releases.atom",
     "atom", "1a", "fastapi"),
    ("SQLAlchemy releases", "https://github.com/sqlalchemy/sqlalchemy/releases.atom",
     "atom", "1a", "sqlalchemy"),
    ("Cloudflare changelog", "https://developers.cloudflare.com/changelog/rss.xml",
     "rss", "1a", "cloudflare"),
    ("Google Workspace release notes",
     "https://workspaceupdates.googleblog.com/atom.xml", "atom", "1a", "google workspace"),
    ("GitHub changelog", "https://github.blog/changelog/feed/", "rss", "1a", "github"),

    # --- 1b: frontier ------------------------------------------------------
    # Anthropic publishes NO feed. Checked 22-Sep-2026: /rss.xml, /news/rss.xml,
    # /news/feed.xml, /engineering/rss.xml and the docs release notes are all 404.
    # Their announcements still reach the lane, through the Claude Code and SDK
    # release feeds above (tier 1a, and closer to what actually changes for a
    # running system) and through the tier-2 discovery feed. A dead URL is worse
    # than an absent one: it looks exactly like a quiet day.
    ("OpenAI blog", "https://openai.com/blog/rss.xml", "rss", "1b", "openai"),
    ("Google DeepMind blog", "https://deepmind.google/blog/rss.xml", "rss", "1b", "google"),

    # --- 2: discovery only, never cited -----------------------------------
    ("Simon Willison", "https://simonwillison.net/atom/everything/", "atom", "2", None),
]


async def check_all() -> int:
    """Fetch every feed once and say which ones actually answer.

    A registry full of dead URLs would make the lane look broken on day one, and
    "no news today" is exactly what a 404 looks like from the outside.
    """
    bad = 0
    async with httpx.AsyncClient(
        timeout=20.0, follow_redirects=True, headers={"user-agent": "tce-news/1.0"}
    ) as client:
        for name, url, kind, tier, _vendor in FEEDS:
            try:
                response = await client.get(url)
                status = response.status_code
                size = len(response.text)
            except httpx.HTTPError as exc:
                print(f"  FAIL  [{tier}] {name}: {type(exc).__name__}")
                bad += 1
                continue
            if status >= 400:
                print(f"  FAIL  [{tier}] {name}: HTTP {status}")
                bad += 1
                continue
            try:
                from tce.news.feeds import parse_feed

                items = parse_feed(kind, response.text)
            except ValueError as exc:
                print(f"  PARSE [{tier}] {name}: {exc}")
                bad += 1
                continue
            newest = items[0].title[:54] if items else "(no entries)"
            print(f"  ok    [{tier}] {name}: {len(items)} items, {size}b | {newest}")
    print(f"\n{len(FEEDS) - bad}/{len(FEEDS)} feeds answered and parsed")
    return 1 if bad else 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fetch each feed, write nothing")
    parser.add_argument("--dry-run", action="store_true", help="print, write nothing")
    parser.add_argument("--workspace", default=os.environ.get("TCE_EDITOR_DEFAULT_WORKSPACE_ID"))
    args = parser.parse_args()

    for name, url, _kind, _tier, _vendor in FEEDS:
        if is_blocked_host(url):
            print(f"refusing to seed a blocked popularity host: {name} ({url})", file=sys.stderr)
            return 2

    if args.check:
        return await check_all()

    by_tier: dict[str, int] = {}
    for _n, _u, _k, tier, _v in FEEDS:
        by_tier[tier] = by_tier.get(tier, 0) + 1
    print(f"{len(FEEDS)} feeds: " + ", ".join(f"tier {k} {v}" for k, v in sorted(by_tier.items())))
    for name, url, kind, tier, vendor in FEEDS:
        print(f"  [{tier}] {name}  ({kind})  {vendor or 'discovery only'}")

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    if not args.workspace:
        print(
            "\nNo workspace. Pass --workspace or set TCE_EDITOR_DEFAULT_WORKSPACE_ID.",
            file=sys.stderr,
        )
        return 2

    from tce.db.session import async_session

    ws = uuid.UUID(args.workspace)
    created = updated = 0
    async with async_session() as session:
        existing = {
            row.url: row
            for row in (
                await session.execute(select(NewsFeed).where(NewsFeed.workspace_id == ws))
            )
            .scalars()
            .all()
        }
        for name, url, kind, tier, vendor in FEEDS:
            row = existing.get(url)
            if row is None:
                session.add(
                    NewsFeed(
                        id=uuid.uuid4(),
                        workspace_id=ws,
                        name=name,
                        url=url,
                        kind=kind,
                        tier=tier,
                        vendor=vendor,
                        enabled=True,
                    )
                )
                created += 1
            else:
                row.name, row.kind, row.tier, row.vendor = name, kind, tier, vendor
                updated += 1
        await session.commit()
    print(f"\n{created} feeds added, {updated} updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
