"""The daily run: find, match, expire, and - only for what matched - appraise.

Rides the existing daily-evidence content run rather than a schedule of its own.
Its collecting stage calls `discover` (deterministic, no model); its extracting
stage calls `appraise_pending` (one subscription job per matched item, capped).
That keeps one cron entry, one lease-and-resume machine, and zero change when the
lane is off. Every public function here is safe to call with the lane off: it
returns immediately and says so.

Nothing in this module may fail the evidence run it rides on. A dead feed, a
page that will not load, a model that is out of capacity - each is recorded in
the counts and the run continues. "News had a bad day" must never become "your
calls were not collected".
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from tce.models.editorial import EvidenceMoment, EvidenceSource, TopicCandidate
from tce.models.news import NewsAnchor, NewsAppraisal, NewsFeed, NewsItem, NewsMatch
from tce.news.anchors import build_anchor_index
from tce.news.appraise import (
    AppraisalInput,
    AppraisalInvalidError,
    build_request,
    validate_appraisal,
)
from tce.news.feeds import fetch_feed, is_blocked_host, record_items, sha256_of
from tce.news.matcher import match_item
from tce.news.record import record_appraisal

# Something older than this is not news, however it arrived.
WINDOW_DAYS = 2
# The daily cap on model calls. A cost and noise control; the positioning control
# is the weekly ceiling in the selector.
MAX_APPRAISALS_PER_DAY = 5
# How far back an anchor's own evidence counts as "recent" for the appraiser.
RECENT_EVIDENCE_DAYS = 30

FetchText = Callable[[str], Awaitable[dict[str, Any]]]
Complete = Callable[[Any], Awaitable[Any]]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def lane_on() -> bool:
    from tce.settings import settings

    return bool(settings.news_lane)


# ---------------------------------------------------------------------------
# Expiry: stale ideas leave on their own, visibly
# ---------------------------------------------------------------------------


async def expire_sweep(session: Any, ws: uuid.UUID, *, now: datetime | None = None) -> dict:
    """Withdraw proposed news ideas past their date, and pull their evidence.

    Withdrawn, never deleted, and the note says when and why, so the topic list
    can show "Went stale on ..." instead of a card silently disappearing. The
    source gets meta.exclude_reason, which the selector already honours, so the
    item cannot come back next week under a new selection run.

    Recorded ideas are left alone: he already said it. Only unrecorded ones go.
    """
    now = now or _now()
    stale = (
        await session.execute(
            select(TopicCandidate).where(
                TopicCandidate.workspace_id == ws,
                TopicCandidate.news_item_id.is_not(None),
                TopicCandidate.expires_at.is_not(None),
                TopicCandidate.expires_at < now,
                TopicCandidate.status == "proposed",
            )
        )
    ).scalars().all()
    withdrawn = 0
    for cand in stale:
        cand.status = "withdrawn"
        cand.editor_notes = (
            f"Went stale on {cand.expires_at:%A %d %B}: it stopped being worth saying "
            "before it was recorded."
        ).replace(" 0", " ")
        withdrawn += 1

    expired_items = (
        await session.execute(
            select(NewsAppraisal.news_item_id).where(
                NewsAppraisal.workspace_id == ws,
                NewsAppraisal.expires_at.is_not(None),
                NewsAppraisal.expires_at < now,
            )
        )
    ).scalars().all()
    excluded = 0
    if expired_items:
        sources = (
            await session.execute(
                select(EvidenceSource).where(
                    EvidenceSource.workspace_id == ws,
                    EvidenceSource.source_kind == "news_item",
                    EvidenceSource.external_id.in_([str(i) for i in expired_items]),
                )
            )
        ).scalars().all()
        for source in sources:
            meta = dict(source.meta or {})
            if meta.get("exclude_reason") != "expired":
                meta["exclude_reason"] = "expired"
                source.meta = meta
                excluded += 1
    await session.flush()
    return {"withdrawn": withdrawn, "sources_excluded": excluded}


async def refresh_live(
    session: Any, ws: uuid.UUID, *, fetch_text: FetchText, now: datetime | None = None
) -> dict:
    """Re-read the announcement behind every idea still waiting to be recorded.

    If the announcement changed, the claim the script rests on may no longer be
    true. The moments go stale (the selector drops stale moments on its own) and
    the idea carries a plain note - it is never silently rewritten.
    """
    now = now or _now()
    rows = (
        await session.execute(
            select(TopicCandidate, NewsItem)
            .join(NewsItem, TopicCandidate.news_item_id == NewsItem.id)
            .where(
                TopicCandidate.workspace_id == ws,
                TopicCandidate.status.in_(("proposed", "selected")),
                TopicCandidate.expires_at.is_not(None),
                TopicCandidate.expires_at >= now,
            )
        )
    ).all()
    changed = checked = 0
    for cand, item in rows:
        url = item.primary_url or item.url
        if not url or not item.content_sha256:
            continue
        checked += 1
        try:
            page = await fetch_text(url)
        except Exception:  # a flaky page is not a changed announcement
            continue
        text = str(page.get("body_text") or "")
        if not text or sha256_of(text) == item.content_sha256:
            continue
        changed += 1
        cand.editor_notes = (
            "The announcement changed since this idea was chosen. Reread it before "
            "recording."
        )
        if item.evidence_source_id:
            for moment in (
                await session.execute(
                    select(EvidenceMoment).where(
                        EvidenceMoment.source_id == item.evidence_source_id,
                        EvidenceMoment.status == "active",
                    )
                )
            ).scalars():
                moment.status = "stale"
    await session.flush()
    return {"checked": checked, "changed": changed}


# ---------------------------------------------------------------------------
# Stage A: fetch and match. No model.
# ---------------------------------------------------------------------------


async def discover(
    session: Any,
    ws: uuid.UUID,
    *,
    client: Any,
    fetch_text: FetchText,
    now: datetime | None = None,
) -> dict:
    """The deterministic half. A quiet day ends here having cost nothing."""
    now = now or _now()
    if not lane_on():
        return {"skipped": "the news lane is switched off"}

    counts: dict[str, Any] = {
        "feeds_ok": 0, "feeds_failed": 0, "items_new": 0, "items_known": 0,
        "matched": 0, "blocked_shape": 0, "no_anchor": 0, "stale": 0, "unverified": 0,
    }
    anchor_result, _ = await build_anchor_index(session, ws, now=now)
    counts["anchors"] = sum(anchor_result.by_kind.values())
    counts["expiry"] = await expire_sweep(session, ws, now=now)
    counts["refresh"] = await refresh_live(session, ws, fetch_text=fetch_text, now=now)

    feeds = (
        await session.execute(
            select(NewsFeed).where(NewsFeed.workspace_id == ws, NewsFeed.enabled.is_(True))
        )
    ).scalars().all()
    for feed in feeds:
        outcome = await fetch_feed(client, feed, now=now)
        if not outcome.ok:
            counts["feeds_failed"] += 1
            continue
        counts["feeds_ok"] += 1
        created, known = await record_items(session, ws, feed, outcome.items, now=now)
        counts["items_new"] += len(created)
        counts["items_known"] += known

    counts.update(await match_pending(session, ws, fetch_text=fetch_text, now=now))
    await session.flush()
    failed = f", {counts['feeds_failed']} feed(s) failed" if counts["feeds_failed"] else ""
    counts["summary"] = (
        f"{counts['items_new']} new item(s) from {counts['feeds_ok']} feed(s){failed}"
        f"; {counts['matched']} matched something of his"
    )
    return counts


async def match_pending(
    session: Any, ws: uuid.UUID, *, fetch_text: FetchText, now: datetime | None = None
) -> dict:
    """Run every unjudged item in the window through the gate.

    Only a matched item has its primary document fetched: the page load is the
    one network cost that scales, so it is spent only where it can matter.
    """
    now = now or _now()
    since = now - timedelta(days=WINDOW_DAYS)
    anchors = (
        await session.execute(
            select(NewsAnchor).where(NewsAnchor.workspace_id == ws, NewsAnchor.active.is_(True))
        )
    ).scalars().all()
    items = (
        await session.execute(
            select(NewsItem).where(
                NewsItem.workspace_id == ws,
                NewsItem.matched.is_(False),
                NewsItem.prefilter_reason.is_(None),
            )
        )
    ).scalars().all()

    out = {"matched": 0, "blocked_shape": 0, "no_anchor": 0, "stale": 0, "unverified": 0}
    for item in items:
        if item.published_at is not None and item.published_at < since:
            item.prefilter_reason = "stale"
            out["stale"] += 1
            continue
        result = match_item(title=item.title, summary=item.summary, anchors=anchors)
        if not result.matched:
            item.prefilter_reason = "blocked_shape" if result.blocked_shape else "no_anchor"
            out["blocked_shape" if result.blocked_shape else "no_anchor"] += 1
            continue

        url = item.primary_url or item.url
        if not url or is_blocked_host(url):
            item.prefilter_reason = "unverified_source"
            out["unverified"] += 1
            continue
        try:
            page = await fetch_text(url)
        except Exception:
            page = {}
        text = str((page or {}).get("body_text") or "").strip()
        if not text:
            # Without the document there is nothing to check a quote against, so
            # nothing can be confirmed. Try again on the next run rather than
            # appraising on a feed summary.
            out["unverified"] += 1
            continue

        item.primary_url = url
        item.extract_private = text
        item.content_sha256 = sha256_of(text)
        item.source_version = item.source_version or item.content_sha256[:16]
        item.matched = True
        for m in result.matches:
            if m.anchor_id is None:
                continue
            session.add(
                NewsMatch(
                    id=uuid.uuid4(), workspace_id=ws, news_item_id=item.id,
                    anchor_id=m.anchor_id, match_kind=m.kind,
                    matched_span=(m.matched_span or "")[:400], score=m.score,
                )
            )
        out["matched"] += 1
    await session.flush()
    return out


# ---------------------------------------------------------------------------
# Stage B: appraise what matched. One subscription job each, capped.
# ---------------------------------------------------------------------------


async def _anchor_moments(
    session: Any, ws: uuid.UUID, item: NewsItem, now: datetime
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], bool]:
    """(anchors for the prompt, moment ids to cite, recent evidence, demonstrated-after).

    The citable moments are what the selector seats beside the news so a
    candidate can cite them: the standing fact behind a client-solution or
    problem anchor, and the recent commit moments of a matched repo.
    """
    rows = (
        await session.execute(
            select(NewsAnchor)
            .join(NewsMatch, NewsMatch.anchor_id == NewsAnchor.id)
            .where(NewsMatch.news_item_id == item.id, NewsMatch.workspace_id == ws)
        )
    ).scalars().all()
    anchors = [
        {"kind": a.kind, "term": a.term, "origin_ref": a.origin_ref, "origin_kind": a.origin_kind}
        for a in rows
    ]
    ids: list[str] = [str(a.standing_moment_id) for a in rows if a.standing_moment_id]
    repos = [a.origin_ref for a in rows if a.kind == "dependency" and a.origin_ref]
    # A vendor, model or capability match proves the NAME is in his world (a
    # config key, the curated list), not that he did anything with it. On its own
    # it has nothing citable, and a news idea citing nothing of his is rejected by
    # the selector every time - so the appraisal would be a model call spent on a
    # guaranteed no. Look for his own recent commits that mention the term.
    named = [
        a.normalized_term for a in rows
        if a.kind in ("vendor", "model_id", "capability") and a.normalized_term
    ]

    recent: list[dict[str, Any]] = []
    demonstrated_after = False
    if repos or named:
        since = now - timedelta(days=RECENT_EVIDENCE_DAYS)
        for moment, source in (
            await session.execute(
                select(EvidenceMoment, EvidenceSource)
                .join(EvidenceSource, EvidenceMoment.source_id == EvidenceSource.id)
                .where(
                    EvidenceMoment.workspace_id == ws,
                    EvidenceMoment.status == "active",
                    EvidenceSource.source_kind == "github_commit_group",
                    EvidenceSource.occurred_at >= since,
                )
                .order_by(EvidenceSource.occurred_at.desc())
                .limit(200)
            )
        ).all():
            if len(recent) >= 5:
                break
            repo = (source.payload_private or {}).get("repo")
            text = " ".join(
                str(x or "") for x in (moment.lesson_summary, moment.excerpt_private)
            ).casefold()
            mentions = any(term in text for term in named)
            if repo not in repos and not mentions:
                continue
            ids.append(str(moment.id))
            recent.append(
                {
                    "source_kind": source.source_kind,
                    "occurred_at": source.occurred_at.date().isoformat()
                    if source.occurred_at else None,
                    "claim_type": moment.claim_type,
                    "lesson_summary": moment.lesson_summary,
                }
            )
            if (
                moment.claim_type in ("demonstrated", "measured")
                and item.published_at is not None
                and source.occurred_at is not None
                and source.occurred_at > item.published_at
            ):
                demonstrated_after = True
    return anchors, list(dict.fromkeys(ids)), recent, demonstrated_after


async def appraise_pending(
    session: Any,
    ws: uuid.UUID,
    *,
    complete: Complete,
    now: datetime | None = None,
    cap: int = MAX_APPRAISALS_PER_DAY,
    only_item: uuid.UUID | None = None,
) -> dict:
    """Appraise matched items that have no appraisal yet, newest first.

    Capacity running out is not a failure: the item stays matched-but-unappraised
    and the next run picks it up. That is the subscription contract - wait, never
    spend.
    """
    from tce.llm import LLMUnavailable

    now = now or _now()
    if not lane_on() and only_item is None:
        return {"skipped": "the news lane is switched off"}

    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    done_today = len(
        (
            await session.execute(
                select(NewsAppraisal.id).where(
                    NewsAppraisal.workspace_id == ws,
                    NewsAppraisal.created_at >= start_of_day,
                )
            )
        ).all()
    )
    budget = max(0, cap - done_today) if only_item is None else 1

    appraised_ids = select(NewsAppraisal.news_item_id).where(NewsAppraisal.workspace_id == ws)
    stmt = (
        select(NewsItem)
        .where(
            NewsItem.workspace_id == ws,
            NewsItem.matched.is_(True),
            NewsItem.id.not_in(appraised_ids),
        )
        .order_by(NewsItem.published_at.desc().nullslast())
    )
    if only_item is not None:
        stmt = stmt.where(NewsItem.id == only_item)
    pending = (await session.execute(stmt.limit(max(budget, 0)))).scalars().all()

    out = {"appraised": 0, "published": 0, "watched": 0, "rejected": 0,
           "waiting": 0, "invalid": 0, "budget_left": budget}
    for item in pending:
        anchors, cite_ids, recent, demo_after = await _anchor_moments(session, ws, item, now)
        if not cite_ids:
            # Nothing of his to cite, so the selector would reject whatever the
            # model said. Parked on the watchlist with the reason instead, and no
            # model call is spent. It comes back when a commit touching this
            # vendor, or a matching standing fact, gives it something to stand on.
            await record_appraisal(
                session, ws, item,
                {
                    "verdict": "watch",
                    "verdict_reason": (
                        "It names something you use, but nothing of yours is on record "
                        "to anchor it yet: no recent commit mentions it and no standing "
                        "fact covers it."
                    ),
                },
                anchors=anchors, anchor_moment_ids=[], now=now,
            )
            out["watched"] += 1
            out["unanchored"] = out.get("unanchored", 0) + 1
            continue
        request = build_request(
            AppraisalInput(
                title=item.title,
                publisher=item.publisher,
                published_at=item.published_at,
                primary_url=item.primary_url,
                document=item.extract_private or "",
                anchors=anchors,
                recent_evidence=recent,
            ),
            workspace_id=ws,
            news_item_id=item.id,
        )
        try:
            result = await complete(request)
        except LLMUnavailable:
            out["waiting"] += 1
            break  # no capacity now; the rest wait for the next run too
        data = getattr(result, "structured", None)
        try:
            clean = validate_appraisal(
                data,
                document=item.extract_private or "",
                has_post_announcement_demonstration=demo_after,
                now=now,
                published_at=item.published_at,
            )
        except AppraisalInvalidError as exc:
            # Recorded as a reject with the reason, so the item is not retried
            # forever and the ledger says exactly why it went nowhere.
            clean = {"verdict": "reject", "verdict_reason": f"appraisal refused: {exc}"}
            out["invalid"] += 1
        await record_appraisal(
            session, ws, item, clean,
            anchors=anchors, anchor_moment_ids=cite_ids,
            job_id=getattr(result, "job_id", None), now=now,
        )
        out["appraised"] += 1
        out[{"publish": "published", "watch": "watched"}.get(clean["verdict"], "rejected")] += 1
    await session.flush()
    return out


# ---------------------------------------------------------------------------
# The manual request: "is this announcement worth anything to me?"
# ---------------------------------------------------------------------------


async def check_one(
    session: Any,
    ws: uuid.UUID,
    *,
    url: str,
    fetch_text: FetchText,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch, match and explain one announcement Ziv pointed at.

    Deliberately synchronous and model-free: he gets the matcher's answer, with
    the matches NAMED, in seconds. Only if it matched does the caller queue the
    one appraisal. The gate is exactly the scheduled one - a manual request is
    looked at sooner, never let through more easily - but it runs even with the
    lane off, because he asked.
    """
    now = now or _now()
    await build_anchor_index(session, ws, now=now)

    if is_blocked_host(url):
        return {
            "status": "unverified",
            "why": (
                "That is a news site's write-up, not the announcement. Give me the "
                "announcement itself; a claim is only ever confirmed from the source."
            ),
        }

    try:
        page = await fetch_text(url)
    except Exception as exc:
        return {"status": "unreachable", "why": f"Could not load the page: {exc}"[:300]}
    body = str((page or {}).get("body_text") or "").strip()
    if not body:
        return {"status": "unreachable", "why": "The page loaded but had no readable text."}

    digest = sha256_of(body)
    external_id = f"manual:{digest[:32]}"
    item = (
        await session.execute(
            select(NewsItem).where(
                NewsItem.workspace_id == ws,
                NewsItem.feed_id.is_(None),
                NewsItem.external_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        item = NewsItem(
            id=uuid.uuid4(), workspace_id=ws, feed_id=None, external_id=external_id,
            url=url, primary_url=url,
            title=str((page or {}).get("title") or url)[:600],
            summary=body[:600], publisher=None,
            # Asked about now; treated as published now, so its freshness window
            # starts from the moment he raised it.
            published_at=now, fetched_at=now,
            extract_private=body, content_sha256=digest, source_version=digest[:16],
            source_tier="1a", matched=False,
        )
        session.add(item)
        await session.flush()

    anchors = (
        await session.execute(
            select(NewsAnchor).where(NewsAnchor.workspace_id == ws, NewsAnchor.active.is_(True))
        )
    ).scalars().all()
    result = match_item(title=item.title, summary=None, body=body, anchors=anchors)
    if not result.matched:
        item.prefilter_reason = "blocked_shape" if result.blocked_shape else "no_anchor"
        await session.flush()
        return {
            "status": "no_match",
            "item_id": str(item.id),
            "why": result.reason,
            "checked": f"{len(anchors)} anchors in his index",
        }

    item.matched = True
    item.prefilter_reason = None
    existing = {
        m.anchor_id
        for m in (
            await session.execute(select(NewsMatch).where(NewsMatch.news_item_id == item.id))
        ).scalars()
    }
    for m in result.matches:
        if m.anchor_id and m.anchor_id not in existing:
            session.add(
                NewsMatch(
                    id=uuid.uuid4(), workspace_id=ws, news_item_id=item.id,
                    anchor_id=m.anchor_id, match_kind=m.kind,
                    matched_span=(m.matched_span or "")[:400], score=m.score,
                )
            )
    await session.flush()
    return {"status": "matched", "item_id": str(item.id), "why": result.why()}
