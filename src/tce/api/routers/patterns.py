"""Pattern template endpoints."""

import json
import logging
import statistics
import uuid
from collections import Counter
from typing import Any

import anthropic
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tce.agents.engagement_scorer import CONFIDENCE_MULTIPLIERS, EngagementScorer
from tce.db.session import get_db
from tce.models.creator_profile import CreatorProfile
from tce.models.pattern_template import PatternTemplate
from tce.models.post_example import PostExample
from tce.schemas.pattern_template import PatternTemplateCreate, PatternTemplateRead
from tce.services.cost_tracker import CostTracker
from tce.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/patterns", tags=["patterns"])

# In-memory enrichment status (this runs rarely, no need for DB)
_enrich_status: dict[str, Any] = {}


@router.post("/templates", response_model=PatternTemplateRead)
async def create_template(
    data: PatternTemplateCreate,
    db: AsyncSession = Depends(get_db),
) -> PatternTemplate:
    template = PatternTemplate(**data.model_dump())
    db.add(template)
    await db.flush()
    return template


@router.get("/templates", response_model=list[PatternTemplateRead])
async def list_templates(
    family: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[PatternTemplate]:
    query = select(PatternTemplate).order_by(PatternTemplate.template_family)
    if family:
        query = query.where(PatternTemplate.template_family == family)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/templates/enrich-status")
async def get_enrich_status() -> dict:
    """Return the current/last enrichment run status."""
    return _enrich_status or {"status": "never_run"}


@router.get("/templates/{template_id}", response_model=PatternTemplateRead)
async def get_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PatternTemplate:
    template = await db.get(PatternTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.post("/templates/enrich")
async def enrich_templates(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run the 4-phase template enrichment pipeline from corpus data."""
    global _enrich_status
    if _enrich_status.get("status") == "running":
        raise HTTPException(status_code=409, detail="Enrichment already running")

    _enrich_status = {"status": "running", "phase": 0, "detail": "Starting..."}

    # Run synchronously (it's fast enough - ~30s total for 112 posts, 38 templates)
    try:
        result = await _run_enrichment(db)
        _enrich_status = {"status": "completed", **result}
        return _enrich_status
    except Exception as e:
        logger.exception("Enrichment pipeline failed")
        _enrich_status = {"status": "error", "detail": str(e)}
        raise HTTPException(status_code=500, detail=str(e))


async def _run_enrichment(db: AsyncSession) -> dict:
    """Execute all 4 enrichment phases."""
    global _enrich_status
    s = Settings()
    api_key = s.anthropic_api_key
    if hasattr(api_key, "get_secret_value"):
        api_key = api_key.get_secret_value()
    client = anthropic.AsyncAnthropic(api_key=api_key)
    tracker = CostTracker(db)
    run_id = uuid.uuid4()

    # ── Phase 1: Score all posts ──
    _enrich_status = {"status": "running", "phase": 1, "detail": "Scoring posts..."}

    posts_result = await db.execute(
        select(PostExample).options(selectinload(PostExample.creator))
    )
    posts = list(posts_result.scalars().all())

    # Build context for EngagementScorer
    post_dicts = []
    for p in posts:
        post_dicts.append({
            "id": str(p.id),
            "visible_shares": p.visible_shares or 0,
            "visible_comments": p.visible_comments or 0,
            "engagement_confidence": p.engagement_confidence or "C",
            "creator_name": p.creator.creator_name if p.creator else "unknown",
            "hook_text": p.hook_text or "",
            "post_text_raw": p.post_text_raw or "",
        })

    # Use EngagementScorer logic directly (pure computation, no LLM)
    scorer = EngagementScorer.__new__(EngagementScorer)
    scorer.name = "engagement_scorer"
    scorer.reports = []

    def _report(msg: str) -> None:
        scorer.reports.append(msg)
    scorer._report = _report

    context = {"post_examples": post_dicts}
    scored_result = await scorer._execute(context)
    scored_posts = scored_result["scored_examples"]

    # Persist scores back to DB
    score_map = {p["id"]: (p.get("raw_score", 0), p.get("final_score", 0)) for p in scored_posts}
    scored_count = 0
    for p in posts:
        pid = str(p.id)
        if pid in score_map:
            p.raw_score = score_map[pid][0]
            p.final_score = score_map[pid][1]
            scored_count += 1
    await db.flush()

    # ── Phase 2: Classify posts into template families ──
    _enrich_status = {"status": "running", "phase": 2, "detail": "Classifying posts into template families..."}

    templates_result = await db.execute(select(PatternTemplate))
    templates = list(templates_result.scalars().all())
    family_list = sorted(set(t.template_family for t in templates))

    # Build classification batches (~40 posts each)
    batch_size = 40
    classified_count = 0
    for i in range(0, len(posts), batch_size):
        batch = posts[i:i + batch_size]
        post_entries = []
        for p in batch:
            text = (p.post_text_raw or p.hook_text or "")[:300]
            if text:
                post_entries.append({"id": str(p.id), "text": text})

        if not post_entries:
            continue

        system_prompt = (
            "You are a content analyst. Given social media posts and a list of template families, "
            "classify each post into the BEST matching template family. "
            "Return ONLY a JSON object: {\"post_id\": \"template_family\", ...}. "
            "Every post MUST be assigned to exactly one family from the list."
        )
        user_content = (
            f"Template families:\n{json.dumps(family_list)}\n\n"
            f"Posts to classify:\n{json.dumps(post_entries, indent=1)}"
        )

        resp = await client.messages.create(
            model=s.haiku_model,
            max_tokens=2048,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        await tracker.record(
            run_id=run_id,
            agent_name="template_enricher",
            model_used=s.haiku_model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

        try:
            raw_text = resp.content[0].text.strip()
            # Handle potential markdown code blocks
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            classifications = json.loads(raw_text)
            if isinstance(classifications, dict):
                post_lookup = {str(p.id): p for p in batch}
                for pid, family in classifications.items():
                    if pid in post_lookup and family in family_list:
                        post_lookup[pid].template_family = family
                        classified_count += 1
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.warning(f"Classification batch parse error: {e}")

    await db.flush()

    # ── Phase 3: Aggregate corpus stats per template ──
    _enrich_status = {"status": "running", "phase": 3, "detail": "Aggregating corpus stats..."}

    # Re-fetch posts with updated template_family
    posts_result2 = await db.execute(
        select(PostExample).options(selectinload(PostExample.creator))
    )
    posts = list(posts_result2.scalars().all())

    # Group posts by template_family
    family_posts: dict[str, list[PostExample]] = {}
    for p in posts:
        if p.template_family:
            family_posts.setdefault(p.template_family, []).append(p)

    enriched_count = 0
    for t in templates:
        matched = family_posts.get(t.template_family, [])
        if not matched:
            continue

        # example_ids
        t.example_ids = [str(p.id) for p in matched]
        t.sample_size = len(matched)

        # median_score
        scores = [p.final_score for p in matched if p.final_score is not None and p.final_score > 0]
        t.median_score = statistics.median(scores) if scores else None

        # confidence_avg
        conf_values = [
            CONFIDENCE_MULTIPLIERS.get(p.engagement_confidence or "C", 0.4)
            for p in matched
        ]
        t.confidence_avg = sum(conf_values) / len(conf_values) if conf_values else None

        # creator_diversity_count
        t.creator_diversity_count = len(set(p.creator_id for p in matched))

        # cta_compatibility
        ctas = [p.cta_type for p in matched if p.cta_type]
        t.cta_compatibility = sorted(set(ctas)) if ctas else None

        # visual_compatibility
        visuals = [p.visual_type for p in matched if p.visual_type]
        t.visual_compatibility = sorted(set(visuals)) if visuals else None

        # tone_profile (frequency map)
        tone_counter: Counter = Counter()
        for p in matched:
            if p.tone_tags:
                tone_counter.update(p.tone_tags)
        t.tone_profile = dict(tone_counter.most_common(10)) if tone_counter else None

        # proof_requirements (most common proof styles)
        proof_styles = [p.proof_style for p in matched if p.proof_style]
        if proof_styles:
            proof_counts = Counter(proof_styles)
            t.proof_requirements = ", ".join(s for s, _ in proof_counts.most_common(3))

        # source_influence_weights
        creator_counts: Counter = Counter()
        for p in matched:
            if p.creator:
                creator_counts[p.creator.creator_name] += 1
        t.source_influence_weights = dict(creator_counts) if creator_counts else None

        enriched_count += 1

    await db.flush()

    # ── Phase 4: AI-enrich template descriptions ──
    _enrich_status = {"status": "running", "phase": 4, "detail": "AI-enriching template descriptions..."}

    ai_enriched = 0
    for t in templates:
        if t.sample_size < 2:
            continue

        matched = family_posts.get(t.template_family, [])
        # Get top 3 examples by score
        top_examples = sorted(
            [p for p in matched if p.final_score],
            key=lambda p: p.final_score or 0,
            reverse=True,
        )[:3]

        if not top_examples:
            continue

        examples_text = "\n\n---\n\n".join(
            f"Example {i+1} (score: {p.final_score:.1f}):\n{(p.post_text_raw or p.hook_text or '')[:500]}"
            for i, p in enumerate(top_examples)
        )

        system_prompt = (
            "You are a content strategy analyst. Given a template formula and real example posts, "
            "produce enriched template metadata. Return ONLY a JSON object with these keys:\n"
            "- best_for: string (1-2 sentence description of ideal use case)\n"
            "- risk_notes: string (what could go wrong when using this template)\n"
            "- anti_patterns: string (what to avoid)\n"
            "No markdown, no explanation."
        )
        user_content = (
            f"Template: {t.template_name} ({t.template_family})\n"
            f"Hook formula: {t.hook_formula or 'N/A'}\n"
            f"Body formula: {t.body_formula or 'N/A'}\n\n"
            f"Top example posts:\n{examples_text}"
        )

        try:
            resp = await client.messages.create(
                model=s.haiku_model,
                max_tokens=512,
                temperature=0.3,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            await tracker.record(
                run_id=run_id,
                agent_name="template_enricher",
                model_used=s.haiku_model,
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            )

            raw_text = resp.content[0].text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            enrichment = json.loads(raw_text)

            if isinstance(enrichment, dict):
                if enrichment.get("best_for"):
                    t.best_for = enrichment["best_for"]
                if enrichment.get("risk_notes"):
                    t.risk_notes = enrichment["risk_notes"]
                if enrichment.get("anti_patterns"):
                    t.anti_patterns = enrichment["anti_patterns"]
                ai_enriched += 1
        except Exception as e:
            logger.warning(f"AI enrichment failed for {t.template_name}: {e}")

    # Update status for enriched templates
    for t in templates:
        if t.sample_size >= 3:
            t.status = "validated"
        elif t.sample_size >= 1:
            t.status = "provisional"

    await db.flush()
    await db.commit()

    return {
        "posts_scored": scored_count,
        "posts_classified": classified_count,
        "templates_enriched": enriched_count,
        "templates_ai_enriched": ai_enriched,
        "total_posts": len(posts),
        "total_templates": len(templates),
        "families_used": len(family_posts),
    }
