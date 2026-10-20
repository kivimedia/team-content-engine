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
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select

from tce.editorial import news_rules
from tce.models.editorial import EvidenceMoment, EvidenceSource, TopicCandidate
from tce.models.news import NewsAnchor, NewsAppraisal, NewsFeed, NewsItem, NewsMatch
from tce.news.anchors import build_anchor_index
from tce.news.appraise import (
    AppraisalInput,
    AppraisalInvalidError,
    build_request,
    validate_appraisal,
    OWNER_PROMPT_VERSION,
)
from tce.news.feeds import fetch_feed, is_blocked_host, record_items, sha256_of
from tce.news.matcher import match_item
from tce.news.record import NEWS_SOURCE_KIND, record_appraisal

# Something older than this is not news, however it arrived.
WINDOW_DAYS = 2
# Feed tiers that are a vendor's own announcement blog (see seed_news_feeds).
ANNOUNCEMENT_TIERS = ("1b",)
# The daily cap on model calls. A cost and noise control; the positioning control
# is the weekly ceiling in the selector. 14-Oct: 5 -> 10, and only real model
# calls count against it (a park costs nothing); 87 matched items had never been
# looked at.
MAX_APPRAISALS_PER_DAY = 10
# Only news this fresh is appraised by the daily run. A parked item ("nothing of
# yours to cite yet") is looked at again inside the same window, so a standing
# fact or a commit added later can bring it back; past it, a model call would be
# spent on a story that has already gone stale. A URL he checks himself is not
# held to it.
FRESH_DAYS = 7
# How many matched items one pass may walk through. Parks are free, so the walk
# is longer than the model budget.
MAX_ITEMS_PER_PASS = 60
# How far back an anchor's own evidence counts as "recent" for the appraiser.
RECENT_EVIDENCE_DAYS = 30
MAX_OWNER_APPRAISALS = 3
MAX_OWNER_SELECTIONS = 3


def _meta(item: Any) -> dict[str, Any]:
    return dict(getattr(item, "editorial_meta", None) or {})


def _set_meta(item: Any, **values: Any) -> None:
    item.editorial_meta = {**_meta(item), **values}


def _editorial_notes(item: Any) -> list[str]:
    meta = _meta(item)
    notes = [
        str(entry.get(key) or "").strip()[:2000]
        for collection, key in (("submissions", "angle"), ("retry_requests", "reason"))
        for entry in (meta.get(collection) or [])[-3:]
        if isinstance(entry, dict)
    ]
    return list(dict.fromkeys(note for note in notes if note))[-5:]


def _fingerprint(value: Any) -> str:
    return sha256_of(json.dumps(value, sort_keys=True, default=str))[:24]


def _publication_date(value: Any) -> datetime | None:
    """An actual publisher date, never the time we fetched or requested it."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


async def _evidence_version(session: Any, ws: uuid.UUID, ids: list[str]) -> str:
    keys = []
    for value in ids:
        try:
            keys.append(uuid.UUID(str(value)))
        except ValueError:
            continue
    rows = (await session.execute(
        select(EvidenceMoment.id, EvidenceMoment.source_version_hash, EvidenceMoment.lesson_summary)
        .where(EvidenceMoment.workspace_id == ws, EvidenceMoment.id.in_(keys))
    )).all() if keys else []
    return _fingerprint(sorted((str(i), v, text) for i, v, text in rows))

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
    owner = news_rules.owner_policy(ws)
    since = now - timedelta(days=FRESH_DAYS if owner else WINDOW_DAYS)
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
                or_(NewsItem.prefilter_reason.is_(None), NewsItem.published_at >= since)
                if owner else NewsItem.prefilter_reason.is_(None),
            )
            .order_by(NewsItem.published_at.desc().nullslast())
        )
    ).scalars().all()
    # A vendor's own announcement blog is about that vendor even when the
    # headline never says so. Release feeds (tier 1a) do not count: their
    # routine patches would spend the day's model calls on version bumps.
    announcers = {
        feed_id: vendor
        for feed_id, vendor in (
            await session.execute(
                select(NewsFeed.id, NewsFeed.vendor).where(
                    NewsFeed.workspace_id == ws,
                    NewsFeed.tier.in_(ANNOUNCEMENT_TIERS),
                    NewsFeed.vendor.is_not(None),
                )
            )
        ).all()
    }

    out = {"matched": 0, "blocked_shape": 0, "no_anchor": 0, "stale": 0, "unverified": 0}
    for item in items:
        if item.published_at is not None and item.published_at < since:
            item.prefilter_reason = "stale"
            out["stale"] += 1
            continue
        prefilter = dict(_meta(item).get("prefilter_retry") or {})
        signature = _fingerprint({
            "policy": news_rules.OWNER_POLICY_VERSION,
            "anchors": sorted((a.kind, a.normalized_term, str(a.standing_moment_id))
                              for a in anchors),
            "source": [item.title, item.summary, item.source_version],
            "editor_retry": _meta(item).get("retry_nonce") if owner else None,
        })
        if owner and prefilter.get("fingerprint") == signature:
            # Only a temporary fetch failure has a time-based retry. A corrected
            # anchor or policy reopens deterministic matching once.
            if prefilter.get("state") != "needs_primary_source":
                continue
            last = _publication_date(prefilter.get("last_attempt"))
            if prefilter.get("attempts", 0) >= 3 or (last and now - last < timedelta(hours=6)):
                continue
        result = match_item(title=item.title, summary=item.summary, anchors=anchors,
                            concept_of=problem_concept_for(ws),
                            source_vendor=announcers.get(item.feed_id),
                            **({"business_relevance": True} if owner else {}))
        if owner:
            _set_meta(item, prefilter_retry={
                "fingerprint": signature, "last_attempt": now.isoformat(),
                "attempts": (prefilter.get("attempts", 0) + 1
                             if prefilter.get("fingerprint") == signature else 1),
                "state": "matched" if result.matched else
                "hard_reject" if result.blocked_shape else "waiting_for_evidence",
            })
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
            if owner and item.source_tier == "2":
                from tce.services.url_fetcher import resolve_primary_announcement
                reader = (
                    resolve_primary_announcement
                    if getattr(fetch_text, "__module__", "") == "tce.services.url_fetcher"
                    else fetch_text
                )
                page = await reader(url)
                if not page.get("source_verified"):
                    page = {}
                else:
                    url = page.get("primary_url") or url
                    item.published_at = _publication_date(page.get("published_at"))
            else:
                page = await fetch_text(
                    url, **({"public_only": True} if owner and
                            getattr(fetch_text, "__module__", "") == "tce.services.url_fetcher"
                            else {}),
                )
        except Exception:
            page = {}
        text = str((page or {}).get("body_text") or "").strip()
        if not text:
            # Without the document there is nothing to check a quote against, so
            # nothing can be confirmed. Try again on the next run rather than
            # appraising on a feed summary.
            out["unverified"] += 1
            if owner:
                item.prefilter_reason = "unverified_source"
                _set_meta(item, prefilter_retry={
                    **(_meta(item).get("prefilter_retry") or {}),
                    "state": "needs_primary_source",
                })
            continue

        item.primary_url = url
        if owner and item.source_tier == "2":
            _set_meta(item, primary_source_verified=True, discovery_url=item.url)
        item.extract_private = text
        item.content_sha256 = sha256_of(text)
        item.source_version = item.source_version or item.content_sha256[:16]
        item.matched = True
        item.prefilter_reason = None
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

# A capability is a reason to test something against an existing problem, not
# evidence that the owner already uses the announced product. These links are
# deliberately about business tasks. Generic AI or vendor names never qualify.
_CAPABILITY_PROBLEMS = {
    "client follow-up": r"\bfollow[ -]?up\b|\benquir\w*\b|\binquir\w*\b|\bleads?\b",
    "meeting notes": r"\b(check[ -]?ins?|sessions?|meeting|call notes|client tracking|next steps)\b",
    "inbox triage": r"\b(emails?|inbox|messages?|enquir\w*|inquir\w*|leads?)\b",
    "business knowledge": r"\b(knowledge|documentation|documents?|shared files|playbooks?|procedures?)\b",
    "client web tools": r"\b(quot\w*|pric\w*|booking|forms?|calculators?|planners?)\b",
    "spreadsheet assistance": r"\b(spreadsheets?|reporting|data entry|campaign numbers)\b",
    "voice reception": r"\b(phone|calls?|voicemail|receptionist)\b",
    "lead handling": r"\b(leads?|enquir\w*|inquir\w*|follow[ -]?up)\b",
    "creative production": r"\b(photos?|video|content|campaign|marketing)\b",
}


async def _standing_problem_context(session: Any, ws: uuid.UUID, item: NewsItem) -> list[Any]:
    from tce.news.matcher import business_capability

    capability = business_capability(
        item.title, " ".join((item.summary or "", (item.extract_private or "")[:8000])),
    )
    pattern = _CAPABILITY_PROBLEMS.get(capability or "")
    if pattern is None:
        return []
    rows = (await session.execute(
        select(EvidenceMoment, EvidenceSource)
        .join(EvidenceSource, EvidenceMoment.source_id == EvidenceSource.id)
        .where(
            EvidenceMoment.workspace_id == ws, EvidenceSource.workspace_id == ws,
            EvidenceMoment.status == "active", EvidenceSource.source_kind == "standing_fact",
            EvidenceMoment.extraction_job_id.is_(None),
            EvidenceMoment.source_version_hash == EvidenceSource.version_hash,
        ).order_by(EvidenceMoment.id)
    )).all()
    relevant = []
    for moment, source in rows:
        ref = moment.news_ref or {}
        if not ref.get("standing") or ref.get("anchor_kind") not in {
            "problem_pattern", "client_solution",
        }:
            continue
        text = " ".join((str(ref.get("anchor_term") or ""), moment.lesson_summary or ""))
        if re.search(pattern, text, flags=re.IGNORECASE):
            relevant.append((moment, source))
    return relevant[:3]


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
            .where(NewsMatch.news_item_id == item.id, NewsMatch.workspace_id == ws,
                   NewsAnchor.workspace_id == ws, NewsAnchor.active.is_(True))
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
    owner = news_rules.owner_policy(ws)
    if owner and not ids:
        for moment, source in await _standing_problem_context(session, ws, item):
            ref = moment.news_ref or {}
            ids.append(str(moment.id))
            anchors.append({
                "kind": ref["anchor_kind"], "term": ref["anchor_term"],
                "origin_ref": str(source.id), "origin_kind": "standing_fact",
                "lesson_summary": moment.lesson_summary,
                "relationship": "audience problem for a proposed test; no claimed product usage",
            })
    named = [
        a.normalized_term for a in rows
        if a.kind in (
            ("vendor", "model_id", "capability", "client_solution", "problem_pattern")
            if owner else ("vendor", "model_id", "capability")
        ) and a.normalized_term
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
                    EvidenceSource.source_kind.in_(
                        ("github_commit_group", "fathom_meeting") if owner
                        else ("github_commit_group",)
                    ),
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
            if owner and not mentions:
                words = set(re.findall(r"\w+", text))
                mentions = any(
                    len(tokens := {w for w in term.split() if len(w) > 3}) >= 3
                    and len(tokens & words) >= max(3, len(tokens) * .75)
                    for term in named
                )
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
                    "moment_id": str(moment.id),
                    "source_version": moment.source_version_hash,
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
    # Only a real model call counts. A park has no job id and cost nothing; when
    # parks counted, an unanchored item could take the day's last slot and the
    # citable one behind it waited until it went stale.
    done_today = len(
        (
            await session.execute(
                select(NewsAppraisal.id).where(
                    NewsAppraisal.workspace_id == ws,
                    NewsAppraisal.created_at >= start_of_day,
                    NewsAppraisal.job_id.is_not(None),
                )
            )
        ).all()
    )
    budget = max(0, cap - done_today) if only_item is None else 1
    owner = news_rules.owner_policy(ws)
    prior: dict[uuid.UUID, Any] = {}
    if owner:
        for row in (await session.execute(
            select(NewsAppraisal).where(NewsAppraisal.workspace_id == ws)
            .order_by(NewsAppraisal.created_at.desc())
        )).scalars():
            prior.setdefault(row.news_item_id, row)

    # Judged by the model = done for good. Parked = looked at again while it is
    # still news, because "nothing of yours to cite" can stop being true.
    judged_ids = select(NewsAppraisal.news_item_id).where(
        NewsAppraisal.workspace_id == ws, NewsAppraisal.job_id.is_not(None)
    )
    parked_ids = select(NewsAppraisal.news_item_id).where(
        NewsAppraisal.workspace_id == ws, NewsAppraisal.job_id.is_(None)
    )
    stmt = (
        select(NewsItem)
        .where(
            NewsItem.workspace_id == ws,
            NewsItem.matched.is_(True),
        )
        .order_by(NewsItem.published_at.desc().nullslast())
    )
    if not owner:
        stmt = stmt.where(NewsItem.id.not_in(judged_ids))
    else:
        stmt = stmt.where(NewsItem.id.not_in(
            select(NewsAppraisal.news_item_id).where(
                NewsAppraisal.workspace_id == ws, NewsAppraisal.verdict == "publish",
            )
        ))
    if only_item is not None:
        stmt = stmt.where(NewsItem.id == only_item)
    else:
        stmt = stmt.where(
            or_(
                NewsItem.published_at.is_(None),
                NewsItem.published_at >= now - timedelta(days=FRESH_DAYS),
            )
        )
    pending = (
        await session.execute(stmt.limit(MAX_ITEMS_PER_PASS if budget else 0))
    ).scalars().all()
    already_parked = (
        set((await session.execute(parked_ids)).scalars().all()) if pending else set()
    )

    out = {"appraised": 0, "published": 0, "watched": 0, "rejected": 0,
           "waiting": 0, "invalid": 0, "budget_left": budget}
    for item in pending:
        if budget <= 0:
            break
        anchors, cite_ids, recent, demo_after = await _anchor_moments(session, ws, item, now)
        retry_fingerprint = None
        if owner:
            previous = prior.get(item.id)
            retry = dict(_meta(item).get("appraisal_retry") or {})
            if previous is not None and previous.verdict == "publish":
                continue
            if item.published_at is None or item.published_at > now:
                _set_meta(item, appraisal_retry={**retry, "state": "needs_source_date"})
                continue
            if item.published_at < now - timedelta(days=FRESH_DAYS):
                _set_meta(item, appraisal_retry={**retry, "state": "expired"})
                continue
            evidence = await _evidence_version(session, ws, cite_ids)
            retry_fingerprint = _fingerprint({
                "source": item.content_sha256, "evidence": evidence,
                "policy": news_rules.OWNER_POLICY_VERSION, "prompt": OWNER_PROMPT_VERSION,
                "editor_retry": _meta(item).get("retry_nonce"),
                "editorial_notes": _editorial_notes(item),
            })
            seen = list(retry.get("fingerprints") or [])
            if retry_fingerprint in seen or len(seen) >= MAX_OWNER_APPRAISALS:
                continue
            policy_changed = (
                previous is not None and previous.prompt_version != OWNER_PROMPT_VERSION
            )
            explicit_retry = retry.get("retry_nonce") != _meta(item).get("retry_nonce")
            # A hard rejection is not a standing invitation to try new wording.
            if previous is not None and previous.job_id is not None:
                state = retry.get("state") or (
                    "hard_reject" if previous.verdict == "reject" else "waiting_for_evidence"
                )
                if state == "hard_reject" and not policy_changed and not explicit_retry:
                    continue
                if not retry and not policy_changed:
                    continue
        if not cite_ids:
            # Nothing of his to cite, so the selector would reject whatever the
            # model said. Parked on the watchlist with the reason instead, and no
            # model call is spent. It comes back when a commit touching this
            # vendor, or a matching standing fact, gives it something to stand on.
            if item.id in already_parked:
                continue  # parked already: one ledger row, not one a day
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
            if owner:
                _set_meta(item, appraisal_retry={
                    **(_meta(item).get("appraisal_retry") or {}),
                    "state": "waiting_for_evidence",
                })
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
                editorial_notes=_editorial_notes(item) if owner else None,
            ),
            workspace_id=ws,
            news_item_id=item.id,
            retry_fingerprint=retry_fingerprint,
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
        receipt = await record_appraisal(
            session, ws, item, clean,
            anchors=anchors, anchor_moment_ids=cite_ids,
            job_id=getattr(result, "job_id", None), now=now,
        )
        if owner:
            retry = dict(_meta(item).get("appraisal_retry") or {})
            _set_meta(
                item,
                news_category=clean.get("news_category", "other"),
                appraisal_retry={
                    "fingerprints": [*(retry.get("fingerprints") or []), retry_fingerprint],
                    "fingerprint": retry_fingerprint,
                    "attempts": len(retry.get("fingerprints") or []) + 1,
                    "state": "qualified" if clean["verdict"] == "publish"
                    else clean.get("recovery_state", "hard_reject"),
                    "policy": news_rules.OWNER_POLICY_VERSION,
                    "prompt_version": OWNER_PROMPT_VERSION,
                    "retry_nonce": _meta(item).get("retry_nonce"),
                },
            )
            saved = await session.get(NewsAppraisal, uuid.UUID(receipt["appraisal_id"]))
            saved.prompt_version = OWNER_PROMPT_VERSION
            if receipt.get("moment_id"):
                moment = await session.get(EvidenceMoment, uuid.UUID(receipt["moment_id"]))
                moment.news_ref = {
                    **(moment.news_ref or {}), "news_category": clean.get("news_category", "other"),
                    "policy_version": news_rules.OWNER_POLICY_VERSION,
                    "editorial_notes": _editorial_notes(item),
                }
        budget -= 1
        out["budget_left"] = budget
        out["appraised"] += 1
        out[{"publish": "published", "watch": "watched"}.get(clean["verdict"], "rejected")] += 1
    await session.flush()
    return out


# ---------------------------------------------------------------------------
# Stage C (14-Oct): a published item becomes a topic the same day
# ---------------------------------------------------------------------------


def _expiry_of(moment: EvidenceMoment) -> datetime | None:
    raw = (moment.news_ref or {}).get("expires_at")
    if not raw:
        return None
    return _publication_date(raw)


async def selection_fingerprint(
    session: Any, ws: uuid.UUID, source: EvidenceSource, moment: EvidenceMoment
) -> str:
    from tce.editorial.selector import PROMPT_VERSION

    ref = moment.news_ref or {}
    nonce = None
    notes = []
    try:
        item = await session.get(NewsItem, uuid.UUID(str(ref.get("news_item_id"))))
        if item is not None and item.workspace_id == ws:
            nonce = _meta(item).get("retry_nonce")
            notes = _editorial_notes(item)
    except (ValueError, TypeError):
        pass
    return _fingerprint({
        "source": source.version_hash, "news_ref": ref,
        "evidence": await _evidence_version(session, ws, ref.get("anchor_moment_ids") or []),
        "policy": news_rules.OWNER_POLICY_VERSION, "prompt": PROMPT_VERSION,
        "editor_retry": nonce,
        "editorial_notes": notes,
    })


async def news_selection_key(session: Any, ws: uuid.UUID, source_ids: list[uuid.UUID]) -> str:
    rows = (await session.execute(
        select(EvidenceMoment, EvidenceSource)
        .join(EvidenceSource, EvidenceMoment.source_id == EvidenceSource.id)
        .where(EvidenceMoment.workspace_id == ws, EvidenceMoment.status == "active",
               EvidenceSource.id.in_(source_ids), EvidenceSource.source_kind == NEWS_SOURCE_KIND)
    )).all()
    parts = [
        (str(source.id), await selection_fingerprint(session, ws, source, moment))
        for moment, source in rows
    ]
    return _fingerprint(sorted(parts))


async def news_awaiting_topic(
    session: Any, ws: uuid.UUID, *, now: datetime | None = None
) -> list[uuid.UUID]:
    """Published news the selector has never looked at, still inside its life.

    Before this, only Monday's weekly run selected. A story judged on a Tuesday
    with a five-day life expired before anything could pick it, which is most of
    why three weeks of news produced no topic at all. Anything the selector has
    already judged - kept or rejected - is in some candidate's moment ids and is
    not offered to it again, so a daily run never re-spends a model call on it.
    """
    now = now or _now()
    rows = (
        await session.execute(
            select(EvidenceMoment, EvidenceSource)
            .join(EvidenceSource, EvidenceMoment.source_id == EvidenceSource.id)
            .where(
                EvidenceMoment.workspace_id == ws,
                EvidenceMoment.status == "active",
                EvidenceSource.source_kind == NEWS_SOURCE_KIND,
                EvidenceSource.occurred_at >= now - timedelta(days=RECENT_EVIDENCE_DAYS),
            )
            .order_by(EvidenceSource.occurred_at.desc())
        )
    ).all()
    if not rows:
        return []
    judged: set[str] = set()
    owner = news_rules.owner_policy(ws)
    judgements: dict[str, list[Any]] = {}
    if owner:
        for candidate in (await session.execute(
            select(TopicCandidate).where(
                TopicCandidate.workspace_id == ws,
                TopicCandidate.created_at >= now - timedelta(days=RECENT_EVIDENCE_DAYS),
            ).order_by(TopicCandidate.created_at.desc())
        )).scalars():
            for value in candidate.moment_ids or []:
                judgements.setdefault(str(value), []).append(candidate)
    for ids in (
        await session.execute(
            select(TopicCandidate.moment_ids).where(
                TopicCandidate.workspace_id == ws,
                TopicCandidate.created_at >= now - timedelta(days=RECENT_EVIDENCE_DAYS),
            )
        )
    ).scalars():
        judged.update(str(i) for i in (ids or []))
    out: list[uuid.UUID] = []
    for moment, source in rows:
        expires = _expiry_of(moment)
        if expires is not None and expires <= now:
            continue
        if source.id in out:
            continue
        if str(moment.id) in judged:
            if not owner:
                continue
            previous = judgements.get(str(moment.id), [])
            if any(c.status in ("proposed", "selected", "recorded") for c in previous):
                continue
            attempts = [
                c for c in previous
                if ((c.gates or {}).get("_news_recovery") or {}).get("policy")
                == news_rules.OWNER_POLICY_VERSION
            ]
            if len(attempts) >= MAX_OWNER_SELECTIONS:
                continue
            latest = previous[0] if previous else None
            gates = (latest.gates or {}) if latest else {}
            recovery = gates.get("_news_recovery") or {}
            code = (gates.get("_rejection") or {}).get("code")
            temporary = recovery.get("state") in (
                "needs_angle", "waiting_for_evidence", "waiting_for_slot",
            ) or code in ("news_ceiling", "news_margin", "news_floor", "news_needs_anchor")
            nonce = None
            try:
                item = await session.get(
                    NewsItem, uuid.UUID(str((moment.news_ref or {}).get("news_item_id")))
                )
                if item is not None and item.workspace_id == ws:
                    nonce = _meta(item).get("retry_nonce")
            except (ValueError, TypeError):
                pass
            explicit_retry = nonce is not None and nonce != recovery.get("retry_nonce")
            if not temporary and not explicit_retry:
                continue
            fingerprint = await selection_fingerprint(session, ws, source, moment)
            if recovery.get("fingerprint") == fingerprint:
                continue
        out.append(source.id)
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
    owner = news_rules.owner_policy(ws)
    existing_url_item = None
    if owner:
        equivalents = [url, "http:" + url[6:]] if url.startswith("https:") else [url]
        existing_url_item = (await session.execute(select(NewsItem).where(
            NewsItem.workspace_id == ws,
            or_(NewsItem.url.in_(equivalents), NewsItem.primary_url.in_(equivalents),
                NewsItem.canonical_url.in_(equivalents)),
        ).order_by(NewsItem.created_at.asc()).limit(1).with_for_update())).scalar_one_or_none()

    if is_blocked_host(url) and not owner:
        return {
            "status": "unverified",
            "why": (
                "That is a news site's write-up, not the announcement. Give me the "
                "announcement itself; a claim is only ever confirmed from the source."
            ),
        }

    try:
        if owner and getattr(fetch_text, "__module__", "") == "tce.services.url_fetcher":
            from tce.services.url_fetcher import resolve_primary_announcement
            page = await resolve_primary_announcement(url)
        else:
            page = await fetch_text(url)
    except Exception as exc:
        return {"status": "unreachable", "why": f"Could not load the page: {exc}"[:300]}
    page = page or {}
    body = str((page or {}).get("body_text") or "").strip()
    if owner and (not page.get("source_verified") or not page.get("primary_url")):
        # Keep the submission and its lineage visible, but never promote a
        # secondary page to primary evidence merely because it is readable.
        external_id = f"manual-unverified:{sha256_of(url)[:32]}"
        item = existing_url_item or (await session.execute(select(NewsItem).where(
            NewsItem.workspace_id == ws, NewsItem.feed_id.is_(None),
            NewsItem.external_id == external_id,
        ))).scalar_one_or_none()
        if item is None:
            item = NewsItem(
                id=uuid.uuid4(), workspace_id=ws, external_id=external_id, url=url,
                title=str(page.get("title") or url)[:600], source_tier="2",
                matched=False, fetched_at=now, primary_url=None, published_at=None,
                summary=body[:600], prefilter_reason="unverified_source",
            )
            session.add(item)
        item.matched = False
        item.primary_url = None
        item.published_at = None
        item.source_tier = "2"
        item.prefilter_reason = "unverified_source"
        _set_meta(
            item, requested_at=now.isoformat(), discovery_url=url, primary_source_verified=False,
            prefilter_retry={"state": "needs_primary_source", "attempts": 0},
        )
        await session.flush()
        return {"status": "unverified", "item_id": str(item.id),
                "why": "Held until a verified primary announcement can be resolved."}
    if not body:
        return {"status": "unreachable", "why": "The page loaded but had no readable text."}

    digest = sha256_of(body)
    external_id = f"manual:{digest[:32]}"
    item = existing_url_item or (
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
            url=url, primary_url=page.get("primary_url") if owner else url,
            title=str((page or {}).get("title") or url)[:600],
            summary=body[:600], publisher=None,
            # Requested and published are different facts. Unknown stays unknown.
            published_at=(
                _publication_date(page.get("published_at"))
                if owner else now
            ), fetched_at=now,
            extract_private=body, content_sha256=digest, source_version=digest[:16],
            source_tier="1a", matched=False,
        )
        session.add(item)
        await session.flush()
    if owner:
        item.primary_url = page["primary_url"]
        item.extract_private = body
        item.content_sha256 = digest
        item.source_version = digest[:16]
        item.title = str(page.get("title") or item.title)[:600]
        date = _publication_date(page.get("published_at"))
        # Correct old manual rows whose "publication" was actually the request
        # time. A missing verified date cannot retain that synthetic freshness.
        if date is not None or not _meta(item).get("published_date_verified"):
            item.published_at = date
        _set_meta(
            item, requested_at=now.isoformat(),
            discovery_url=page.get("discovery_url") or url, primary_source_verified=True,
            published_date_verified=date is not None,
            appraisal_retry={
                **(_meta(item).get("appraisal_retry") or {}),
                **({"state": "needs_source_date"} if item.published_at is None else {}),
            },
        )

    anchors = (
        await session.execute(
            select(NewsAnchor).where(NewsAnchor.workspace_id == ws, NewsAnchor.active.is_(True))
        )
    ).scalars().all()
    result = match_item(title=item.title, summary=None, body=body, anchors=anchors,
                        concept_of=problem_concept_for(ws),
                        **({"business_relevance": True} if news_rules.owner_policy(ws) else {}))
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


def problem_concept_for(ws: Any):
    """Lane workspaces count two forms of one word as one problem; owners get None,
    so their matching is exactly what it was."""
    from tce.editorial.lane_profile import profile_for
    from tce.news.matcher import concept_key

    return concept_key if profile_for(ws) is not None else None
