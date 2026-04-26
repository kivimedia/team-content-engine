"""CRUD routes for Video Studio scripts (walking + talking-head).

Unified list endpoint so the Video Studio "Library" pill can show both
walking_video_scripts and video_lead_scripts in one feed. Detail + status
updates are type-aware via the `kind` path segment.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.video_lead_script import VideoLeadScript
from tce.models.walking_video_script import WalkingVideoScript
from tce.settings import settings

router = APIRouter(prefix="/video-scripts", tags=["video-scripts"])

# Destination is hardcoded so this endpoint cannot be used as an open relay.
# If we ever need more recipients, move to an allowlist (never free-form input).
_EMAIL_RECIPIENT = "ravivziv@gmail.com"


class ScriptStatusUpdate(BaseModel):
    # Any subset of these can be patched in one call. Status remains required
    # where it used to be; other fields are optional so the frontend can send
    # just operator_feedback or just full_script without a status change.
    status: str | None = None  # draft | approved | recorded | edited | published | rejected | archived
    video_file_path: str | None = None  # raw recording URL/path (set when marking recorded)
    edited_video_file_path: str | None = None  # CutSense output URL/path (set when marking edited)
    full_script: str | None = None  # inline edit target
    operator_feedback: str | None = None  # revision notes / "tune next time"
    hook: str | None = None  # inline hook edit


def _walking_to_card(row: WalkingVideoScript) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": "walking",
        "title": row.title,
        "hook": row.hook,
        "status": row.status,
        "topic": row.topic,
        "word_count": row.word_count,
        "estimated_duration_seconds": row.estimated_duration_seconds,
        "duration_target_seconds": row.duration_target_seconds,
        "niche": row.niche,
        "hook_formula": row.hook_formula,
        "format_label": row.format_label,
        "creator_profile_id": str(row.creator_profile_id) if row.creator_profile_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _talking_to_card(row: VideoLeadScript) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": "talking_head",
        "title": row.title,
        "hook": row.hook,
        "status": row.status,
        "topic": row.topic,
        "word_count": row.word_count,
        "estimated_duration_seconds": int((row.estimated_duration_minutes or 0) * 60) or None,
        "duration_target_seconds": None,
        "niche": row.niche,
        "hook_formula": None,
        "format_label": "talking_head",
        "creator_profile_id": None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
async def list_video_scripts(
    kind: str | None = None,  # "walking" | "talking_head" | None (both)
    status: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List scripts from both tables. kind filters the source table."""
    limit = max(1, min(limit, 500))
    cards: list[dict[str, Any]] = []

    if kind in (None, "walking"):
        q = select(WalkingVideoScript).order_by(WalkingVideoScript.created_at.desc()).limit(limit)
        if status:
            q = q.where(WalkingVideoScript.status == status)
        result = await db.execute(q)
        cards.extend(_walking_to_card(r) for r in result.scalars().all())

    if kind in (None, "talking_head"):
        q = select(VideoLeadScript).order_by(VideoLeadScript.created_at.desc()).limit(limit)
        if status:
            q = q.where(VideoLeadScript.status == status)
        result = await db.execute(q)
        cards.extend(_talking_to_card(r) for r in result.scalars().all())

    cards.sort(key=lambda c: c.get("created_at") or "", reverse=True)
    return cards[:limit]


@router.get("/walking/{script_id}")
async def get_walking_script(
    script_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(WalkingVideoScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Walking-video script not found")
    return {
        **_walking_to_card(row),
        "full_script": row.full_script,
        "shot_notes": row.shot_notes or {},
        "cutsense_prompt": row.cutsense_prompt,
        "thesis": row.thesis,
        "target_audience": row.target_audience,
        "seo_description": row.seo_description,
        "tags": row.tags or [],
        "repurpose": row.repurpose or {},
        "operator_feedback": row.operator_feedback,
        "personal_anchor": row.personal_anchor,
        "strategic_justification": row.strategic_justification,
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        "video_file_path": row.video_file_path,
        "edited_video_file_path": row.edited_video_file_path,
        "pipeline_run_id": str(row.pipeline_run_id) if row.pipeline_run_id else None,
    }


@router.get("/talking_head/{script_id}")
async def get_talking_head_script(
    script_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(VideoLeadScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Talking-head script not found")
    return {
        **_talking_to_card(row),
        "full_script": row.full_script,
        "sections": row.sections or [],
        "title_pattern": row.title_pattern,
        "target_audience": row.target_audience,
        "key_takeaway": row.key_takeaway,
        "seo_description": row.seo_description,
        "tags": row.tags or [],
        "blog_repurpose_outline": row.blog_repurpose_outline,
        "pipeline_run_id": str(row.pipeline_run_id) if row.pipeline_run_id else None,
    }


@router.patch("/walking/{script_id}")
async def update_walking_script(
    script_id: uuid.UUID,
    data: ScriptStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(WalkingVideoScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Walking-video script not found")
    # Apply only fields the caller actually sent.
    if data.status is not None:
        valid = {"draft", "approved", "recorded", "edited", "published", "rejected", "archived"}
        if data.status not in valid:
            raise HTTPException(status_code=400, detail=f"Invalid status; must be one of {sorted(valid)}")
        row.status = data.status
        if data.status == "recorded":
            row.recorded_at = datetime.utcnow()
    if data.video_file_path is not None:
        row.video_file_path = data.video_file_path
    if data.edited_video_file_path is not None:
        row.edited_video_file_path = data.edited_video_file_path
    if data.full_script is not None:
        row.full_script = data.full_script
        # Recompute word count so library card + estimated duration stay honest
        wc = len(data.full_script.split()) if data.full_script.strip() else 0
        row.word_count = wc
        row.estimated_duration_seconds = int(wc * 60 / 140) if wc else row.estimated_duration_seconds
    if data.hook is not None:
        row.hook = data.hook
    if data.operator_feedback is not None:
        row.operator_feedback = data.operator_feedback
    await db.commit()
    await db.refresh(row)
    return _walking_to_card(row)


def _format_email_subject(title: str | None) -> str:
    return f"[Video Script] {title or 'Untitled'}"


def _format_email_body(script: dict[str, Any]) -> str:
    """Mirror the frontend compose-URL body so operator sees the same shape."""
    lines: list[str] = []
    lines.append(script.get("hook") or "")
    lines.append("")
    lines.append("---")
    lines.append((script.get("full_script") or "").strip())
    lines.append("")
    lines.append("---")
    lines.append(f"Shot notes: {json.dumps(script.get('shot_notes') or {}, indent=2)}")
    if script.get("cutsense_prompt"):
        lines.append("")
        lines.append(f"CutSense prompt: {script['cutsense_prompt']}")
    lines.append("")
    dur = script.get("estimated_duration_seconds") or "?"
    wc = script.get("word_count") or "?"
    niche = script.get("niche") or "?"
    lines.append(f"Duration: {dur}s | Words: {wc} | Niche: {niche}")
    if script.get("topic"):
        lines.append(f"Topic: {script['topic']}")
    if script.get("thesis"):
        lines.append(f"Thesis: {script['thesis']}")
    return "\n".join(lines)


async def _send_via_gws(subject: str, body: str) -> dict[str, Any]:
    """Invoke the `gws` CLI to deliver mail via the Gmail API.

    Auth comes from ~/.config/gws/ on the VPS (credentials copied from local
    install). Recipient is fixed to _EMAIL_RECIPIENT - do not accept
    caller-supplied recipients. Uses argv (create_subprocess_exec, not shell),
    so subject/body cannot be injected.
    """
    proc = await asyncio.create_subprocess_exec(
        "gws", "gmail", "+send",
        "--to", _EMAIL_RECIPIENT,
        "--subject", subject,
        "--body", body,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(status_code=504, detail="gws send timed out after 30s")
    if proc.returncode != 0:
        err = (stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace")).strip()
        raise HTTPException(status_code=502, detail=f"gws send failed: {err[:500]}")
    text = stdout.decode("utf-8", errors="replace")
    try:
        start = text.find("{")
        parsed = json.loads(text[start:]) if start >= 0 else {}
        return {
            "ok": True,
            "gmail_message_id": parsed.get("id"),
            "thread_id": parsed.get("threadId"),
            "to": _EMAIL_RECIPIENT,
        }
    except json.JSONDecodeError:
        return {"ok": True, "to": _EMAIL_RECIPIENT, "raw": text[:500]}


_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
_MAX_UPLOAD_BYTES = 3_000_000_000  # 3 GB hard cap per upload (single-shot path; chunked uploads use /api/v1/uploads/* which has its own cap)


async def _save_upload(upload: UploadFile, dest: Path) -> int:
    """Stream the upload to disk. Returns bytes written. Enforces size cap."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with dest.open("wb") as out:
        while True:
            chunk = await upload.read(1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Upload exceeds {_MAX_UPLOAD_BYTES // 1_000_000} MB")
            out.write(chunk)
    return written


def _resolve_ext(upload: UploadFile) -> str:
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in _VIDEO_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported video extension {ext!r}; expected one of {sorted(_VIDEO_EXTS)}")
    return ext


@router.post("/walking/{script_id}/upload-raw")
async def upload_walking_raw(
    script_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Accept the raw recording from the operator, store on disk, set
    video_file_path + status=recorded. URL is served by the /media mount."""
    row = await db.get(WalkingVideoScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Walking-video script not found")
    ext = _resolve_ext(file)
    out_path = Path(settings.video_output_dir) / "walking_scripts" / str(script_id) / f"raw{ext}"
    bytes_written = await _save_upload(file, out_path)
    row.video_file_path = f"/media/walking_scripts/{script_id}/raw{ext}"
    row.status = "recorded"
    row.recorded_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return {
        **_walking_to_card(row),
        "video_file_path": row.video_file_path,
        "edited_video_file_path": row.edited_video_file_path,
        "bytes_written": bytes_written,
    }


@router.post("/walking/{script_id}/upload-edited")
async def upload_walking_edited(
    script_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Accept the CutSense-edited video, store on disk, set
    edited_video_file_path + status=edited."""
    row = await db.get(WalkingVideoScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Walking-video script not found")
    ext = _resolve_ext(file)
    out_path = Path(settings.video_output_dir) / "walking_scripts" / str(script_id) / f"edited{ext}"
    bytes_written = await _save_upload(file, out_path)
    row.edited_video_file_path = f"/media/walking_scripts/{script_id}/edited{ext}"
    row.status = "edited"
    await db.commit()
    await db.refresh(row)
    return {
        **_walking_to_card(row),
        "video_file_path": row.video_file_path,
        "edited_video_file_path": row.edited_video_file_path,
        "bytes_written": bytes_written,
    }


@router.post("/walking/{script_id}/email")
async def email_walking_script(
    script_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(WalkingVideoScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Walking-video script not found")
    payload = {
        **_walking_to_card(row),
        "full_script": row.full_script,
        "shot_notes": row.shot_notes or {},
        "cutsense_prompt": row.cutsense_prompt,
        "thesis": row.thesis,
    }
    return await _send_via_gws(_format_email_subject(row.title), _format_email_body(payload))


@router.post("/talking_head/{script_id}/email")
async def email_talking_head_script(
    script_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(VideoLeadScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Talking-head script not found")
    payload = {
        **_talking_to_card(row),
        "full_script": row.full_script,
    }
    return await _send_via_gws(_format_email_subject(row.title), _format_email_body(payload))


# ─────────────────────────────────────────────────────────────────────────────
# Weekly walking-video pipeline endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/walking/weekly/{weekly_plan_id}/recording")
async def get_weekly_recording(
    weekly_plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the current WeeklyWalkingRecording row for this week (for dashboard polling)."""
    from tce.models.weekly_walking_recording import WeeklyWalkingRecording
    result = await db.execute(
        select(WeeklyWalkingRecording).where(WeeklyWalkingRecording.weekly_plan_id == weekly_plan_id)
    )
    recording = result.scalar_one_or_none()
    if not recording:
        raise HTTPException(status_code=404, detail="No recording for this week")
    return {
        "recording_id": str(recording.id),
        "weekly_plan_id": str(recording.weekly_plan_id),
        "status": recording.status,
        "error_message": recording.error_message,
        "cutsense_jobs": recording.cutsense_jobs or {},
        "pipeline_run_id": str(recording.pipeline_run_id) if recording.pipeline_run_id else None,
        "transcript_ready": recording.transcript_json is not None,
        "alignment_ready": recording.alignment_json is not None,
    }


@router.get("/walking/weekly/{weekly_plan_id}/export-docx")
async def export_weekly_scripts_docx(
    weekly_plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return a single DOCX bundling all 5 approved walking scripts for the week.

    Scripts are fetched via ContentCalendarEntry.weekly_plan_id join,
    ordered by calendar date (day 1 first). Disabled until all 5 have status=approved.
    """
    from fastapi.responses import StreamingResponse
    from tce.models.content_calendar import ContentCalendarEntry
    from tce.utils.docx import build_weekly_scripts_docx

    # Pull calendar entries for this week that have linked walking scripts
    entries_result = await db.execute(
        select(ContentCalendarEntry)
        .where(
            ContentCalendarEntry.weekly_plan_id == weekly_plan_id,
            ContentCalendarEntry.walking_video_script_id.isnot(None),
        )
        .order_by(ContentCalendarEntry.date)
    )
    entries = entries_result.scalars().all()

    if not entries:
        raise HTTPException(status_code=404, detail="No walking-video scripts found for this weekly plan")

    script_ids = [e.walking_video_script_id for e in entries if e.walking_video_script_id]
    scripts_result = await db.execute(
        select(WalkingVideoScript).where(WalkingVideoScript.id.in_(script_ids))
    )
    scripts_by_id = {s.id: s for s in scripts_result.scalars().all()}

    # Preserve calendar order
    scripts = [scripts_by_id[e.walking_video_script_id] for e in entries if e.walking_video_script_id in scripts_by_id]

    EXPORTABLE = {"draft", "approved", "recorded", "edited", "published"}
    not_approved = [s.title for s in scripts if s.status not in EXPORTABLE]
    if not_approved:
        raise HTTPException(
            status_code=400,
            detail=f"Scripts not yet approved: {not_approved}. Approve all scripts before exporting.",
        )

    docx_bytes = build_weekly_scripts_docx(scripts)

    return StreamingResponse(
        iter([docx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=\"week_{weekly_plan_id}_scripts.docx\""},
    )


@router.post("/walking/weekly/{weekly_plan_id}/upload-recording")
async def upload_weekly_recording(
    weekly_plan_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Accept the single long walking video for the whole week.

    Creates (or replaces) the WeeklyWalkingRecording row for this week,
    stores the file at {video_output_dir}/weekly_recordings/{weekly_plan_id}/raw{ext}.
    """
    from datetime import timezone
    from tce.models.weekly_walking_recording import WeeklyWalkingRecording

    ext = _resolve_ext(file)
    out_path = Path(settings.video_output_dir) / "weekly_recordings" / str(weekly_plan_id) / f"raw{ext}"
    bytes_written = await _save_upload(file, out_path)

    # Upsert: if a recording already exists for this week, replace it
    existing_result = await db.execute(
        select(WeeklyWalkingRecording).where(WeeklyWalkingRecording.weekly_plan_id == weekly_plan_id)
    )
    recording = existing_result.scalar_one_or_none()

    if recording:
        recording.long_video_path = str(out_path)
        recording.status = "uploaded"
        recording.transcript_json = None
        recording.alignment_json = None
        recording.cutsense_jobs = None
        recording.error_message = None
        recording.updated_at = datetime.now(tz=timezone.utc)
    else:
        recording = WeeklyWalkingRecording(
            weekly_plan_id=weekly_plan_id,
            long_video_path=str(out_path),
            status="uploaded",
        )
        db.add(recording)

    await db.commit()
    await db.refresh(recording)

    return {
        "recording_id": str(recording.id),
        "weekly_plan_id": str(weekly_plan_id),
        "status": recording.status,
        "long_video_path": recording.long_video_path,
        "bytes_written": bytes_written,
    }


@router.post("/walking/weekly/{weekly_plan_id}/run-split-edit")
async def run_weekly_split_edit(
    weekly_plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Kick off the weekly walking-video split-and-edit pipeline.

    Requires a WeeklyWalkingRecording with status=uploaded.
    Returns 202 with pipeline_run_id immediately; pipeline runs async.
    """
    import asyncio
    from tce.models.weekly_walking_recording import WeeklyWalkingRecording

    if not settings.weekly_walking_pipeline:
        raise HTTPException(status_code=403, detail="Weekly walking pipeline is not enabled (TCE_WEEKLY_WALKING_PIPELINE=1)")

    recording_result = await db.execute(
        select(WeeklyWalkingRecording).where(WeeklyWalkingRecording.weekly_plan_id == weekly_plan_id)
    )
    recording = recording_result.scalar_one_or_none()

    if not recording:
        raise HTTPException(status_code=404, detail="No recording found for this week. Upload a video first.")
    if not recording.long_video_path:
        raise HTTPException(status_code=400, detail="Recording has no video path set")

    # Resolve calendar entries to get script IDs in day order
    from tce.models.content_calendar import ContentCalendarEntry
    entries_result = await db.execute(
        select(ContentCalendarEntry)
        .where(
            ContentCalendarEntry.weekly_plan_id == weekly_plan_id,
            ContentCalendarEntry.walking_video_script_id.isnot(None),
        )
        .order_by(ContentCalendarEntry.date)
    )
    entries = entries_result.scalars().all()
    script_ids = [str(e.walking_video_script_id) for e in entries if e.walking_video_script_id]

    # Import pipeline machinery
    from tce.db.session import async_session
    from tce.models.pipeline_run import PipelineRun
    from tce.orchestrator.engine import PipelineOrchestrator
    from tce.orchestrator.workflows import WORKFLOWS
    from tce.services.cost_tracker import CostTracker
    from tce.services.prompt_manager import PromptManager

    pipeline_run_id = uuid.uuid4()
    run_record = PipelineRun(
        id=pipeline_run_id,
        workflow="weekly_walking_split_edit",
        status="running",
        context={"recording_id": str(recording.id), "weekly_plan_id": str(weekly_plan_id), "script_ids": script_ids},
    )
    db.add(run_record)
    recording.pipeline_run_id = pipeline_run_id
    await db.commit()

    steps = WORKFLOWS["weekly_walking_split_edit"]

    async def _run() -> None:
        async with async_session() as bk_db:
            try:
                cost_tracker = CostTracker()
                prompt_manager = PromptManager(bk_db)
                orchestrator = PipelineOrchestrator(
                    steps=steps,
                    db=bk_db,
                    settings=settings,
                    cost_tracker=cost_tracker,
                    prompt_manager=prompt_manager,
                    run_id=pipeline_run_id,
                )
                initial_ctx = {"recording_id": str(recording.id), "weekly_plan_id": str(weekly_plan_id), "script_ids": script_ids}
                result = await orchestrator.run(initial_ctx)
                run_rec = await bk_db.get(PipelineRun, pipeline_run_id)
                if run_rec:
                    run_rec.status = "failed" if result.get("has_failures") else "completed"
                    from datetime import timezone
                    run_rec.completed_at = datetime.now(tz=timezone.utc)
                    await bk_db.commit()
            except Exception as exc:
                try:
                    run_rec = await bk_db.get(PipelineRun, pipeline_run_id)
                    if run_rec:
                        run_rec.status = "failed"
                        run_rec.error_message = str(exc)
                        from datetime import timezone
                        run_rec.completed_at = datetime.now(tz=timezone.utc)
                        await bk_db.commit()
                except Exception:
                    pass

    asyncio.create_task(_run())

    return {
        "pipeline_run_id": str(pipeline_run_id),
        "recording_id": str(recording.id),
        "weekly_plan_id": str(weekly_plan_id),
        "status": "started",
    }


@router.get("/cutsense-proxy/jobs/{job_id}/status")
async def cutsense_job_status_proxy(job_id: str) -> dict[str, Any]:
    """Proxy CutSense GET /jobs/:id/status so the browser doesn't need to reach localhost:8300.

    Returns the raw CutSense status payload or a synthetic {state: 'not_found'} on error.
    """
    import aiohttp
    api_url = settings.cutsense_api_url
    service_key = settings.cutsense_service_key
    headers: dict[str, str] = {}
    if service_key:
        headers["X-Service-Key"] = service_key
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{api_url}/jobs/{job_id}/status",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 404:
                    return {"job_id": job_id, "state": "not_found"}
                return await resp.json()
    except Exception:
        return {"job_id": job_id, "state": "unreachable"}


@router.patch("/talking_head/{script_id}")
async def update_talking_head_script(
    script_id: uuid.UUID,
    data: ScriptStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(VideoLeadScript, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="Talking-head script not found")
    valid = {"draft", "approved", "recorded", "repurposed", "rejected"}
    if data.status not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid status; must be one of {sorted(valid)}")
    row.status = data.status
    await db.commit()
    await db.refresh(row)
    return _talking_to_card(row)
