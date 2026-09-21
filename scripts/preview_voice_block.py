"""Show what the writer will hear before it writes a given idea.

The voice block is the part that decides whether a script sounds like him, so it
has to be readable by a person, not only by a model.

    python scripts/preview_voice_block.py <workspace_id> <candidate_id>
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import select

from tce.db.session import async_session
from tce.editorial import voice_retrieval
from tce.models.editorial import TopicCandidate


async def main(workspace_id: uuid.UUID, candidate_id: uuid.UUID) -> None:
    async with async_session() as db:
        cand = (
            await db.execute(
                select(TopicCandidate).where(
                    TopicCandidate.id == candidate_id,
                    TopicCandidate.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if cand is None:
            raise SystemExit("no such idea in this workspace")
        print(f"IDEA: {cand.title}\n")
        block, used = await voice_retrieval.block_for_idea(
            db, workspace_id, title=cand.title, lesson=cand.lesson
        )
        print(block or "(no voice block: the corpus is empty or unreadable)")
        print(f"\n--- {len(used['samples'])} stretches, {used['sample_words']} words ---")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id")
    parser.add_argument("candidate_id")
    args = parser.parse_args()
    asyncio.run(main(uuid.UUID(args.workspace_id), uuid.UUID(args.candidate_id)))
