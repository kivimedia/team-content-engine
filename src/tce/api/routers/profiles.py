"""Creator and founder voice profile endpoints."""

import asyncio
import json
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.creator_profile import CreatorProfile
from tce.models.founder_voice_profile import FounderVoiceProfile
from tce.models.post_example import PostExample
from tce.schemas.creator_profile import (
    CreatorProfileCreate,
    CreatorProfileRead,
    CreatorProfileUpdate,
)
from tce.schemas.founder_voice_profile import (
    FounderVoiceProfileCreate,
    FounderVoiceProfileRead,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/profiles", tags=["profiles"])


# Creator profiles
@router.post("/creators", response_model=CreatorProfileRead)
async def create_creator(
    data: CreatorProfileCreate,
    db: AsyncSession = Depends(get_db),
) -> CreatorProfile:
    profile = CreatorProfile(**data.model_dump())
    db.add(profile)
    await db.flush()
    return profile


@router.get("/creators", response_model=list[CreatorProfileRead])
async def list_creators(db: AsyncSession = Depends(get_db)) -> list[CreatorProfile]:
    result = await db.execute(select(CreatorProfile).order_by(CreatorProfile.creator_name))
    return list(result.scalars().all())


@router.get("/creators/{creator_id}", response_model=CreatorProfileRead)
async def get_creator(
    creator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CreatorProfile:
    profile = await db.get(CreatorProfile, creator_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Creator not found")
    return profile


@router.patch("/creators/{creator_id}", response_model=CreatorProfileRead)
async def update_creator(
    creator_id: uuid.UUID,
    data: CreatorProfileUpdate,
    db: AsyncSession = Depends(get_db),
) -> CreatorProfile:
    profile = await db.get(CreatorProfile, creator_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Creator not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    await db.flush()
    return profile


@router.post(
    "/creators/{creator_id}/analyze-voice",
    response_model=CreatorProfileRead,
)
async def analyze_creator_voice(
    creator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CreatorProfile:
    """Analyze a creator's posts to generate voice_axes and top_patterns."""
    profile = await db.get(CreatorProfile, creator_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Creator not found")

    # Load their posts
    result = await db.execute(
        select(PostExample).where(PostExample.creator_id == creator_id).limit(40)
    )
    posts = list(result.scalars().all())
    if not posts:
        raise HTTPException(
            status_code=400,
            detail="No posts found for this creator",
        )

    # Build sample text from posts
    samples = []
    for p in posts[:30]:
        text = p.hook_text or ""
        if p.body_text:
            text += "\n" + p.body_text[:300]
        if text.strip():
            samples.append(text.strip()[:500])

    if not samples:
        raise HTTPException(
            status_code=400,
            detail="Posts have no text content",
        )

    import anthropic

    from tce.settings import Settings

    s = Settings()
    api_key = s.anthropic_api_key
    if hasattr(api_key, "get_secret_value"):
        api_key = api_key.get_secret_value()
    client = anthropic.AsyncAnthropic(api_key=api_key)

    resp = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        temperature=0.3,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Analyze these {len(samples)} post samples "
                    f"from {profile.creator_name} and rate their "
                    f"writing style on these axes (1-10 each):\n\n"
                    f"urgency, curiosity, sharpness, friendliness, "
                    f"practicality, sentence_punch, contrarian_heat, "
                    f"strategic_depth, executive_clarity, "
                    f"emotional_intensity\n\n"
                    f"Also identify their top 2-3 template families "
                    f"from: big_shift_explainer, contrarian_diagnosis, "
                    f"tactical_workflow_guide, case_study_build_story, "
                    f"second_order_implication, founder_reflection, "
                    f"hidden_feature_shortcut, teardown_myth_busting, "
                    f"comment_keyword_cta_guide, weekly_roundup\n\n"
                    f"SAMPLES:\n" + "\n---\n".join(samples[:20]) + "\n\nReply with ONLY JSON: "
                    '{"voice_axes": {"urgency": N, ...}, '
                    '"top_patterns": ["pattern1", ...], '
                    '"style_notes": "one-line summary"}. '
                    "No markdown."
                ),
            }
        ],
    )

    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        analysis = json.loads(text)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Failed to parse voice analysis",
        )

    profile.voice_axes = analysis.get("voice_axes")
    profile.top_patterns = analysis.get("top_patterns")
    if analysis.get("style_notes"):
        profile.style_notes = analysis["style_notes"]
    await db.flush()

    logger.info(
        "creator.voice_analyzed",
        name=profile.creator_name,
        axes=profile.voice_axes,
    )
    return profile


# Founder voice profiles
@router.post("/founder-voice", response_model=FounderVoiceProfileRead)
async def create_founder_voice(
    data: FounderVoiceProfileCreate,
    db: AsyncSession = Depends(get_db),
) -> FounderVoiceProfile:
    profile = FounderVoiceProfile(**data.model_dump())
    db.add(profile)
    await db.flush()
    return profile


@router.get("/founder-voice", response_model=list[FounderVoiceProfileRead])
async def list_founder_voices(db: AsyncSession = Depends(get_db)) -> list[FounderVoiceProfile]:
    result = await db.execute(select(FounderVoiceProfile))
    return list(result.scalars().all())


@router.post("/founder-voice/extract")
async def extract_founder_voice(
    document_id: uuid.UUID,
    source_type: str = "book",
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger founder voice extraction from an uploaded document (PRD Section 50.6)."""

    from tce.models.source_document import SourceDocument

    doc = await db.get(SourceDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get the extracted text - prefer extracted_text field, fallback to notes
    founder_text = doc.extracted_text or doc.notes or ""
    if not founder_text:
        raise HTTPException(
            status_code=400,
            detail=(
                "Document has no extracted text. Ingest the document first via /documents/upload."
            ),
        )

    # Trigger founder_voice_extraction workflow as background task
    async def _run_extraction() -> None:
        from tce.db.session import async_session
        from tce.orchestrator.engine import PipelineOrchestrator
        from tce.orchestrator.workflows import WORKFLOWS
        from tce.settings import settings

        async with async_session() as extraction_db:
            orchestrator = PipelineOrchestrator(
                steps=WORKFLOWS["founder_voice_extraction"],
                db=extraction_db,
                settings=settings,
            )
            result = await orchestrator.run(
                {
                    "founder_text": founder_text,
                    "source_type": source_type,
                    "document_id": str(document_id),
                }
            )

            # Save the extracted voice profile to DB
            # Orchestrator nests agent output inside result["context"]
            ctx = result.get("context", result)
            voice_data = ctx.get("founder_voice", {})
            if voice_data:
                profile = FounderVoiceProfile(
                    source_document_ids=[str(document_id)],
                    vocabulary_signature=voice_data.get("vocabulary_signature"),
                    sentence_rhythm_profile=voice_data.get("sentence_rhythm_profile"),
                    values_and_beliefs=voice_data.get("values_and_beliefs"),
                    metaphor_families=voice_data.get("metaphor_families"),
                    tone_range=voice_data.get("tone_range"),
                    taboos=voice_data.get("taboos"),
                    recurring_themes=voice_data.get("recurring_themes"),
                    humor_type=voice_data.get("humor_type"),
                )
                extraction_db.add(profile)

            await extraction_db.commit()

    asyncio.create_task(_run_extraction())

    return {
        "status": "extraction_started",
        "document_id": str(document_id),
        "source_type": source_type,
        "message": (
            "Founder voice extraction has been triggered. "
            "Check /profiles/founder-voice for results."
        ),
    }
