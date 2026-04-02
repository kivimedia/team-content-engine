"""Video asset endpoints - generate, list, manage, SSE progress, batch rendering."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.render_queue import RenderQueueJob
from tce.models.video_asset import VideoAsset
from tce.models.post_package import PostPackage
from tce.orchestrator.engine import PipelineOrchestrator
from tce.orchestrator.workflows import WORKFLOWS
from tce.services.render_queue import RenderQueueService
from tce.services.video_render import VideoRenderService
from tce.settings import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/videos", tags=["videos"])


def _get_render_service() -> VideoRenderService:
    return VideoRenderService(
        remotion_path=settings.remotion_project_path,
        output_dir=settings.video_output_dir,
        codec=settings.video_default_codec,
        max_render_seconds=settings.video_max_render_seconds,
    )


class VideoGenerateRequest(BaseModel):
    post_package_id: str | None = None
    context: dict[str, Any] = {}


@router.post("/generate")
async def generate_videos(
    request: VideoGenerateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate videos for a post package or from raw context.

    If post_package_id is provided, loads context from the package.
    Otherwise uses the provided context dict directly.
    """
    context: dict[str, Any] = dict(request.context)

    if request.post_package_id:
        pkg = await db.get(PostPackage, uuid.UUID(request.post_package_id))
        if not pkg:
            raise HTTPException(status_code=404, detail="PostPackage not found")

        # Build context from package fields
        if pkg.story_brief:
            context.setdefault("story_brief", pkg.story_brief)
        if pkg.research_brief:
            context.setdefault("research_brief", pkg.research_brief)
        if pkg.cta_package:
            cta = pkg.cta_package
            context.setdefault("cta_keyword", cta.get("cta_keyword", ""))
        if pkg.facebook_post:
            context.setdefault("facebook_draft", {"facebook_post": pkg.facebook_post})
        if pkg.linkedin_post:
            context.setdefault("linkedin_draft", {"linkedin_post": pkg.linkedin_post})
        context["_post_package_id"] = pkg.id

    if not context.get("story_brief"):
        raise HTTPException(
            status_code=400,
            detail="No story_brief in context. Provide post_package_id or context with story_brief.",
        )

    steps = WORKFLOWS["video_generation"]
    run_id = uuid.uuid4()

    async def _run() -> None:
        from tce.db.session import async_session

        async with async_session() as pipe_db:
            orch = PipelineOrchestrator(
                steps=steps,
                db=pipe_db,
                settings=settings,
                run_id=run_id,
            )
            await orch.run(context)

    asyncio.create_task(_run())

    return {
        "run_id": str(run_id),
        "status": "started",
        "status_url": f"/api/v1/pipeline/{run_id}/status",
    }


@router.get("/")
async def list_videos(
    package_id: str | None = None,
    guide_id: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List video assets, optionally filtered by package or guide."""
    stmt = select(VideoAsset).order_by(VideoAsset.created_at.desc()).limit(limit)

    if package_id:
        stmt = stmt.where(VideoAsset.package_id == uuid.UUID(package_id))
    if guide_id:
        stmt = stmt.where(VideoAsset.guide_id == uuid.UUID(guide_id))

    result = await db.execute(stmt)
    assets = result.scalars().all()

    return [
        {
            "id": str(a.id),
            "package_id": str(a.package_id) if a.package_id else None,
            "guide_id": str(a.guide_id) if a.guide_id else None,
            "template_name": a.template_name,
            "composition_id": a.composition_id,
            "video_url": a.video_url,
            "thumbnail_url": a.thumbnail_url,
            "duration_seconds": a.duration_seconds,
            "resolution": a.resolution,
            "codec": a.codec,
            "file_size_bytes": a.file_size_bytes,
            "render_time_seconds": a.render_time_seconds,
            "operator_selected": a.operator_selected,
            "operator_notes": a.operator_notes,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in assets
    ]


@router.get("/{video_id}")
async def get_video(
    video_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a single video asset by ID."""
    asset = await db.get(VideoAsset, uuid.UUID(video_id))
    if not asset:
        raise HTTPException(status_code=404, detail="Video asset not found")

    return {
        "id": str(asset.id),
        "package_id": str(asset.package_id) if asset.package_id else None,
        "guide_id": str(asset.guide_id) if asset.guide_id else None,
        "template_name": asset.template_name,
        "composition_id": asset.composition_id,
        "composition_props": asset.composition_props,
        "video_url": asset.video_url,
        "video_s3_path": asset.video_s3_path,
        "thumbnail_url": asset.thumbnail_url,
        "duration_seconds": asset.duration_seconds,
        "resolution": asset.resolution,
        "codec": asset.codec,
        "file_size_bytes": asset.file_size_bytes,
        "render_time_seconds": asset.render_time_seconds,
        "render_cost_usd": asset.render_cost_usd,
        "operator_selected": asset.operator_selected,
        "operator_notes": asset.operator_notes,
        "pipeline_run_id": str(asset.pipeline_run_id) if asset.pipeline_run_id else None,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


class VideoSelectRequest(BaseModel):
    selected: bool = True
    notes: str | None = None


@router.patch("/{video_id}/select")
async def select_video(
    video_id: str,
    request: VideoSelectRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Mark a video as operator-selected (or deselect it)."""
    asset = await db.get(VideoAsset, uuid.UUID(video_id))
    if not asset:
        raise HTTPException(status_code=404, detail="Video asset not found")

    asset.operator_selected = request.selected
    if request.notes is not None:
        asset.operator_notes = request.notes
    await db.commit()

    return {"status": "updated", "operator_selected": str(asset.operator_selected)}


# --- Render Queue endpoints ---


class QueueRenderRequest(BaseModel):
    template_name: str
    props: dict[str, Any] = {}
    package_id: str | None = None
    guide_id: str | None = None


@router.post("/queue")
async def queue_render(
    request: QueueRenderRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Enqueue a render job and start processing it in the background."""
    svc = RenderQueueService(_get_render_service(), db)

    pkg_id = uuid.UUID(request.package_id) if request.package_id else None
    gid = uuid.UUID(request.guide_id) if request.guide_id else None

    job = await svc.enqueue(
        template_name=request.template_name,
        props=request.props,
        package_id=pkg_id,
        guide_id=gid,
    )

    # Process in background
    async def _process() -> None:
        from tce.db.session import async_session

        async with async_session() as bg_db:
            bg_svc = RenderQueueService(_get_render_service(), bg_db)
            await bg_svc.process_job(job.id)

    asyncio.create_task(_process())

    return {
        "job_id": str(job.id),
        "status": "queued",
        "template_name": job.template_name,
    }


@router.get("/queue")
async def list_queue(
    package_id: str | None = None,
    pipeline_run_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List render queue jobs."""
    svc = RenderQueueService(_get_render_service(), db)
    return await svc.get_queue_status(
        package_id=uuid.UUID(package_id) if package_id else None,
        pipeline_run_id=uuid.UUID(pipeline_run_id) if pipeline_run_id else None,
    )


@router.get("/queue/{job_id}")
async def get_queue_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a single render queue job status."""
    job = await db.get(RenderQueueJob, uuid.UUID(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")

    return {
        "id": str(job.id),
        "template_name": job.template_name,
        "status": job.status,
        "progress_pct": job.progress_pct,
        "error_message": job.error_message,
        "video_asset_id": str(job.video_asset_id) if job.video_asset_id else None,
        "output_path": job.output_path,
        "thumbnail_path": job.thumbnail_path,
        "render_time_seconds": job.render_time_seconds,
        "queued_at": job.queued_at.isoformat() if job.queued_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


# --- SSE progress endpoint ---


@router.get("/queue/{job_id}/progress")
async def stream_job_progress(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """SSE endpoint for real-time render progress updates.

    Clients connect with EventSource and receive events like:
      data: {"status": "rendering", "progress": 30, "step": "rendering_video"}
      data: {"status": "completed", "progress": 100, "video_asset_id": "..."}
    """
    import json

    # Verify job exists
    job = await db.get(RenderQueueJob, uuid.UUID(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")

    # If already completed/failed, return final state immediately
    if job.status in ("completed", "failed"):
        async def _done():
            event = {
                "status": job.status,
                "progress": job.progress_pct,
                "video_asset_id": str(job.video_asset_id) if job.video_asset_id else None,
                "error_message": job.error_message,
            }
            yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(_done(), media_type="text/event-stream")

    # Subscribe to live updates
    svc = RenderQueueService(_get_render_service(), db)
    q = svc.subscribe(job_id)

    async def _stream():
        try:
            # Send initial state
            yield f"data: {json.dumps({'status': job.status, 'progress': job.progress_pct})}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("status") in ("completed", "failed"):
                        break
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
        finally:
            svc.unsubscribe(job_id, q)

    return StreamingResponse(_stream(), media_type="text/event-stream")


# --- Product Demo ---


class ProductDemoRequest(BaseModel):
    product_name: str
    product_tagline: str
    product_features: list[str] = []
    product_problem: str | None = None
    demo_video_url: str | None = None
    screenshot_urls: list[str] = []
    cta_text: str = "zivraviv.com"


@router.post("/product-demo")
async def create_product_demo(
    request: ProductDemoRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate a product demo video from product info.

    Accepts product details and optional screen recordings/screenshots,
    triggers the ProductDemo Remotion template via the pipeline.
    """
    context: dict[str, Any] = {
        "product_name": request.product_name,
        "product_tagline": request.product_tagline,
        "product_features": request.product_features,
        "product_problem": request.product_problem or "",
        "demo_video_url": request.demo_video_url or "",
        "screenshot_urls": request.screenshot_urls,
        "cta_keyword": request.cta_text,
        "story_brief": {
            "thesis": request.product_tagline,
            "topic": request.product_name,
        },
    }

    steps = WORKFLOWS.get("product_demo") or WORKFLOWS["video_generation"]
    run_id = uuid.uuid4()

    async def _run() -> None:
        from tce.db.session import async_session

        async with async_session() as pipe_db:
            orch = PipelineOrchestrator(
                steps=steps,
                db=pipe_db,
                settings=settings,
                run_id=run_id,
            )
            await orch.run(context)

    asyncio.create_task(_run())

    return {
        "run_id": str(run_id),
        "status": "started",
        "product_name": request.product_name,
        "status_url": f"/api/v1/pipeline/{run_id}/status",
    }


# --- Batch rendering ---


class BatchRenderRequest(BaseModel):
    package_ids: list[str] = []
    guide_id: str | None = None
    templates: list[str] | None = None


@router.post("/batch")
async def batch_render(
    request: BatchRenderRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Batch enqueue video renders for multiple packages.

    If templates is None, uses smart template selection from video_agent.
    Otherwise renders the specified templates for each package.
    """
    from tce.agents.video_agent import VideoAgent

    svc = RenderQueueService(_get_render_service(), db)
    agent = VideoAgent(settings=settings)
    jobs_created = []

    for pkg_id_str in request.package_ids:
        pkg = await db.get(PostPackage, uuid.UUID(pkg_id_str))
        if not pkg:
            logger.warning("batch_render.package_not_found", package_id=pkg_id_str)
            continue

        # Build context from package
        context: dict[str, Any] = {}
        if pkg.story_brief:
            context["story_brief"] = pkg.story_brief
        if pkg.research_brief:
            context["research_brief"] = pkg.research_brief
        if pkg.cta_package:
            context["cta_keyword"] = pkg.cta_package.get("cta_keyword", "")
        if pkg.facebook_post:
            context["facebook_draft"] = {"facebook_post": pkg.facebook_post}
        if pkg.linkedin_post:
            context["linkedin_draft"] = {"linkedin_post": pkg.linkedin_post}

        if request.templates:
            # Render specific templates
            for tpl in request.templates:
                props = agent._build_props_for_template(tpl, context)
                if props:
                    job = await svc.enqueue(
                        template_name=tpl,
                        props=props,
                        package_id=uuid.UUID(pkg_id_str),
                    )
                    jobs_created.append(str(job.id))
        else:
            # Smart selection: let agent pick templates
            renders = agent._select_templates(context)
            for tpl_name, props in renders:
                job = await svc.enqueue(
                    template_name=tpl_name,
                    props=props,
                    package_id=uuid.UUID(pkg_id_str),
                )
                jobs_created.append(str(job.id))

    # Process all queued jobs in background
    async def _process_all() -> None:
        from tce.db.session import async_session

        async with async_session() as bg_db:
            bg_svc = RenderQueueService(_get_render_service(), bg_db)
            await bg_svc.process_all_queued()

    if jobs_created:
        asyncio.create_task(_process_all())

    return {
        "jobs_created": len(jobs_created),
        "job_ids": jobs_created,
        "status": "processing",
    }
