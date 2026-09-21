"""Collect the months of calls that predate the engine.

The engine only ever collected the weeks it ran for, so the corpus of how Ziv talks
was two weeks deep. Fathom still holds the rest, and the collector already takes any
window: this walks backwards a month at a time so one long request cannot lose
everything, and so progress is visible while it runs.

Existing calls are recognised by their external id and skipped, which makes this safe
to re-run and safe to interrupt.

    python scripts/backfill_fathom_history.py <workspace_id> --months 6
    python scripts/backfill_fathom_history.py <workspace_id> --months 6 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from tce.db.session import async_session
from tce.evidence.collect import collect_fathom
from tce.models.editorial import EvidenceCollectionRun, EvidenceSource


async def stored(workspace_id: uuid.UUID) -> tuple[int, datetime | None]:
    async with async_session() as db:
        row = (
            await db.execute(
                select(func.count(EvidenceSource.id), func.min(EvidenceSource.occurred_at)).where(
                    EvidenceSource.workspace_id == workspace_id,
                    EvidenceSource.source_kind == "fathom_meeting",
                )
            )
        ).first()
    return int(row[0] or 0), row[1]


async def main(workspace_id: uuid.UUID, months: int, apply: bool) -> None:
    count, earliest = await stored(workspace_id)
    print(f"{count} calls stored, earliest {earliest or '(none)'}")

    now = datetime.now(UTC)
    # A month at a time, newest first: an interrupted backfill still leaves the most
    # useful half done, and a single failing window does not cost the rest.
    windows = [
        (now - timedelta(days=30 * (i + 1)), now - timedelta(days=30 * i)) for i in range(months)
    ]
    print(f"{len(windows)} windows back to {windows[-1][0].date()}")
    if not apply:
        print("\nnothing collected. Re-run with --apply.")
        return

    sm = async_session
    for start, end in windows:
        print(f"\n--- {start.date()} to {end.date()}")
        try:
            run_id = await collect_fathom(sm, workspace_id, start, end)
        except Exception as exc:  # one bad window must not end the backfill
            print(f"  failed: {type(exc).__name__}: {exc}")
            continue
        async with async_session() as db:
            run = (
                await db.execute(
                    select(EvidenceCollectionRun).where(EvidenceCollectionRun.id == run_id)
                )
            ).scalar_one_or_none()
        counts = (run.counts if run else {}) or {}
        print(
            f"  listed {counts.get('listed', 0)}, "
            f"new {counts.get('created', counts.get('inserted', 0))}, "
            f"skipped {counts.get('duplicates_skipped', 0)}"
            + (f", errors {len(run.errors)}" if run and run.errors else "")
        )

    count_after, earliest_after = await stored(workspace_id)
    print(f"\n{count_after} calls stored (was {count}), earliest {earliest_after}")
    print("Now rebuild the corpus: scripts/build_voice_corpus.py <workspace_id> --apply")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id")
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(uuid.UUID(args.workspace_id), max(1, args.months), args.apply))
