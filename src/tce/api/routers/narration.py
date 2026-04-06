"""Narration endpoints - script generation, audio upload, alignment, rendering."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.narration_script import NarrationScript
from tce.models.post_package import PostPackage
from tce.models.research_brief import ResearchBrief
from tce.models.story_brief import StoryBrief
from tce.models.video_lead_script import VideoLeadScript
from tce.models.video_asset import VideoAsset
from tce.services.render_queue import RenderQueueService
from tce.services.video_render import VideoRenderService
from tce.settings import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/narration", tags=["narration"])


# --- TTS (ElevenLabs) ---


@router.get("/tts-voices")
async def list_tts_voices() -> dict:
    """List available ElevenLabs voices."""
    if not settings.elevenlabs_api_key:
        return {"configured": False, "voices": [], "message": "ElevenLabs API key not configured"}
    from tce.services.tts import TTSService
    svc = TTSService(api_key=settings.elevenlabs_api_key, model=settings.elevenlabs_model)
    try:
        voices = await svc.list_voices()
    except Exception as exc:
        logger.warning("tts.list_voices_failed", error=str(exc)[:200])
        return {"configured": True, "voices": [], "default_voice_id": settings.elevenlabs_voice_id, "message": "Voice listing unavailable - API key may lack voices_read permission. TTS generation still works."}
    return {"configured": True, "voices": voices, "default_voice_id": settings.elevenlabs_voice_id}


class TTSPreviewRequest(BaseModel):
    text: str
    voice_id: str | None = None
    script_id: str | None = None


@router.post("/tts-preview")
async def tts_preview(request: TTSPreviewRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Generate a short TTS audio clip for preview."""
    if not settings.elevenlabs_api_key:
        raise HTTPException(status_code=400, detail="ElevenLabs API key not configured in settings")
    from tce.services.tts import TTSService
    svc = TTSService(api_key=settings.elevenlabs_api_key, model=settings.elevenlabs_model)
    voice_id = request.voice_id or settings.elevenlabs_voice_id
    if not voice_id:
        raise HTTPException(status_code=400, detail="No voice_id provided and no default configured")

    # Truncate preview to first 200 chars
    preview_text = request.text[:200]
    run_id = uuid.uuid4()
    result = await svc.generate(
        segments=[{"narratorText": preview_text}],
        voice_id=voice_id,
        run_id=run_id,
    )

    # Copy to remotion public dir for serving
    remotion_path = settings.remotion_project_path
    if not remotion_path:
        remotion_path = str(Path(__file__).resolve().parents[4] / "remotion")
    audio_dest_dir = Path(remotion_path) / "public" / "audio"
    audio_dest_dir.mkdir(parents=True, exist_ok=True)
    audio_filename = f"tts_preview_{run_id}.mp3"
    audio_dest = audio_dest_dir / audio_filename
    shutil.copy2(result.file_path, str(audio_dest))

    return {
        "audio_url": f"/api/v1/narration/audio/{audio_filename}",
        "duration_seconds": result.duration_seconds,
        "voice_id": voice_id,
        "cost_estimate_usd": result.cost_estimate_usd,
    }


@router.post("/scripts/{script_id}/tts-generate")
async def generate_tts_for_script(
    script_id: str,
    voice_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate full voiceover for all segments in a script using ElevenLabs."""
    if not settings.elevenlabs_api_key:
        raise HTTPException(status_code=400, detail="ElevenLabs API key not configured")
    ns = await db.get(NarrationScript, uuid.UUID(script_id))
    if not ns:
        raise HTTPException(status_code=404, detail="NarrationScript not found")
    if not ns.segments:
        raise HTTPException(status_code=400, detail="Script has no segments")

    from tce.services.tts import TTSService
    svc = TTSService(api_key=settings.elevenlabs_api_key, model=settings.elevenlabs_model)
    vid = voice_id or settings.elevenlabs_voice_id
    if not vid:
        raise HTTPException(status_code=400, detail="No voice_id provided and no default configured")

    run_id = ns.pipeline_run_id or uuid.uuid4()
    result, timed_segments = await svc.generate_with_timestamps(
        segments=ns.segments,
        voice_id=vid,
        run_id=run_id,
    )

    # Copy audio to remotion public
    remotion_path = settings.remotion_project_path
    if not remotion_path:
        remotion_path = str(Path(__file__).resolve().parents[4] / "remotion")
    audio_dest_dir = Path(remotion_path) / "public" / "audio"
    audio_dest_dir.mkdir(parents=True, exist_ok=True)
    audio_filename = f"{script_id}.mp3"
    audio_dest = audio_dest_dir / audio_filename
    shutil.copy2(result.file_path, str(audio_dest))

    # Update script
    ns.audio_file_path = str(audio_dest)
    ns.audio_format = "mp3"
    ns.audio_duration_sec = result.duration_seconds
    ns.segments = timed_segments
    ns.alignment_method = "tts_auto"
    ns.status = "aligned"
    await db.commit()

    return {
        "status": "aligned",
        "audio_url": f"/api/v1/narration/audio/{audio_filename}",
        "duration_seconds": result.duration_seconds,
        "segments": timed_segments,
        "cost_estimate_usd": result.cost_estimate_usd,
        "voice_id": vid,
    }


@router.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Serve audio files from remotion public/audio/."""
    from fastapi.responses import FileResponse
    remotion_path = settings.remotion_project_path
    if not remotion_path:
        remotion_path = str(Path(__file__).resolve().parents[4] / "remotion")
    audio_path = Path(remotion_path) / "public" / "audio" / filename
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(str(audio_path), media_type="audio/mpeg")


def _get_alignment_service():
    from tce.services.audio_alignment import AudioAlignmentService
    return AudioAlignmentService(
        openai_api_key=settings.openai_api_key,
        audio_dir=settings.audio_upload_dir,
    )


def _get_render_service() -> VideoRenderService:
    return VideoRenderService(
        remotion_path=settings.remotion_project_path,
        output_dir=settings.video_output_dir,
        codec=settings.video_default_codec,
        max_render_seconds=settings.video_max_render_seconds,
    )


# --- Auto-generate (get or create) ---


@router.get("/scripts/auto/{package_id}")
async def get_or_create_script(
    package_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the latest script for a package, generating one if none exists.

    This is the Script tab's primary load endpoint - ensures a script
    is always ready without the user clicking Generate.
    """
    pkg = await db.get(PostPackage, uuid.UUID(package_id))
    if not pkg:
        raise HTTPException(status_code=404, detail="PostPackage not found")

    # Check if script already exists
    stmt = (
        select(NarrationScript)
        .where(NarrationScript.package_id == uuid.UUID(package_id))
        .order_by(NarrationScript.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        video_url = None
        if existing.video_asset_id:
            va = await db.get(VideoAsset, existing.video_asset_id)
            if va:
                video_url = va.video_url
        return {
            "id": str(existing.id),
            "package_id": str(existing.package_id) if existing.package_id else None,
            "template_style": existing.template_style,
            "segments": existing.segments,
            "status": existing.status,
            "estimated_duration_sec": existing.estimated_duration_sec,
            "word_count": existing.word_count,
            "audio_file_path": existing.audio_file_path,
            "audio_duration_sec": existing.audio_duration_sec,
            "audio_format": existing.audio_format,
            "video_asset_id": str(existing.video_asset_id) if existing.video_asset_id else None,
            "video_url": video_url,
            "auto_generated": False,
        }

    # No script exists - generate one now
    request = GenerateScriptRequest(package_id=package_id)
    data = await generate_script(request, db)
    data["auto_generated"] = True
    return data


# --- Script Generation ---


class GenerateScriptRequest(BaseModel):
    package_id: str
    style_override: str | None = None


@router.post("/generate-script")
async def generate_script(
    request: GenerateScriptRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate a narration script from a PostPackage."""
    pkg = await db.get(PostPackage, uuid.UUID(request.package_id))
    if not pkg:
        raise HTTPException(status_code=404, detail="PostPackage not found")

    # Build context from package and related models
    context: dict[str, Any] = {}

    # Load StoryBrief via FK
    if pkg.brief_id:
        brief = await db.get(StoryBrief, pkg.brief_id)
        if brief:
            context["story_brief"] = {
                "topic": brief.topic,
                "thesis": brief.thesis,
                "desired_belief_shift": brief.desired_belief_shift,
                "audience": brief.audience,
                "angle_type": brief.angle_type,
                "cta_goal": brief.cta_goal,
            }

    # Load ResearchBrief via FK
    if pkg.research_brief_id:
        rb = await db.get(ResearchBrief, pkg.research_brief_id)
        if rb:
            context["research_brief"] = {
                "topic": rb.topic,
                "verified_claims": rb.verified_claims or [],
                "key_findings": rb.thesis_candidates or [],
                "source_refs": rb.source_refs or [],
                "risk_flags": rb.risk_flags or [],
            }

    # CTA from PostPackage columns
    if pkg.cta_keyword:
        context["cta_keyword"] = pkg.cta_keyword
    if pkg.facebook_post:
        context["facebook_draft"] = {"facebook_post": pkg.facebook_post}
    if pkg.linkedin_post:
        context["linkedin_draft"] = {"linkedin_post": pkg.linkedin_post}

    if request.style_override:
        context["style_override"] = request.style_override

    # Load founder voice profile for script voice matching
    from tce.models.founder_voice_profile import FounderVoiceProfile
    fv_result = await db.execute(
        select(FounderVoiceProfile).order_by(
            FounderVoiceProfile.created_at.desc()
        ).limit(1)
    )
    founder_voice = fv_result.scalar_one_or_none()
    if founder_voice:
        context["founder_voice"] = {
            "recurring_themes": founder_voice.recurring_themes or [],
            "values_and_beliefs": founder_voice.values_and_beliefs or [],
            "taboos": founder_voice.taboos or [],
            "tone_range": founder_voice.tone_range or {},
            "humor_type": founder_voice.humor_type,
            "metaphor_families": founder_voice.metaphor_families or [],
        }

    # Run ScriptAgent
    from tce.agents.script_agent import ScriptAgent
    from tce.services.cost_tracker import CostTracker
    from tce.services.prompt_manager import PromptManager

    cost_tracker = CostTracker(db)
    prompt_manager = PromptManager(db)
    run_id = uuid.uuid4()

    agent = ScriptAgent(
        db=db,
        settings=settings,
        cost_tracker=cost_tracker,
        prompt_manager=prompt_manager,
        run_id=run_id,
    )
    result = await agent.run(context)
    script_data = result.get("narration_script", {})

    # Save to DB
    ns = NarrationScript(
        package_id=pkg.id,
        template_style=script_data.get("template_style", "hook_cta"),
        segments=script_data.get("segments"),
        status="ready_to_record",
        estimated_duration_sec=script_data.get("estimated_duration_sec"),
        word_count=script_data.get("word_count"),
        pipeline_run_id=run_id,
    )
    db.add(ns)
    await db.commit()
    await db.refresh(ns)

    return {
        "id": str(ns.id),
        "template_style": ns.template_style,
        "segments": ns.segments,
        "status": ns.status,
        "estimated_duration_sec": ns.estimated_duration_sec,
        "word_count": ns.word_count,
    }


@router.post("/generate-video-lead")
async def generate_video_lead_from_package(
    request: GenerateScriptRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate a TJ-style video lead script from a PostPackage."""
    pkg = await db.get(PostPackage, uuid.UUID(request.package_id))
    if not pkg:
        raise HTTPException(status_code=404, detail="PostPackage not found")

    context: dict[str, Any] = {"niche": "coaching", "cta_url": "https://kivimedia.co/30"}

    if pkg.brief_id:
        brief = await db.get(StoryBrief, pkg.brief_id)
        if brief:
            context["story_brief"] = {
                "topic": brief.topic,
                "thesis": brief.thesis,
                "desired_belief_shift": brief.desired_belief_shift,
                "audience": brief.audience,
                "angle_type": brief.angle_type,
                "cta_goal": brief.cta_goal,
            }

    if pkg.research_brief_id:
        rb = await db.get(ResearchBrief, pkg.research_brief_id)
        if rb:
            context["research_brief"] = {
                "topic": rb.topic,
                "verified_claims": rb.verified_claims or [],
                "key_findings": rb.thesis_candidates or [],
                "source_refs": rb.source_refs or [],
            }

    # Founder voice
    from tce.models.founder_voice_profile import FounderVoiceProfile
    fv_result = await db.execute(
        select(FounderVoiceProfile).order_by(
            FounderVoiceProfile.created_at.desc()
        ).limit(1)
    )
    fv = fv_result.scalar_one_or_none()
    if fv:
        context["voice_profile"] = {
            "recurring_themes": fv.recurring_themes or [],
            "values_and_beliefs": fv.values_and_beliefs or [],
            "taboos": fv.taboos or [],
            "tone_range": fv.tone_range or {},
            "metaphor_style": ", ".join(fv.metaphor_families or []),
        }

    from tce.agents.video_lead_writer import VideoLeadWriter
    from tce.services.cost_tracker import CostTracker
    from tce.services.prompt_manager import PromptManager

    cost_tracker = CostTracker(db)
    prompt_manager = PromptManager(db)
    run_id = uuid.uuid4()

    agent = VideoLeadWriter(
        db=db,
        settings=settings,
        cost_tracker=cost_tracker,
        prompt_manager=prompt_manager,
        run_id=run_id,
    )
    result = await agent.run(context)
    vls_data = result.get("video_lead_script") or {}

    story = context.get("story_brief", {})
    vls = VideoLeadScript(
        title=vls_data.get("title", "Untitled"),
        title_pattern=vls_data.get("title_pattern"),
        hook=vls_data.get("hook"),
        full_script=vls_data.get("full_script"),
        sections=vls_data.get("sections"),
        word_count=vls_data.get("word_count"),
        estimated_duration_minutes=vls_data.get("estimated_duration_minutes"),
        target_audience=vls_data.get("target_audience"),
        key_takeaway=vls_data.get("key_takeaway"),
        niche="coaching",
        seo_description=vls_data.get("seo_description"),
        tags=vls_data.get("tags"),
        blog_repurpose_outline=vls_data.get("blog_repurpose_outline"),
        pipeline_run_id=run_id,
        topic=story.get("topic"),
        thesis=story.get("thesis"),
    )
    db.add(vls)
    await db.commit()
    await db.refresh(vls)

    return {
        "id": str(vls.id),
        "title": vls.title,
        "full_script": vls.full_script,
        "sections": vls.sections,
        "word_count": vls.word_count,
        "estimated_duration_minutes": vls.estimated_duration_minutes,
        "target_audience": vls.target_audience,
        "seo_description": vls.seo_description,
        "tags": vls.tags,
        "blog_repurpose_outline": vls.blog_repurpose_outline,
        "hook": vls.hook,
        "key_takeaway": vls.key_takeaway,
    }


# --- CRUD ---


@router.get("/scripts")
async def list_scripts(
    package_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List narration scripts with optional filters."""
    stmt = select(NarrationScript).order_by(NarrationScript.created_at.desc()).limit(limit)

    if package_id:
        stmt = stmt.where(NarrationScript.package_id == uuid.UUID(package_id))
    if status:
        stmt = stmt.where(NarrationScript.status == status)

    result = await db.execute(stmt)
    scripts = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "package_id": str(s.package_id) if s.package_id else None,
            "template_style": s.template_style,
            "status": s.status,
            "estimated_duration_sec": s.estimated_duration_sec,
            "audio_duration_sec": s.audio_duration_sec,
            "word_count": s.word_count,
            "segment_count": len(s.segments) if s.segments else 0,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in scripts
    ]


@router.get("/scripts/{script_id}")
async def get_script(
    script_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a narration script with full segment data."""
    ns = await db.get(NarrationScript, uuid.UUID(script_id))
    if not ns:
        raise HTTPException(status_code=404, detail="NarrationScript not found")

    # Resolve video_url from VideoAsset if rendered
    video_url = None
    if ns.video_asset_id:
        va = await db.get(VideoAsset, ns.video_asset_id)
        if va:
            video_url = va.video_url

    return {
        "id": str(ns.id),
        "package_id": str(ns.package_id) if ns.package_id else None,
        "template_style": ns.template_style,
        "segments": ns.segments,
        "status": ns.status,
        "audio_file_path": ns.audio_file_path,
        "audio_duration_sec": ns.audio_duration_sec,
        "audio_format": ns.audio_format,
        "alignment_method": ns.alignment_method,
        "estimated_duration_sec": ns.estimated_duration_sec,
        "word_count": ns.word_count,
        "video_asset_id": str(ns.video_asset_id) if ns.video_asset_id else None,
        "video_url": video_url,
        "pipeline_run_id": str(ns.pipeline_run_id) if ns.pipeline_run_id else None,
        "created_at": ns.created_at.isoformat() if ns.created_at else None,
    }


class UpdateScriptRequest(BaseModel):
    segments: list[dict[str, Any]] | None = None


@router.patch("/scripts/{script_id}")
async def update_script(
    script_id: str,
    request: UpdateScriptRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Edit script segments (e.g. narrator text before recording)."""
    ns = await db.get(NarrationScript, uuid.UUID(script_id))
    if not ns:
        raise HTTPException(status_code=404, detail="NarrationScript not found")

    if request.segments is not None:
        ns.segments = request.segments
        # Recalculate word count
        total_words = sum(
            len(seg.get("narratorText", "").split()) for seg in request.segments
        )
        ns.word_count = total_words
        ns.estimated_duration_sec = round(total_words / 2.5, 1)
        # If segments are edited after alignment, reset to re-record/re-align
        if ns.status in ("aligned", "rendered"):
            ns.status = "ready_to_record"

    await db.commit()
    return {"status": "updated"}


# --- Audio Upload ---


@router.post("/scripts/{script_id}/upload-audio")
async def upload_audio(
    script_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upload WAV/MP3 audio recording for a script."""
    ns = await db.get(NarrationScript, uuid.UUID(script_id))
    if not ns:
        raise HTTPException(status_code=404, detail="NarrationScript not found")

    # Validate file type
    ext = Path(file.filename or "audio.wav").suffix.lower()
    if ext not in (".wav", ".mp3", ".m4a", ".ogg"):
        raise HTTPException(status_code=400, detail=f"Unsupported audio format: {ext}")

    # Save to disk
    audio_dir = Path(settings.audio_upload_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"{script_id}{ext}"

    with open(audio_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Detect duration
    svc = _get_alignment_service()
    try:
        duration = await svc.detect_duration(str(audio_path))
    except Exception as exc:
        logger.warning("audio.duration_detection_failed", error=str(exc)[:200])
        duration = None

    # Update script
    ns.audio_file_path = str(audio_path)
    ns.audio_format = ext.lstrip(".")
    ns.audio_duration_sec = duration
    ns.status = "audio_uploaded"
    await db.commit()

    return {
        "status": "audio_uploaded",
        "audio_path": str(audio_path),
        "audio_duration_sec": duration,
        "audio_format": ext.lstrip("."),
    }


# --- Whisper Alignment ---


@router.post("/scripts/{script_id}/align")
async def align_script(
    script_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run Whisper alignment on the uploaded audio."""
    ns = await db.get(NarrationScript, uuid.UUID(script_id))
    if not ns:
        raise HTTPException(status_code=404, detail="NarrationScript not found")

    if not ns.audio_file_path:
        raise HTTPException(status_code=400, detail="No audio uploaded. Upload audio first.")

    if not ns.segments:
        raise HTTPException(status_code=400, detail="No segments in script.")

    svc = _get_alignment_service()

    aligned_segments, whisper_result = await svc.align_script(
        ns.audio_file_path, ns.segments
    )

    # Audio cleanup: remove fillers, tighten gaps, best-take selection
    cleanup_applied = False
    try:
        from tce.services.audio_cleanup import AudioCleanupService
        cleanup_svc = AudioCleanupService()
        cleaned_path, cleaned_segments = await cleanup_svc.clean_audio(
            ns.audio_file_path, whisper_result, aligned_segments,
        )
        if cleaned_path != ns.audio_file_path:
            # Re-align on cleaned audio (timestamps shifted after cuts)
            aligned_segments, whisper_result = await svc.align_script(
                cleaned_path, cleaned_segments
            )
            ns.audio_file_path = cleaned_path
            cleanup_applied = True
            logger.info("narration.align.cleanup_applied", script_id=script_id)
    except Exception as exc:
        logger.warning("narration.align.cleanup_failed", error=str(exc)[:200])

    ns.segments = aligned_segments
    ns.whisper_transcript = whisper_result
    ns.alignment_method = "whisper_auto"
    ns.status = "aligned"

    # Update audio duration from Whisper if not set
    if not ns.audio_duration_sec and whisper_result.get("duration"):
        ns.audio_duration_sec = whisper_result["duration"]

    await db.commit()

    return {
        "status": "aligned",
        "segments": aligned_segments,
        "whisper_duration": whisper_result.get("duration"),
        "whisper_word_count": len(whisper_result.get("words", [])),
        "audio_cleaned": cleanup_applied,
    }


# --- Manual Timestamp Adjustment ---


class SegmentTimingUpdate(BaseModel):
    segments: list[dict[str, Any]]


@router.patch("/scripts/{script_id}/segments")
async def update_segment_timing(
    script_id: str,
    request: SegmentTimingUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Manual timestamp adjustment for segments."""
    ns = await db.get(NarrationScript, uuid.UUID(script_id))
    if not ns:
        raise HTTPException(status_code=404, detail="NarrationScript not found")

    ns.segments = request.segments
    ns.alignment_method = "manual"
    if ns.status in ("audio_uploaded", "aligned"):
        ns.status = "aligned"
    await db.commit()

    return {"status": "updated"}


# --- Render ---


@router.post("/scripts/{script_id}/render")
async def render_narrated_video(
    script_id: str,
    resolution: str = "reel",
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Enqueue a narrated video render from an aligned script."""
    ns = await db.get(NarrationScript, uuid.UUID(script_id))
    if not ns:
        raise HTTPException(status_code=404, detail="NarrationScript not found")

    if ns.status not in ("aligned", "rendered"):
        raise HTTPException(
            status_code=400,
            detail=f"Script must be aligned before rendering. Current status: {ns.status}",
        )

    if not ns.audio_file_path or not ns.segments:
        raise HTTPException(status_code=400, detail="Missing audio or segments.")

    # Copy audio to remotion/public/audio/ for staticFile() access
    remotion_path = settings.remotion_project_path
    if not remotion_path:
        remotion_path = str(Path(__file__).resolve().parents[4] / "remotion")

    audio_dest_dir = Path(remotion_path) / "public" / "audio"
    audio_dest_dir.mkdir(parents=True, exist_ok=True)

    audio_ext = ns.audio_format or "wav"
    audio_filename = f"{script_id}.{audio_ext}"
    audio_dest = audio_dest_dir / audio_filename

    audio_src = Path(ns.audio_file_path)
    if not audio_src.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Audio file not found at {ns.audio_file_path}. Re-upload audio.",
        )
    shutil.copy2(str(audio_src), str(audio_dest))

    # Build props
    template_map = {
        "reel": "narrated_video",
        "square": "narrated_video_square",
        "landscape": "narrated_video_landscape",
    }
    if resolution not in template_map:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resolution '{resolution}'. Use: {list(template_map.keys())}",
        )
    template_name = template_map[resolution]

    props = {
        "audioUrl": f"audio/{audio_filename}",
        "segments": ns.segments,
        "ctaText": "zivraviv.com",
    }

    # Enqueue render
    svc = RenderQueueService(_get_render_service(), db)
    job = await svc.enqueue(
        template_name=template_name,
        props=props,
        package_id=ns.package_id,
        pipeline_run_id=ns.pipeline_run_id,
    )

    # Process in background
    async def _process() -> None:
        try:
            from tce.db.session import async_session

            async with async_session() as bg_db:
                bg_svc = RenderQueueService(_get_render_service(), bg_db)
                result_job = await bg_svc.process_job(job.id)

                # Link video asset to narration script
                if result_job and result_job.video_asset_id:
                    script = await bg_db.get(NarrationScript, uuid.UUID(script_id))
                    if script:
                        script.video_asset_id = result_job.video_asset_id
                        script.status = "rendered"
                        await bg_db.commit()
        except Exception:
            logger.exception("narration.render.background_failed", script_id=script_id)

    import asyncio
    asyncio.create_task(_process())

    return {
        "job_id": str(job.id),
        "template_name": template_name,
        "status": "queued",
        "audio_url": f"audio/{audio_filename}",
    }
