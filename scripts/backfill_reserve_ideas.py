"""Give the already-stored near-miss ideas their evidence back.

Every selection run validates far more ideas than it proposes and stores the rest
with the reason they lost. Until now those rows were saved without their citations,
so nothing could offer them later - an idea with no evidence cannot be scripted.

The selector keeps citations on new ones. This rebuilds them for the ones already
stored, from the moments each row still cites, so "Find more ideas" has something
to hand over tonight rather than after the next weekly run.

Only ideas cut for lack of room are touched. A gate failure, an invented outcome
or a duplicate was cut because it was wrong, and stays wrong.

    python scripts/backfill_reserve_ideas.py <workspace_id>
    python scripts/backfill_reserve_ideas.py <workspace_id> --apply
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from typing import Any

from sqlalchemy import select

from tce.db.session import async_session
from tce.editorial.common import ORIGIN_SELECTOR_REJECTED
from tce.editorial.selector import RESERVE_CODES
from tce.models.editorial import EvidenceMoment, EvidenceSource, TopicCandidate


def citation(moment: EvidenceMoment, source: EvidenceSource) -> dict[str, Any]:
    """The same shape the selector writes, so a promoted idea is scripted the same way."""
    return {
        "moment_id": str(moment.id),
        "source_id": str(source.id),
        "source_kind": source.source_kind,
        "source_title": source.title,
        "occurred_at": source.occurred_at.isoformat() if source.occurred_at else None,
        "span_start_s": moment.span_start_s,
        "span_end_s": moment.span_end_s,
        "code_refs": moment.code_refs,
        "url_private": source.url_private,
        "claim_type": moment.claim_type,
        "speaker": moment.speaker,
        "speaker_confidence": moment.speaker_confidence,
        "translation_label": moment.translation_label,
        "language_uncertain": bool(moment.language_uncertain),
        "sensitivity_flags": list(moment.sensitivity_flags or []),
        "excerpt_private": moment.excerpt_private,
    }


async def main(workspace_id: uuid.UUID, apply: bool) -> None:
    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(TopicCandidate).where(
                        TopicCandidate.workspace_id == workspace_id,
                        TopicCandidate.status == "rejected",
                        TopicCandidate.origin == ORIGIN_SELECTOR_REJECTED,
                    )
                )
            )
            .scalars()
            .all()
        )
        wanted = [
            r
            for r in rows
            if (r.gates or {}).get("_rejection", {}).get("code") in RESERVE_CODES
            and not r.citations_private
            and r.moment_ids
        ]
        print(f"{len(rows)} stored rejections, {len(wanted)} cut only for lack of room")
        if not wanted:
            return

        needed = {str(m) for r in wanted for m in (r.moment_ids or [])}
        pairs = (
            await db.execute(
                select(EvidenceMoment, EvidenceSource)
                .join(EvidenceSource, EvidenceSource.id == EvidenceMoment.source_id)
                .where(
                    EvidenceMoment.workspace_id == workspace_id,
                    EvidenceMoment.status == "active",
                    EvidenceMoment.id.in_([uuid.UUID(m) for m in needed]),
                )
            )
        ).all()
        by_id = {str(m.id): (m, s) for m, s in pairs}
        print(f"{len(by_id)} of {len(needed)} cited moments are still active evidence")

        rebuilt = 0
        for row in wanted:
            cites = [by_id[str(m)] for m in row.moment_ids if str(m) in by_id]
            # All of them or none: a script written from half the evidence would
            # cite things the idea was never judged on.
            if len(cites) != len(row.moment_ids or []):
                continue
            if apply:
                row.citations_private = [citation(m, s) for m, s in cites]
                gates = dict(row.gates or {})
                gates["_reserve"] = True
                row.gates = gates
            rebuilt += 1

        if apply:
            await db.commit()
            print(f"gave {rebuilt} ideas their evidence back; they can be offered now")
        else:
            print(f"{rebuilt} could be restored. Re-run with --apply.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(uuid.UUID(args.workspace_id), args.apply))
