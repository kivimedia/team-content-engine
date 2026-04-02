"""VideoRenderService - subprocess bridge to Remotion for video rendering."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# Template -> Remotion composition ID mapping
TEMPLATE_COMPOSITIONS: dict[str, str] = {
    "hook_reel": "HookReel",
    "hook_reel_square": "HookReelSquare",
    "stat_reveal": "StatReveal",
    "stat_reveal_square": "StatRevealSquare",
    "before_after": "BeforeAfter",
    "before_after_square": "BeforeAfterSquare",
    "before_after_landscape": "BeforeAfterLandscape",
    "step_framework": "StepFramework",
    "step_framework_square": "StepFrameworkSquare",
    "post_teaser": "PostTeaser",
    "post_teaser_square": "PostTeaserSquare",
    "narrated_video": "NarratedVideo",
    "narrated_video_square": "NarratedVideoSquare",
    "narrated_video_landscape": "NarratedVideoLandscape",
    "product_demo": "ProductDemo",
    "product_demo_square": "ProductDemoSquare",
    "product_demo_landscape": "ProductDemoLandscape",
}


class VideoRenderResult:
    """Result from a single video render."""

    def __init__(
        self,
        *,
        template_name: str,
        composition_id: str,
        output_path: str,
        duration_seconds: float,
        resolution: str,
        codec: str,
        file_size_bytes: int,
        render_time_seconds: float,
        props: dict[str, Any],
    ):
        self.template_name = template_name
        self.composition_id = composition_id
        self.output_path = output_path
        self.duration_seconds = duration_seconds
        self.resolution = resolution
        self.codec = codec
        self.file_size_bytes = file_size_bytes
        self.render_time_seconds = render_time_seconds
        self.props = props
        self.thumbnail_path: str | None = None


class VideoRenderService:
    """Renders video templates via Remotion CLI subprocess."""

    def __init__(
        self,
        remotion_path: str = "",
        output_dir: str = "/tmp/tce-video",
        codec: str = "h264",
        max_render_seconds: int = 120,
    ):
        if remotion_path:
            self.remotion_path = Path(remotion_path)
        else:
            # Auto-detect: assume remotion/ is a sibling of src/
            self.remotion_path = Path(__file__).resolve().parents[3] / "remotion"

        self.output_dir = Path(output_dir)
        self.codec = codec
        self.max_render_seconds = max_render_seconds

    async def render(
        self,
        template_name: str,
        props: dict[str, Any],
        *,
        run_id: uuid.UUID | None = None,
    ) -> VideoRenderResult:
        """Render a single video template with the given props.

        Args:
            template_name: Key from TEMPLATE_COMPOSITIONS (e.g. "hook_reel")
            props: JSON-serializable props to pass to the Remotion composition
            run_id: Pipeline run ID for organizing output

        Returns:
            VideoRenderResult with output path and metadata
        """
        composition_id = TEMPLATE_COMPOSITIONS.get(template_name)
        if not composition_id:
            raise ValueError(
                f"Unknown template '{template_name}'. "
                f"Available: {list(TEMPLATE_COMPOSITIONS.keys())}"
            )

        # Create output directory
        rid = str(run_id or uuid.uuid4())
        out_dir = self.output_dir / rid
        out_dir.mkdir(parents=True, exist_ok=True)

        # Write props to temp file
        props_path = out_dir / f"{template_name}_props.json"
        props_path.write_text(json.dumps(props, ensure_ascii=False))

        output_path = out_dir / f"{template_name}.mp4"
        entry_file = self.remotion_path / "src" / "index.ts"

        cmd = [
            "npx",
            "remotion",
            "render",
            str(entry_file),
            composition_id,
            str(output_path),
            f"--props={props_path}",
            f"--codec={self.codec}",
        ]

        logger.info(
            "video.render.start",
            template=template_name,
            composition=composition_id,
            output=str(output_path),
        )

        start = time.monotonic()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.remotion_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.max_render_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(
                f"Remotion render timed out after {self.max_render_seconds}s "
                f"for template {template_name}"
            )

        elapsed = time.monotonic() - start

        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", errors="replace")[:500]
            logger.error(
                "video.render.failed",
                template=template_name,
                returncode=proc.returncode,
                stderr=err_text,
            )
            raise RuntimeError(f"Remotion render failed (exit {proc.returncode}): {err_text}")

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"Render produced no output at {output_path}")

        file_size = output_path.stat().st_size

        # Extract resolution from composition name
        resolution = "1080x1920"  # default vertical
        if "Square" in composition_id:
            resolution = "1080x1080"
        elif "Landscape" in composition_id:
            resolution = "1920x1080"

        # Duration from composition definition (approximate from file)
        # Remotion default durations are set in Root.tsx
        duration_map = {
            "HookReel": 8.0,
            "HookReelSquare": 8.0,
            "StatReveal": 10.0,
            "StatRevealSquare": 10.0,
            "BeforeAfter": 12.0,
            "BeforeAfterSquare": 12.0,
            "BeforeAfterLandscape": 12.0,
            "StepFramework": 20.0,
            "StepFrameworkSquare": 20.0,
            "PostTeaser": 10.0,
            "PostTeaserSquare": 10.0,
        }
        # NarratedVideo duration is dynamic - estimate from segment end times or props
        if composition_id.startswith("NarratedVideo"):
            segments = props.get("segments", [])
            if segments:
                last_seg = segments[-1]
                duration = last_seg.get("endSec", 0) + 2.0  # +2s buffer
            else:
                duration = 45.0
        else:
            duration = duration_map.get(composition_id, 8.0)

        logger.info(
            "video.render.complete",
            template=template_name,
            file_size=file_size,
            render_time=f"{elapsed:.1f}s",
            output=str(output_path),
        )

        result = VideoRenderResult(
            template_name=template_name,
            composition_id=composition_id,
            output_path=str(output_path),
            duration_seconds=duration,
            resolution=resolution,
            codec=self.codec,
            file_size_bytes=file_size,
            render_time_seconds=round(elapsed, 2),
            props=props,
        )

        # Auto-generate thumbnail (frame 0 as PNG)
        try:
            thumb_path = await self.render_thumbnail(
                template_name, props, run_id=run_id
            )
            result.thumbnail_path = thumb_path
        except Exception as exc:
            logger.warning(
                "video.thumbnail.failed",
                template=template_name,
                error=str(exc)[:200],
            )

        return result

    async def render_thumbnail(
        self,
        template_name: str,
        props: dict[str, Any],
        *,
        run_id: uuid.UUID | None = None,
        frame: int = 30,
    ) -> str:
        """Render a single frame as PNG thumbnail.

        Args:
            template_name: Key from TEMPLATE_COMPOSITIONS
            props: Props to pass to the composition
            run_id: Pipeline run ID for organizing output
            frame: Which frame to capture (default 30 = 1 second in)

        Returns:
            Path to the generated PNG file
        """
        composition_id = TEMPLATE_COMPOSITIONS.get(template_name)
        if not composition_id:
            raise ValueError(f"Unknown template '{template_name}'")

        rid = str(run_id or uuid.uuid4())
        out_dir = self.output_dir / rid
        out_dir.mkdir(parents=True, exist_ok=True)

        props_path = out_dir / f"{template_name}_thumb_props.json"
        props_path.write_text(json.dumps(props, ensure_ascii=False))

        thumb_path = out_dir / f"{template_name}_thumb.png"
        entry_file = self.remotion_path / "src" / "index.ts"

        cmd = [
            "npx",
            "remotion",
            "still",
            str(entry_file),
            composition_id,
            str(thumb_path),
            f"--props={props_path}",
            f"--frame={frame}",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.remotion_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=60
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Thumbnail render timed out for {template_name}")

        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"Thumbnail render failed: {err_text}")

        if not thumb_path.exists() or thumb_path.stat().st_size == 0:
            raise RuntimeError(f"Thumbnail produced no output at {thumb_path}")

        logger.info(
            "video.thumbnail.complete",
            template=template_name,
            output=str(thumb_path),
            size=thumb_path.stat().st_size,
        )

        return str(thumb_path)

    async def render_batch(
        self,
        renders: list[tuple[str, dict[str, Any]]],
        *,
        run_id: uuid.UUID | None = None,
    ) -> list[VideoRenderResult]:
        """Render multiple templates sequentially.

        Args:
            renders: List of (template_name, props) tuples
            run_id: Shared pipeline run ID

        Returns:
            List of VideoRenderResult (failed renders are logged and skipped)
        """
        results: list[VideoRenderResult] = []
        for template_name, props in renders:
            try:
                result = await self.render(template_name, props, run_id=run_id)
                results.append(result)
            except Exception as exc:
                logger.warning(
                    "video.render.batch_skip",
                    template=template_name,
                    error=str(exc)[:200],
                )
        return results
