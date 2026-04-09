"""Pipeline result persistence — converts agent output dicts into ORM records."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.creator_profile import CreatorProfile
from tce.models.image_asset import ImageAsset
from tce.models.pattern_template import PatternTemplate
from tce.models.post_example import PostExample
from tce.models.post_package import PostPackage
from tce.models.qa_scorecard import QAScorecard
from tce.models.research_brief import ResearchBrief
from tce.models.story_brief import StoryBrief
from tce.models.trend_brief import TrendBrief
from tce.models.weekly_guide import WeeklyGuide

logger = structlog.get_logger()


def _to_str(val: Any) -> str | None:
    """Convert a value to string - handles lists from LLM output."""
    if val is None:
        return None
    if isinstance(val, list):
        return "; ".join(str(v) for v in val)
    return str(val)


def _clean_text(text: str | None) -> str | None:
    """Clean up LLM output - replace all dash-like Unicode chars with single hyphen."""
    if not text:
        return text
    # em dash, en dash, horizontal bar, figure dash, quotation dash, swung dash,
    # two-em dash, three-em dash, small em dash, fullwidth hyphen-minus
    for ch in "\u2014\u2013\u2015\u2012\u2015\u2053\u2E3A\u2E3B\uFE58\uFF0D":
        text = text.replace(ch, " - ")
    return text.replace("--", " - ")


def _clean_list(items: list[str] | None) -> list[str] | None:
    """Clean a list of strings."""
    if not items:
        return items
    return [_clean_text(s) or s for s in items]


def _clean_dict(d: dict | None) -> dict | None:
    """Recursively clean string values in a dict."""
    if not d:
        return d
    out = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = _clean_text(v) or v
        elif isinstance(v, dict):
            out[k] = _clean_dict(v)
        elif isinstance(v, list):
            out[k] = [_clean_text(i) if isinstance(i, str) else i for i in v]
        else:
            out[k] = v
    return out


class PipelineResultSaver:
    """Persists agent output dicts as ORM records."""

    def __init__(self, db: AsyncSession, run_id: uuid.UUID, workspace_id: uuid.UUID | None = None) -> None:
        self.db = db
        self.run_id = run_id
        self.workspace_id = workspace_id

    def _stamp(self, record: Any) -> Any:
        """Stamp workspace_id on a record before adding to DB."""
        if self.workspace_id and hasattr(record, "workspace_id"):
            record.workspace_id = self.workspace_id
        return record

    def _add(self, record: Any) -> None:
        """Add a record to DB with workspace_id stamped."""
        self._stamp(record)
        self._add(record)

    # --- Corpus ingestion pipeline ---

    async def _get_or_create_creator(self, creator_name: str) -> uuid.UUID:
        """Find existing creator by name or create a new one."""
        result = await self.db.execute(
            select(CreatorProfile).where(CreatorProfile.creator_name == creator_name)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing.id

        creator = CreatorProfile(
            creator_name=creator_name,
            style_notes="Auto-created from corpus analysis",
        )
        self._add(creator)
        await self.db.flush()
        logger.info("saver.creator_created", name=creator_name, id=str(creator.id))
        return creator.id

    async def save_post_examples(self, context: dict[str, Any]) -> list[uuid.UUID]:
        """Save CorpusAnalyst output as PostExample records."""
        examples = context.get("post_examples", [])
        created_ids: list[uuid.UUID] = []

        # Build creator_name -> creator_id cache (auto-create missing creators)
        creator_cache: dict[str, uuid.UUID] = {}

        for ex in examples:
            creator_name = ex.get("creator_name", "unknown")

            if creator_name not in creator_cache:
                creator_cache[creator_name] = await self._get_or_create_creator(creator_name)

            creator_id = creator_cache[creator_name]
            doc_id = ex.get("document_id")

            record = PostExample(
                document_id=uuid.UUID(str(doc_id)) if doc_id else None,
                creator_id=uuid.UUID(str(creator_id)),
                page_number=ex.get("page_number"),
                post_text_raw=ex.get("post_text_raw"),
                hook_text=ex.get("hook_text"),
                body_text=ex.get("body_text"),
                cta_text=ex.get("cta_text"),
                hook_type=ex.get("hook_type"),
                body_structure=ex.get("body_structure"),
                story_arc=ex.get("story_arc"),
                tension_type=ex.get("tension_type"),
                cta_type=ex.get("cta_type"),
                visual_type=ex.get("visual_type"),
                visual_description=ex.get("visual_description"),
                proof_style=ex.get("proof_style"),
                tone_tags=ex.get("tone_tags"),
                topic_tags=ex.get("topic_tags"),
                audience_guess=ex.get("audience_guess"),
                paragraph_count=ex.get("paragraph_count"),
                uses_bullets=ex.get("uses_bullets"),
                has_explicit_keyword_cta=ex.get("has_explicit_keyword_cta"),
                visible_comments=ex.get("visible_comments"),
                visible_shares=ex.get("visible_shares"),
                engagement_confidence=ex.get("engagement_confidence", "C"),
                ocr_confidence=ex.get("ocr_confidence"),
                evidence_image_ref=ex.get("evidence_image_ref"),
                parser_notes=ex.get("parser_notes"),
            )
            self._add(record)
            await self.db.flush()
            created_ids.append(record.id)

        logger.info(
            "saver.post_examples",
            count=len(created_ids),
            run_id=str(self.run_id),
        )
        return created_ids

    async def save_engagement_scores(self, context: dict[str, Any]) -> int:
        """Update PostExample records with scores from EngagementScorer."""
        scored = context.get("scored_examples", [])
        updated = 0

        for ex in scored:
            example_id = ex.get("example_id")
            if not example_id:
                continue
            record = await self.db.get(PostExample, uuid.UUID(str(example_id)))
            if record:
                record.raw_score = ex.get("raw_score")
                record.final_score = ex.get("final_score")
                updated += 1

        await self.db.flush()
        logger.info("saver.engagement_scores", updated=updated)
        return updated

    async def save_templates(self, context: dict[str, Any]) -> list[uuid.UUID]:
        """Save PatternMiner output as PatternTemplate records."""
        templates = context.get("templates", [])
        created_ids: list[uuid.UUID] = []

        for tpl in templates:
            record = PatternTemplate(
                template_name=tpl.get("template_name", "Unnamed Template"),
                template_family=tpl.get("template_family", "unknown"),
                best_for=_to_str(tpl.get("best_for")),
                hook_formula=_to_str(tpl.get("hook_formula")),
                body_formula=_to_str(tpl.get("body_formula")),
                proof_requirements=_to_str(tpl.get("proof_requirements")),
                cta_compatibility=tpl.get("cta_compatibility"),
                visual_compatibility=tpl.get("visual_compatibility"),
                platform_fit=tpl.get("platform_fit"),
                tone_profile=tpl.get("tone_profile"),
                risk_notes=_to_str(tpl.get("risk_notes")),
                anti_patterns=_to_str(tpl.get("anti_patterns")),
                source_influence_weights=tpl.get("source_influence_weights"),
                status="provisional",
            )
            self._add(record)
            await self.db.flush()
            created_ids.append(record.id)

        logger.info("saver.templates", count=len(created_ids))
        return created_ids

    # --- Daily content pipeline ---

    async def save_trend_brief(self, context: dict[str, Any]) -> uuid.UUID | None:
        """Save TrendScout output as a TrendBrief record."""
        brief = context.get("trend_brief", {})
        if not brief:
            return None

        record = TrendBrief(
            date=date.today(),
            brief_type=context.get("scan_type", "daily"),
            trends=brief.get("trends"),
        )
        self._add(record)
        await self.db.flush()
        logger.info("saver.trend_brief", id=str(record.id))
        return record.id

    async def save_story_brief(
        self, context: dict[str, Any]
    ) -> tuple[uuid.UUID | None, dict | None]:
        """Save StoryStrategist output as a StoryBrief record.

        Returns (brief_id, resolved_template_dict) where resolved_template_dict
        contains the full template formulas if the LLM chose a known template.
        """
        brief = context.get("story_brief", {})
        if not brief:
            return None, None

        # Resolve template name (string) to UUID FK
        template_name = brief.get("template_id")
        resolved_tpl_id = None
        resolved_tpl_dict = None
        if template_name:
            result = await self.db.execute(
                select(PatternTemplate).where(
                    PatternTemplate.template_name == template_name
                )
            )
            tpl = result.scalar_one_or_none()
            if tpl:
                resolved_tpl_id = tpl.id
                resolved_tpl_dict = {
                    "template_name": tpl.template_name,
                    "template_family": tpl.template_family,
                    "hook_formula": tpl.hook_formula,
                    "body_formula": tpl.body_formula,
                    "anti_patterns": tpl.anti_patterns,
                }
                logger.info(
                    "saver.template_resolved",
                    name=template_name,
                    id=str(tpl.id),
                )
            else:
                logger.warning("saver.template_not_found", name=template_name)

        record = StoryBrief(
            topic=_clean_text(brief.get("topic", "")),
            audience=_clean_text(brief.get("audience")),
            angle_type=brief.get("angle_type", "unknown"),
            desired_belief_shift=_clean_text(brief.get("desired_belief_shift")),
            house_voice_weights=brief.get("house_voice_weights"),
            thesis=_clean_text(brief.get("thesis")),
            evidence_requirements=brief.get("evidence_requirements"),
            cta_goal=_clean_text(brief.get("cta_goal")),
            visual_job=_clean_text(brief.get("visual_job")),
            platform_notes=brief.get("platform_notes"),
            template_id=resolved_tpl_id,
        )
        self._add(record)
        await self.db.flush()
        logger.info("saver.story_brief", id=str(record.id), template=template_name)
        return record.id, resolved_tpl_dict

    async def save_research_brief(self, context: dict[str, Any]) -> uuid.UUID | None:
        """Save ResearchAgent output as a ResearchBrief record."""
        brief = context.get("research_brief", {})
        if not brief:
            return None

        record = ResearchBrief(
            topic=brief.get("topic", ""),
            verified_claims=brief.get("verified_claims"),
            uncertain_claims=brief.get("uncertain_claims"),
            rejected_claims=brief.get("rejected_claims"),
            source_refs=brief.get("source_refs"),
            freshness_date=brief.get("freshness_date"),
            thesis_candidates=brief.get("thesis_candidates"),
            risk_flags=brief.get("risk_flags"),
            safe_to_publish=brief.get("safe_to_publish"),
        )
        self._add(record)
        await self.db.flush()
        logger.info("saver.research_brief", id=str(record.id))
        return record.id

    async def save_post_package(self, context: dict[str, Any]) -> uuid.UUID | None:
        """Assemble FB/LI drafts, CTA, and image prompts into a PostPackage."""
        fb = context.get("facebook_draft", {})
        li = context.get("linkedin_draft", {})
        cta = context.get("cta_package", {})
        image_prompts = context.get("image_prompts", [])
        brief_id = context.get("_story_brief_id")
        research_brief_id = context.get("_research_brief_id")
        guide_id = context.get("_weekly_guide_id")

        # Merge hook variants from both platforms
        hooks = fb.get("hook_variants", []) + li.get("hook_variants", [])

        # Build quality_scores with QA results + copy analysis metadata
        qa_scores = context.get("qa_result", context.get("quality_scores"))
        matched_template = context.get("matched_template") or context.get("_resolved_template")
        copy_analysis = context.get("copy_analysis")
        quality_meta = {}
        if qa_scores:
            quality_meta.update(qa_scores if isinstance(qa_scores, dict) else {})
        if matched_template:
            quality_meta["matched_template"] = matched_template
        if copy_analysis:
            quality_meta["copy_analysis"] = copy_analysis

        record = PostPackage(
            brief_id=brief_id,
            research_brief_id=research_brief_id,
            weekly_guide_id=guide_id,
            facebook_post=_clean_text(fb.get("facebook_post")),
            linkedin_post=_clean_text(li.get("linkedin_post")),
            hook_variants=_clean_list(hooks) if hooks else None,
            cta_keyword=cta.get("weekly_keyword") or context.get("weekly_keyword"),
            secondary_cta_keyword=cta.get("secondary_keyword"),
            dm_flow=_clean_dict(cta.get("dm_flow")),
            image_prompts=image_prompts if image_prompts else None,
            quality_scores=quality_meta if quality_meta else None,
            approval_status="draft",
            pipeline_run_id=self.run_id,
        )
        self._add(record)
        await self.db.flush()

        # Save image assets
        for prompt in image_prompts:
            asset = ImageAsset(
                package_id=record.id,
                prompt_text=prompt.get("prompt_text", prompt.get("detailed_prompt", "")),
                negative_prompt=prompt.get("negative_prompt"),
                aspect_ratio=prompt.get("aspect_ratio"),
            )
            self._add(asset)

        await self.db.flush()
        logger.info(
            "saver.post_package",
            id=str(record.id),
            images=len(image_prompts),
        )
        return record.id

    async def save_qa_scorecard(self, context: dict[str, Any]) -> uuid.UUID | None:
        """Save QAAgent output as a QAScorecard record."""
        scorecard = context.get("qa_scorecard", {})
        package_id = context.get("_post_package_id")
        if not scorecard or not package_id:
            return None

        record = QAScorecard(
            package_id=package_id,
            dimension_scores=scorecard.get("dimension_scores", {}),
            composite_score=scorecard.get("composite_score"),
            pass_status=scorecard.get("pass_status", "pending"),
            model_justifications=scorecard.get("model_justifications"),
            final_verdict=scorecard.get("pass_status", "pending"),
            scored_by="model",
        )
        self._add(record)
        await self.db.flush()
        logger.info(
            "saver.qa_scorecard",
            id=str(record.id),
            status=record.pass_status,
        )
        return record.id

    # --- Weekly planning pipeline ---

    async def save_weekly_guide(self, context: dict[str, Any]) -> uuid.UUID | None:
        """Save DocxGuideBuilder output as WeeklyGuide + DOCX file."""
        guide = context.get("guide_content", {})
        if not guide:
            return None

        docx_path = context.get("_guide_docx_path")

        # Build markdown from sections for inline viewing
        sections = guide.get("sections", [])
        markdown_parts = [f"# {guide.get('guide_title', 'Weekly Guide')}\n"]
        for s in sections:
            sec_type = s.get("type", "narrative")
            title = s.get("title", "")

            if sec_type == "comparison":
                if title:
                    markdown_parts.append(f"\n## {title}\n")
                bad_label = s.get("bad_label", "Before")
                good_label = s.get("good_label", "After")
                markdown_parts.append(f"| {bad_label} | {good_label} |")
                markdown_parts.append("|---|---|")
                bad_items = s.get("bad_items", [])
                good_items = s.get("good_items", [])
                for i in range(max(len(bad_items), len(good_items))):
                    b = bad_items[i] if i < len(bad_items) else ""
                    g = good_items[i] if i < len(good_items) else ""
                    markdown_parts.append(f"| {b} | {g} |")
            elif sec_type == "framework":
                if title:
                    markdown_parts.append(f"\n## {title}\n")
                intro = s.get("intro", "")
                if intro:
                    markdown_parts.append(intro)
                for i, step in enumerate(s.get("steps", []), 1):
                    markdown_parts.append(f"\n### {i}. {step.get('label', '')}\n")
                    if step.get("explanation"):
                        markdown_parts.append(step["explanation"])
                    for bullet in step.get("bullets", []):
                        markdown_parts.append(f"- {bullet}")
                    if step.get("action"):
                        markdown_parts.append(f"\n**ACTION:** {step['action']}")
            elif sec_type == "scenarios":
                if title:
                    markdown_parts.append(f"\n## {title}\n")
                for sc in s.get("scenarios", []):
                    markdown_parts.append(f'**"{sc.get("situation", "")}"**')
                    markdown_parts.append(f"{sc.get('response', '')}\n")
            elif sec_type == "closing":
                markdown_parts.append(f"\n---\n\n**{s.get('headline', '')}**\n")
                for i, step in enumerate(s.get("recap_steps", []), 1):
                    markdown_parts.append(f"{i}. {step}")
                if s.get("cta"):
                    markdown_parts.append(f"\n*{s['cta']}*")
            elif sec_type == "callout":
                label = s.get("label", "NOTE")
                markdown_parts.append(f"\n> **{label}:** {s.get('content', '')}\n")
            else:
                # narrative or unknown
                if title:
                    markdown_parts.append(f"\n## {title}\n")
                content = s.get("content", "")
                if content:
                    markdown_parts.append(content)
        markdown_content = "\n".join(markdown_parts) if sections else None

        # Support reiteration: update existing guide instead of creating new
        existing_id = context.get("_existing_guide_id")
        if existing_id:
            record = await self.db.get(WeeklyGuide, uuid.UUID(str(existing_id)))
            if record:
                record.guide_title = guide.get("guide_title", record.guide_title)
                record.docx_path = docx_path
                record.markdown_content = markdown_content
                record.cta_keyword = guide.get(
                    "cta_keyword",
                    context.get("weekly_keyword", record.cta_keyword),
                )
                await self.db.flush()
                logger.info("saver.weekly_guide.updated", id=str(record.id))
                return record.id

        record = WeeklyGuide(
            week_start_date=date.today(),
            weekly_theme=guide.get(
                "weekly_theme",
                context.get("weekly_theme", ""),
            ),
            guide_title=guide.get("guide_title", "Weekly Guide"),
            docx_path=docx_path,
            markdown_content=markdown_content,
            cta_keyword=guide.get(
                "cta_keyword",
                context.get("weekly_keyword"),
            ),
        )
        self._add(record)
        await self.db.flush()
        logger.info("saver.weekly_guide", id=str(record.id))
        return record.id
