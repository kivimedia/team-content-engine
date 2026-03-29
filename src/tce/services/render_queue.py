"""RenderQueueService - manages video render jobs with status tracking."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.render_queue import RenderQueueJob
from tce.models.video_asset import VideoAsset
from tce.services.video_render import VideoRenderService

logger = structlog.get_logger()


class RenderQueueService:
    """Wraps VideoRenderService with job tracking and progress updates."""

    def __init__(
        self,
        render_service: VideoRenderService,
        db: AsyncSession,
    ):
        self.render_service = render_service
        self.db = db
        # SSE subscribers: job_id -> list of asyncio.Queue
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, job_id: str) -> asyncio.Queue:
        """Subscribe to progress updates for a job."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        subs = self._subscribers.get(job_id, [])
        if q in subs:
            subs.remove(q)
        if not subs:
            self._subscribers.pop(job_id, None)

    async def _notify(self, job_id: str, event: dict[str, Any]) -> None:
        """Push an event to all subscribers of a job."""
        for q in self._subscribers.get(job_id, []):
            await q.put(event)

    async def enqueue(
        self,
        template_name: str,
        props: dict[str, Any],
        *,
        package_id: uuid.UUID | None = None,
        guide_id: uuid.UUID | None = None,
        pipeline_run_id: uuid.UUID | None = None,
        composition_id: str | None = None,
    ) -> RenderQueueJob:
        """Create a new render job in the queue."""
        from tce.services.video_render import TEMPLATE_COMPOSITIONS

        comp_id = composition_id or TEMPLATE_COMPOSITIONS.get(template_name)

        job = RenderQueueJob(
            pipeline_run_id=pipeline_run_id,
            package_id=package_id,
            guide_id=guide_id,
            template_name=template_name,
            composition_id=comp_id,
            composition_props=props,
            status="queued",
            progress_pct=0,
            queued_at=datetime.utcnow(),
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        logger.info(
            "render_queue.enqueued",
            job_id=str(job.id),
            template=template_name,
        )
        return job

    async def process_job(self, job_id: uuid.UUID, run_id: uuid.UUID | None = None) -> RenderQueueJob:
        """Process a single render job - updates status throughout."""
        job = await self.db.get(RenderQueueJob, job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        jid = str(job.id)

        # Mark as rendering
        job.status = "rendering"
        job.progress_pct = 10
        job.started_at = datetime.utcnow()
        await self.db.commit()
        await self._notify(jid, {"status": "rendering", "progress": 10})

        try:
            # Run the actual render
            job.progress_pct = 30
            await self.db.commit()
            await self._notify(jid, {"status": "rendering", "progress": 30, "step": "rendering_video"})

            result = await self.render_service.render(
                job.template_name,
                job.composition_props or {},
                run_id=run_id or job.pipeline_run_id,
            )

            job.progress_pct = 80
            await self.db.commit()
            await self._notify(jid, {"status": "rendering", "progress": 80, "step": "saving_asset"})

            # Create VideoAsset record
            asset = VideoAsset(
                package_id=job.package_id,
                guide_id=job.guide_id,
                template_name=result.template_name,
                composition_id=result.composition_id,
                composition_props=result.props,
                duration_seconds=result.duration_seconds,
                resolution=result.resolution,
                codec=result.codec,
                file_size_bytes=result.file_size_bytes,
                render_time_seconds=result.render_time_seconds,
                pipeline_run_id=job.pipeline_run_id,
                thumbnail_path=result.thumbnail_path,
            )
            # Compute persistent video_url from output path
            if result.output_path:
                video_dir = str(self.render_service.output_dir).rstrip("/\\")
                rel_path = result.output_path.replace(video_dir, "").lstrip("/\\").replace("\\", "/")
                asset.video_url = f"/media/{rel_path}"
            if result.thumbnail_path:
                video_dir = str(self.render_service.output_dir).rstrip("/\\")
                rel_thumb = result.thumbnail_path.replace(video_dir, "").lstrip("/\\").replace("\\", "/")
                asset.thumbnail_url = f"/media/{rel_thumb}"
            self.db.add(asset)
            await self.db.flush()

            # Update job as completed
            job.status = "completed"
            job.progress_pct = 100
            job.completed_at = datetime.utcnow()
            job.render_time_seconds = result.render_time_seconds
            job.output_path = result.output_path
            job.thumbnail_path = result.thumbnail_path
            job.video_asset_id = asset.id
            await self.db.commit()

            await self._notify(jid, {
                "status": "completed",
                "progress": 100,
                "video_asset_id": str(asset.id),
                "video_url": asset.video_url,
                "output_path": result.output_path,
            })

            logger.info(
                "render_queue.completed",
                job_id=jid,
                template=job.template_name,
                render_time=result.render_time_seconds,
            )

        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)[:500]
            job.completed_at = datetime.utcnow()
            await self.db.commit()

            await self._notify(jid, {
                "status": "failed",
                "progress": 0,
                "error": str(exc)[:200],
            })

            logger.error(
                "render_queue.failed",
                job_id=jid,
                template=job.template_name,
                error=str(exc)[:200],
            )

        return job

    async def process_all_queued(self, run_id: uuid.UUID | None = None) -> list[RenderQueueJob]:
        """Process all queued jobs sequentially."""
        stmt = (
            select(RenderQueueJob)
            .where(RenderQueueJob.status == "queued")
            .order_by(RenderQueueJob.queued_at)
        )
        result = await self.db.execute(stmt)
        jobs = result.scalars().all()

        processed = []
        for job in jobs:
            result_job = await self.process_job(job.id, run_id=run_id)
            processed.append(result_job)

        return processed

    async def get_queue_status(
        self,
        package_id: uuid.UUID | None = None,
        pipeline_run_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Get status of all jobs, optionally filtered."""
        stmt = select(RenderQueueJob).order_by(RenderQueueJob.queued_at.desc())

        if package_id:
            stmt = stmt.where(RenderQueueJob.package_id == package_id)
        if pipeline_run_id:
            stmt = stmt.where(RenderQueueJob.pipeline_run_id == pipeline_run_id)

        result = await self.db.execute(stmt)
        jobs = result.scalars().all()

        return [
            {
                "id": str(j.id),
                "template_name": j.template_name,
                "status": j.status,
                "progress_pct": j.progress_pct,
                "error_message": j.error_message,
                "video_asset_id": str(j.video_asset_id) if j.video_asset_id else None,
                "output_path": j.output_path,
                "thumbnail_path": j.thumbnail_path,
                "render_time_seconds": j.render_time_seconds,
                "queued_at": j.queued_at.isoformat() if j.queued_at else None,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in jobs
        ]
