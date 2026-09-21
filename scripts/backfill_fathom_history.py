"""Collect the months of calls that predate the engine.

The engine only ever collected the weeks it ran for, so the corpus of how Ziv talks
was two weeks deep. Fathom still holds the rest.

ONE window by default, not one per month. The listing filter is `created_after` with
no upper bound, so every window paginates from its own start all the way to today and
then discards whatever falls outside it: the March window walked 68 pages to keep 114
meetings and threw 558 away. Splitting six months into six windows multiplies that
pagination sixfold for no coverage at all, and it is what made Fathom answer 429 and
lose May, June and July on the first run. `--monthly` keeps the old behaviour.

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


async def main(
    workspace_id: uuid.UUID,
    months: int,
    apply: bool,
    pause: float = 0.0,
    monthly: bool = False,
) -> None:
    count, earliest = await stored(workspace_id)
    print(f"{count} calls stored, earliest {earliest or '(none)'}")

    now = datetime.now(UTC)
    if monthly:
        # One window per month, newest first. Costs six paginations for six months.
        windows = [
            (now - timedelta(days=30 * (i + 1)), now - timedelta(days=30 * i))
            for i in range(months)
        ]
    else:
        # One window over the whole span: one pagination, everything in range kept.
        windows = [(now - timedelta(days=30 * months), now)]
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
            f"in window {counts.get('in_window', 0)}, "
            # 'processed' is the ledger's key for what it actually stored. Guessing
            # at 'created'/'inserted' printed "new 0" for a window that had just
            # stored 424 calls - a status line that lies is worse than none.
            f"stored {counts.get('processed', 0)}, "
            f"unchanged {counts.get('unchanged', 0)}"
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
    parser.add_argument("--pause", type=float, default=90.0, help="seconds between windows")
    parser.add_argument(
        "--monthly", action="store_true", help="one window per month (six paginations)"
    )
    args = parser.parse_args()
    asyncio.run(
        main(
            uuid.UUID(args.workspace_id), max(1, args.months), args.apply, args.pause, args.monthly
        )
    )
