"""Content management endpoints — PostPackage, WeeklyGuide, ImageAsset."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.post_package import PostPackage
from tce.models.weekly_guide import WeeklyGuide
from tce.schemas.post_package import PostPackageRead, PostPackageUpdate
from tce.schemas.weekly_guide import WeeklyGuideCreate, WeeklyGuideRead

router = APIRouter(prefix="/content", tags=["content"])


# Post packages
@router.get("/packages", response_model=list[PostPackageRead])
async def list_packages(
    status: str | None = None,
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[PostPackage]:
    query = select(PostPackage).order_by(PostPackage.created_at.desc())
    if status:
        query = query.where(PostPackage.approval_status == status)
    if not include_archived:
        query = query.where(PostPackage.is_archived.is_(False))
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
    existing = await db.execute(
        select(ImageAsset).where(ImageAsset.package_id == package_id)
    )
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

        generated.append({
            "index": i,
            "status": "generated",
            "image_url": result.get("image_url"),
            "time": result.get("generation_time_seconds"),
        })

    # Also update image_prompts JSONB with URLs for dashboard display
    updated_prompts = list(pkg.image_prompts)
    for g in generated:
        idx = g["index"]
        if g["status"] == "generated" and idx < len(updated_prompts):
            updated_prompts[idx]["image_url"] = g["image_url"]
    pkg.image_prompts = updated_prompts

    await db.flush()
    await db.refresh(pkg)

    return {"package_id": str(package_id), "results": generated}


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
        raise HTTPException(status_code=404, detail="DOCX file not found on disk")
    return FileResponse(
        path=str(docx_file),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{guide.guide_title}.docx",
    )
