"""Video Agent - selects templates and renders videos via Remotion.

Phase 2: Rule-based smart template selection. Picks the best templates
based on which context keys have data, renders via subprocess bridge.
"""

from __future__ import annotations

import re
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

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        svc = VideoRenderService(
            remotion_path=self.settings.remotion_project_path or "",
            output_dir=self.settings.video_output_dir,
            codec=self.settings.video_default_codec,
            max_render_seconds=self.settings.video_max_render_seconds,
        )

        renders = self._select_templates(context)

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
        for r in results:
            video_assets.append({
                "template_name": r.template_name,
                "composition_id": r.composition_id,
                "output_path": r.output_path,
                "duration_seconds": r.duration_seconds,
                "resolution": r.resolution,
                "codec": r.codec,
                "file_size_bytes": r.file_size_bytes,
                "render_time_seconds": r.render_time_seconds,
                "props": r.props,
            })

        self._report(f"Rendered {len(video_assets)} video(s) successfully")
        return {"video_assets": video_assets}
