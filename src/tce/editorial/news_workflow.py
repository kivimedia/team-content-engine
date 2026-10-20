"""Owner news receipts and progress. No publishing and no model calls here."""
from __future__ import annotations

import ipaddress
import hashlib
import math
import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select, text
from sqlalchemy.orm import load_only

from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate, VideoPublication
from tce.models.news import NewsAppraisal, NewsItem

TARGET_SHARE = .25
WINDOW_DAYS = 42
RECENT_ORIGINALS = 12


def submission_url(value: str) -> str:
    """Public HTTPS only, no credentials, secret query strings or tracking."""
    parts = urlsplit(value.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise ValueError("Use a public HTTPS announcement URL without credentials.")
    if host == "localhost" or "." not in host or host.endswith((".local", ".internal")):
        raise ValueError("Use a public announcement URL.")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("Use a public announcement URL.")
    except ValueError as exc:
        if "public" in str(exc):
            raise
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith("utm_") or low in {"fbclid", "gclid", "ref"}:
            continue
        if low not in {"id", "page", "v", "lang"}:
            raise ValueError("Remove query parameters that could contain private access tokens.")
        query.append((key, value))
    if parts.port not in (None, 443):
        raise ValueError("Use the announcement's standard HTTPS URL.")
    return urlunsplit(("https", host, parts.path or "/", urlencode(query), ""))


def category(candidate: TopicCandidate | None, item: NewsItem | None = None) -> str:
    value = ((candidate.gates or {}).get("_news_category") if candidate else None)
    value = value or ((item.editorial_meta or {}).get("news_category") if item else None)
    if value in {"ai", "software", "other"}:
        return value
    return "unknown" if candidate and candidate.news_item_id else "other"


def choose_news_candidate(
    candidates: list[Any], packets_by_candidate: dict[uuid.UUID, Any],
    uploaded_candidate_ids: set[uuid.UUID],
) -> Any | None:
    """Keep human choices, scripts and recordings visible over fresh proposals."""
    def priority(candidate: Any) -> tuple[int, datetime, str]:
        packet = packets_by_candidate.get(candidate.id)
        if candidate.id in uploaded_candidate_ids or candidate.status in {"recorded", "published"}:
            rank = 5
        elif candidate.status == "selected":
            rank = 4
        elif candidate.status == "proposed" and packet and packet.status in {"ready", "exported"}:
            rank = 3
        elif candidate.status == "proposed" and packet:
            rank = 2
        elif candidate.status == "proposed":
            rank = 1
        else:
            rank = 0
        return rank, candidate.created_at or datetime.min, str(candidate.id)
    return max(candidates, key=priority) if candidates else None


def published_mix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    originals: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["original_id"])
        if key not in originals or row["posted_at"] < originals[key]["posted_at"]:
            originals[key] = row
    ordered = sorted(originals.values(), key=lambda r: r["posted_at"], reverse=True)
    total = len(ordered)
    ai = sum(r["category"] == "ai" for r in ordered)
    recent = ordered[:RECENT_ORIGINALS]
    return {
        "published_originals": total, "ai_news_originals": ai,
        "share": ai / total if total else None, "target": TARGET_SHARE,
        "unclassified_news": sum(r["category"] == "unknown" for r in ordered),
        "recent_originals": len(recent),
        "recent_ai_news": sum(r["category"] == "ai" for r in recent),
        "next_four_ai_suggestion": max(0, min(4, math.ceil((total + 4) * TARGET_SHARE - ai))),
    }


async def record_submission(db: Any, ws: uuid.UUID, item: NewsItem,
                            sender: str, angle: str) -> dict[str, Any]:
    if item.workspace_id != ws:
        raise ValueError("Story belongs to another workspace.")
    url = submission_url(item.canonical_url or item.primary_url or item.url)
    receipt_id = str(uuid.uuid5(ws, "news-handoff:" + url))
    meta = dict(item.editorial_meta or {})
    entries = list(meta.get("submissions") or [])
    if not any(s.get("sender") == sender and s.get("angle") == angle for s in entries):
        if len(entries) >= 20:
            raise ValueError("This story already has twenty suggestions. Review its existing brief.")
        entries.append({
            "sender": sender[:100], "angle": angle[:2000],
            "received_at": datetime.utcnow().isoformat() + "Z",
        })
    meta.update(receipt_id=receipt_id, submissions=entries)
    item.editorial_meta = meta
    item.canonical_url = url
    await db.flush()
    return {
        "receipt_id": receipt_id, "item_id": str(item.id), "url": url,
        "state": "awaiting_appraisal" if item.matched else item.prefilter_reason or "needs_match",
        "next": "TCE will review the source, relevance and claims before preparing a recording brief.",
    }


async def workflow_status(db: Any, ws: uuid.UUID, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.utcnow()
    from tce.editorial.news_rules import owner_policy
    if not owner_policy(ws):
        return {"enabled": False}
    candidates = list((await db.execute(
        select(TopicCandidate).where(TopicCandidate.workspace_id == ws)
    )).scalars())
    by_id = {c.id: c for c in candidates}
    items = list((await db.execute(select(NewsItem).options(load_only(
        NewsItem.id, NewsItem.title, NewsItem.url, NewsItem.primary_url,
        NewsItem.published_at, NewsItem.created_at, NewsItem.editorial_meta,
        NewsItem.prefilter_reason,
    )).where(
        NewsItem.workspace_id == ws,
        NewsItem.created_at >= now - timedelta(days=WINDOW_DAYS),
    ).order_by(NewsItem.created_at.desc()))).scalars())
    by_item = {i.id: i for i in items}
    # Count the original candidate once, even across uploads and platforms. Read
    # all receipts before filtering on first publication so reposts cannot reset age.
    posts = (await db.execute(
        select(VideoPublication, RecordingUpload)
        .join(RecordingUpload, VideoPublication.upload_id == RecordingUpload.id)
        .where(VideoPublication.workspace_id == ws, RecordingUpload.workspace_id == ws,
               VideoPublication.status == "posted", VideoPublication.posted_at.is_not(None))
    )).all()
    original_rows: dict[str, dict] = {}
    for post, upload in posts:
        cid = post.candidate_id or upload.candidate_id
        cand = by_id.get(cid)
        if cand and (cand.origin == "technical_validation"
                     or (cand.gates or {}).get("_technical_validation")
                     or cand.title.lower().startswith("technical validation")):
            continue
        key = str(cid or upload.id)
        row = {"original_id": key, "posted_at": post.posted_at,
               "category": category(cand, by_item.get(cand.news_item_id) if cand else None)}
        if key not in original_rows or post.posted_at < original_rows[key]["posted_at"]:
            original_rows[key] = row
    mix = published_mix([r for r in original_rows.values()
                         if r["posted_at"] >= now - timedelta(days=WINDOW_DAYS)])
    packets = list((await db.execute(select(RecordingPacket).where(
        RecordingPacket.workspace_id == ws, RecordingPacket.status != "superseded",
    ).order_by(RecordingPacket.version.desc()))).scalars())
    by_packet: dict[uuid.UUID, RecordingPacket] = {}
    for packet in packets:
        by_packet.setdefault(packet.candidate_id, packet)
    uploads = set((await db.execute(select(RecordingUpload.candidate_id).where(
        RecordingUpload.workspace_id == ws, RecordingUpload.archived_at.is_(None),
    ))).scalars())
    appraisals = list((await db.execute(select(NewsAppraisal).where(
        NewsAppraisal.workspace_id == ws,
    ).order_by(NewsAppraisal.created_at.desc()))).scalars())
    by_appraisal = {}
    for appraisal in appraisals:
        by_appraisal.setdefault(appraisal.news_item_id, appraisal)
    queue = []
    for item in items:
        choices = [c for c in candidates if c.news_item_id == item.id]
        cand = choose_news_candidate(choices, by_packet, uploads)
        packet = by_packet.get(cand.id) if cand else None
        appraisal = by_appraisal.get(item.id)
        meta = item.editorial_meta or {}
        reason = ""
        if cand and cand.id in uploads:
            state, next_action = "recorded", "Review the edit in Library"
        elif cand and cand.expires_at and cand.expires_at <= now:
            state, next_action = "expired", "Refresh the source or develop an honest retrospective"
        elif packet and packet.status in {"ready", "exported"}:
            state, next_action = "ready_to_record", "Open the brief and record"
        elif cand and cand.status in {"proposed", "selected"}:
            state, next_action = "needs_brief", "Prepare the recording brief"
            preparation = meta.get("packet_preparation") or {}
            if (preparation.get("state") in {"requested", "already_in_progress"}
                    and preparation.get("claim_until", "") > now.isoformat()):
                state, next_action = "preparing", "The recording brief is being prepared"
            elif preparation.get("state") == "failed":
                next_action = "Brief preparation needs review before retrying"
        elif cand:
            state, next_action = "held", "Review the reason before retrying"
            reason = str((cand.gates or {}).get("_rejection") or cand.editor_notes or "")
        elif appraisal:
            state, next_action = appraisal.verdict, "Review the appraisal"
            reason = appraisal.verdict_reason or ""
        else:
            state = (meta.get("appraisal_retry") or {}).get("state") or item.prefilter_reason or "awaiting_appraisal"
            next_action = "Review the source and relevance"
        # Show actionable work and explicit handoffs first, not thousands of feed rejects.
        if cand or meta.get("submissions") or (appraisal and appraisal.verdict == "publish"):
            queue.append({
                "item_id": str(item.id), "candidate_id": str(cand.id) if cand else None,
                "title": cand.title if cand else item.title, "category": category(cand, item),
                "state": state, "next_action": next_action, "reason": reason[:500],
                "source_url": item.primary_url or item.url,
                "published_at": item.published_at.isoformat() + "Z" if item.published_at else None,
                "deadline": cand.expires_at.isoformat() + "Z" if cand and cand.expires_at else None,
                "packet_id": str(packet.id) if packet else None,
                "receipt_id": meta.get("receipt_id"), "preparation": meta.get("packet_preparation"),
            })
    priority = {"ready_to_record": 0, "preparing": 1, "needs_brief": 2,
                "publish": 3, "awaiting_appraisal": 4}
    queue.sort(key=lambda q: priority.get(q["state"], 4))
    # Queue shows one useful card per story. WIP counts all actual scripts and
    # claims, including an alternate proposal hidden by a human-selected card.
    ready_ids = {
        c.id for c in candidates
        if c.id in by_packet and by_packet[c.id].status in {"ready", "exported"}
        and c.status in {"proposed", "selected"} and c.id not in uploads
        and (c.expires_at is None or c.expires_at > now)
        and category(c, by_item.get(c.news_item_id)) == "ai"
    }
    preparing_ids = set()
    for item in items:
        preparation = (item.editorial_meta or {}).get("packet_preparation") or {}
        if (preparation.get("state") not in {"requested", "already_in_progress"}
                or preparation.get("claim_until", "") <= now.isoformat()):
            continue
        raw_id = preparation.get("candidate_id")
        if not raw_id:
            parts = str(preparation.get("fingerprint") or "").split(":")
            raw_id = parts[1] if len(parts) >= 2 and parts[0] == "news-brief-v2" else None
        try:
            cid = uuid.UUID(str(raw_id))
        except (ValueError, TypeError):
            continue
        c = by_id.get(cid)
        if (c and c.status in {"proposed", "selected"} and cid not in ready_ids
                and cid not in uploads and (c.expires_at is None or c.expires_at > now)
                and category(c, item) == "ai"):
            preparing_ids.add(cid)
    return {
        "enabled": True, "window_days": WINDOW_DAYS, "mix": mix, "queue": queue[:30],
        "recording_owner": "Ziv", "measurement": "TCE publication receipts; one original video counted once.",
        "ready_to_record": len(ready_ids), "preparing": len(preparing_ids),
    }


async def prepare_news_briefs(sm: Any, ws: uuid.UUID, *, limit: int = 2) -> dict[str, Any]:
    """Carry accepted AI stories to the existing durable packet workflow.

    Prepare at most two alternatives per run. This is a work-in-progress bound,
    never a topic quota. Existing scripts, human choices and recordings win.
    """
    from fastapi import BackgroundTasks, HTTPException
    from tce.api.routers.editorial import StartPacketRequest, start_packet
    from tce.editorial import lineup
    from tce.editorial.news_rules import owner_policy
    from tce.models.editorial_workspace import WeeklyLineupItem

    if not owner_policy(ws):
        return {"enabled": False}
    now = datetime.utcnow()
    async with sm() as db:
        data = await workflow_status(db, ws, now=now)
    ready = data["ready_to_record"]
    in_progress = data.get("preparing", sum(q["state"] == "preparing" for q in data["queue"]))
    available = max(0, limit - ready - in_progress)
    choices = [q for q in data["queue"] if q["state"] == "needs_brief"
               and q["category"] == "ai" and not q["packet_id"]]
    outcomes = []
    for choice in choices:
        if len(outcomes) >= available:
            break
        cid = uuid.UUID(choice["candidate_id"])
        async with sm() as db:
            # Serialize the short claim transaction across API and scheduler
            # processes. Never hold a database lock while the writer runs.
            if db.bind.dialect.name == "postgresql":
                lock_id = int.from_bytes(hashlib.sha256(
                    f"news-preparation:{ws}".encode()
                ).digest()[:8], "big", signed=True)
                await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
            fresh = await workflow_status(db, ws)
            occupied = fresh["ready_to_record"] + fresh.get(
                "preparing", sum(q["state"] == "preparing" for q in fresh["queue"]),
            )
            if occupied >= limit:
                break
            if not any(q["candidate_id"] == str(cid) and q["state"] == "needs_brief"
                       and not q["packet_id"] for q in fresh["queue"]):
                continue
            item = (await db.execute(select(NewsItem).where(
                NewsItem.id == uuid.UUID(choice["item_id"]), NewsItem.workspace_id == ws,
            ).with_for_update())).scalar_one()
            meta = dict(item.editorial_meta or {})
            attempt = dict(meta.get("packet_preparation") or {})
            if (attempt.get("state") in {"requested", "already_in_progress"}
                    and attempt.get("claim_until", "") > now.isoformat()):
                continue
            fingerprint = f"news-brief-v2:{cid}:{meta.get('retry_nonce', '')}"
            if attempt.get("fingerprint") == fingerprint and attempt.get("state") == "failed":
                continue
            cand = await db.get(TopicCandidate, cid)
            week = await lineup.current_lineup(db, ws)
            entry = (await db.execute(select(WeeklyLineupItem).where(
                WeeklyLineupItem.workspace_id == ws, WeeklyLineupItem.lineup_id == week.id,
                WeeklyLineupItem.candidate_id == cid,
            ))).scalar_one_or_none()
            if entry is None:
                entry = await lineup.add_topic(db, ws, week, cand, slot="reserve", added_by="news-editor")
                entry.reason = "AI news recording option. Verify availability, then choose when to record."
                entry.status = "preparing"
            claim_token = str(uuid.uuid4())
            item.editorial_meta = {**meta, "packet_preparation": {
                "fingerprint": fingerprint, "state": "requested",
                "candidate_id": str(cid),
                "claim_token": claim_token,
                "requested_at": now.isoformat() + "Z", "recording_owner": "Ziv",
                "claim_until": (now + timedelta(minutes=45)).isoformat(),
            }}
            await db.commit()
        background = BackgroundTasks()
        try:
            receipt = await start_packet(
                str(cid), background, StartPacketRequest(replace=False), ws, sm,
            )
            await background()
            state = "requested"
        except HTTPException as exc:
            # A user or another run already started/wrote the same brief.
            if exc.status_code == 409:
                state, receipt = "already_in_progress", {"detail": str(exc.detail)}
            else:
                state, receipt = "failed", {"detail": "The packet request was refused."}
        except Exception:
            state, receipt = "failed", {"detail": "Brief preparation failed; review and retry."}
        async with sm() as db:
            item = (await db.execute(select(NewsItem).where(
                NewsItem.id == uuid.UUID(choice["item_id"]), NewsItem.workspace_id == ws,
            ).with_for_update())).scalar_one()
            meta = dict(item.editorial_meta or {})
            if (meta.get("packet_preparation") or {}).get("claim_token") != claim_token:
                outcomes.append({"candidate_id": str(cid), "state": "claim_replaced"})
                continue
            from tce.editorial import status as job_status
            job = job_status.get(ws, "packet", str(cid)) or {}
            if job.get("state") == "failed":
                state = "failed"
            item.editorial_meta = {**meta, "packet_preparation": {
                **(meta.get("packet_preparation") or {}), "state": state, "receipt": receipt,
            }}
            await db.commit()
        outcomes.append({"candidate_id": str(cid), "state": state})
    return {"enabled": True, "outcomes": outcomes, "already_ready": ready}
