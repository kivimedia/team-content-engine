"""Video Agent - selects templates and renders videos via Remotion.

Phase 2: Rule-based smart template selection. Picks the best templates
based on which context keys have data, renders via subprocess bridge.
Includes optional TTS voiceover via ElevenLabs and per-client brand injection.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import structlog

from tce.agents.base import AgentBase
from tce.agents.registry import register_agent
from tce.services.video_render import TEMPLATE_COMPOSITIONS, VideoRenderService

logger = structlog.get_logger()


def _extract_stat(text: str) -> dict[str, Any] | None:
    """Try to pull a numeric stat from a claim string.

    Returns dict with statValue, statSuffix, claimText or None.
    """
    m = re.search(r"(\$?)([\d,]+(?:\.\d+)?)\s*(%|x|X|\+|B|M|K)?", text)
    if not m:
        return None
    prefix = m.group(1)
    raw_num = m.group(2).replace(",", "")
    suffix = m.group(3) or ""
    try:
        val = float(raw_num)
    except ValueError:
        return None
    claim = text[m.end():].strip().lstrip("- ").strip()
    if not claim:
        claim = text[:m.start()].strip().rstrip("- ").strip()
    if not claim:
        claim = text
    return {
        "statValue": val,
        "statSuffix": f"{prefix}{suffix}" if prefix or suffix else "%",
        "claimText": claim,
    }


def _extract_before_after(context: dict[str, Any]) -> dict[str, str] | None:
    """Try to find before/after comparison data in context.

    Sources: guide_sections, story_brief.desired_belief_shift, weekly_plan
    """
    # Check story_brief for desired_belief_shift (before -> after)
    story = context.get("story_brief") or {}
    shift = story.get("desired_belief_shift", "")
    if shift and " -> " in shift:
        parts = shift.split(" -> ", 1)
        return {"before": parts[0].strip(), "after": parts[1].strip()}

    # Check guide_sections for comparison sections
    guide_sections = context.get("guide_sections") or []
    for section in guide_sections:
        if isinstance(section, dict):
            if section.get("before") and section.get("after"):
                return {"before": section["before"], "after": section["after"]}

    # Check weekly_plan days for belief shifts
    plan = context.get("weekly_plan") or {}
    for day in plan.get("days", []):
        brief = day.get("story_brief") or day
        shift = brief.get("desired_belief_shift", "")
        if shift and " -> " in shift:
            parts = shift.split(" -> ", 1)
            return {"before": parts[0].strip(), "after": parts[1].strip()}

    return None


def _extract_steps(context: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Try to find framework/step data in context.

    Sources: guide_sections (framework type), story_brief (if it has steps)
    """
    guide_sections = context.get("guide_sections") or []
    for section in guide_sections:
        if isinstance(section, dict):
            steps = section.get("steps") or section.get("framework_steps")
            if steps and isinstance(steps, list) and len(steps) >= 2:
                result = []
                for i, s in enumerate(steps[:5], 1):
                    text = s if isinstance(s, str) else s.get("text", str(s))
                    result.append({"num": i, "text": text})
                return result

    # Check if research_brief has key_findings that could be steps
    research = context.get("research_brief") or {}
    findings = research.get("key_findings") or []
    if isinstance(findings, list) and len(findings) >= 3:
        result = []
        for i, f in enumerate(findings[:5], 1):
            text = f if isinstance(f, str) else f.get("finding", str(f))
            result.append({"num": i, "text": text})
        return result

    return None


def _extract_hook(context: dict[str, Any]) -> dict[str, Any] | None:
    """Try to extract a post hook for the PostTeaser template.

    Sources: facebook_draft, linkedin_draft
    """
    # Try facebook first (shorter, punchier)
    fb = context.get("facebook_draft") or {}
    fb_post = fb.get("facebook_post", "")
    if fb_post:
        # Take first 2 lines as hook
        lines = [l.strip() for l in fb_post.strip().split("\n") if l.strip()]
        hook = " ".join(lines[:2])
        if len(hook) > 20:
            return {"hookText": hook[:200], "platform": "facebook"}

    li = context.get("linkedin_draft") or {}
    li_post = li.get("linkedin_post", "")
    if li_post:
        lines = [l.strip() for l in li_post.strip().split("\n") if l.strip()]
        hook = " ".join(lines[:2])
        if len(hook) > 20:
            return {"hookText": hook[:200], "platform": "linkedin"}

    return None


def _build_product_demo_props(
    context: dict[str, Any], cta: str
) -> dict[str, Any] | None:
    """Build ProductDemo props from context.

    Expects: product_name, product_tagline, and optionally
    product_features, demo_video_url, screenshot_urls.
    """
    product_name = context.get("product_name", "")
    tagline = context.get("product_tagline", "")
    if not product_name or not tagline:
        return None

    features = context.get("product_features") or []
    demo_url = context.get("demo_video_url", "")
    screenshots = context.get("screenshot_urls") or []
    problem_text = context.get("product_problem", "")

    scenes: list[dict[str, Any]] = []

    # Title scene (always)
    scenes.append({"type": "title", "durationSec": 4, "content": {}})

    # Problem scene (if provided)
    if problem_text:
        scenes.append({
            "type": "problem",
            "durationSec": 4,
            "content": {"text": problem_text},
        })

    # Demo scene (if video or screenshots provided)
    if demo_url:
        scenes.append({
            "type": "demo",
            "durationSec": 8,
            "content": {"src": demo_url, "isVideo": True, "urlText": product_name.lower() + ".com"},
        })
    elif screenshots:
        for i, ss_url in enumerate(screenshots[:3]):
            scenes.append({
                "type": "demo",
                "durationSec": 5,
                "content": {"src": ss_url, "urlText": product_name.lower() + ".com"},
            })

    # Features scene
    if features:
        scenes.append({
            "type": "features",
            "durationSec": 6,
            "content": {"title": "Key Features", "features": features[:5]},
        })

    # CTA scene (always)
    scenes.append({"type": "cta", "durationSec": 4, "content": {}})

    return {
        "productName": product_name,
        "tagline": tagline,
        "scenes": scenes,
        "demoVideoUrl": demo_url or None,
        "screenshotUrls": screenshots or None,
        "ctaText": cta,
    }


@register_agent
class VideoAgent(AgentBase):
    """Renders video assets from pipeline context using smart template selection."""

    name: str = "video_agent"
    default_model: str = "claude-haiku-4-5-20251001"  # unused - no LLM calls

    def _select_templates(self, context: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """Select templates and build props based on available context data.

        Returns list of (template_name, props) tuples.
        """
        renders: list[tuple[str, dict[str, Any]]] = []
        cta = context.get("cta_keyword") or context.get("weekly_keyword") or "zivraviv.com"
        story_brief = context.get("story_brief") or {}

        thesis = story_brief.get("thesis", "")
        if thesis:
            hook_props = {
                "thesis": thesis,
                "attribution": context.get("creator_name", "Ziv Raviv"),
                "ctaText": cta,
            }
            renders.append(("hook_reel", hook_props))
            renders.append(("hook_reel_square", hook_props))

        research_brief = context.get("research_brief") or {}
        for claim in research_brief.get("verified_claims") or []:
            claim_text = claim if isinstance(claim, str) else claim.get("claim", "")
            source_text = "" if isinstance(claim, str) else claim.get("source", "")
            stat = _extract_stat(claim_text)
            if stat:
                stat_props = {
                    "statValue": stat["statValue"],
                    "statSuffix": stat["statSuffix"],
                    "claimText": stat["claimText"],
                    "sourceText": source_text or "Verified source",
                    "ctaText": cta,
                }
                renders.append(("stat_reveal", stat_props))
                renders.append(("stat_reveal_square", stat_props))
                break

        ba = _extract_before_after(context)
        if ba:
            ba_props = {
                "title": story_brief.get("topic", "The Shift"),
                "before": ba["before"],
                "after": ba["after"],
                "ctaText": cta,
            }
            renders.append(("before_after", ba_props))
            renders.append(("before_after_square", ba_props))

        steps = _extract_steps(context)
        if steps:
            sf_props: dict[str, Any] = {
                "title": story_brief.get("topic", "The Framework"),
                "steps": steps,
                "ctaText": cta,
            }
            kw = context.get("cta_keyword") or context.get("weekly_keyword")
            if kw and kw != cta:
                sf_props["ctaKeyword"] = kw
            renders.append(("step_framework", sf_props))
            renders.append(("step_framework_square", sf_props))

        hook = _extract_hook(context)
        if hook:
            teaser_props: dict[str, Any] = {
                "hookText": hook["hookText"],
                "platform": hook["platform"],
            }
            kw = context.get("cta_keyword") or context.get("weekly_keyword")
            if kw:
                teaser_props["ctaKeyword"] = kw
            renders.append(("post_teaser", teaser_props))
            renders.append(("post_teaser_square", teaser_props))

        # Product demo: if context has product info
        product_name = context.get("product_name")
        product_tagline = context.get("product_tagline")
        if product_name and product_tagline:
            demo_props = _build_product_demo_props(context, cta)
            if demo_props:
                renders.append(("product_demo", demo_props))
                renders.append(("product_demo_landscape", demo_props))

        return renders

    def _build_props_for_template(
        self, template_name: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Build props for a specific template from context. Returns None if not enough data."""
        cta = context.get("cta_keyword") or context.get("weekly_keyword") or "zivraviv.com"
        story_brief = context.get("story_brief") or {}
        base_name = template_name.replace("_square", "").replace("_landscape", "")

        if base_name == "hook_reel":
            thesis = story_brief.get("thesis", "")
            if not thesis:
                return None
            return {
                "thesis": thesis,
                "attribution": context.get("creator_name", "Ziv Raviv"),
                "ctaText": cta,
            }

        if base_name == "stat_reveal":
            research = context.get("research_brief") or {}
            for claim in research.get("verified_claims") or []:
                claim_text = claim if isinstance(claim, str) else claim.get("claim", "")
                source_text = "" if isinstance(claim, str) else claim.get("source", "")
                stat = _extract_stat(claim_text)
                if stat:
                    return {
                        "statValue": stat["statValue"],
                        "statSuffix": stat["statSuffix"],
                        "claimText": stat["claimText"],
                        "sourceText": source_text or "Verified source",
                        "ctaText": cta,
                    }
            return None

        if base_name == "before_after":
            ba = _extract_before_after(context)
            if not ba:
                return None
            return {
                "title": story_brief.get("topic", "The Shift"),
                "before": ba["before"],
                "after": ba["after"],
                "ctaText": cta,
            }

        if base_name == "step_framework":
            steps = _extract_steps(context)
            if not steps:
                return None
            props: dict[str, Any] = {
                "title": story_brief.get("topic", "The Framework"),
                "steps": steps,
                "ctaText": cta,
            }
            kw = context.get("cta_keyword") or context.get("weekly_keyword")
            if kw and kw != cta:
                props["ctaKeyword"] = kw
            return props

        if base_name == "post_teaser":
            hook = _extract_hook(context)
            if not hook:
                return None
            props = {
                "hookText": hook["hookText"],
                "platform": hook["platform"],
            }
            kw = context.get("cta_keyword") or context.get("weekly_keyword")
            if kw:
                props["ctaKeyword"] = kw
            return props

        return None

    async def _generate_voiceover(
        self, context: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]] | None:
        """Generate TTS voiceover if narration_script exists and ElevenLabs is configured.

        Returns (audio_url_for_remotion, timed_segments) or None if TTS unavailable.
        """
        narration = context.get("narration_script")
        if not narration or not isinstance(narration, dict):
            return None

        segments = narration.get("segments", [])
        if not segments:
            return None

        api_key = self.settings.elevenlabs_api_key
        if not api_key:
            self._report("ElevenLabs not configured - skipping voiceover")
            return None

        from tce.services.tts import TTSService

        # Check for per-client voice config from brand profile
        voice_config = context.get("_brand_voice_config")
        voice_id = (
            (voice_config or {}).get("elevenlabs_voice_id")
            or self.settings.elevenlabs_voice_id
        )

        tts = TTSService(
            api_key=api_key,
            voice_id=voice_id,
            model=self.settings.elevenlabs_model,
            output_dir=self.settings.audio_upload_dir,
        )

        self._report("Generating voiceover via ElevenLabs...")
        result, timed_segments = await tts.generate_with_timestamps(
            segments,
            voice_config=voice_config,
            run_id=self.run_id,
        )
        self._report(
            f"Voiceover generated: {result.duration_seconds:.1f}s, "
            f"${result.cost_estimate_usd:.3f}"
        )

        # Copy MP3 to Remotion's public/audio/ for staticFile() serving
        remotion_path = Path(
            self.settings.remotion_project_path
            or (Path(__file__).resolve().parents[3] / "remotion")
        )
        audio_dest = remotion_path / "public" / "audio"
        audio_dest.mkdir(parents=True, exist_ok=True)
        dest_file = audio_dest / f"{self.run_id or 'voiceover'}.mp3"
        await __import__("asyncio").to_thread(
            shutil.copy2, result.file_path, str(dest_file)
        )

        # Return the Remotion-relative audio URL
        audio_url = f"audio/{dest_file.name}"
        return audio_url, timed_segments

    async def _load_brand(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """Load brand profile for the current creator from DB.

        Returns brand override dict for Remotion props, or None.
        """
        if not self.db:
            return None

        try:
            from sqlalchemy import select
            from tce.models.brand_profile import BrandProfile

            # Try creator-specific brand first
            creator_name = context.get("creator_name", "")
            stmt = select(BrandProfile).order_by(BrandProfile.created_at.desc()).limit(1)
            result = await self.db.execute(stmt)
            brand = result.scalar_one_or_none()

            if not brand:
                return None

            brand_override = {}
            if brand.colors:
                brand_override.update(brand.colors)
            if brand.fonts:
                brand_override["headingFont"] = brand.fonts.get("heading", "")
                brand_override["bodyFont"] = brand.fonts.get("body", "")
            if brand.logo_url:
                brand_override["logoUrl"] = brand.logo_url

            # Store voice config in context for TTS
            if brand.voice_config:
                context["_brand_voice_config"] = brand.voice_config

            return brand_override if brand_override else None
        except Exception:
            # BrandProfile table might not exist yet
            logger.debug("video_agent.brand_load_skipped")
            return None

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        svc = VideoRenderService(
            remotion_path=self.settings.remotion_project_path or "",
            output_dir=self.settings.video_output_dir,
            codec=self.settings.video_default_codec,
            max_render_seconds=self.settings.video_max_render_seconds,
        )

        # Load per-client brand (if available)
        brand_override = await self._load_brand(context)

        # Generate voiceover (if narration_script exists and ElevenLabs configured)
        voiceover_result = await self._generate_voiceover(context)

        renders = self._select_templates(context)

        # If we have voiceover, add NarratedVideo renders
        if voiceover_result:
            audio_url, timed_segments = voiceover_result
            cta = context.get("cta_keyword") or context.get("weekly_keyword") or "zivraviv.com"
            narrated_props: dict[str, Any] = {
                "audioUrl": audio_url,
                "segments": timed_segments,
                "ctaText": cta,
            }
            renders.append(("narrated_video", narrated_props))
            renders.append(("narrated_video_square", narrated_props))

        # Inject brand override into all render props
        if brand_override:
            for i, (tpl_name, props) in enumerate(renders):
                props["brand"] = brand_override
                renders[i] = (tpl_name, props)

        # Log what was selected
        for tpl_name, _ in renders:
            base = tpl_name.replace("_square", "").replace("_landscape", "")
            if tpl_name == base:
                self._report(f"Selected: {tpl_name}")

        if not renders:
            self._report("No renderable content found in context - skipping video generation")
            return {"video_assets": []}

        self._report(f"Rendering {len(renders)} video(s)...")
        results = await svc.render_batch(renders, run_id=self.run_id)

        video_assets = []
        output_dir = Path(svc.output_dir)
        for r in results:
            # Compute web-accessible URL relative to the /media mount
            try:
                rel_path = Path(r.output_path).relative_to(output_dir)
                video_url = f"/media/{rel_path.as_posix()}"
            except ValueError:
                video_url = None

            thumbnail_url = None
            if r.thumbnail_path:
                try:
                    rel_thumb = Path(r.thumbnail_path).relative_to(output_dir)
                    thumbnail_url = f"/media/{rel_thumb.as_posix()}"
                except ValueError:
                    pass

            video_assets.append({
                "template_name": r.template_name,
                "composition_id": r.composition_id,
                "output_path": r.output_path,
                "video_url": video_url,
                "thumbnail_url": thumbnail_url,
                "duration_seconds": r.duration_seconds,
                "resolution": r.resolution,
                "codec": r.codec,
                "file_size_bytes": r.file_size_bytes,
                "render_time_seconds": r.render_time_seconds,
                "props": r.props,
            })

        self._report(f"Rendered {len(video_assets)} video(s) successfully")
        return {"video_assets": video_assets}
