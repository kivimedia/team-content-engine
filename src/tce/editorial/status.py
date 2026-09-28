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


# ---------------------------------------------------------------------------
# Packet requests: what became of a script he asked for
# ---------------------------------------------------------------------------
# 28-Sep-2026: he asked for a script while the worker group was parked on its
# weekly limit. The request gave up at once, the job was written when capacity
# came back, and nothing saved it: the topic said "no script" until someone
# asked again. The scheduler tick now saves such a job by itself (see
# `unsaved_packet_requests`), so everything he is told here says so, and never
# "interrupted, retry" for work that finishes on its own.

# How far back the tick looks for a request whose job finished after it ended.
# A weekly limit can park a job for up to a week.
REDRIVE_LOOKBACK_DAYS = 8
WRITING_WORDS = "Asked for. It is written on your PC worker and saves itself when it is done."
SAVING_WORDS = "Written. It is saved within five minutes, without a new model call."


def israel_time(moment: datetime) -> str:
    """A naive UTC instant as he reads it: "Wed 30-Sep at 07:00", his clock."""
    from zoneinfo import ZoneInfo

    from tce.editorial.common import WEEK_TIMEZONE

    local = moment.replace(tzinfo=UTC).astimezone(ZoneInfo(WEEK_TIMEZONE))
    return f"{local:%a} {local.day}-{local:%b} at {local:%H:%M}"


def capacity_words(retry_at: datetime | None) -> str:
    when = f" on {israel_time(retry_at)}" if retry_at else ""
    return (
        f"Waiting for your Claude limit to reset{when}. The script is written then and "
        "saves itself; nothing to ask again."
    )


def packet_wait_words(outcome_status: str, retry_at: datetime | None) -> tuple[str, str]:
    """(current_activity, detail) for a request that stopped waiting on its job.

    Both ways a request stops waiting leave the job to finish later, and the tick
    saves it then: "waiting_capacity" (the weekly or five-hour limit) and
    "timeout" (still queued when the request's wait ran out).
    """
    if outcome_status == "waiting_capacity":
        return "Waiting for your Claude limit to reset", capacity_words(retry_at)
    return "Waiting for the PC worker", WRITING_WORDS


async def capacity_park(session: Any, *, now: datetime | None = None) -> datetime | None:
    """When the subscription worker group is parked on its usage limit, until when.

    While it is parked no new job is leased, so a job can sit "queued" for days
    without being at fault: it is waiting for capacity like its parked sibling.
    """
    from sqlalchemy import select

    from tce.llm.queue import WORKER_GROUP_KEY, utcnow
    from tce.models.content_run import WorkerGroupState

    group = (
        await session.execute(
            select(WorkerGroupState).where(WorkerGroupState.group_key == WORKER_GROUP_KEY)
        )
    ).scalar_one_or_none()
    now = now or utcnow()
    if group is None or group.state != "waiting_capacity" or not group.retry_at:
        return None
    return group.retry_at if group.retry_at > now else None


def _packet_request(
    job: Any,
    *,
    saved_version: int | None,
    park: datetime | None,
    failed_resume: str | None = None,
) -> dict[str, Any]:
    """One packet job's honest state, for the status route, the week and the tick.

    state/resumable/activity are the status route's durable view; `request` is
    what the week, Today and the topic show ("pending" means it finishes by
    itself, so nothing offers to ask for it again); `action` is the tick's.
    """
    from tce.editorial.common import job_prompt_text, parse_packet_header
    from tce.editorial.packets import PacketValidationError, validate_packet_output
    from tce.llm.queue import utcnow

    replayable = parse_packet_header(job_prompt_text(job.request_json)) is not None
    # A parked job whose retry time has passed is leasable again: it is not
    # waiting for capacity any more, only for the worker to take it.
    retry_at = (
        job.retry_at
        if job.status == "waiting_capacity" and job.retry_at and job.retry_at > utcnow()
        else None
    )
    # A job not yet taken waits on the parked group too. A leased one is being
    # written right now, and saying it waits for the limit would be wrong.
    if job.status in ("queued", "waiting_capacity") and park is not None:
        retry_at = retry_at or park

    def request(kind: str, label: str, sentence: str, pending: bool) -> dict[str, Any]:
        return {
            "state": kind,
            "pending": pending,
            "label": label,
            "sentence": sentence,
            "retry_at": _iso_naive(retry_at),
            "job_id": str(job.id),
        }

    if saved_version is not None:
        return {
            "state": "done",
            "resumable": False,
            "activity": f"Packet v{saved_version} saved",
            "request": None,
            "action": "saved",
        }
    if job.status in IN_FLIGHT and replayable:
        parked = retry_at is not None
        words = capacity_words(retry_at) if parked else WRITING_WORDS
        return {
            "state": "waiting",
            "resumable": True,
            "activity": words,
            "request": request(
                "waiting_capacity" if parked else "writing",
                "Script waiting for your Claude limit" if parked else "Script asked for",
                words,
                True,
            ),
            "action": "waiting",
        }
    if job.status == "succeeded":
        try:
            validate_packet_output(job.result_json)
            valid = True
        except PacketValidationError:
            valid = False
        if valid and replayable and failed_resume is None:
            return {
                "state": "waiting",
                "resumable": True,
                "activity": SAVING_WORDS,
                "request": request("saving", "Script written, saving it", SAVING_WORDS, True),
                "action": "resume",
            }
        if valid and replayable:
            words = f"Written, but it could not be saved ({failed_resume}). Ask for a new script."
        elif valid:
            words = "Written, but the request that asked for it is lost. Ask for a new script."
        else:
            words = "Packet job output failed validation; request a new packet."
        return {
            "state": "failed",
            "resumable": False,
            "activity": words,
            "request": request("failed", "Script not saved", words, False),
            "action": "failed",
        }
    if job.status in IN_FLIGHT:
        words = (
            f"Packet job {job.status}, but the request that asked for it is lost and it "
            "cannot be picked up again. Ask for a new script."
        )
        return {
            "state": "interrupted",
            "resumable": False,
            "activity": words,
            "request": request("failed", "Script request lost", words, False),
            "action": "failed",
        }
    words = f"Packet job {job.status}: {job.error_code or ''}".strip()
    return {
        "state": "failed",
        "resumable": False,
        "activity": words,
        "request": request(
            "failed", "Script request stopped", f"The last try stopped ({words}). Ask again.", False
        ),
        "action": "failed",
    }


def _failed_resume(
    workspace_id: uuid.UUID, candidate_id: uuid.UUID, job_id: uuid.UUID
) -> str | None:
    """Why a resume of this very job ended failed in this process, if it did.

    Saving a written job cannot fail by waiting; when it fails (a stricter check
    at save time, the idea withdrawn) it fails the same way every time, so the
    tick must not try again every five minutes, and nothing may promise it.
    """
    entry = get(workspace_id, "packet", str(candidate_id))
    if entry and entry.get("resumed_job_id") == str(job_id) and entry.get("state") == "failed":
        return str(entry.get("detail") or entry.get("current_activity") or "it failed")
    return None


async def _newest_packet_jobs(
    session: Any,
    ws: uuid.UUID,
    *,
    candidate_ids: list[uuid.UUID] | None = None,
    since: datetime | None = None,
) -> dict[uuid.UUID, Any]:
    """The newest packet job per idea: a later ask replaces an earlier one."""
    from sqlalchemy import select

    from tce.models.llm_job import LLMJob

    stmt = (
        select(LLMJob)
        .where(
            LLMJob.workspace_id == ws,
            LLMJob.job_type == PACKET_JOB_TYPE,
            LLMJob.run_id.is_not(None),
        )
        .order_by(LLMJob.created_at.desc())
    )
    if candidate_ids is not None:
        if not candidate_ids:
            return {}
        stmt = stmt.where(LLMJob.run_id.in_(candidate_ids))
    if since is not None:
        stmt = stmt.where(LLMJob.created_at >= since)
    newest: dict[uuid.UUID, Any] = {}
    for job in (await session.execute(stmt)).scalars():
        newest.setdefault(job.run_id, job)
    return newest


async def _saved_versions(
    session: Any, ws: uuid.UUID, jobs: dict[uuid.UUID, Any]
) -> dict[uuid.UUID, int]:
    """Which of these jobs a packet was saved from, by idea, with the version."""
    from sqlalchemy import select

    from tce.models.editorial import RecordingPacket

    if not jobs:
        return {}
    rows = await session.execute(
        select(RecordingPacket.candidate_id, RecordingPacket.job_id, RecordingPacket.version).where(
            RecordingPacket.workspace_id == ws,
            RecordingPacket.job_id.in_([job.id for job in jobs.values()]),
        )
    )
    saved: dict[uuid.UUID, int] = {}
    for candidate_id, job_id, version in rows.all():
        job = jobs.get(candidate_id)
        if job is not None and job.id == job_id:
            saved[candidate_id] = min(version, saved.get(candidate_id, version))
    return saved


async def latest_packet_job(
    session: Any, workspace_id: uuid.UUID | str, candidate_id: uuid.UUID | str
) -> dict[str, Any] | None:
    """The newest packet job on record for a candidate, with an honest state."""
    from tce.editorial.common import coerce_uuid

    ws = coerce_uuid(workspace_id)
    cid = coerce_uuid(candidate_id)
    job = (await _newest_packet_jobs(session, ws, candidate_ids=[cid])).get(cid)
    if job is None:
        return None
    saved = (await _saved_versions(session, ws, {cid: job})).get(cid)
    view = _packet_request(
        job,
        saved_version=saved,
        park=await capacity_park(session),
        failed_resume=_failed_resume(ws, cid, job.id),
    )
    packet_id = None
    if saved is not None:
        from sqlalchemy import select

        from tce.models.editorial import RecordingPacket

        packet_id = (
            await session.execute(
                select(RecordingPacket.id).where(
                    RecordingPacket.workspace_id == ws,
                    RecordingPacket.candidate_id == cid,
                    RecordingPacket.job_id == job.id,
                    RecordingPacket.version == saved,
                )
            )
        ).scalar_one_or_none()

    return {
        "source": "durable",
        "candidate_id": str(cid),
        "state": view["state"],
        "resumable": view["resumable"],
        "packet_id": str(packet_id) if packet_id is not None else None,
        "current_activity": view["activity"],
        "job_ids": [str(job.id)],
        "job": _job_brief(job),
    }


async def packet_requests(
    session: Any, workspace_id: uuid.UUID | str, candidate_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """What became of the script asked for on each of these ideas, if anything.

    Only ideas whose newest ask is not saved are in the answer. The week, Today
    and the topic read it so a script on its way is never offered again as if
    nothing had been asked (28-Sep: "Prepare the script" said "a few minutes"
    while the worker was parked for two days).
    """
    from tce.editorial.common import coerce_uuid

    ws = coerce_uuid(workspace_id)
    jobs = await _newest_packet_jobs(session, ws, candidate_ids=list(candidate_ids))
    saved = await _saved_versions(session, ws, jobs)
    park = await capacity_park(session) if jobs else None
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for cid, job in jobs.items():
        if cid in saved:
            continue
        view = _packet_request(
            job, saved_version=None, park=park, failed_resume=_failed_resume(ws, cid, job.id)
        )
        if view["request"] is not None:
            out[cid] = view["request"]
    return out


async def unsaved_packet_requests(
    session: Any, workspace_id: uuid.UUID | str, *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Script requests that ended before their job did, for the scheduler tick.

    Each row's `action`:
    - "resume": the job succeeded and nothing saved it. Resuming it replays the
      stored request, which finds the finished job, so the save costs no model call.
    - "waiting": the job is still queued, leased or parked, or a take is being
      recorded on the script it would replace. Left alone; a later tick sees it.
    - "failed": the job failed or was cancelled, or its answer cannot be saved.
      Left as it is: re-queueing a failed job is his call, not the clock's.
    Ideas he took away or rejected are not listed: the ask no longer stands.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from tce.editorial.common import coerce_uuid
    from tce.editorial.packets import RECORDING_IN_PROGRESS_STATUSES
    from tce.llm.queue import utcnow
    from tce.models.editorial import TopicCandidate
    from tce.models.recording_session import RecordingSession

    ws = coerce_uuid(workspace_id)
    now = now or utcnow()
    jobs = await _newest_packet_jobs(session, ws, since=now - timedelta(days=REDRIVE_LOOKBACK_DAYS))
    saved = await _saved_versions(session, ws, jobs)
    jobs = {cid: job for cid, job in jobs.items() if cid not in saved}
    if not jobs:
        return []
    standing = {
        row[0]
        for row in (
            await session.execute(
                select(TopicCandidate.id).where(
                    TopicCandidate.workspace_id == ws,
                    TopicCandidate.id.in_(list(jobs)),
                    TopicCandidate.status.notin_(("rejected", "withdrawn")),
                )
            )
        ).all()
    }
    recording = {
        row[0]
        for row in (
            await session.execute(
                select(RecordingSession.candidate_id).where(
                    RecordingSession.workspace_id == ws,
                    RecordingSession.candidate_id.in_(list(jobs)),
                    RecordingSession.status.in_(RECORDING_IN_PROGRESS_STATUSES),
                )
            )
        ).all()
    }
    park = await capacity_park(session, now=now)
    out: list[dict[str, Any]] = []
    for cid, job in sorted(jobs.items(), key=lambda kv: kv[1].created_at or now):
        if cid not in standing:
            continue
        failed_resume = _failed_resume(ws, cid, job.id)
        view = _packet_request(job, saved_version=None, park=park, failed_resume=failed_resume)
        action = view["action"]
        request = view["request"] or {}
        reason = {
            "queued": "queued for the PC worker",
            "leased": "being written",
            "waiting_capacity": "waiting for capacity",
        }.get(job.status, "")
        if action == "waiting" and request.get("state") == "waiting_capacity":
            reason = "waiting for capacity"
        if action == "resume" and cid in recording:
            # The newest script is what the studio shows; saving a new one now
            # would move the words he is reading out from under the take.
            action, reason = "waiting", "a take is being recorded on this script"
        if action == "failed":
            reason = failed_resume or view["activity"]
        out.append(
            {
                "candidate_id": cid,
                "job_id": job.id,
                "job_status": job.status,
                "retry_at": request.get("retry_at"),
                "error_code": job.error_code,
                "action": action,
                "reason": reason,
            }
        )
    return out


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
