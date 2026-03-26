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
    db: AsyncSession = Depends(get_db),
) -> list[PostPackage]:
    query = select(PostPackage).order_by(PostPackage.created_at.desc())
    if status:
        query = query.where(PostPackage.approval_status == status)
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
    return pkg


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
async def list_guides(db: AsyncSession = Depends(get_db)) -> list[WeeklyGuide]:
    result = await db.execute(
        select(WeeklyGuide).order_by(WeeklyGuide.week_start_date.desc())
    )
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
