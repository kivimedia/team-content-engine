"""Import explicitly reviewed news briefs using the normal evidence and script gates.

Default is a transaction rollback. --apply writes only to the configured owner
workspace, keeps a private before-state snapshot, and never publishes or exports.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text

from tce.db.session import async_session
from tce.editorial import lineup
from tce.editorial.news_workflow import record_submission
from tce.editorial.packets import save_reviewed_news_packet
from tce.editorial.selector import PoolMoment, save_reviewed_news_candidate
from tce.models.editorial import EvidenceMoment, EvidenceSource, RecordingPacket, TopicCandidate
from tce.models.editorial_workspace import TopicDecision, WeeklyLineup, WeeklyLineupItem
from tce.models.news import NewsFeed, NewsItem
from tce.news.appraise import validate_appraisal
from tce.news.record import record_appraisal
from tce.services.url_fetcher import fetch_url_text
from tce.settings import settings

QUOTES = {
    "gemini-sites": "export interactive apps built in the Gemini app directly to Google Sites",
    "meeting-recaps": "Action items: Assigned next steps with designated owners",
    "sheets-ios": "you can ask questions about your data, generate analytical insights, and create charts",
    "haiku-roles": "Haiku 5.5 is designed for high-volume, cost-sensitive tasks.",
}


def packet_data(brief: dict, ids: list[str]) -> dict:
    phrases, bullets = brief["script"], brief["bullets"]
    return {
        "bullets": bullets, "script_phrases": phrases,
        "facebook_post": brief["title"] + ". " + brief["what_changed"]
                         + " " + brief["test_proposal"],
        "linkedin_post": brief["title"] + ". " + brief["what_changed"]
                         + " " + brief["why_for_you"],
        "interviewer_prompt": "Explain the change, the proposed test and what remains untested.",
        "hook_options": [
            {"id": f"hook-{i+1}", "text": hook,
             "question": "What useful business decision does this change make possible?",
             "payoff_phrase_id": "p006", "moment_ids": ids,
             "rationale": "Connects the sourced change to a concrete owner decision."}
            for i, hook in enumerate(brief["hooks"])
        ],
        "selected_hook_id": "hook-1",
        "beats": [
            {"id": f"b{i+1:02d}", "label": label, "bullet_index": i,
             "start_phrase_id": f"p{1+i*len(phrases)//len(bullets):03d}",
             "end_phrase_id": f"p{(i+1)*len(phrases)//len(bullets):03d}"}
            for i, label in enumerate(bullets)
        ],
        "self_check": {"proposed_demo_only": True, "source_dates_checked": True},
    }


def snapshot(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


async def run(args):
    ws = uuid.UUID(str(settings.editor_default_workspace_id))
    briefs = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    if len(briefs) != 4 or {b["slug"] for b in briefs} != set(QUOTES):
        raise ValueError("This bounded recovery accepts the four approved review pitches only.")
    before, receipts = [], []
    async with async_session() as db:
        if db.bind.dialect.name == "postgresql":
            lock_key = int.from_bytes(hashlib.sha256(
                f"reviewed-news-recovery:{ws}".encode()
            ).digest()[:8], "big", signed=True)
            await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        week_before = (await db.execute(select(WeeklyLineup).where(
            WeeklyLineup.workspace_id == ws,
            WeeklyLineup.week_start == lineup.week_start_for(None),
        ))).scalar_one_or_none()
        lineup_before = {
            "week": snapshot(week_before) if week_before else None,
            "items": [snapshot(row) for row in (await db.execute(
                select(WeeklyLineupItem).where(
                    WeeklyLineupItem.workspace_id == ws,
                    WeeklyLineupItem.lineup_id == week_before.id,
                )
            )).scalars()] if week_before else [],
        }
        for brief in briefs:
            # Re-running a completed review returns its original receipt.
            review_ref = args.review_ref + ":" + brief["slug"]
            reviewed = list((await db.execute(select(TopicCandidate).where(
                TopicCandidate.workspace_id == ws,
                TopicCandidate.editor_notes.contains(review_ref),
            ))).scalars())
            old = next((c for c in reviewed
                        if ((c.gates or {}).get("_editorial_review") or {}).get("reference")
                        == review_ref), None)
            if old:
                packet = (await db.execute(select(RecordingPacket).where(
                    RecordingPacket.workspace_id == ws, RecordingPacket.candidate_id == old.id,
                    RecordingPacket.status != "superseded",
                ).limit(1))).scalar_one_or_none()
                if packet:
                    receipts.append({"slug": brief["slug"], "candidate_id": str(old.id),
                                     "packet_id": str(packet.id), "status": packet.status,
                                     "already_present": True})
                    continue
            item = await db.get(NewsItem, uuid.UUID(brief["news_item_id"])) if brief["news_item_id"] else None
            if item is None:
                item = (await db.execute(select(NewsItem).where(
                    NewsItem.workspace_id == ws, NewsItem.url == brief["source_url"],
                ).limit(1))).scalar_one_or_none()
            created_item = item is None
            verified_primary = brief["source_url"]
            if created_item:
                if brief["slug"] != "haiku-roles":
                    raise ValueError("A previously reviewed Google source is missing; recheck it.")
                feed = (await db.execute(select(NewsFeed).where(
                    NewsFeed.workspace_id == ws,
                    NewsFeed.url == "https://www.anthropic.com/news",
                ))).scalar_one_or_none()
                if feed is None:
                    raise ValueError("Register the Anthropic primary feed before this recovery.")
                page = await fetch_url_text(brief["source_url"], public_only=True)
                if page.get("status") != "ok" or not page.get("source_verified"):
                    raise ValueError("The primary announcement could not be verified.")
                verified_primary = page.get("primary_url") or brief["source_url"]
                document = page["body_text"]
                expected_date = datetime.fromisoformat(brief["published"])
                fetched_date = page.get("published_at")
                if fetched_date:
                    actual_date = (fetched_date if isinstance(fetched_date, datetime)
                                   else datetime.fromisoformat(str(fetched_date).replace("Z", "+00:00")))
                    if actual_date.date() != expected_date.date():
                        raise ValueError("The primary page date differs from the reviewed date.")
                else:
                    readable = expected_date.strftime("%B ") + str(expected_date.day) + expected_date.strftime(", %Y")
                    if readable.casefold() not in re.sub(r"\s+", " ", document).casefold():
                        raise ValueError("The reviewed date is not visible in the primary document.")
                digest = hashlib.sha256(document.encode()).hexdigest()
                item = NewsItem(
                    id=uuid.uuid5(ws, "review-source:" + brief["source_url"]), workspace_id=ws,
                    # The direct collector uses the article URL as external ID.
                    # Seeding this identity avoids a second story on its next run.
                    feed_id=feed.id, external_id=brief["source_url"], url=brief["source_url"],
                    primary_url=verified_primary, canonical_url=brief["source_url"],
                    title=page.get("title") or brief["title"], publisher="Anthropic",
                    published_at=expected_date,
                    fetched_at=datetime.utcnow(), extract_private=document,
                    content_sha256=digest, source_version=digest[:16], source_tier="1b",
                    matched=True,
                )
                db.add(item)
                await db.flush()
            if item.workspace_id != ws:
                raise ValueError("Foreign workspace source.")
            before.append({"item": snapshot(item), "created_item": created_item,
                           "candidate": snapshot(old) if old else None})
            document = item.extract_private or item.raw_private or ""
            raw_appraisal = {
                "verdict": "publish", "verdict_reason": "Explicitly prioritized by Ziv; developed and source-checked in this session.",
                "news_category": "ai", "what_happened": brief["what_changed"],
                "audience_consequence": brief["why_for_you"], "distinct_claim": brief["test_proposal"],
                "do_differently": [brief["test_proposal"]],
                "confirmed_facts": [{"claim": brief["what_changed"], "quote": QUOTES[brief["slug"]]}],
                "ziv_interpretation": [brief["why_for_you"]], "predictions": [],
                "format": "three_things_id_test",
                "perishability": "month" if brief["slug"] == "haiku-roles"
                                  else "week" if brief["slug"] == "meeting-recaps" else "days",
                "story_weight": "small", "weight_reason": "",
                "scores": {"owner_relevance": 5, "consequence_specificity": 4, "distinctiveness": 4},
            }
            checked = validate_appraisal(
                raw_appraisal, document=document, published_at=item.published_at,
                has_post_announcement_demonstration=False,
            )
            anchor_ids = [uuid.UUID(x) for x in brief["anchor_ids"]]
            anchors = list((await db.execute(select(EvidenceMoment).where(
                EvidenceMoment.id.in_(anchor_ids), EvidenceMoment.workspace_id == ws,
                EvidenceMoment.status == "active",
            ))).scalars())
            if len(anchors) != len(anchor_ids):
                raise ValueError("A reviewed audience anchor is no longer active.")
            old_moments = list((await db.execute(select(EvidenceMoment).where(
                EvidenceMoment.source_id == item.evidence_source_id,
                EvidenceMoment.workspace_id == ws, EvidenceMoment.status == "active",
            ))).scalars()) if item.evidence_source_id else []
            before[-1]["moments"] = [snapshot(m) for m in old_moments]
            prior_source = (await db.execute(select(EvidenceSource).where(
                EvidenceSource.workspace_id == ws,
                EvidenceSource.source_kind == "news_item",
                EvidenceSource.external_id == str(item.id),
            ))).scalar_one_or_none()
            before[-1]["source"] = snapshot(prior_source) if prior_source else None
            item.primary_url = verified_primary
            item.editorial_meta = {**(item.editorial_meta or {}), "news_category": "ai",
                                   "review_ref": review_ref, "published_date_verified": True,
                                   "primary_source_verified": True,
                                   "published_date_provenance": "primary source checked in editorial review"}
            saved = await record_appraisal(db, ws, item, checked, anchors=[
                {"kind": (m.news_ref or {}).get("anchor_kind"),
                 "term": (m.news_ref or {}).get("anchor_term")} for m in anchors
            ], anchor_moment_ids=brief["anchor_ids"])
            moment = await db.get(EvidenceMoment, uuid.UUID(saved["moment_id"]))
            moment.news_ref = {**moment.news_ref, "news_category": "ai",
                               "editor_review_ref": review_ref}
            source = await db.get(EvidenceSource, item.evidence_source_id)
            pool = [PoolMoment(moment=moment, source=source, in_week=True)]
            for anchor in anchors:
                pool.append(PoolMoment(moment=anchor, source=await db.get(EvidenceSource, anchor.source_id),
                                       in_week=False))
            raw_candidate = {
                "moment_ids": [str(p.moment.id) for p in pool], "title": brief["title"],
                "lesson": brief["why_for_you"], "audience": brief["audience"],
                "public_angle": brief["test_proposal"],
                "reasons_to_care": [brief["what_changed"], brief["why_for_you"]],
                "public_safety_notes": brief["availability"] + "\n"
                    + "Proposed demo, not tested. Avoid: " + "; ".join(brief["do_not_say"]),
                "freshness_role": "news",
                "gates": {
                    "small_service_business": {"pass": True, "reason": "A narrow task within an owner-led business."},
                    "coach_or_event_owner_relevance": {"pass": True, "reason": brief["why_for_you"]},
                    "concrete_supported_substance": {"pass": True, "reason": "Primary announcement cited; the demo remains a proposal."},
                    "connects_to_ziv_work": {"pass": True, "reason": "Cites the existing audience or client-system standing facts named in this review."},
                },
                "scores": {"owner_relevance": 5, "useful_lesson": 4, "support_strength": 4},
            }
            candidate = await save_reviewed_news_candidate(db, ws, raw_candidate, pool, review_ref)
            packet = await save_reviewed_news_packet(
                db, ws, candidate.id, packet_data(brief, candidate.moment_ids), review_ref=review_ref,
            )
            if packet.status != "ready":
                raise ValueError(f"{brief['slug']} failed safety: {packet.public_safety}")
            week = await lineup.current_lineup(db, ws)
            entry = await lineup.add_topic(db, ws, week, candidate, slot="reserve", added_by="ziv-reviewed-news")
            entry.packet_id, entry.status = packet.id, "ready"
            entry.reason = "Prioritized by Ziv on October 20. Source checked; proposed demo remains untested."
            # Superseded evidence stays in history. Do not let the old invented
            # interpretation compete with the newly checked version in future runs.
            human_candidates = list((await db.execute(select(TopicCandidate).where(
                TopicCandidate.workspace_id == ws, TopicCandidate.news_item_id == item.id,
            ))).scalars())
            scripted_ids = set((await db.execute(select(RecordingPacket.candidate_id).where(
                RecordingPacket.workspace_id == ws,
                RecordingPacket.candidate_id.in_([c.id for c in human_candidates]),
            ))).scalars())
            human_ids = set((await db.execute(select(WeeklyLineupItem.candidate_id).where(
                WeeklyLineupItem.workspace_id == ws,
                WeeklyLineupItem.candidate_id.in_([c.id for c in human_candidates]),
            ))).scalars())
            human_ids.update((await db.execute(select(TopicDecision.candidate_id).where(
                TopicDecision.workspace_id == ws,
                TopicDecision.candidate_id.in_([c.id for c in human_candidates]),
            ))).scalars())
            before[-1]["replaced_candidates"] = []
            for previous in human_candidates:
                if (previous.id != candidate.id and previous.status == "proposed"
                        and previous.origin == "selector"
                        and previous.id not in scripted_ids | human_ids):
                    before[-1]["replaced_candidates"].append(snapshot(previous))
                    previous.status = "withdrawn"
                    previous.editor_notes = (
                        (previous.editor_notes or "") + "\nReplaced by the source-checked "
                        f"editorial review {review_ref}; candidate {candidate.id}."
                    ).strip()
            protected_moments = {
                str(mid) for c in human_candidates
                if c.status in {"selected", "recorded", "published"}
                or c.id in scripted_ids | human_ids
                for mid in (c.moment_ids or [])
            }
            for previous in old_moments:
                if str(previous.id) not in protected_moments:
                    previous.status = "stale"
            receipt = await record_submission(db, ws, item, "ziv-editorial-review", brief["test_proposal"])
            receipts.append({**receipt, "slug": brief["slug"], "candidate_id": str(candidate.id),
                             "packet_id": str(packet.id), "status": packet.status,
                             "created_candidate": old is None,
                             "score": candidate.rank_score,
                             "appraisal_id": saved["appraisal_id"],
                             "moment_id": saved["moment_id"],
                             "source_id": str(item.evidence_source_id),
                             "created_source": prior_source is None,
                             "lineup_id": str(week.id),
                             "lineup_entry_id": str(entry.id)})
        if args.apply:
            if not args.backup:
                raise ValueError("--backup is required when applying.")
            backup = Path(args.backup)
            # Exclusive creation and private permissions apply from the first
            # byte, before the database transaction is committed.
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"review_ref": args.review_ref, "before": before,
                           "lineup_before": lineup_before,
                           "receipts": receipts}, stream, default=str, indent=2)
            await db.commit()
        else:
            await db.rollback()
    print(json.dumps({"applied": args.apply, "review_ref": args.review_ref, "briefs": receipts}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--review-ref", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup")
    asyncio.run(run(parser.parse_args()))
