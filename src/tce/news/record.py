"""Turn a validated appraisal into evidence the selector can see.

Until this exists the lane is inert: the matcher passes items, the appraiser
judges them, and the selector never learns about any of it, because it reads
`EvidenceMoment` rows and nothing wrote one.

A published appraisal becomes:

  NewsAppraisal          the eight answers, whole, for the card and for audit
  EvidenceSource         source_kind "news_item", payload = the primary document
  EvidenceMoment         ONE per item, carrying `news_ref`

`news_ref` is where everything the selector needs later lives, so it never has to
join back to the news tables in the hot path: the appraisal's scores (for the news
formula), published_at and expires_at (for freshness), story_weight (for the
second-slot rule), perishability (for the durable conversion), and
`anchor_moment_ids` - the call and commit moments this item is anchored on, which
is how the selector puts the anchor in the same shard as the news so it can be
cited at all.

A `watch` verdict writes the appraisal and a watchlist row and NO evidence: it is
real, but it does not connect yet, so it must not reach the week pool. A `reject`
writes only the appraisal, for the ledger.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from tce.evidence.common import stable_hash
from tce.models.editorial import EvidenceMoment, EvidenceSource
from tce.models.news import NewsAppraisal, NewsItem, NewsWatchlist
from tce.news.appraise import PROMPT_VERSION

NEWS_SOURCE_KIND = "news_item"

# A news claim is quoted from a document, never measured. The selector's
# invented-outcome check relies on nothing here ever claiming "measured".
NEWS_CLAIM_TYPE = "quoted"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def record_appraisal(
    session: Any,
    workspace_id: uuid.UUID | str,
    item: NewsItem,
    appraisal: dict[str, Any],
    *,
    anchors: list[dict[str, Any]],
    anchor_moment_ids: list[str],
    job_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Store one validated appraisal and, for a publish, the evidence behind it.

    `appraisal` is the output of `validate_appraisal`, so every claim in it has
    already survived the quote check and the overlap check.
    """
    ws = uuid.UUID(str(workspace_id))
    now = now or datetime.now(UTC).replace(tzinfo=None)
    verdict = appraisal["verdict"]

    row = NewsAppraisal(
        id=uuid.uuid4(),
        workspace_id=ws,
        news_item_id=item.id,
        job_id=job_id,
        prompt_version=PROMPT_VERSION,
        verdict=verdict,
        verdict_reason=appraisal.get("verdict_reason"),
        format=appraisal.get("format"),
        what_happened=appraisal.get("what_happened"),
        audience_consequence=appraisal.get("audience_consequence"),
        distinct_claim=appraisal.get("distinct_claim"),
        do_differently=appraisal.get("do_differently") or [],
        confirmed_facts=appraisal.get("confirmed_facts") or [],
        ziv_interpretation=appraisal.get("ziv_interpretation") or [],
        predictions=appraisal.get("predictions") or [],
        anchors=anchors,
        scores=appraisal.get("scores") or {},
        perishability=appraisal.get("perishability"),
        expires_at=appraisal.get("expires_at"),
        story_weight=appraisal.get("story_weight") or "small",
        weight_reason=appraisal.get("weight_reason"),
    )
    session.add(row)

    if verdict == "watch":
        existing = (
            await session.execute(
                select(NewsWatchlist).where(
                    NewsWatchlist.workspace_id == ws,
                    NewsWatchlist.news_item_id == item.id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                NewsWatchlist(
                    id=uuid.uuid4(),
                    workspace_id=ws,
                    news_item_id=item.id,
                    reason=appraisal.get("verdict_reason"),
                    recheck_anchor_kinds=sorted({a.get("kind") for a in anchors if a.get("kind")}),
                    created_by="appraiser",
                )
            )
        await session.flush()
        return {"appraisal_id": str(row.id), "verdict": verdict, "moment_id": None}

    if verdict != "publish":
        await session.flush()
        return {"appraisal_id": str(row.id), "verdict": verdict, "moment_id": None}

    # --- publish: make it evidence the selector can see --------------------
    payload = {
        "title": item.title,
        "primary_url": item.primary_url or item.url,
        "publisher": item.publisher,
        "document": item.extract_private or item.raw_private or item.summary or "",
    }
    version_hash = item.content_sha256 or stable_hash(payload)

    source = (
        await session.execute(
            select(EvidenceSource).where(
                EvidenceSource.workspace_id == ws,
                EvidenceSource.source_kind == NEWS_SOURCE_KIND,
                EvidenceSource.external_id == str(item.id),
            )
        )
    ).scalar_one_or_none()
    if source is None:
        source = EvidenceSource(
            id=uuid.uuid4(),
            workspace_id=ws,
            source_kind=NEWS_SOURCE_KIND,
            external_id=str(item.id),
            title=item.title[:500],
            # The week the idea belongs to is the week it was PUBLISHED, not the
            # week it was found, so a late find is not dressed up as fresh.
            occurred_at=item.published_at or now,
            fetched_at=now,
            version_hash=version_hash,
            revision=1,
            fetch_status="ok",
            url_private=item.primary_url or item.url,
            payload_private=payload,
            meta={"news_item_id": str(item.id), "tier": item.source_tier},
        )
        session.add(source)
        await session.flush()
    item.evidence_source_id = source.id

    facts = appraisal.get("confirmed_facts") or []
    lesson = appraisal.get("distinct_claim") or appraisal.get("what_happened") or item.title
    moment = EvidenceMoment(
        id=uuid.uuid4(),
        workspace_id=ws,
        source_id=source.id,
        source_version_hash=source.version_hash,
        excerpt_private="\n".join(f.get("quote", "") for f in facts)[:4000] or item.title,
        context_private=appraisal.get("what_happened"),
        lesson_summary=str(lesson)[:2000],
        claim_type=NEWS_CLAIM_TYPE,
        speaker=item.publisher,
        speaker_confidence="high",
        language=item.language or "en",
        sensitivity_flags=[],
        status="active",
        extraction_job_id=job_id,
        news_ref={
            "news_item_id": str(item.id),
            "appraisal_id": str(row.id),
            "primary_url": item.primary_url or item.url,
            "publisher": item.publisher,
            "published_at": _iso(item.published_at),
            "expires_at": _iso(appraisal.get("expires_at")),
            "content_sha256": item.content_sha256,
            "source_version": item.source_version,
            "quoted_span": facts[0]["quote"] if facts else None,
            "format": appraisal.get("format"),
            "perishability": appraisal.get("perishability"),
            "story_weight": appraisal.get("story_weight") or "small",
            "scores": appraisal.get("scores") or {},
            # The point of the whole record: the moments this news is anchored
            # on, so the selector can seat them in the same shard and a
            # candidate can cite them.
            "anchor_moment_ids": [str(i) for i in anchor_moment_ids],
        },
    )
    session.add(moment)
    await session.flush()
    return {"appraisal_id": str(row.id), "verdict": verdict, "moment_id": str(moment.id)}
