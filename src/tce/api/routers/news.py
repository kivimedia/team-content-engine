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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, text
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


def _owner_news(ws: uuid.UUID) -> None:
    from tce.editorial.news_rules import owner_policy
    if not owner_policy(ws):
        raise HTTPException(status_code=403, detail="This editorial workflow is owner-only.")


class SubmissionIn(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    angle: str = Field(min_length=10, max_length=2000)
    sender: str = Field(default="km-bot", min_length=1, max_length=100)


@router.post("/submissions")
async def submit_story(
    body: SubmissionIn,
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: Any = Depends(get_news_sessionmaker),
) -> dict[str, Any]:
    """Durable editorial intake. A receipt is not an approval or a publication."""
    import hashlib
    from tce.editorial.news_workflow import record_submission, submission_url
    from tce.news import discovery
    from tce.services.url_fetcher import fetch_url_text

    _owner_news(ws)
    try:
        url = submission_url(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    async with sessionmaker() as db:
        if db.bind.dialect.name == "postgresql":
            lock_id = int.from_bytes(hashlib.sha256(f"{ws}:{url}".encode()).digest()[:8],
                                     "big", signed=True)
            await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
        equivalents = [url, "http:" + url[6:]]
        item = (await db.execute(select(NewsItem).where(
            NewsItem.workspace_id == ws,
            or_(NewsItem.canonical_url.in_(equivalents), NewsItem.primary_url.in_(equivalents),
                NewsItem.url.in_(equivalents)),
        ).order_by(NewsItem.created_at.asc()).limit(1).with_for_update())).scalar_one_or_none()
        if item is None or (
            (item.feed_id is None or item.source_tier == "2")
            and not (item.editorial_meta or {}).get("primary_source_verified")
        ):
            out = await discovery.check_one(db, ws, url=url, fetch_text=fetch_url_text)
            if not out.get("item_id"):
                raise HTTPException(status_code=422, detail=out.get("why", "Source unavailable."))
            item = await db.get(NewsItem, uuid.UUID(out["item_id"]))
        try:
            receipt = await record_submission(db, ws, item, body.sender, body.angle)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await db.commit()
    return receipt


@router.get("/workflow")
async def news_workflow(
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: Any = Depends(get_news_sessionmaker),
) -> dict[str, Any]:
    from tce.editorial.news_workflow import workflow_status
    async with sessionmaker() as db:
        return await workflow_status(db, ws)


@router.get("/items/{item_id}/handoff")
async def handoff_status(
    item_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: Any = Depends(get_news_sessionmaker),
) -> dict[str, Any]:
    from datetime import datetime
    from tce.editorial.news_workflow import choose_news_candidate
    from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate
    from tce.models.news import NewsAppraisal

    _owner_news(ws)
    async with sessionmaker() as db:
        item = await db.get(NewsItem, item_id)
        if item is None or item.workspace_id != ws:
            raise HTTPException(status_code=404, detail="No such story.")
        meta = item.editorial_meta or {}
        candidates = list((await db.execute(select(TopicCandidate).where(
            TopicCandidate.workspace_id == ws, TopicCandidate.news_item_id == item_id,
        ).order_by(TopicCandidate.created_at.desc()))).scalars())
        ids = [c.id for c in candidates]
        all_packets = list((await db.execute(select(RecordingPacket).where(
            RecordingPacket.workspace_id == ws, RecordingPacket.candidate_id.in_(ids),
            RecordingPacket.status != "superseded",
        ).order_by(RecordingPacket.version.desc()))).scalars())
        packet_map = {}
        for row in all_packets:
            packet_map.setdefault(row.candidate_id, row)
        upload_ids = set((await db.execute(select(RecordingUpload.candidate_id).where(
            RecordingUpload.workspace_id == ws, RecordingUpload.candidate_id.in_(ids),
            RecordingUpload.archived_at.is_(None),
        ))).scalars())
        cand = choose_news_candidate(candidates, packet_map, upload_ids)
        state = item.prefilter_reason or "awaiting_appraisal"
        next_action = "TCE will check the source, relevance and claims."
        packet = None
        if cand:
            packet = packet_map.get(cand.id)
            if cand.id in upload_ids:
                state, next_action = "recorded", "Ziv can review the edit in Library."
            elif cand.status in {"rejected", "withdrawn"}:
                state, next_action = "held", "Review the editorial reason before retrying."
            elif cand.expires_at and cand.expires_at <= datetime.utcnow():
                state, next_action = "expired", "Refresh the source or develop a retrospective."
            elif packet and packet.status in {"ready", "exported"}:
                state, next_action = "ready_to_record", "Ziv can open the brief and record."
            else:
                state, next_action = "needs_brief", "Prepare the approved topic as a recording brief."
        else:
            appraisal = (await db.execute(select(NewsAppraisal).where(
                NewsAppraisal.workspace_id == ws, NewsAppraisal.news_item_id == item_id,
            ).order_by(NewsAppraisal.created_at.desc()).limit(1))).scalar_one_or_none()
            if appraisal:
                state = (meta.get("appraisal_retry") or {}).get("state") or appraisal.verdict
                next_action = ("TCE will develop a topic and recording brief."
                               if appraisal.verdict == "publish" else appraisal.verdict_reason)
        return {
            "receipt_id": meta.get("receipt_id"), "item_id": str(item.id),
            "state": state, "next": next_action,
            "candidate_id": str(cand.id) if cand else None,
            "packet_id": str(packet.id) if packet else None,
        }


class RetryIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1500)


@router.post("/items/{item_id}/retry")
async def retry_story(
    item_id: uuid.UUID, body: RetryIn,
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: Any = Depends(get_news_sessionmaker),
) -> dict[str, Any]:
    from datetime import datetime
    _owner_news(ws)
    async with sessionmaker() as db:
        item = (await db.execute(select(NewsItem).where(
            NewsItem.id == item_id, NewsItem.workspace_id == ws,
        ).with_for_update())).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="No such story.")
        meta = dict(item.editorial_meta or {})
        requests = list(meta.get("retry_requests") or [])
        requests.append({"reason": body.reason, "at": datetime.utcnow().isoformat() + "Z"})
        item.editorial_meta = {**meta, "retry_nonce": str(uuid.uuid4()),
                               "retry_requests": requests[-20:]}
        await db.commit()
    return {"item_id": str(item_id), "state": "retry_requested",
            "next": "Review requested. The next news run checks your reason and evidence "
                    "within the per-story retry limit; a request is not an acceptance."}


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


# ---------------------------------------------------------------------------
# The manual request
# ---------------------------------------------------------------------------


class CheckIn(BaseModel):
    url: str = Field(min_length=8, max_length=1000)


async def _appraise_in_background(sessionmaker: Any, ws: uuid.UUID, item_id: uuid.UUID) -> None:
    """The one model call, outside the request. Waiting for capacity is fine."""
    from tce import llm as _llm
    from tce.news import discovery

    async with sessionmaker() as session:
        await discovery.appraise_pending(
            session, ws, complete=_llm.complete, only_item=item_id
        )
        await session.commit()


@router.post("/check")
async def check(
    body: CheckIn,
    background: BackgroundTasks,
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_news_sessionmaker),
) -> dict[str, Any]:
    """"Is this announcement worth anything to me?"

    Answers the matching question immediately, with what it matched named. If it
    matched, one appraisal is queued and GET /news/items/{id} says how it went.
    """
    from tce.news import discovery
    from tce.services.url_fetcher import fetch_url_text

    async with sessionmaker() as session:
        out = await discovery.check_one(session, ws, url=body.url, fetch_text=fetch_url_text)
        await session.commit()
    if out.get("status") == "matched":
        background.add_task(
            _appraise_in_background, sessionmaker, ws, uuid.UUID(out["item_id"])
        )
        out["appraising"] = True
    return out


@router.get("/items/{item_id}")
async def item_status(
    item_id: uuid.UUID,
    ws: uuid.UUID = Depends(require_private_workspace),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_news_sessionmaker),
) -> dict[str, Any]:
    from tce.models.news import NewsAppraisal

    async with sessionmaker() as session:
        item = await session.get(NewsItem, item_id)
        if item is None or item.workspace_id != ws:
            raise HTTPException(status_code=404, detail="no such item")
        appraisal = (
            await session.execute(
                select(NewsAppraisal)
                .where(NewsAppraisal.news_item_id == item.id, NewsAppraisal.workspace_id == ws)
                .order_by(NewsAppraisal.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    state = (
        "appraised" if appraisal
        else "waiting for the appraisal" if item.matched
        else f"not taken further: {item.prefilter_reason or 'not matched'}"
    )
    return {
        "item_id": str(item.id),
        "title": item.title,
        "url": item.primary_url or item.url,
        "state": state,
        "appraisal": None if appraisal is None else {
            "verdict": appraisal.verdict,
            "reason": appraisal.verdict_reason,
            "format": appraisal.format,
            "expires_at": _iso(appraisal.expires_at),
            "story_weight": appraisal.story_weight,
            "do_differently": list(appraisal.do_differently or []),
            "next": (
                "It joins the next weekly selection as a candidate."
                if appraisal.verdict == "publish"
                else "It is on the watchlist on the Timely tab."
                if appraisal.verdict == "watch"
                else "Not taken further."
            ),
        },
    }
