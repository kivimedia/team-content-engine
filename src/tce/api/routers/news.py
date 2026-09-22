"""The Timely tab: what TCE believes his world is, and what it did with the week.

The page you open when the lane suggests something strange, because the answer is
almost always a wrong anchor. Four things, all private to the editor:

  the anchor index     the named things an announcement can land on
  feed health          which feeds answered, and which are DOWN - kept apart,
                       because "no news today" and "four feeds are down" must
                       never look the same
  the watchlist        real, but it does not connect yet; somewhere he goes,
                       never something that arrives
  standing facts       what Kivi Media runs and what its owners keep bringing,
                       editable, since they are the only anchors a person writes

Nothing here spends a model call or starts a run.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tce.api.private_access import require_private_workspace
from tce.models.editorial import EvidenceMoment, EvidenceSource
from tce.models.news import NewsAnchor, NewsFeed, NewsItem, NewsWatchlist
from tce.news.feeds import FAILURES_BEFORE_ALARM, health_lines
from tce.news.standing import (
    SOURCE_KIND as STANDING_KIND,
)
from tce.news.standing import (
    StandingFact,
    StandingFactRejectedError,
    seed_standing_facts,
)

router = APIRouter(prefix="/news", tags=["news"])


def get_news_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Overridable in tests, like the evidence routes."""
    from tce.db.session import async_session

    return async_session


def _iso(value: Any) -> str | None:
    return value.isoformat() + "Z" if value else None


async def _standing_facts(session: AsyncSession, ws: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(EvidenceMoment)
            .join(EvidenceSource, EvidenceMoment.source_id == EvidenceSource.id)
            .where(
                EvidenceMoment.workspace_id == ws,
                EvidenceSource.source_kind == STANDING_KIND,
                EvidenceMoment.status == "active",
            )
        )
    ).scalars().all()
    facts = []
    for moment in rows:
        ref = moment.news_ref or {}
        facts.append(
            {
                "anchor_kind": ref.get("anchor_kind"),
                "anchor_term": ref.get("anchor_term"),
                "lesson": moment.lesson_summary,
                "note": moment.excerpt_private if moment.excerpt_private != moment.lesson_summary
                else None,
                "position": ref.get("position", 0),
            }
        )
    facts.sort(key=lambda f: (f["anchor_kind"] or "", f["position"]))
    return facts


@router.get("/overview")
async def overview(
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_news_sessionmaker),
) -> dict[str, Any]:
    from tce.settings import settings

    async with sessionmaker() as session:
        anchors = (
            await session.execute(
                select(NewsAnchor)
                .where(NewsAnchor.workspace_id == ws, NewsAnchor.active.is_(True))
                .order_by(NewsAnchor.kind, NewsAnchor.weight.desc(), NewsAnchor.normalized_term)
            )
        ).scalars().all()
        feeds = (
            await session.execute(select(NewsFeed).where(NewsFeed.workspace_id == ws))
        ).scalars().all()
        watch_rows = (
            await session.execute(
                select(NewsWatchlist, NewsItem)
                .join(NewsItem, NewsWatchlist.news_item_id == NewsItem.id)
                .where(NewsWatchlist.workspace_id == ws, NewsWatchlist.resolved_at.is_(None))
                .order_by(NewsWatchlist.created_at.desc())
                .limit(100)
            )
        ).all()
        standing = await _standing_facts(session, ws)

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for anchor in anchors:
        by_kind.setdefault(anchor.kind, []).append(
            {
                "term": anchor.term,
                "weight": anchor.weight,
                "origin": anchor.origin_ref or anchor.origin_kind,
                "citable": anchor.standing_moment_id is not None,
            }
        )

    return {
        # Said first, because a switched-off lane explains an empty page.
        "lane_on": bool(settings.news_lane),
        "anchors": by_kind,
        "anchor_count": len(anchors),
        "feeds": [
            {
                "name": f.name,
                "tier": f.tier,
                "enabled": f.enabled,
                "status": f.last_status,
                "last_fetched_at": _iso(f.last_fetched_at),
                "consecutive_failures": f.consecutive_failures or 0,
                "down": (f.consecutive_failures or 0) >= FAILURES_BEFORE_ALARM,
                "error": f.last_error,
            }
            for f in sorted(feeds, key=lambda f: (-(f.consecutive_failures or 0), f.name))
        ],
        "feed_alarms": health_lines(list(feeds)),
        "watchlist": [
            {
                "id": str(w.id),
                "title": item.title,
                "publisher": item.publisher,
                "published_at": _iso(item.published_at),
                "url": item.primary_url or item.url,
                "reason": w.reason,
                "watching_for": list(w.recheck_anchor_kinds or []),
            }
            for w, item in watch_rows
        ],
        "standing_facts": standing,
    }


class FactIn(BaseModel):
    anchor_kind: str
    anchor_term: str = Field(min_length=1)
    lesson: str = Field(min_length=1)
    note: str | None = None


class FactsIn(BaseModel):
    facts: list[FactIn]


@router.put("/standing-facts")
async def replace_standing_facts(
    body: FactsIn,
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_news_sessionmaker),
) -> dict[str, Any]:
    """Replace the list. Previous facts are retired as stale, never deleted.

    Refuses anything specific (a name, an email, a money figure) with the reason,
    because a standing fact is a category and it is scanned when it is typed.
    """
    facts = [StandingFact(f.anchor_kind, f.anchor_term, f.lesson, f.note) for f in body.facts]
    async with sessionmaker() as session:
        try:
            result = await seed_standing_facts(session, ws, facts, author="editor")
        except StandingFactRejectedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await session.commit()
    return result
