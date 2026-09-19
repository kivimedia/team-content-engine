"""Status for long editorial jobs (selection, packets).

Two layers. The in-process registry answers "what is this process awaiting right now"
with a live current_activity string. It resets on restart, so the durable views below
rebuild the state of the newest selection run / packet job from llm_jobs and the saved
rows: a restarted process reports queued, waiting, failed or finished-but-unsaved work
honestly (and whether a retry can resume it) instead of "idle".
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

_LOCK = threading.Lock()
_ENTRIES: dict[tuple[str, str, str], dict[str, Any]] = {}
_MAX_ENTRIES = 500


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _key(workspace_id: uuid.UUID | str, kind: str, key: str) -> tuple[str, str, str]:
    return (str(workspace_id), kind, str(key))


def start(
    workspace_id: uuid.UUID | str, kind: str, key: str, activity: str, **extra: Any
) -> dict[str, Any]:
    entry = {
        "workspace_id": str(workspace_id),
        "kind": kind,
        "key": str(key),
        "state": "running",
        "current_activity": activity,
        "job_ids": [],
        "started_at": _now(),
        "updated_at": _now(),
        "finished_at": None,
        "detail": None,
        **extra,
    }
    with _LOCK:
        if len(_ENTRIES) >= _MAX_ENTRIES:
            oldest = sorted(_ENTRIES.items(), key=lambda kv: kv[1]["updated_at"])[:50]
            for k, _ in oldest:
                _ENTRIES.pop(k, None)
        _ENTRIES[_key(workspace_id, kind, key)] = entry
    return dict(entry)


def update(workspace_id: uuid.UUID | str, kind: str, key: str, **fields: Any) -> None:
    with _LOCK:
        entry = _ENTRIES.get(_key(workspace_id, kind, key))
        if entry is None:
            return
        job_id = fields.pop("job_id", None)
        if job_id and str(job_id) not in entry["job_ids"]:
            entry["job_ids"].append(str(job_id))
        entry.update(fields)
        entry["updated_at"] = _now()
        if fields.get("state") in ("done", "waiting", "failed"):
            entry["finished_at"] = _now()


def get(workspace_id: uuid.UUID | str, kind: str, key: str) -> dict[str, Any] | None:
    with _LOCK:
        entry = _ENTRIES.get(_key(workspace_id, kind, key))
        return dict(entry, job_ids=list(entry["job_ids"])) if entry else None


def is_running(workspace_id: uuid.UUID | str, kind: str, key: str) -> bool:
    entry = get(workspace_id, kind, key)
    return bool(entry and entry["state"] == "running")


def list_for_workspace(workspace_id: uuid.UUID | str, limit: int = 50) -> list[dict[str, Any]]:
    ws = str(workspace_id)
    with _LOCK:
        rows = [
            dict(e, job_ids=list(e["job_ids"]))
            for e in _ENTRIES.values()
            if e["workspace_id"] == ws
        ]
    rows.sort(key=lambda e: e["updated_at"], reverse=True)
    return rows[:limit]


def clear() -> None:
    with _LOCK:
        _ENTRIES.clear()


# ---------------------------------------------------------------------------
# Durable views (survive a restart)
# ---------------------------------------------------------------------------
# Rebuilt from llm_jobs (prompt headers carry week, shard and request identity) and the
# persisted rows. They report what is actually on record: a job that is still queued
# after the request waiting for it died is "interrupted", not "idle" and not "running".

SELECTION_JOB_TYPE = "editorial_selection"
PACKET_JOB_TYPE = "recording_packet"
IN_FLIGHT = ("queued", "leased", "waiting_capacity")
_SELECTION_LOOKBACK = 400


def _iso_naive(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _job_brief(job: Any, **extra: Any) -> dict[str, Any]:
    return {
        "job_id": str(job.id),
        "status": job.status,
        "attempt_count": job.attempt_count,
        "retry_at": _iso_naive(job.retry_at),
        "error_code": job.error_code,
        "error_detail": job.error_detail,
        "created_at": _iso_naive(job.created_at),
        "completed_at": _iso_naive(job.completed_at),
        **extra,
    }


async def latest_selection_run(
    session: Any, workspace_id: uuid.UUID | str, week_start: str
) -> dict[str, Any] | None:
    """The newest selection run on record for a week, with an honest state.

    state: done | waiting | failed | interrupted. `resumable` says whether POST /select
    will re-attach to this run's jobs instead of starting a new one.
    """
    from sqlalchemy import select

    from tce.editorial.common import coerce_uuid, job_can_requeue, job_prompt_text
    from tce.editorial.common import parse_selection_header as parse
    from tce.models.editorial import TopicCandidate
    from tce.models.llm_job import LLMJob

    ws = coerce_uuid(workspace_id)
    jobs = (
        (
            await session.execute(
                select(LLMJob)
                .where(LLMJob.workspace_id == ws, LLMJob.job_type == SELECTION_JOB_TYPE)
                .order_by(LLMJob.created_at.desc())
                .limit(_SELECTION_LOOKBACK)
            )
        )
        .scalars()
        .all()
    )
    runs: dict[uuid.UUID, dict[str, Any]] = {}
    for job in jobs:
        meta = parse(job_prompt_text(job.request_json))
        if meta is None or meta["week_start"] != week_start or job.run_id is None:
            continue
        run = runs.setdefault(
            job.run_id,
            {"jobs": [], "rank": None, "shards": None, "max_candidates": None},
        )
        run["shards"] = run["shards"] or meta["shards"]
        if run["max_candidates"] is None:
            run["max_candidates"] = meta["max_candidates"]
        if meta["stage"] == "rank":
            # the run's one global ranking job, after all shards finished
            run["rank"] = job
        else:
            run["jobs"].append((meta, job))
    if not runs:
        return None

    def newest(run: dict[str, Any]) -> datetime:
        stamps = [j.created_at or datetime.min for _m, j in run["jobs"]]
        if run["rank"] is not None:
            stamps.append(run["rank"].created_at or datetime.min)
        return max(stamps)

    run_id, run = max(runs.items(), key=lambda kv: newest(kv[1]))
    rank_job = run["rank"]
    saved = (
        await session.execute(
            select(TopicCandidate.id)
            .where(TopicCandidate.workspace_id == ws, TopicCandidate.selection_run_id == run_id)
            .limit(1)
        )
    ).first() is not None

    shard_rows = []
    counts: dict[str, int] = {}
    has_output = False
    finalists = 0  # candidates proposed by finished shards (before code checks)
    unreadable = 0
    requeueable = True
    for meta, job in sorted(run["jobs"], key=lambda mj: mj[0]["shard"] or 1):
        counts[job.status] = counts.get(job.status, 0) + 1
        shard_rows.append(
            _job_brief(
                job,
                shard=meta["shard"] or 1,
                shards=meta["shards"],
                moments=len(meta["moment_ids"]),
            )
        )
        if job.status == "succeeded":
            data = job.result_json
            if not isinstance(data, dict):
                unreadable += 1
            elif data.get("candidates") or data.get("rejections"):
                has_output = True
                finalists += len(data.get("candidates") or [])
        if job.status in ("failed", "cancelled") and not job_can_requeue(job):
            requeueable = False

    total = run["shards"] or len(run["jobs"])
    missing = total - len(run["jobs"])
    finished = counts.get("succeeded", 0)
    shards_done = finished == total and missing == 0
    # the selector ranks globally only with 2+ shards and 2+ validated finalists; this
    # count is the shards' raw proposals, so it is an upper bound
    rank_pending = shards_done and total > 1 and finalists > 1 and rank_job is None
    rank_row = None
    if rank_job is not None:
        counts[rank_job.status] = counts.get(rank_job.status, 0) + 1
        rank_row = _job_brief(rank_job, stage="rank", shards=total)
        if rank_job.status == "succeeded":
            data = rank_job.result_json
            if not isinstance(data, dict):
                unreadable += 1
            elif data.get("selected") or data.get("duplicates") or data.get("not_selected"):
                has_output = True
        if rank_job.status in ("failed", "cancelled") and not job_can_requeue(rank_job):
            requeueable = False
    waiting = [j for _m, j in run["jobs"] if j.status == "waiting_capacity"]
    if rank_job is not None and rank_job.status == "waiting_capacity":
        waiting.append(rank_job)
    retry_at = max((j.retry_at for j in waiting if j.retry_at), default=None)
    summary = f"{finished} of {total} shard job(s) finished"
    if rank_job is not None:
        summary += f"; global ranking job {rank_job.status}"
    elif rank_pending:
        summary += "; global ranking not started"
    in_flight = sum(counts.get(s, 0) for s in IN_FLIGHT)

    if saved:
        state, resumable = "done", False
        activity = f"Selection saved ({summary})"
    elif missing > 0:
        state, resumable = "failed", False
        activity = (
            f"Selection run interrupted while enqueueing: {len(run['jobs'])} of {total} jobs "
            "exist. Start a new selection."
        )
    elif counts.get("failed") or counts.get("cancelled") or unreadable:
        state, resumable = "failed", bool(requeueable and not unreadable)
        bad = counts.get("failed", 0) + counts.get("cancelled", 0) + unreadable
        jobs_total = total + (1 if rank_job is not None else 0)
        activity = f"Selection not saved ({summary}): {bad} of {jobs_total} job(s) failed. " + (
            "Retry re-queues the failed job(s) once and reuses the finished ones."
            if resumable
            else "Start a new selection."
        )
    elif in_flight:
        state = "waiting" if waiting else "interrupted"
        resumable = True
        activity = (
            f"{summary}; {in_flight} still {'waiting for capacity' if waiting else 'queued'}"
            + (f" until {_iso_naive(retry_at)}" if retry_at else "")
            + ". No request is waiting to save the result in this process: retry resumes "
            "the same jobs."
        )
    elif has_output and rank_pending:
        state, resumable = "interrupted", True
        activity = (
            f"{summary}: the request ended before the global ranking ran. Retry reuses the "
            "finished shard jobs, runs the one global ranking job (when 2 or more finalists "
            "pass the checks) and saves the result."
        )
    elif has_output:
        state, resumable = "interrupted", True
        activity = (
            f"{summary} but the result was never saved (the request ended first). Retry "
            "saves it without new model calls."
        )
    else:
        state, resumable = "done", False
        activity = f"Selection finished with nothing to save ({summary})"

    return {
        "source": "durable",
        "selection_run_id": str(run_id),
        "week_start": week_start,
        "state": state,
        "resumable": resumable,
        "saved": saved,
        "current_activity": activity,
        "job_ids": [s["job_id"] for s in shard_rows] + ([rank_row["job_id"]] if rank_row else []),
        "job_counts": counts,
        "shards": shard_rows,
        # the run's global ranking job across shard finalists (None until it exists; runs
        # with one shard never need one)
        "rank": rank_row,
        "shards_expected": total,
        "max_candidates": run["max_candidates"],
        "retry_at": _iso_naive(retry_at),
    }


async def latest_packet_job(
    session: Any, workspace_id: uuid.UUID | str, candidate_id: uuid.UUID | str
) -> dict[str, Any] | None:
    """The newest packet job on record for a candidate, with an honest state."""
    from sqlalchemy import select

    from tce.editorial.common import coerce_uuid, job_prompt_text, parse_packet_header
    from tce.editorial.packets import PacketValidationError, validate_packet_output
    from tce.models.editorial import RecordingPacket
    from tce.models.llm_job import LLMJob

    ws = coerce_uuid(workspace_id)
    cid = coerce_uuid(candidate_id)
    job = (
        (
            await session.execute(
                select(LLMJob)
                .where(
                    LLMJob.workspace_id == ws,
                    LLMJob.job_type == PACKET_JOB_TYPE,
                    LLMJob.run_id == cid,
                )
                .order_by(LLMJob.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if job is None:
        return None
    packet = (
        await session.execute(
            select(RecordingPacket.id, RecordingPacket.version).where(
                RecordingPacket.workspace_id == ws,
                RecordingPacket.candidate_id == cid,
                RecordingPacket.job_id == job.id,
            )
        )
    ).first()
    replayable = parse_packet_header(job_prompt_text(job.request_json)) is not None

    if packet is not None:
        state, resumable = "done", False
        activity = f"Packet v{packet.version} saved"
    elif job.status in IN_FLIGHT:
        state = "waiting" if job.status == "waiting_capacity" else "interrupted"
        resumable = replayable
        activity = (
            f"Packet job {job.status}"
            + (f" until {_iso_naive(job.retry_at)}" if job.retry_at else "")
            + ". No request is waiting to save it in this process: "
            + ("retry resumes the same job." if replayable else "request a new packet.")
        )
    elif job.status == "succeeded":
        try:
            validate_packet_output(job.result_json)
            valid = True
        except PacketValidationError:
            valid = False
        if valid:
            state, resumable = "interrupted", replayable
            activity = "Packet written but never saved (the request ended first). " + (
                "Retry saves it without a new model call."
                if replayable
                else "Request a new packet."
            )
        else:
            state, resumable = "failed", False
            activity = "Packet job output failed validation; request a new packet."
    else:
        state, resumable = "failed", False
        activity = f"Packet job {job.status}: {job.error_code or ''}".strip()

    return {
        "source": "durable",
        "candidate_id": str(cid),
        "state": state,
        "resumable": resumable,
        "packet_id": str(packet.id) if packet is not None else None,
        "current_activity": activity,
        "job_ids": [str(job.id)],
        "job": _job_brief(job),
    }


async def unattended_jobs(session: Any, workspace_id: uuid.UUID | str) -> list[dict[str, Any]]:
    """Editorial jobs still queued/leased/waiting in the database for this workspace."""
    from sqlalchemy import select

    from tce.editorial.common import coerce_uuid, job_prompt_text, parse_selection_header
    from tce.models.llm_job import LLMJob

    ws = coerce_uuid(workspace_id)
    rows = (
        (
            await session.execute(
                select(LLMJob)
                .where(
                    LLMJob.workspace_id == ws,
                    LLMJob.job_type.in_((SELECTION_JOB_TYPE, PACKET_JOB_TYPE)),
                    LLMJob.status.in_(IN_FLIGHT),
                )
                .order_by(LLMJob.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    out = []
    for job in rows:
        if job.job_type == SELECTION_JOB_TYPE:
            meta = parse_selection_header(job_prompt_text(job.request_json)) or {}
            key = {
                "kind": "select",
                "key": meta.get("week_start"),
                "selection_run_id": str(job.run_id) if job.run_id else None,
                "shard": meta.get("shard") or 1,
                "shards": meta.get("shards"),
            }
            if meta.get("stage") == "rank":
                key["stage"] = "rank"
                key["shard"] = None
        else:
            key = {"kind": "packet", "key": str(job.run_id) if job.run_id else None}
        out.append(_job_brief(job, **key))
    return out
