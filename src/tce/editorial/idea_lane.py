"""New ideas from a call: an idea he says out loud, or a research run he starts.

Neither path writes a TopicCandidate. Each one only records EVIDENCE - his own
spoken words, or a published announcement after the usual match and appraisal -
and then runs the selector scoped to that evidence, in its adds-only mode. So the
four gates, the anchor rule, the no-invented-outcome check and the duplicate check
decide exactly as they do for a call or a commit, and nothing already on his week
is withdrawn. `tests/unit/test_no_ungated_topic_source.py` holds that line.

Progress lives in `editorial.status` (in memory, like a packet): a restart loses
the progress line, never the evidence, and the next weekly selection sees it.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select

from tce.db.workspace_filter import workspace_language
from tce.editorial import status as job_status
from tce.editorial.common import current_week_start, open_session
from tce.models.editorial import EvidenceMoment, EvidenceSource, TopicCandidate

logger = structlog.get_logger()

SPOKEN_KIND = "spoken_idea"
KIND_SPOKEN = "spoken_idea"
KIND_RESEARCH = "idea_research"
MAX_RESEARCH_URLS = 6
MAX_RESEARCH_IDEAS = 3
SEED_DAYS = 21

# 27-Sep: "research new topics, decide how many, choose a specific type of videos".
# A topic's type (its lane) is a fact of its evidence, so each type is found where
# that evidence lives: news on the web, coaching in his calls, build in his commits.
KINDS = ("any", "news", "coaching", "build")
KIND_LABEL = {"any": "", "news": "news", "coaching": "coaching", "build": "build"}
KIND_SOURCES = {"coaching": ("fathom_meeting",), "build": ("github_commit_group",)}
MAX_IDEAS_ASKED = 10


def pages_for(count: int) -> int:
    """How many pages a web search reads for the number of ideas he asked for."""
    return max(MAX_RESEARCH_URLS, min(20, 2 * int(count) + 2))


def _topics_word(n: int, kind: str) -> str:
    label = KIND_LABEL.get(kind, "")
    return f"{n} new {label + ' ' if label else ''}topic{'s' if n != 1 else ''}"


async def _tell_his_phone(sm: Any, ws: uuid.UUID, run_id: uuid.UUID, ideas: list[dict], kind: str) -> None:
    """Closed the app? The topics are on his list, and his phone is told once."""
    if not ideas:
        return
    from tce.editorial import notify

    try:
        async with open_session(sm) as db:
            event = await notify.record_event(db, ws, {
                "kind": "new_topics",
                "dedupe_key": f"new_topics:{run_id}",
                "title": _topics_word(len(ideas), kind).capitalize(),
                "body": "; ".join(str(i.get("title") or "") for i in ideas)[:300],
                "path": "/topics",
            })
            if event is not None:
                await notify.deliver(db, ws, event)
            await db.commit()
    except Exception:  # a failed buzz never loses the topics themselves
        logger.warning("idea_lane.notify_failed", exc_info=True)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _clean(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


# ---------------------------------------------------------------------------
# An idea he said
# ---------------------------------------------------------------------------


async def record_spoken_idea(
    session: Any,
    ws: uuid.UUID,
    *,
    run_id: uuid.UUID,
    said: str,
    idea: str,
    angle: str | None = None,
    by: str = "voice",
    call_id: str | None = None,
    now: datetime | None = None,
) -> tuple[EvidenceSource, EvidenceMoment]:
    """His words, kept verbatim, as one evidence source with one moment.

    Written by a person like a standing fact, so the extractor never reads it
    (it is not in EXTRACTABLE_KINDS), and quoted, because it is exactly what he
    said.
    """
    now = now or _now()
    said = str(said or "").strip()[:4000]
    idea = _clean(idea, 2000)
    angle = _clean(angle, 2000) or None
    if not said or not idea:
        raise ValueError("an idea needs his words and a one-line summary")
    digest = hashlib.sha256(f"{said}\n{idea}\n{angle or ''}".encode()).hexdigest()
    source = EvidenceSource(
        id=uuid.uuid4(),
        workspace_id=ws,
        source_kind=SPOKEN_KIND,
        external_id=str(run_id),
        title=idea[:500],
        occurred_at=now,
        fetched_at=now,
        version_hash=digest,
        revision=1,
        fetch_status="ok",
        payload_private={"said": said, "idea": idea, "angle": angle, "call_id": call_id},
        meta={"origin": "voice_idea", "run_id": str(run_id), "by": by, "call_id": call_id},
    )
    session.add(source)
    await session.flush()
    moment = EvidenceMoment(
        id=uuid.uuid4(),
        workspace_id=ws,
        source_id=source.id,
        source_version_hash=digest,
        excerpt_private=said,
        context_private=angle,
        lesson_summary=idea,
        claim_type="quoted",
        speaker="Ziv",
        speaker_confidence="high",
        # A Hebrew workspace's spoken idea is Hebrew; every other one stays "en".
        language=workspace_language(ws),
        sensitivity_flags=[],
        status="active",
    )
    session.add(moment)
    await session.flush()
    return source, moment


def _rejection_said(rej: dict[str, Any]) -> str:
    gate = str(rej.get("gate") or "").replace("_", " ")
    reason = _clean(rej.get("reason"), 300)
    if rej.get("code") == "duplicate_existing":
        return f"It is already on your list: {reason}"
    if gate and gate != "unspecified":
        return f"It did not pass the {gate} check: {reason}"
    return reason


async def _mark_origin(sm: Any, ws: uuid.UUID, ids: list[str], note: str) -> None:
    if not ids:
        return
    async with open_session(sm) as db:
        rows = (
            await db.execute(
                select(TopicCandidate).where(
                    TopicCandidate.workspace_id == ws,
                    TopicCandidate.id.in_([uuid.UUID(i) for i in ids]),
                )
            )
        ).scalars().all()
        for row in rows:
            row.editor_notes = ((row.editor_notes + "\n") if row.editor_notes else "") + note
        await db.commit()


async def run_spoken_idea(
    sm: Any,
    ws: uuid.UUID,
    run_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    write_script: bool,
    by: str = "voice",
) -> None:
    """Gate the idea, and on a pass start its script. Never raises."""
    from tce.editorial.selector import select_candidates

    key = str(run_id)

    def on_activity(msg: str, **kw: Any) -> None:
        job_status.update(ws, KIND_SPOKEN, key, current_activity=msg, job_id=kw.get("job_id"))

    try:
        result = await select_candidates(
            sm,
            ws,
            current_week_start(),
            max_candidates=1,
            selection_run_id=run_id,
            on_activity=on_activity,
            source_ids=[source_id],
            adds_only=True,
        )
    except Exception as exc:
        logger.exception("idea_lane.spoken_failed", run_id=key)
        job_status.update(
            ws, KIND_SPOKEN, key, state="failed", finished_at=_now().isoformat(),
            current_activity="The check stopped with an error", detail=type(exc).__name__,
            said=f"The check stopped with an error ({type(exc).__name__}). Your words are kept.",
        )
        return

    if result.status == "waiting_capacity":
        job_status.update(
            ws, KIND_SPOKEN, key, state="waiting", detail=result.detail,
            said="is waiting for the writing computer to be free; your words are kept and "
            "it carries on by itself",
        )
        return
    if result.status not in ("complete", "no_evidence"):
        job_status.update(
            ws, KIND_SPOKEN, key, state="failed", finished_at=_now().isoformat(),
            detail=result.detail, said=f"could not be checked: {result.detail or result.status}",
        )
        return

    if not result.candidates:
        why = _rejection_said(result.rejected[0]) if result.rejected else "No idea came out of it."
        job_status.update(
            ws, KIND_SPOKEN, key, state="done", finished_at=_now().isoformat(),
            result={"saved": False, "rejected": result.rejected},
            said=f"was not saved. {why}",
        )
        return

    cand = result.candidates[0]
    cid = cand["id"]
    await _mark_origin(sm, ws, [cid], "Your idea, said on a call")
    script_started = False
    if write_script:
        script_started = await _start_script(sm, ws, uuid.UUID(cid), by=by)
    job_status.update(
        ws, KIND_SPOKEN, key, state="done", finished_at=_now().isoformat(),
        result={
            "saved": True, "candidate_id": cid, "title": cand.get("title"),
            "script_started": script_started, "gates": cand.get("gates"),
        },
        said=(
            f'is saved as "{cand.get("title")}"'
            + ("; its script is being written now" if script_started else "")
        ),
    )


async def _start_script(sm: Any, ws: uuid.UUID, cid: uuid.UUID, *, by: str) -> bool:
    """Start the script the way the Write script button does, in the background."""
    import asyncio

    from tce.api.routers.editorial import _run_packet

    if job_status.is_running(ws, "packet", str(cid)):
        return True
    job_status.start(ws, "packet", str(cid), "Queued packet", candidate_id=str(cid))
    task = asyncio.create_task(_run_packet(sm, ws, cid, None))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    return True


_BACKGROUND: set[Any] = set()


# ---------------------------------------------------------------------------
# A research run he started
# ---------------------------------------------------------------------------


async def seed_queries(session: Any, ws: uuid.UUID, now: datetime | None = None) -> list[str]:
    """"Surprise me": queries from what he has actually been working on lately.

    Never a feed and never a fixed list of sites: the seeds are the lessons of
    his own most recent calls and commits.
    """
    now = now or _now()
    rows = (
        await session.execute(
            select(EvidenceMoment.lesson_summary, EvidenceSource.source_kind)
            .join(EvidenceSource, EvidenceSource.id == EvidenceMoment.source_id)
            .where(
                EvidenceMoment.workspace_id == ws,
                EvidenceMoment.status == "active",
                EvidenceSource.source_kind.in_(("fathom_meeting", "github_commit_group")),
                EvidenceSource.occurred_at >= now - timedelta(days=SEED_DAYS),
            )
            .order_by(EvidenceSource.occurred_at.desc())
            .limit(3)
        )
    ).all()
    return [_clean(r[0], 120) for r in rows if r[0]]


async def run_idea_research(
    sm: Any,
    ws: uuid.UUID,
    run_id: uuid.UUID,
    *,
    topic: str | None,
    count: int = MAX_RESEARCH_IDEAS,
    kind: str = "any",
    days: int = SEED_DAYS,
    search: Any = None,
    fetch_text: Any = None,
    complete: Any = None,
) -> None:
    """Find new ideas of the kind he asked for, as many as he asked. Never raises."""
    key = str(run_id)
    count = max(1, min(MAX_IDEAS_ASKED, int(count or MAX_RESEARCH_IDEAS)))
    kind = kind if kind in KINDS else "any"
    # 27-Sep: "five ideas from the last two weeks of Fathom" - his window, not ours.
    days = max(1, min(60, int(days or SEED_DAYS)))
    try:
        if kind in KIND_SOURCES:
            await _run_from_his_work(sm, ws, run_id, topic=topic, count=count, kind=kind, days=days)
        else:
            await _run_idea_research(
                sm, ws, run_id, topic=topic, search=search, fetch_text=fetch_text,
                complete=complete, count=count, kind=kind,
            )
    except Exception as exc:
        logger.exception("idea_lane.research_failed", run_id=key)
        job_status.update(
            ws, KIND_RESEARCH, key, state="failed", finished_at=_now().isoformat(),
            detail=type(exc).__name__,
            said=f"stopped with an error ({type(exc).__name__}). Nothing on your list changed.",
        )


async def _run_from_his_work(
    sm: Any, ws: uuid.UUID, run_id: uuid.UUID, *, topic: str | None, count: int, kind: str,
    days: int = SEED_DAYS,
) -> None:
    """Coaching topics from his recent calls, build topics from his recent commits,
    through the same selector and gates as the weekly run, adds-only."""
    from tce.editorial import selector

    key = str(run_id)
    since = _now() - timedelta(days=days)
    job_status.update(ws, KIND_RESEARCH, key, current_activity=f"Reading your recent {'calls' if kind == 'coaching' else 'commits'}")
    async with open_session(sm) as db:
        q = select(EvidenceSource.id).where(
            EvidenceSource.workspace_id == ws,
            EvidenceSource.source_kind.in_(KIND_SOURCES[kind]),
            EvidenceSource.created_at >= since,
        )
        if topic:
            q = q.where(EvidenceSource.title.ilike(f"%{_clean(topic, 80)}%"))
        source_ids = list((await db.execute(q.order_by(EvidenceSource.created_at.desc()).limit(60))).scalars().all())
    where = "calls" if kind == "coaching" else "commits"
    if not source_ids:
        job_status.update(
            ws, KIND_RESEARCH, key, state="done", finished_at=_now().isoformat(),
            said=f"found no {where} of yours from the last {days} days"
            + (f" about {topic}" if topic else "") + ". Nothing on your list changed.",
            result={"ideas": [], "kind": kind},
        )
        return
    job_status.update(ws, KIND_RESEARCH, key, current_activity=f"Checking {len(source_ids)} {where} against your four checks")
    result = await selector.select_candidates(
        sm, ws, current_week_start(), max_candidates=count, selection_run_id=run_id,
        source_ids=source_ids, adds_only=True,
        on_activity=lambda msg, **kw: job_status.update(ws, KIND_RESEARCH, key, current_activity=msg),
    )
    if result.status == "waiting_capacity":
        job_status.update(ws, KIND_RESEARCH, key, state="waiting", detail=result.detail,
                          said="waits for the writing computer and carries on by itself.")
        return
    ideas = [{"candidate_id": c["id"], "title": c.get("title")} for c in result.candidates]
    await _mark_origin(sm, ws, [c["candidate_id"] for c in ideas], f"From your recent {where}")
    looked = f"read {len(source_ids)} of your {where} from the last {days} days"
    if ideas:
        said = f"{looked}. {_topics_word(len(ideas), kind).capitalize()} on your list: " + "; ".join(
            f'"{c["title"]}"' for c in ideas) + "."
    else:
        why = _rejection_said(result.rejected[0]) if result.rejected else ""
        said = f"{looked}. Nothing new passed the checks; the rest is already on your list. {why}".strip()
    job_status.update(ws, KIND_RESEARCH, key, state="done", finished_at=_now().isoformat(),
                      said=said, result={"ideas": ideas, "kind": kind, "sources": len(source_ids)})
    await _tell_his_phone(sm, ws, run_id, ideas, kind)


async def _run_idea_research(
    sm: Any,
    ws: uuid.UUID,
    run_id: uuid.UUID,
    *,
    topic: str | None,
    search: Any,
    fetch_text: Any,
    complete: Any,
    count: int = MAX_RESEARCH_IDEAS,
    kind: str = "any",
) -> None:
    from tce import llm as _llm
    from tce.editorial.selector import select_candidates
    from tce.models.news import NewsAppraisal, NewsItem
    from tce.news import discovery
    from tce.news.feeds import is_blocked_host
    from tce.services.url_fetcher import fetch_url_text
    from tce.services.web_search import WebSearchService

    key = str(run_id)
    fetch_text = fetch_text or fetch_url_text
    complete = complete or _llm.complete

    def activity(msg: str, **extra: Any) -> None:
        job_status.update(ws, KIND_RESEARCH, key, current_activity=msg, **extra)

    def finish(said: str, **result: Any) -> None:
        job_status.update(
            ws, KIND_RESEARCH, key, state="done", finished_at=_now().isoformat(),
            said=said, result=result,
        )

    if topic:
        queries = [_clean(topic, 200)]
    else:
        async with open_session(sm) as db:
            queries = await seed_queries(db, ws)
        if not queries:
            finish("found nothing to start from: no calls or commits in the last three weeks.")
            return

    service = search or WebSearchService()
    if not getattr(service, "api_key", True):
        finish(
            "could not search: web search is not set up on TCE (no search key). "
            "Nothing was looked at and nothing on your list changed.",
            queries=queries, web_status="no_key",
        )
        return

    activity(f"Searching the web for {len(queries)} question(s)")
    urls: list[str] = []
    blocked = 0
    pages = pages_for(count)
    per_query = max(3, pages // len(queries) + 1)
    for q in queries:
        try:
            hits = await service.search(q, count=per_query + 4, freshness="pm", raise_errors=True)
        except Exception as exc:
            finish(
                f"could not search the web ({type(exc).__name__}). Nothing on your list changed.",
                queries=queries, web_status="failed",
            )
            return
        taken = 0
        for hit in hits:
            url = str(hit.get("url") or "")
            if not url.startswith("http") or url in urls:
                continue
            # A news site's write-up is never the source; the lane confirms a
            # claim only from the announcement itself.
            if is_blocked_host(url):
                blocked += 1
                continue
            urls.append(url)
            taken += 1
            if taken >= per_query:
                break
    urls = urls[:pages]

    counts = {"pages": len(urls), "news_sites_skipped": blocked, "no_match": 0,
              "unreachable": 0, "matched": 0, "published": 0, "watched": 0, "rejected": 0,
              "waiting": 0}
    news_sources: list[uuid.UUID] = []
    anchor_ids: set[str] = set()
    for i, url in enumerate(urls, start=1):
        activity(f"Reading page {i} of {len(urls)}")
        async with open_session(sm) as db:
            out = await discovery.check_one(db, ws, url=url, fetch_text=fetch_text)
            await db.commit()
        status = out.get("status")
        if status == "no_match":
            counts["no_match"] += 1
            continue
        if status != "matched":
            counts["unreachable"] += 1
            continue
        counts["matched"] += 1
        item_id = uuid.UUID(out["item_id"])
        activity(f"Page {i} touches something you use; weighing it")
        async with open_session(sm) as db:
            done = await discovery.appraise_pending(db, ws, complete=complete, only_item=item_id)
            await db.commit()
            if done.get("waiting"):
                counts["waiting"] += 1
                continue
            item = await db.get(NewsItem, item_id)
            verdict = (
                await db.execute(
                    select(NewsAppraisal.verdict)
                    .where(NewsAppraisal.workspace_id == ws, NewsAppraisal.news_item_id == item_id)
                    .order_by(NewsAppraisal.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if verdict == "publish" and item is not None and item.evidence_source_id:
                counts["published"] += 1
                news_sources.append(item.evidence_source_id)
                moments = (
                    await db.execute(
                        select(EvidenceMoment).where(
                            EvidenceMoment.workspace_id == ws,
                            EvidenceMoment.source_id == item.evidence_source_id,
                        )
                    )
                ).scalars().all()
                for m in moments:
                    anchor_ids.update((m.news_ref or {}).get("anchor_moment_ids") or [])
            elif verdict == "watch":
                counts["watched"] += 1
            else:
                counts["rejected"] += 1

    about = f'"{topic}"' if topic else "what you have been working on"
    looked = (
        f"looked at {counts['pages']} pages about {about}"
        + (f" (skipped {blocked} news write-ups)" if blocked else "")
        + f": {counts['no_match']} touched nothing you use"
        + (f", {counts['watched']} are on the watchlist until you have something of yours to "
           "say about them" if counts["watched"] else "")
        + (f", {counts['rejected']} were not worth a video" if counts["rejected"] else "")
        + (f", {counts['waiting']} wait for the writing computer" if counts["waiting"] else "")
        + (f", {counts['unreachable']} would not load" if counts["unreachable"] else "")
        + "."
    )
    if not news_sources:
        finish(f"{looked} No new idea.", queries=queries, counts=counts, urls=urls,
               web_status="searched", ideas=[])
        return

    source_ids = list(dict.fromkeys(news_sources))
    if anchor_ids:
        async with open_session(sm) as db:
            anchor_sources = (
                await db.execute(
                    select(EvidenceMoment.source_id).where(
                        EvidenceMoment.workspace_id == ws,
                        EvidenceMoment.id.in_([uuid.UUID(a) for a in anchor_ids]),
                    )
                )
            ).scalars().all()
        source_ids += [s for s in anchor_sources if s not in source_ids]

    activity("Checking the finds against your four checks")
    result = await select_candidates(
        sm,
        ws,
        current_week_start(),
        max_candidates=count,
        selection_run_id=run_id,
        source_ids=source_ids,
        adds_only=True,
        on_activity=lambda msg, **kw: activity(msg),
    )
    if result.status == "waiting_capacity":
        job_status.update(
            ws, KIND_RESEARCH, key, state="waiting", detail=result.detail,
            said=f"{looked} The last check waits for the writing computer and carries on "
            "by itself.",
        )
        return
    ideas = [{"candidate_id": c["id"], "title": c.get("title")} for c in result.candidates]
    label = f"From research on {topic}" if topic else "From research on your recent work"
    await _mark_origin(sm, ws, [c["candidate_id"] for c in ideas], label)
    if ideas:
        names = "; ".join(f'"{c["title"]}"' for c in ideas)
        said = f"{looked} New on your list: {names}."
    else:
        why = _rejection_said(result.rejected[0]) if result.rejected else ""
        said = f"{looked} None of it made a new idea. {why}".strip()
    finish(
        said, queries=queries, counts=counts, urls=urls, web_status="searched", ideas=ideas,
        rejected=result.rejected,
    )
    await _tell_his_phone(sm, ws, run_id, ideas, kind)
