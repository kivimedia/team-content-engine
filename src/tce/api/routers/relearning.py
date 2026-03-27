"""Relearning review endpoints (PRD Section 48.7)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.post_example import PostExample
from tce.models.source_document import SourceDocument
from tce.services.relearning import RelearningService

router = APIRouter(prefix="/relearning", tags=["relearning"])


class EvaluateRequest(BaseModel):
    document_id: str


@router.get("/status")
async def get_relearning_status(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get current relearning status - recent documents and their evaluation state."""
    result = await db.execute(
        select(SourceDocument).order_by(SourceDocument.created_at.desc()).limit(10)
    )
    docs = result.scalars().all()

    service = RelearningService(db)
    statuses = []
    for doc in docs:
        summary = await service.get_relearning_summary(doc.id)
        statuses.append(
            {
                "document_id": str(doc.id),
                "file_name": doc.file_name,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "summary": summary,
            }
        )

    return {"recent_documents": statuses}


@router.post("/evaluate")
async def evaluate_document(
    request: EvaluateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger relearning evaluation on a document's post examples."""
    doc_id = uuid.UUID(request.document_id)

    result = await db.execute(select(PostExample).where(PostExample.document_id == doc_id))
    examples = list(result.scalars().all())

    if not examples:
        raise HTTPException(404, "No examples found for this document")

    # Convert ORM objects to dicts for the relearning service
    example_dicts: list[dict[str, Any]] = [
        {
            "hook_type": ex.hook_type,
            "body_structure": ex.body_structure,
            "engagement_confidence": ex.engagement_confidence,
            "creator_name": "",  # resolved via join if needed; service uses creator_name key
        }
        for ex in examples
    ]

    service = RelearningService(db)
    trigger_result = await service.detect_trigger(example_dicts)
    triggers_raw = trigger_result.get("triggers", [])
    new_creators = trigger_result.get("new_creators", [])

    # Normalise into a list of dicts for the proposals loop
    triggers: list[dict[str, Any]] = []
    for t in triggers_raw:
        if t == "new_creator":
            for name in new_creators:
                triggers.append({"type": "new_creator", "creator_name": name})
        else:
            triggers.append({"type": t})

    proposals = []
    for trigger in triggers:
        if trigger.get("type") == "new_creator":
            eval_result = await service.evaluate_new_creator(trigger["creator_name"], example_dicts)
            proposals.append(
                {
                    "type": "new_creator_admission",
                    "creator_name": trigger["creator_name"],
                    **eval_result,
                }
            )
        elif trigger.get("type") == "more_examples_existing_creator":
            additions = trigger_result.get("existing_creator_additions", {})
            for creator_name, count in additions.items():
                proposals.append(
                    {
                        "type": "existing_creator_update",
                        "creator_name": creator_name,
                        "new_example_count": count,
                        "action": "re-score and re-mine templates",
                    }
                )

    return {
        "document_id": request.document_id,
        "example_count": len(examples),
        "triggers": triggers,
        "proposals": proposals,
    }


@router.get("/proposals")
async def list_proposals(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List creator stats that may need relearning (from recent evaluations)."""
    result = await db.execute(
        select(
            PostExample.creator_id,
            func.count().label("example_count"),
            func.avg(PostExample.final_score).label("avg_score"),
        ).group_by(PostExample.creator_id)
    )
    rows = result.all()

    return {
        "creators": [
            {
                "creator_id": str(r[0]),
                "example_count": r[1],
                "avg_score": round(float(r[2]), 2) if r[2] else None,
            }
            for r in rows
            if r[0]
        ],
    }


class ProposalAction(BaseModel):
    reason: str = ""


@router.post("/proposals/{creator_id}/approve")
async def approve_proposal(
    creator_id: str,
    body: ProposalAction | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Approve a relearning proposal for a creator - triggers re-scoring."""
    cid = uuid.UUID(creator_id)

    result = await db.execute(
        select(func.count()).select_from(PostExample).where(PostExample.creator_id == cid)
    )
    count = result.scalar() or 0
    if count == 0:
        raise HTTPException(404, f"No examples found for creator {creator_id}")

    service = RelearningService(db)
    # Run re-evaluation on the creator's examples
    examples_result = await db.execute(select(PostExample).where(PostExample.creator_id == cid))
    examples = list(examples_result.scalars().all())
    example_dicts = [
        {
            "hook_type": ex.hook_type,
            "body_structure": ex.body_structure,
            "engagement_confidence": ex.engagement_confidence,
            "creator_name": "",
        }
        for ex in examples
    ]
    eval_result = await service.evaluate_new_creator(creator_id, example_dicts)

    return {
        "status": "approved",
        "creator_id": creator_id,
        "example_count": count,
        "evaluation": eval_result,
        "reason": body.reason if body else "",
    }


@router.post("/proposals/{creator_id}/reject")
async def reject_proposal(
    creator_id: str,
    body: ProposalAction | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reject a relearning proposal for a creator."""
    cid = uuid.UUID(creator_id)

    result = await db.execute(
        select(func.count()).select_from(PostExample).where(PostExample.creator_id == cid)
    )
    count = result.scalar() or 0
    if count == 0:
        raise HTTPException(404, f"No examples found for creator {creator_id}")

    return {
        "status": "rejected",
        "creator_id": creator_id,
        "example_count": count,
        "reason": body.reason if body else "",
    }
