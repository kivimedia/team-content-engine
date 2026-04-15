"""Content management endpoints - PostPackage, WeeklyGuide, ImageAsset."""

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.post_package import PostPackage
from tce.models.weekly_guide import WeeklyGuide
from tce.settings import settings
from tce.schemas.post_package import PostPackageRead, PostPackageUpdate
from tce.schemas.weekly_guide import WeeklyGuideCreate, WeeklyGuideRead

router = APIRouter(prefix="/content", tags=["content"])


# Post packages
@router.get("/packages", response_model=list[PostPackageRead])
async def list_packages(
    status: str | None = None,
    include_archived: bool = False,
    pipeline_run_id: str | None = None,
    guide_id: str | None = None,
    source: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[PostPackage]:
    query = select(PostPackage).order_by(PostPackage.created_at.desc())
    if source:
        query = query.where(PostPackage.source == source)
    if pipeline_run_id:
        from sqlalchemy import cast, String
        query = query.where(
            cast(PostPackage.pipeline_run_id, String) == pipeline_run_id
        )
    if guide_id:
        try:
            gid = uuid.UUID(guide_id)
        except ValueError:
            return []
        query = query.where(PostPackage.weekly_guide_id == gid)
    if status:
        query = query.where(PostPackage.approval_status == status)
    if not include_archived:
        query = query.where(PostPackage.is_archived.is_(False))
    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/packages/{package_id}", response_model=PostPackageRead)
async def get_package(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PostPackage:
    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    return pkg


@router.patch("/packages/{package_id}", response_model=PostPackageRead)
async def update_package(
    package_id: uuid.UUID,
    data: PostPackageUpdate,
    db: AsyncSession = Depends(get_db),
) -> PostPackage:
    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(pkg, key, value)
    await db.flush()
    await db.refresh(pkg)
    return pkg


@router.post("/packages/{package_id}/approve", response_model=PostPackageRead)
async def approve_package(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PostPackage:
    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    pkg.approval_status = "approved"
    await db.flush()
    await db.refresh(pkg)
    return pkg


@router.post("/packages/{package_id}/reject", response_model=PostPackageRead)
async def reject_package(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PostPackage:
    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    pkg.approval_status = "rejected"
    await db.flush()
    await db.refresh(pkg)
    return pkg


@router.post("/packages/{package_id}/archive", response_model=PostPackageRead)
async def archive_package(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PostPackage:
    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    pkg.is_archived = True
    await db.flush()
    await db.refresh(pkg)
    return pkg


@router.post("/packages/{package_id}/unarchive", response_model=PostPackageRead)
async def unarchive_package(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PostPackage:
    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    pkg.is_archived = False
    await db.flush()
    await db.refresh(pkg)
    return pkg


async def _regenerate_hooks_for_package(pkg: PostPackage, db: AsyncSession) -> None:
    """Regenerate hook_variants from current post content via LLM."""
    import json

    import anthropic

    from tce.services.cost_tracker import CostTracker
    from tce.services.pipeline_saver import _clean_list
    from tce.settings import Settings

    if not pkg.facebook_post and not pkg.linkedin_post:
        return

    s = Settings()
    api_key = s.anthropic_api_key
    if hasattr(api_key, "get_secret_value"):
        api_key = api_key.get_secret_value()
    client = anthropic.AsyncAnthropic(api_key=api_key)

    system_prompt = (
        "You are a B2B social media content strategist. "
        "Given a social media post, generate 5 alternative opening hooks. "
        "Each hook must be 1-2 sentences max and could replace the current first line. "
        "The hooks MUST be about the SAME topic and message as the post. "
        "Return ONLY a JSON array of 5 strings. No explanation, no markdown."
    )

    hooks: list[str] = []
    tracker = CostTracker(db)
    for platform, text in [("Facebook", pkg.facebook_post), ("LinkedIn", pkg.linkedin_post)]:
        if not text:
            continue
        resp = await client.messages.create(
            model=s.haiku_model,
            max_tokens=512,
            temperature=0.7,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Platform: {platform}\n\nPost:\n{text}"}],
        )
        try:
            platform_hooks = json.loads(resp.content[0].text.strip())
            if isinstance(platform_hooks, list):
                hooks.extend([str(h) for h in platform_hooks[:5]])
        except (json.JSONDecodeError, IndexError):
            pass
        await tracker.record(
            run_id=uuid.uuid4(),
            agent_name="hook_regenerator",
            model_used=s.haiku_model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

    pkg.hook_variants = _clean_list(hooks) if hooks else None


@router.post("/packages/backfill-hooks")
async def backfill_hooks(db: AsyncSession = Depends(get_db)) -> dict:
    """Regenerate hooks for ALL non-archived packages from their current post content."""
    result = await db.execute(
        select(PostPackage)
        .where(PostPackage.is_archived.is_(False))
        .order_by(PostPackage.created_at.desc())
    )
    packages = list(result.scalars().all())
    total = len(packages)
    updated = 0
    errors: list[dict] = []
    for pkg in packages:
        if not pkg.facebook_post and not pkg.linkedin_post:
            continue
        try:
            await _regenerate_hooks_for_package(pkg, db)
            updated += 1
        except Exception as e:
            errors.append({"id": str(pkg.id), "error": str(e)})
    await db.flush()
    return {"total": total, "updated": updated, "errors": errors}


@router.post("/packages/{package_id}/regenerate-hooks", response_model=PostPackageRead)
async def regenerate_hooks(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PostPackage:
    """Regenerate hook_variants from current post content via LLM."""
    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if not pkg.facebook_post and not pkg.linkedin_post:
        raise HTTPException(status_code=400, detail="No post content to generate hooks from")
    await _regenerate_hooks_for_package(pkg, db)
    await db.flush()
    await db.refresh(pkg)
    return pkg


@router.post("/packages/{package_id}/generate-images")
async def generate_images(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate images for a package's prompts using fal.ai."""
    from tce.models.image_asset import ImageAsset
    from tce.services.image_generation import ImageGenerationService

    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if not pkg.image_prompts:
        raise HTTPException(status_code=400, detail="No image prompts in this package")

    svc = ImageGenerationService()
    results = await svc.generate_batch(pkg.image_prompts)

    # Update existing ImageAsset rows or create new ones
    existing = await db.execute(select(ImageAsset).where(ImageAsset.package_id == package_id))
    existing_assets = list(existing.scalars().all())

    generated = []
    for i, result in enumerate(results):
        if result.get("status") == "skipped":
            generated.append({"index": i, "status": "skipped", "reason": result.get("reason")})
            continue
        if result.get("status") == "failed":
            generated.append({"index": i, "status": "failed", "error": result.get("error")})
            continue

        # Update existing asset or create new one
        if i < len(existing_assets):
            asset = existing_assets[i]
        else:
            asset = ImageAsset(
                package_id=package_id,
                prompt_text=result.get("prompt_text", ""),
            )
            db.add(asset)

        asset.image_url = result.get("image_url")
        asset.image_s3_path = result.get("image_s3_path")
        asset.fal_model_used = result.get("fal_model_used")
        asset.fal_request_id = result.get("fal_request_id")
        asset.generation_time_seconds = result.get("generation_time_seconds")
        asset.generation_cost_usd = result.get("generation_cost_usd")

        generated.append(
            {
                "index": i,
                "status": "generated",
                "image_url": result.get("image_url"),
                "time": result.get("generation_time_seconds"),
            }
        )

    # Also update image_prompts JSONB with URLs for dashboard display
    # Deep-copy to ensure SQLAlchemy detects the JSONB mutation
    import json as _json
    updated_prompts = _json.loads(_json.dumps(pkg.image_prompts))
    for g in generated:
        idx = g["index"]
        if g["status"] == "generated" and idx < len(updated_prompts):
            updated_prompts[idx]["image_url"] = g["image_url"]
    pkg.image_prompts = updated_prompts

    await db.flush()
    await db.refresh(pkg)

    return {"package_id": str(package_id), "results": generated}


@router.get("/packages/{package_id}/context")
async def get_package_context(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get explainability context for a package - story brief, research brief, plan context."""
    from tce.models.content_calendar import ContentCalendarEntry as ContentCalendar
    from tce.models.research_brief import ResearchBrief
    from tce.models.story_brief import StoryBrief

    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    context: dict = {"package_id": str(package_id)}

    # Story brief
    if pkg.brief_id:
        brief = await db.get(StoryBrief, pkg.brief_id)
        if brief:
            context["story_brief"] = {
                "topic": brief.topic,
                "audience": brief.audience,
                "angle_type": brief.angle_type,
                "thesis": brief.thesis,
                "desired_belief_shift": brief.desired_belief_shift,
                "evidence_requirements": brief.evidence_requirements,
                "cta_goal": brief.cta_goal,
                "visual_job": brief.visual_job,
                "house_voice_weights": brief.house_voice_weights,
            }

    # Research brief (find closest by topic from story brief)
    if context.get("story_brief", {}).get("topic"):
        topic_search = context["story_brief"]["topic"][:60]
        res_result = await db.execute(
            select(ResearchBrief)
            .where(ResearchBrief.topic.ilike(f"%{topic_search}%"))
            .order_by(ResearchBrief.created_at.desc())
            .limit(1)
        )
        research = res_result.scalar_one_or_none()
        if research:
            context["research_brief"] = {
                "topic": research.topic,
                "verified_claims": research.verified_claims,
                "uncertain_claims": research.uncertain_claims,
                "source_refs": research.source_refs,
                "safe_to_publish": research.safe_to_publish,
                "risk_flags": research.risk_flags,
                "thesis_candidates": research.thesis_candidates,
            }

    # Plan context from calendar entry
    cal_result = await db.execute(
        select(ContentCalendar)
        .where(ContentCalendar.post_package_id == package_id)
        .limit(1)
    )
    cal_entry = cal_result.scalar_one_or_none()
    if cal_entry:
        context["calendar"] = {
            "date": str(cal_entry.date),
            "day_of_week": cal_entry.day_of_week,
            "angle_type": cal_entry.angle_type,
            "topic": cal_entry.topic,
            "operator_notes": cal_entry.operator_notes,
        }
        if cal_entry.plan_context:
            context["plan_context"] = cal_entry.plan_context

    # Proof trail from proof_checker agent
    if pkg.proof_trail:
        context["proof_trail"] = pkg.proof_trail
    if pkg.proof_status:
        context["proof_status"] = pkg.proof_status

    return context


@router.get("/search")
async def search_content(
    q: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Search across packages, briefs, and templates."""
    from tce.models.pattern_template import PatternTemplate
    from tce.models.story_brief import StoryBrief

    results = []
    search_term = f"%{q}%"

    # Search packages
    pkg_result = await db.execute(
        select(PostPackage)
        .where(
            (PostPackage.facebook_post.ilike(search_term))
            | (PostPackage.linkedin_post.ilike(search_term))
            | (PostPackage.cta_keyword.ilike(search_term))
        )
        .limit(20)
    )
    for pkg in pkg_result.scalars().all():
        results.append({
            "type": "package",
            "id": str(pkg.id),
            "title": (pkg.facebook_post or "")[:80],
            "status": pkg.approval_status,
            "cta": pkg.cta_keyword,
            "date": str(pkg.created_at),
        })

    # Search story briefs
    brief_result = await db.execute(
        select(StoryBrief)
        .where(
            (StoryBrief.topic.ilike(search_term))
            | (StoryBrief.thesis.ilike(search_term))
        )
        .limit(10)
    )
    for b in brief_result.scalars().all():
        results.append({
            "type": "brief",
            "id": str(b.id),
            "title": b.topic or "",
            "thesis": b.thesis,
            "date": str(b.created_at),
        })

    # Search templates
    tmpl_result = await db.execute(
        select(PatternTemplate)
        .where(
            (PatternTemplate.template_name.ilike(search_term))
            | (PatternTemplate.template_family.ilike(search_term))
            | (PatternTemplate.best_for.ilike(search_term))
        )
        .limit(10)
    )
    for t in tmpl_result.scalars().all():
        results.append({
            "type": "template",
            "id": str(t.id),
            "title": t.template_name,
            "family": t.template_family,
        })

    return results


@router.post("/packages/cleanup-dashes")
async def cleanup_dashes(db: AsyncSession = Depends(get_db)) -> dict:
    """One-time cleanup: replace emdashes/en dashes in all existing packages."""
    from tce.services.pipeline_saver import _clean_dict, _clean_list, _clean_text

    result = await db.execute(select(PostPackage))
    packages = list(result.scalars().all())
    fixed = 0
    _dash_chars = "\u2014\u2013\u2015\u2012\u2053\u2E3A\u2E3B\uFE58\uFF0D"
    def _has_bad_dash(s: str) -> bool:
        return any(c in s for c in _dash_chars) or "--" in s

    for pkg in packages:
        changed = False
        if pkg.facebook_post and _has_bad_dash(pkg.facebook_post):
            pkg.facebook_post = _clean_text(pkg.facebook_post)
            changed = True
        if pkg.linkedin_post and _has_bad_dash(pkg.linkedin_post):
            pkg.linkedin_post = _clean_text(pkg.linkedin_post)
            changed = True
        if pkg.hook_variants:
            cleaned = _clean_list(pkg.hook_variants)
            if cleaned != pkg.hook_variants:
                pkg.hook_variants = cleaned
                changed = True
        if pkg.dm_flow:
            cleaned = _clean_dict(pkg.dm_flow)
            if cleaned != pkg.dm_flow:
                pkg.dm_flow = cleaned
                changed = True
        if changed:
            fixed += 1
    await db.flush()
    return {"total": len(packages), "fixed": fixed}


@router.post("/packages/{package_id}/export")
async def export_package(
    package_id: uuid.UUID,
    platform: str = "manual",
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Export a package for publishing (copy-paste ready)."""
    from tce.services.publishing import get_adapter

    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    adapter = get_adapter(platform)
    package_dict = {
        "facebook_post": pkg.facebook_post,
        "linkedin_post": pkg.linkedin_post,
        "hook_variants": pkg.hook_variants,
        "cta_keyword": pkg.cta_keyword,
        "dm_flow": pkg.dm_flow,
    }
    return await adapter.publish(package_dict)


# Weekly guides
@router.post("/guides", response_model=WeeklyGuideRead)
async def create_guide(
    data: WeeklyGuideCreate,
    db: AsyncSession = Depends(get_db),
) -> WeeklyGuide:
    guide = WeeklyGuide(**data.model_dump())
    db.add(guide)
    await db.flush()
    return guide


@router.get("/guides", response_model=list[WeeklyGuideRead])
async def list_guides(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[WeeklyGuide]:
    query = select(WeeklyGuide).order_by(WeeklyGuide.week_start_date.desc())
    if not include_archived:
        query = query.where(WeeklyGuide.is_archived.is_(False))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/guides/{guide_id}", response_model=WeeklyGuideRead)
async def get_guide(
    guide_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WeeklyGuide:
    guide = await db.get(WeeklyGuide, guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")
    return guide


@router.post("/guides/{guide_id}/archive", response_model=WeeklyGuideRead)
async def archive_guide(
    guide_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WeeklyGuide:
    guide = await db.get(WeeklyGuide, guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")
    guide.is_archived = True
    await db.flush()
    await db.refresh(guide)
    return guide


@router.post("/guides/{guide_id}/unarchive", response_model=WeeklyGuideRead)
async def unarchive_guide(
    guide_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WeeklyGuide:
    guide = await db.get(WeeklyGuide, guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")
    guide.is_archived = False
    await db.flush()
    await db.refresh(guide)
    return guide


@router.get("/guides/{guide_id}/download")
async def download_guide(
    guide_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Download the guide DOCX file."""
    guide = await db.get(WeeklyGuide, guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")
    if not guide.docx_path:
        raise HTTPException(status_code=404, detail="No DOCX file generated for this guide")
    docx_file = Path(guide.docx_path)
    if not docx_file.exists():
        # Regenerate DOCX from markdown content if available
        if guide.markdown_content:
            import tempfile

            from tce.utils.docx import create_guide_docx

            tmp_dir = tempfile.mkdtemp(prefix="tce_guide_")
            sections = [{"type": "narrative", "title": guide.guide_title, "content": guide.markdown_content}]
            docx_file = Path(create_guide_docx(guide.guide_title, "", sections, tmp_dir))
            guide.docx_path = str(docx_file)
            await db.flush()
        else:
            raise HTTPException(status_code=404, detail="DOCX file not found and no content to regenerate")
    return FileResponse(
        path=str(docx_file),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{guide.guide_title}.docx",
    )


# In-memory regen progress (UI feedback only, not critical state)
_regen_progress: dict[str, dict] = {}


@router.get("/guides/{guide_id}/regen-status")
async def get_regen_status(guide_id: uuid.UUID) -> dict:
    """Poll regeneration/generation progress by guide ID or tracking ID."""
    status = _regen_progress.get(str(guide_id))
    if not status:
        return {"status": "idle"}
    return status


@router.get("/generation-status/{tracking_id}")
async def get_tracking_status(tracking_id: str) -> dict:
    """Poll generation progress by tracking ID (for generate-from-post)."""
    status = _regen_progress.get(tracking_id)
    if not status:
        return {"status": "idle"}
    return status


@router.post("/guides/{guide_id}/regenerate")
async def regenerate_guide(
    guide_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    operator_feedback: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Regenerate a guide with quality gate iteration loop.

    Loads context from associated post packages (story briefs, research briefs),
    then runs the guide builder up to 3 times until composite >= 8.0.
    Runs in background so the endpoint returns immediately.

    Optional operator_feedback: free-text instructions injected into the quality
    feedback prompt (e.g. "accuracy is too low, cite more sources").
    """
    guide = await db.get(WeeklyGuide, guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")

    gid = str(guide_id)
    if _regen_progress.get(gid, {}).get("status") == "running":
        return {"status": "already_running", "guide_id": gid}

    from datetime import datetime, timezone
    _regen_progress[gid] = {
        "status": "running",
        "attempt": 0,
        "detail": "Starting...",
        "phase": 0,
        "total_phases": 4,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "step_status": {},
        "step_logs": {},
        "research_summary": None,
        "scores": None,
        "score_history": [],
        "operator_feedback": operator_feedback,
    }

    # Kick off regeneration in background
    background_tasks.add_task(_regenerate_guide_task, gid, operator_feedback)
    return {"status": "started", "guide_id": gid}


async def _run_orch_with_live_status(
    orch: "PipelineOrchestrator",
    ctx: dict,
    guide_id_str: str,
    phase_label: str,
) -> dict:
    """Run orchestrator while forwarding live step_status + step_logs to _regen_progress."""
    import asyncio

    result_holder: dict = {"result": None, "error": None, "done": False}

    async def _run() -> None:
        try:
            result_holder["result"] = await orch.run(ctx)
        except Exception as e:
            result_holder["error"] = e
        finally:
            result_holder["done"] = True

    task = asyncio.create_task(_run())
    while not result_holder["done"]:
        await asyncio.sleep(2)
        status = orch.get_status()
        existing = _regen_progress.get(guide_id_str, {})
        existing.update({
            "step_status": status.get("step_status", {}),
            "step_logs": status.get("step_logs", {}),
            "phase_label": phase_label,
        })
        _regen_progress[guide_id_str] = existing
    await task
    # Final status snapshot
    final_status = orch.get_status()
    existing = _regen_progress.get(guide_id_str, {})
    existing.update({
        "step_status": final_status.get("step_status", {}),
        "step_logs": final_status.get("step_logs", {}),
    })
    _regen_progress[guide_id_str] = existing
    if result_holder["error"]:
        raise result_holder["error"]
    return result_holder["result"]


async def _regenerate_guide_task(
    guide_id_str: str, operator_feedback: str | None = None
) -> None:
    """Background task: run full pipeline (research + strategy + guide) with quality gate.

    Phase 1: Trend Scout - find real trending stories with sources
    Phase 2: Story Strategist - pick an angle + thesis + evidence requirements
    Phase 3: Research Agent - verify claims via web search, produce cited sources
    Phase 4: Guide Builder - generate guide from verified research (iterate up to 3x)
    """
    import structlog
    from datetime import datetime

    from tce.db.session import async_session
    from tce.orchestrator.engine import PipelineOrchestrator
    from tce.orchestrator.workflows import WORKFLOWS
    from tce.models.pipeline_run import PipelineRun
    from tce.services.guide_assessor import (
        MAX_ITERATIONS,
        QUALITY_THRESHOLD,
        assess_guide_content,
        build_feedback_prompt,
    )

    logger = structlog.get_logger()
    guide_uuid = uuid.UUID(guide_id_str)
    prog = _regen_progress

    def _update(detail: str, **extra: object) -> None:
        existing = prog.get(guide_id_str, {})
        existing.update({"status": "running", "detail": detail, **extra})
        prog[guide_id_str] = existing

    _update("Loading guide context and founder voice...")

    # --- Load existing guide info + founder voice ---
    async with async_session() as db:
        guide = await db.get(WeeklyGuide, guide_uuid)
        if not guide:
            prog[guide_id_str] = {"status": "error", "detail": "Guide not found"}
            return

        guide_theme = guide.weekly_theme or guide.guide_title or ""
        guide_keyword = guide.cta_keyword or "guide"

        # Build base context for the full pipeline
        guide_context: dict = {
            "topic": guide_theme,
            "weekly_theme": guide_theme,
            "weekly_keyword": guide_keyword,
            "scan_type": "weekly",
            "_existing_guide_id": guide_id_str,
        }

        # Load founder voice profile
        try:
            from tce.models.founder_voice_profile import FounderVoiceProfile
            fv_result = await db.execute(
                select(FounderVoiceProfile).order_by(
                    FounderVoiceProfile.created_at.desc()
                ).limit(1)
            )
            fv = fv_result.scalar_one_or_none()
            if fv:
                guide_context["founder_voice"] = {
                    "recurring_themes": fv.recurring_themes or [],
                    "values_and_beliefs": fv.values_and_beliefs or [],
                    "taboos": fv.taboos or [],
                    "tone_range": fv.tone_range or {},
                    "humor_type": fv.humor_type,
                    "metaphor_families": fv.metaphor_families or [],
                }
                guide_context["house_voice_config"] = {
                    "author_name": getattr(fv, "creator_name", "Ziv Raviv"),
                    "author_url": "zivraviv.com",
                }
        except Exception:
            pass

        # If existing quality scores, inject feedback
        if guide.quality_scores and guide.quality_scores.get("composite", 10) < QUALITY_THRESHOLD:
            feedback = build_feedback_prompt(
                guide.quality_scores,
                guide.iteration_count or 1,
            )
            if operator_feedback:
                feedback += (
                    "\n\n--- OPERATOR INSTRUCTIONS (highest priority) ---\n"
                    f"{operator_feedback}\n"
                    "--- END OPERATOR INSTRUCTIONS ---"
                )
            guide_context["_quality_feedback"] = feedback
        elif operator_feedback:
            # No prior scores but operator has specific instructions
            guide_context["_quality_feedback"] = (
                "\n--- OPERATOR INSTRUCTIONS (highest priority) ---\n"
                f"{operator_feedback}\n"
                "--- END OPERATOR INSTRUCTIONS ---"
            )

    # --- Phase 1: Run trend_scout + story_strategist + research_agent ---
    # Use weekly_planning workflow steps MINUS docx_guide_builder
    # (we'll run the guide builder separately in the quality gate loop)
    research_steps = [
        s for s in WORKFLOWS["weekly_planning"]
        if s.agent_name != "docx_guide_builder"
    ]

    _update("Phase 1/4: Running research pipeline (trend scout, strategist, research agent)...", phase=1, total_phases=4)
    logger.info("regenerate_guide.research_phase", guide_id=guide_id_str)

    research_run_id = uuid.uuid4()
    async with async_session() as run_db:
        run_record = PipelineRun(
            run_id=research_run_id,
            workflow="guide_research",
            status="running",
            started_at=datetime.utcnow(),
        )
        run_db.add(run_record)
        await run_db.commit()
        run_record_id = run_record.id

        orch = PipelineOrchestrator(
            steps=research_steps,
            db=run_db,
            settings=settings,
            run_id=research_run_id,
        )

        research_result = await _run_orch_with_live_status(
            orch, guide_context, guide_id_str, "Research Phase"
        )

    # Update run record
    async with async_session() as bk_db:
        run_record = await bk_db.get(PipelineRun, run_record_id)
        if run_record:
            has_failures = any(
                v == "failed"
                for v in research_result.get("step_status", {}).values()
            )
            run_record.status = "failed" if has_failures else "completed"
            run_record.completed_at = datetime.utcnow()
            run_record.step_results = research_result.get("step_status", {})
            await bk_db.commit()

    # Extract research results into context for guide builder
    research_ctx = research_result.get("context", {})
    step_status = research_result.get("step_status", {})

    # Report what we found
    trend_brief = research_ctx.get("trend_brief", {})
    story_brief = research_ctx.get("story_brief", {})
    research_brief = research_ctx.get("research_brief", {})
    trends_found = len(trend_brief.get("trends", []))
    claims_found = len(research_brief.get("verified_claims", []))
    sources_found = len(research_brief.get("source_refs", []))

    logger.info(
        "regenerate_guide.research_done",
        trends=trends_found,
        claims=claims_found,
        sources=sources_found,
        step_status=step_status,
    )

    _update(
        f"Research complete: {trends_found} trends, {claims_found} verified claims, "
        f"{sources_found} sources. Starting guide generation...",
        research_summary={"trends": trends_found, "claims": claims_found, "sources": sources_found},
    )

    if claims_found == 0:
        logger.warning("regenerate_guide.no_claims")
        # Still proceed - guide builder will do its best

    # Merge research context into guide context for the guide builder
    for key in ("trend_brief", "story_brief", "research_brief", "cta_package"):
        if key in research_ctx:
            guide_context[key] = research_ctx[key]

    # --- Phase 2-4: Guide builder with quality gate loop ---
    guide_steps = WORKFLOWS["guide_only"]
    best_composite = 0.0

    for attempt in range(1, MAX_ITERATIONS + 1):
        logger.info("regenerate_guide.guide_attempt", attempt=attempt)
        phase_num = attempt + 1  # phase 2, 3, 4
        _update(
            f"Phase {phase_num}/4: Writing guide (attempt {attempt}/{MAX_ITERATIONS}) "
            f"with {claims_found} verified claims...",
            attempt=attempt,
            max_attempts=MAX_ITERATIONS,
            phase=phase_num,
            total_phases=4,
        )

        run_id = uuid.uuid4()
        async with async_session() as run_db:
            run_record = PipelineRun(
                run_id=run_id,
                workflow="guide_only",
                status="running",
                started_at=datetime.utcnow(),
            )
            run_db.add(run_record)
            await run_db.commit()
            run_record_id = run_record.id

            orch = PipelineOrchestrator(
                steps=guide_steps,
                db=run_db,
                settings=settings,
                run_id=run_id,
            )
            result = await _run_orch_with_live_status(
                orch, guide_context, guide_id_str,
                f"Writing Guide (attempt {attempt}/{MAX_ITERATIONS})",
            )

        async with async_session() as bk_db:
            run_record = await bk_db.get(PipelineRun, run_record_id)
            if run_record:
                has_failures = any(
                    v == "failed"
                    for v in result.get("step_status", {}).values()
                )
                run_record.status = "failed" if has_failures else "completed"
                run_record.completed_at = datetime.utcnow()
                run_record.step_results = result.get("step_status", {})
                await bk_db.commit()

        new_guide_id = result.get("context", {}).get("_weekly_guide_id")
        if not new_guide_id:
            logger.warning("regenerate_guide.no_guide_id", attempt=attempt)
            prog[guide_id_str] = {
                "status": "error",
                "detail": f"Guide generation failed (attempt {attempt})",
            }
            break

        _update(
            f"Assessing quality (attempt {attempt}/{MAX_ITERATIONS})...",
            attempt=attempt,
            max_attempts=MAX_ITERATIONS,
            phase=attempt + 1,
        )

        # Assess
        async with async_session() as assess_db:
            guide_obj = await assess_db.get(
                WeeklyGuide, uuid.UUID(str(new_guide_id))
            )
            if not guide_obj or not guide_obj.markdown_content:
                logger.warning("regenerate_guide.no_content", attempt=attempt)
                prog[guide_id_str] = {
                    "status": "error",
                    "detail": "Guide generated but has no content",
                }
                break

            try:
                scores = await assess_guide_content(
                    markdown_content=guide_obj.markdown_content,
                    guide_title=guide_obj.guide_title,
                    settings=settings,
                    db=assess_db,
                )
            except Exception as ae:
                logger.exception("regenerate_guide.assess_failed", attempt=attempt)
                scores = {"error": str(ae), "composite": 0}

            composite = scores.get("composite", 0.0)
            best_composite = composite

            # Get per-dimension breakdown for status
            dims = ["practical", "valuable", "generous", "accurate", "quick_win", "transformation"]
            dim_summary = ", ".join(
                f"{d[:4]}:{scores.get(d, {}).get('score', '?')}"
                for d in dims
                if isinstance(scores.get(d), dict)
            )

            history = guide_obj.assessment_history or []
            history.append({"iteration": attempt, **scores})
            guide_obj.assessment_history = history
            guide_obj.iteration_count = attempt
            guide_obj.quality_scores = scores

            # Build per-dimension scores dict for frontend
            dim_scores = {}
            for d in dims:
                val = scores.get(d)
                if isinstance(val, dict):
                    dim_scores[d] = val.get("score", 0)

            # Append to score history
            existing_prog = prog.get(guide_id_str, {})
            score_history = existing_prog.get("score_history", [])
            score_history.append({
                "attempt": attempt,
                "composite": composite,
                **dim_scores,
            })

            if composite >= QUALITY_THRESHOLD:
                guide_obj.quality_gate_passed = True
                await assess_db.commit()
                existing_prog.update({
                    "status": "done",
                    "attempt": attempt,
                    "composite": composite,
                    "passed": True,
                    "scores": dim_scores,
                    "score_history": score_history,
                    "detail": (
                        f"Passed! Score: {composite:.1f}/10 (attempt {attempt}). "
                        f"[{dim_summary}]"
                    ),
                })
                prog[guide_id_str] = existing_prog
                break
            elif attempt == MAX_ITERATIONS:
                guide_obj.quality_gate_passed = False
                await assess_db.commit()
                existing_prog.update({
                    "status": "done",
                    "attempt": attempt,
                    "composite": composite,
                    "passed": False,
                    "scores": dim_scores,
                    "score_history": score_history,
                    "detail": (
                        f"Best: {composite:.1f}/10 after {attempt} attempts. "
                        f"[{dim_summary}]"
                    ),
                })
                prog[guide_id_str] = existing_prog
            else:
                guide_obj.quality_gate_passed = None
                await assess_db.commit()
                feedback = build_feedback_prompt(scores, attempt)
                if operator_feedback:
                    feedback += (
                        "\n\n--- OPERATOR INSTRUCTIONS (highest priority) ---\n"
                        f"{operator_feedback}\n"
                        "--- END OPERATOR INSTRUCTIONS ---"
                    )
                guide_context["_quality_feedback"] = feedback
                guide_context["_existing_guide_id"] = str(new_guide_id)
                _update(
                    f"Score {composite:.1f}/10 [{dim_summary}] - "
                    f"reiterating with feedback (attempt {attempt + 1} next)...",
                    attempt=attempt,
                    max_attempts=MAX_ITERATIONS,
                    composite=composite,
                    scores=dim_scores,
                    score_history=score_history,
                    phase=attempt + 2,
                )


class GenerateFromPostRequest(BaseModel):
    post_text: str
    cta_keyword: str = "guide"
    operator_feedback: str | None = None


@router.post("/guides/generate-from-post")
async def generate_guide_from_post(
    body: GenerateFromPostRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Generate a new guide based on a specific social media post.

    Takes the post text, extracts the promise/topic, runs research pipeline,
    then generates a guide that delivers on that promise. Quality gate loop
    iterates up to 3 times.
    """
    # Use a synthetic ID for progress tracking (no existing guide yet)
    tracking_id = str(uuid.uuid4())

    from datetime import datetime, timezone
    _regen_progress[tracking_id] = {
        "status": "running",
        "attempt": 0,
        "detail": "Starting from post...",
        "phase": 0,
        "total_phases": 4,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "step_status": {},
        "step_logs": {},
        "research_summary": None,
        "scores": None,
        "score_history": [],
        "operator_feedback": body.operator_feedback,
        "from_post": True,
    }

    background_tasks.add_task(
        _generate_from_post_task,
        tracking_id,
        body.post_text,
        body.cta_keyword,
        body.operator_feedback,
    )
    return {"status": "started", "tracking_id": tracking_id}


async def _generate_from_post_task(
    tracking_id: str,
    post_text: str,
    cta_keyword: str,
    operator_feedback: str | None = None,
) -> None:
    """Generate a new guide from a social media post's promise."""
    import structlog
    from datetime import datetime

    from tce.db.session import async_session
    from tce.orchestrator.engine import PipelineOrchestrator
    from tce.orchestrator.workflows import WORKFLOWS
    from tce.models.pipeline_run import PipelineRun
    from tce.services.guide_assessor import (
        MAX_ITERATIONS,
        QUALITY_THRESHOLD,
        assess_guide_content,
        build_feedback_prompt,
    )

    logger = structlog.get_logger()
    prog = _regen_progress

    def _update(detail: str, **extra: object) -> None:
        existing = prog.get(tracking_id, {})
        existing.update({"status": "running", "detail": detail, **extra})
        prog[tracking_id] = existing

    _update("Extracting topic from post and loading founder voice...")

    # Extract a topic/theme from the post (first 200 chars or the promise)
    post_lines = [l.strip() for l in post_text.strip().split("\n") if l.strip()]
    # Use the first substantial line as topic, full post as context
    topic = post_lines[0][:200] if post_lines else "AI infrastructure"

    guide_context: dict = {
        "topic": topic,
        "weekly_theme": topic,
        "weekly_keyword": cta_keyword,
        "scan_type": "weekly",
        # Pass the full post so the guide builder knows what promise to deliver on
        "_source_post": post_text,
    }

    # Load founder voice
    async with async_session() as db:
        try:
            from tce.models.founder_voice_profile import FounderVoiceProfile
            fv_result = await db.execute(
                select(FounderVoiceProfile).order_by(
                    FounderVoiceProfile.created_at.desc()
                ).limit(1)
            )
            fv = fv_result.scalar_one_or_none()
            if fv:
                guide_context["founder_voice"] = {
                    "recurring_themes": fv.recurring_themes or [],
                    "values_and_beliefs": fv.values_and_beliefs or [],
                    "taboos": fv.taboos or [],
                    "tone_range": fv.tone_range or {},
                    "humor_type": fv.humor_type,
                    "metaphor_families": fv.metaphor_families or [],
                }
                guide_context["house_voice_config"] = {
                    "author_name": getattr(fv, "creator_name", "Ziv Raviv"),
                    "author_url": "zivraviv.com",
                }
        except Exception:
            pass

    # Inject operator feedback + source post instructions
    post_instruction = (
        "\n--- SOURCE POST (the guide MUST deliver on this post's promise) ---\n"
        f"{post_text}\n"
        "--- END SOURCE POST ---\n\n"
        "The reader commented the CTA keyword on the above post. "
        "Your guide MUST directly deliver on whatever the post promised. "
        "Match the topic, angle, and specificity of the post. "
        "The guide is the payoff - make it worth the comment."
    )
    if operator_feedback:
        post_instruction += (
            "\n\n--- OPERATOR INSTRUCTIONS (highest priority) ---\n"
            f"{operator_feedback}\n"
            "--- END OPERATOR INSTRUCTIONS ---"
        )
    guide_context["_quality_feedback"] = post_instruction

    # --- Phase 1: Research ---
    research_steps = [
        s for s in WORKFLOWS["weekly_planning"]
        if s.agent_name != "docx_guide_builder"
    ]

    _update(
        "Phase 1/4: Running research pipeline on post topic...",
        phase=1, total_phases=4,
    )
    logger.info("generate_from_post.research_phase", tracking_id=tracking_id)

    research_run_id = uuid.uuid4()
    async with async_session() as run_db:
        run_record = PipelineRun(
            run_id=research_run_id,
            workflow="guide_from_post_research",
            status="running",
            started_at=datetime.utcnow(),
        )
        run_db.add(run_record)
        await run_db.commit()
        run_record_id = run_record.id

        orch = PipelineOrchestrator(
            steps=research_steps,
            db=run_db,
            settings=settings,
            run_id=research_run_id,
        )
        research_result = await _run_orch_with_live_status(
            orch, guide_context, tracking_id, "Research Phase"
        )

    # Update run record
    async with async_session() as bk_db:
        run_record = await bk_db.get(PipelineRun, run_record_id)
        if run_record:
            has_failures = any(
                v == "failed"
                for v in research_result.get("step_status", {}).values()
            )
            run_record.status = "failed" if has_failures else "completed"
            run_record.completed_at = datetime.utcnow()
            run_record.step_results = research_result.get("step_status", {})
            await bk_db.commit()

    # Extract research context
    research_ctx = research_result.get("context", {})
    trend_brief = research_ctx.get("trend_brief", {})
    research_brief = research_ctx.get("research_brief", {})
    trends_found = len(trend_brief.get("trends", []))
    claims_found = len(research_brief.get("verified_claims", []))
    sources_found = len(research_brief.get("source_refs", []))

    _update(
        f"Research complete: {trends_found} trends, {claims_found} verified claims, "
        f"{sources_found} sources. Starting guide generation...",
        research_summary={"trends": trends_found, "claims": claims_found, "sources": sources_found},
    )

    # Merge research into guide context
    for key in ("trend_brief", "story_brief", "research_brief", "cta_package"):
        if key in research_ctx:
            guide_context[key] = research_ctx[key]

    # --- Phases 2-4: Guide builder with quality gate ---
    guide_steps = WORKFLOWS["guide_only"]
    dims = ["practical", "valuable", "generous", "accurate", "quick_win", "transformation"]

    for attempt in range(1, MAX_ITERATIONS + 1):
        phase_num = attempt + 1
        _update(
            f"Phase {phase_num}/4: Writing guide (attempt {attempt}/{MAX_ITERATIONS})...",
            attempt=attempt, max_attempts=MAX_ITERATIONS,
            phase=phase_num, total_phases=4,
        )

        run_id = uuid.uuid4()
        async with async_session() as run_db:
            run_record = PipelineRun(
                run_id=run_id,
                workflow="guide_from_post",
                status="running",
                started_at=datetime.utcnow(),
            )
            run_db.add(run_record)
            await run_db.commit()
            run_record_id = run_record.id

            orch = PipelineOrchestrator(
                steps=guide_steps,
                db=run_db,
                settings=settings,
                run_id=run_id,
            )
            result = await _run_orch_with_live_status(
                orch, guide_context, tracking_id,
                f"Writing Guide (attempt {attempt}/{MAX_ITERATIONS})",
            )

        async with async_session() as bk_db:
            run_record = await bk_db.get(PipelineRun, run_record_id)
            if run_record:
                has_failures = any(
                    v == "failed"
                    for v in result.get("step_status", {}).values()
                )
                run_record.status = "failed" if has_failures else "completed"
                run_record.completed_at = datetime.utcnow()
                run_record.step_results = result.get("step_status", {})
                await bk_db.commit()

        new_guide_id = result.get("context", {}).get("_weekly_guide_id")
        if not new_guide_id:
            prog[tracking_id] = {
                "status": "error",
                "detail": f"Guide generation failed (attempt {attempt})",
            }
            break

        _update(
            f"Assessing quality (attempt {attempt}/{MAX_ITERATIONS})...",
            attempt=attempt, max_attempts=MAX_ITERATIONS, phase=phase_num,
        )

        # Assess
        async with async_session() as assess_db:
            guide_obj = await assess_db.get(
                WeeklyGuide, uuid.UUID(str(new_guide_id))
            )
            if not guide_obj or not guide_obj.markdown_content:
                prog[tracking_id] = {
                    "status": "error",
                    "detail": "Guide generated but has no content",
                }
                break

            try:
                scores = await assess_guide_content(
                    markdown_content=guide_obj.markdown_content,
                    guide_title=guide_obj.guide_title,
                    settings=settings,
                    db=assess_db,
                )
            except Exception as ae:
                logger.exception("generate_from_post.assess_failed", attempt=attempt)
                scores = {"error": str(ae), "composite": 0}

            composite = scores.get("composite", 0.0)
            dim_summary = ", ".join(
                f"{d[:4]}:{scores.get(d, {}).get('score', '?')}"
                for d in dims
                if isinstance(scores.get(d), dict)
            )

            dim_scores = {}
            for d in dims:
                val = scores.get(d)
                if isinstance(val, dict):
                    dim_scores[d] = val.get("score", 0)

            history = guide_obj.assessment_history or []
            history.append({"iteration": attempt, **scores})
            guide_obj.assessment_history = history
            guide_obj.iteration_count = attempt
            guide_obj.quality_scores = scores

            existing_prog = prog.get(tracking_id, {})
            score_history = existing_prog.get("score_history", [])
            score_history.append({"attempt": attempt, "composite": composite, **dim_scores})

            if composite >= QUALITY_THRESHOLD:
                guide_obj.quality_gate_passed = True
                await assess_db.commit()
                existing_prog.update({
                    "status": "done",
                    "attempt": attempt,
                    "composite": composite,
                    "passed": True,
                    "scores": dim_scores,
                    "score_history": score_history,
                    "guide_id": str(new_guide_id),
                    "detail": (
                        f"Passed! Score: {composite:.1f}/10 (attempt {attempt}). "
                        f"[{dim_summary}]"
                    ),
                })
                prog[tracking_id] = existing_prog
                break
            elif attempt == MAX_ITERATIONS:
                guide_obj.quality_gate_passed = False
                await assess_db.commit()
                existing_prog.update({
                    "status": "done",
                    "attempt": attempt,
                    "composite": composite,
                    "passed": False,
                    "scores": dim_scores,
                    "score_history": score_history,
                    "guide_id": str(new_guide_id),
                    "detail": (
                        f"Best: {composite:.1f}/10 after {attempt} attempts. "
                        f"[{dim_summary}]"
                    ),
                })
                prog[tracking_id] = existing_prog
            else:
                guide_obj.quality_gate_passed = None
                await assess_db.commit()
                feedback = build_feedback_prompt(scores, attempt)
                feedback += (
                    "\n\n--- SOURCE POST (the guide MUST deliver on this post's promise) ---\n"
                    f"{post_text}\n"
                    "--- END SOURCE POST ---"
                )
                if operator_feedback:
                    feedback += (
                        "\n\n--- OPERATOR INSTRUCTIONS (highest priority) ---\n"
                        f"{operator_feedback}\n"
                        "--- END OPERATOR INSTRUCTIONS ---"
                    )
                guide_context["_quality_feedback"] = feedback
                guide_context["_existing_guide_id"] = str(new_guide_id)
                _update(
                    f"Score {composite:.1f}/10 [{dim_summary}] - "
                    f"reiterating (attempt {attempt + 1} next)...",
                    attempt=attempt, max_attempts=MAX_ITERATIONS,
                    composite=composite, scores=dim_scores,
                    score_history=score_history, phase=attempt + 2,
                )


@router.post("/guides/{guide_id}/assess")
async def assess_guide(
    guide_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run LLM-based quality assessment on a guide across 6 dimensions."""
    from tce.services.guide_assessor import QUALITY_THRESHOLD, assess_guide_content

    guide = await db.get(WeeklyGuide, guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")
    if not guide.markdown_content:
        raise HTTPException(status_code=400, detail="Guide has no content to assess")

    scores = await assess_guide_content(
        markdown_content=guide.markdown_content,
        guide_title=guide.guide_title,
        settings=settings,
        db=db,
    )
    composite = scores.get("composite", 0.0)

    guide.quality_scores = scores
    guide.quality_gate_passed = composite >= QUALITY_THRESHOLD
    if not guide.iteration_count:
        guide.iteration_count = 1
    history = guide.assessment_history or []
    history.append({"iteration": guide.iteration_count, **scores})
    guide.assessment_history = history
    await db.commit()

    return scores


@router.post("/guides/backfill-assess")
async def backfill_assess_guides(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Assess all guides that haven't been scored yet (or re-assess all)."""
    from tce.services.guide_assessor import QUALITY_THRESHOLD, assess_guide_content

    result = await db.execute(
        select(WeeklyGuide).where(
            WeeklyGuide.is_archived.is_(False),
            WeeklyGuide.markdown_content.isnot(None),
        )
    )
    guides = list(result.scalars().all())

    assessed = 0
    passed = 0
    failed = 0
    results = []

    for guide in guides:
        try:
            scores = await assess_guide_content(
                markdown_content=guide.markdown_content,
                guide_title=guide.guide_title,
                settings=settings,
                db=db,
            )
            composite = scores.get("composite", 0.0)
            guide.quality_scores = scores
            guide.quality_gate_passed = composite >= QUALITY_THRESHOLD
            if not guide.iteration_count:
                guide.iteration_count = 1
            guide.assessment_history = [{"iteration": 1, **scores}]
            assessed += 1
            if composite >= QUALITY_THRESHOLD:
                passed += 1
            else:
                failed += 1
            results.append({
                "id": str(guide.id),
                "title": guide.guide_title,
                "composite": composite,
                "passed": composite >= QUALITY_THRESHOLD,
            })
        except Exception as e:
            results.append({
                "id": str(guide.id),
                "title": guide.guide_title,
                "error": str(e)[:200],
            })

    await db.commit()
    return {"assessed": assessed, "passed": passed, "failed": failed, "results": results}


# GAP-37: Select an image from a package
@router.post("/packages/{package_id}/select-image")
async def select_image(
    package_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark one image as operator-selected in a package."""
    import json as _json

    idx = body.get("index", 0)
    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if not pkg.image_prompts or idx >= len(pkg.image_prompts):
        raise HTTPException(status_code=400, detail="Invalid image index")

    updated = _json.loads(_json.dumps(pkg.image_prompts))
    for i, ip in enumerate(updated):
        ip["selected"] = i == idx
    pkg.image_prompts = updated
    await db.flush()
    await db.refresh(pkg)

    # Also update ImageAsset.operator_selected if exists
    from tce.models.image_asset import ImageAsset

    assets = await db.execute(select(ImageAsset).where(ImageAsset.package_id == package_id))
    for i, asset in enumerate(assets.scalars().all()):
        asset.operator_selected = i == idx
    await db.flush()

    return {"selected_index": idx}


# GAP-37: Regenerate a single image
@router.post("/packages/{package_id}/regenerate-image/{image_index}")
async def regenerate_single_image(
    package_id: uuid.UUID,
    image_index: int,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Regenerate a single image from its prompt, optionally with a modification note."""
    import json as _json

    from tce.services.image_generation import ImageGenerationService

    pkg = await db.get(PostPackage, package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if not pkg.image_prompts or image_index >= len(pkg.image_prompts):
        raise HTTPException(status_code=400, detail="Invalid image index")

    prompt = pkg.image_prompts[image_index]
    base_prompt = prompt.get("prompt_text", prompt.get("detailed_prompt", ""))

    # If a modification comment is provided, append it to the prompt
    modification = (body or {}).get("modification", "").strip()
    if modification:
        base_prompt = f"{base_prompt}\n\nModification: {modification}"

    svc = ImageGenerationService()
    result = await svc.generate_image(
        prompt_text=base_prompt,
        negative_prompt=prompt.get("negative_prompt"),
        aspect_ratio=prompt.get("aspect_ratio"),
    )

    if result.get("status") == "generated":
        updated = _json.loads(_json.dumps(pkg.image_prompts))
        updated[image_index]["image_url"] = result["image_url"]
        pkg.image_prompts = updated
        await db.flush()
        await db.refresh(pkg)

    return {"index": image_index, **result}


# ---------------------------------------------------------------------------
# Element-level feedback + regeneration (Phase 3 - 4-week planner)
# ---------------------------------------------------------------------------


class ElementFeedbackRequest(BaseModel):
    element: str  # "facebook_post" | "linkedin_post" | "hook" | "image_0"
    feedback: str


@router.post("/packages/{package_id}/element-feedback")
async def element_feedback(
    package_id: uuid.UUID,
    request: ElementFeedbackRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Regenerate a single element of a post package based on operator feedback."""
    from tce.services.element_regenerator import regenerate_element

    try:
        result = await regenerate_element(
            package_id=package_id,
            element_type=request.element,
            feedback=request.feedback,
            db=db,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
