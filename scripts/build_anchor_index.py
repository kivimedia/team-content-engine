"""Rebuild the anchor index and print what TCE believes Ziv's work is.

Deterministic, no model call, safe to run nightly and safe to run twice.

Read the dry run before enabling the lane. If TCE's idea of the stack is wrong,
everything downstream is wrong, and this is the cheapest moment to find out: an
announcement can only reach Ziv by matching a row printed here.

Usage:
    PYTHONPATH=src python scripts/build_anchor_index.py --dry-run
    PYTHONPATH=src python scripts/build_anchor_index.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict

from tce.news.anchors import build_anchor_index


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print, write nothing")
    parser.add_argument(
        "--window-days",
        type=int,
        default=90,
        help="how far back a repo must have a commit to count (default 90)",
    )
    parser.add_argument("--workspace", default=os.environ.get("TCE_EDITOR_DEFAULT_WORKSPACE_ID"))
    args = parser.parse_args()

    if not args.workspace:
        print(
            "No workspace. Pass --workspace or set TCE_EDITOR_DEFAULT_WORKSPACE_ID.",
            file=sys.stderr,
        )
        return 2

    from tce.db.session import async_session

    async with async_session() as session:
        result, anchors = await build_anchor_index(
            session,
            args.workspace,
            window_days=args.window_days,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            await session.commit()

    grouped: dict[str, list] = defaultdict(list)
    for anchor in anchors:
        grouped[anchor.kind].append(anchor)

    for kind in sorted(grouped):
        rows = grouped[kind]
        print(f"\n## {kind}  ({len(rows)})")
        for anchor in sorted(rows, key=lambda a: (-a.weight, a.normalized)):
            where = anchor.origin_ref or anchor.origin_kind
            weight = f"  w={anchor.weight}" if anchor.weight != 1.0 else ""
            cite = "  [citable]" if anchor.standing_moment_id else ""
            print(f"  - {anchor.term}{weight}   <- {where}{cite}")

    if result.skipped_unusable:
        print(f"\nskipped as too generic to match on ({len(result.skipped_unusable)}):")
        for item in sorted(result.skipped_unusable)[:20]:
            print(f"  - {item}")

    print("\n" + result.summary())
    if args.dry_run:
        print("dry run: nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
