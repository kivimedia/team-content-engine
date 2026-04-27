"""Content management endpoints - PostPackage, WeeklyGuide, ImageAsset."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.post_package import PostPackage
from tce.models.story_brief import StoryBrief
from tce.models.tracked_repo import TrackedRepo
from tce.models.weekly_guide import WeeklyGuide
from tce.schemas.post_package import PostPackageRead, PostPackageUpdate
from tce.schemas.weekly_guide import WeeklyGuideCreate, WeeklyGuideRead

router = APIRouter(prefix="/content", tags=["content"])


def _repo_name_from(repo: TrackedRepo) -> str | None:
    """Repo name for Library card titles. Prefers display_name, falls back to
    the last segment of the slug or repo URL (strip .git, trailing slashes)."""
    if repo.display_name:
        return repo.display_name
    raw = (repo.slug or repo.repo_url or "").rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    tail = raw.rsplit("/", 1)[-1]
    return tail or raw or None


def _attach_titles(packages: list[PostPackage], repos: dict, briefs: dict) -> None:
    """Set a computed `title` attribute on each package based on its source."""
    for p in packages:
        title: str | None = None
        if p.source == "repo" and p.source_repo_id and p.source_repo_id in repos:
            title = _repo_name_from(repos[p.source_repo_id])
        elif p.source == "topic" and p.brief_id and p.brief_id in briefs:
            title = briefs[p.brief_id].topic
        # Final fallback for any source without a strong title source: use the
        # first line of the FB or LI post. Catches orphan repo packages from
        # before source_repo_id was populated, plus the generic "copy" source.
        if not title and (p.source in ("repo", "copy") or p.source is None):
            text = (p.facebook_post or p.linkedin_post or "").strip()
            first_line = text.split("\n", 1)[0].strip() if text else ""
            if first_line:
                title = (first_line[:80] + "...") if len(first_line) > 80 else first_line
        p.title = title  # picked up by Pydantic from_attributes


# Post packages
@router.get("/packages", response_model=list[PostPackageRead])
async def list_packages(
    status: str | None = None,
    include_archived: bool = False,
    pipeline_run_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[PostPackage]:
    query = select(PostPackage).order_by(PostPackage.created_at.desc())
    if pipeline_run_id:
        from sqlalchemy import cast, String
        query = query.where(
            cast(PostPackage.pipeline_run_id, String) == pipeline_run_id
        )
    if status:
        query = query.where(PostPackage.approval_status == status)
    if not include_archived:
        query = query.where(PostPackage.is_archived.is_(False))
    result = await db.execute(query)
    packages = list(result.scalars().all())

    # Bulk-fetch source records once, then compute Library card titles in Python.
    repo_ids = {p.source_repo_id for p in packages if p.source == "repo" and p.source_repo_id}
    brief_ids = {p.brief_id for p in packages if p.source == "topic" and p.brief_id}
    repos: dict = {}
    if repo_ids:
        rs = await db.execute(select(TrackedRepo).where(TrackedRepo.id.in_(repo_ids)))
        repos = {r.id: r for r in rs.scalars()}
    briefs: dict = {}
    if brief_ids:
        bs = await db.execute(select(StoryBrief).where(StoryBrief.id.in_(brief_ids)))
        briefs = {b.id: b for b in bs.scalars()}
    _attach_titles(packages, repos, briefs)
    return packages


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
    for pkg in packages:
        changed = False
        if pkg.facebook_post and (
            "\u2014" in pkg.facebook_post
            or "\u2013" in pkg.facebook_post
            or "--" in pkg.facebook_post
        ):
            pkg.facebook_post = _clean_text(pkg.facebook_post)
            changed = True
        if pkg.linkedin_post and (
            "\u2014" in pkg.linkedin_post
            or "\u2013" in pkg.linkedin_post
            or "--" in pkg.linkedin_post
        ):
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


@router.post("/guides/{guide_id}/assess")
async def assess_guide(
    guide_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run LLM-based quality assessment on a guide across 6 dimensions."""
    guide = await db.get(WeeklyGuide, guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="Guide not found")
    if not guide.markdown_content:
        raise HTTPException(status_code=400, detail="Guide has no content to assess")

    import anthropic

    from tce.services.cost_tracker import CostTracker
    from tce.settings import Settings

    s = Settings()
    api_key = s.anthropic_api_key
    if hasattr(api_key, "get_secret_value"):
        api_key = api_key.get_secret_value()
    client = anthropic.AsyncAnthropic(api_key=api_key)

    # Truncate to ~8K chars for Haiku assessment
    content = guide.markdown_content[:8000]
    word_count = len(guide.markdown_content.split())

    system = (
        "You are a content quality assessor for B2B lead magnets (free guides given to readers "
        "who comment a keyword on social media). Score the guide on exactly 6 dimensions, 1-10 each. "
        "Be critical - most guides score 5-7. A 9-10 means genuinely exceptional.\n\n"
        "DIMENSIONS:\n"
        "1. practical - Can the reader DO something concrete after reading? Are there actionable steps, "
        "checklists, templates, or exercises? (not just theory)\n"
        "2. valuable - Would a smart professional pay $49 for this? Does it contain insights they "
        "can't easily Google? Does it save them real time or money?\n"
        "3. generous - Does it give away real substance, or does it tease and gatekeep? "
        "Is the framework complete enough to use without buying anything else?\n"
        "4. accurate - Are claims supported by specific data, studies, or named examples? "
        "Or is it full of vague 'studies show' and unsourced percentages?\n"
        "5. quick_win - Does it include an exercise or tool the reader can complete in under "
        "15 minutes that produces a visible result? (worksheet, score, decision, audit)\n"
        "6. transformation - Does the reader's mental model shift? Will they think differently "
        "about the topic after reading? Is there a clear before/after belief change?\n\n"
        "OUTPUT: JSON only, no markdown. Format:\n"
        '{"practical":{"score":N,"reason":"..."},"valuable":{"score":N,"reason":"..."},'
        '"generous":{"score":N,"reason":"..."},"accurate":{"score":N,"reason":"..."},'
        '"quick_win":{"score":N,"reason":"..."},"transformation":{"score":N,"reason":"..."},'
        '"composite":N.N,"summary":"1-2 sentence overall assessment"}'
    )

    resp = await client.messages.create(
        model=s.haiku_model,
        max_tokens=1024,
        temperature=0.2,
        system=system,
        messages=[{
            "role": "user",
            "content": (
                f"GUIDE TITLE: {guide.guide_title}\n"
                f"WORD COUNT: {word_count}\n\n"
                f"CONTENT:\n{content}"
            ),
        }],
    )

    import json

    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        scores = json.loads(text)
    except json.JSONDecodeError:
        scores = {"error": "Failed to parse assessment", "raw": text[:500]}

    # Compute composite if not provided
    if "composite" not in scores and "error" not in scores:
        dims = [scores[d]["score"] for d in ["practical", "valuable", "generous", "accurate", "quick_win", "transformation"] if isinstance(scores.get(d), dict)]
        if dims:
            scores["composite"] = round(sum(dims) / len(dims), 1)

    # Persist scores
    guide.quality_scores = scores
    await db.flush()

    # Record cost
    tracker = CostTracker(db)
    await tracker.record(
        run_id=uuid.uuid4(),
        agent_name="guide_assessor",
        model_used=s.haiku_model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )
    await db.commit()

    return scores


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
