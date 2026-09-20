"""Collapse ideas already on the list that say the same thing.

The cross-week check stops NEW repeats. The ones already on his list predate it,
so they are collapsed once, here, by the same rule the selector now applies.

Nothing is deleted. The loser is withdrawn with the reason on the row, which is
the same state "Put it away" produces, so it stays in the recorder's Put away
section and one tap brings it back.

    python scripts/dedupe_existing_ideas.py            # say what it would do
    python scripts/dedupe_existing_ideas.py --apply    # do it
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from tce.db.session import async_session
from tce.editorial.dedupe import find_duplicate
from tce.models.editorial import TopicCandidate

LIVE = ("proposed", "selected", "recorded", "published")
# The further along the pipeline, the more it has cost him already.
ORDER = {"published": 4, "recorded": 3, "selected": 2, "proposed": 1}


def keeps(a: TopicCandidate, b: TopicCandidate) -> tuple[TopicCandidate, TopicCandidate]:
    """(keep, drop). Furthest along wins; then the better rank; then the older row."""
    key = lambda row: (  # noqa: E731
        ORDER.get(row.status, 0),
        -(row.rank if row.rank is not None else 10_000),
        -row.created_at.timestamp(),
    )
    return (a, b) if key(a) >= key(b) else (b, a)


async def main(workspace_id: uuid.UUID, apply: bool) -> None:
    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(TopicCandidate)
                    .where(
                        TopicCandidate.workspace_id == workspace_id,
                        TopicCandidate.status.in_(LIVE),
                        TopicCandidate.origin != "technical_validation",
                    )
                    .order_by(TopicCandidate.week_start.desc())
                )
            )
            .scalars()
            .all()
        )
        print(f"{len(rows)} ideas on the list")

        dropped: set[uuid.UUID] = set()
        pairs: list[tuple[TopicCandidate, TopicCandidate]] = []
        for i, row in enumerate(rows):
            if row.id in dropped:
                continue
            others = [r for r in rows[:i] if r.id not in dropped]
            hit = find_duplicate(row, others)
            if hit is None:
                continue
            keep, drop = keeps(row, hit[0])
            dropped.add(drop.id)
            pairs.append((keep, drop))

        if not pairs:
            print("nothing says the same thing twice")
            return
        for keep, drop in pairs:
            print(f"\n  keep ({keep.status:<9}) {keep.title}")
            print(f"  drop ({drop.status:<9}) {drop.title}")

        if not apply:
            print(f"\n{len(pairs)} to collapse. Re-run with --apply.")
            return

        now = datetime.now(UTC).replace(tzinfo=None)
        for keep, drop in pairs:
            drop.status = "withdrawn"
            drop.updated_at = now
            drop.editor_notes = (
                (drop.editor_notes + "\n") if drop.editor_notes else ""
            ) + f"Put away on {now:%d %b}: it says the same thing as {keep.title!r}."
        await db.commit()
        print(f"\ncollapsed {len(pairs)}; each one is in Put away and can be brought back")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(uuid.UUID(args.workspace_id), args.apply))
