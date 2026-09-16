"""Seed editor-accepted calibration ideas for one workspace.

    python scripts/seed_calibration_feedback.py --workspace-id <uuid> --file <private.json>
    python scripts/seed_calibration_feedback.py --workspace-id <uuid> --file <private.json> \
        --dry-run

The JSON file is PRIVATE and must live outside this repository. Format: a list of
    {"title", "lesson", "public_angle", "audience", "source_kind", "source_ref", "span", "note"}
audience is coaches | event_owners | both.

Each item becomes a TopicCandidate (origin "calibration", status "selected") with an
approve/publish feedback row, in that workspace only. Rerunning skips titles that are
already seeded.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

REPO_ROOT = Path(__file__).resolve().parent.parent


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--file", required=True, help="private JSON outside the repository")
    parser.add_argument("--week-start", help="YYYY-MM-DD (default: this week's Monday)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from tce.editorial.feedback import FeedbackError, seed_calibration, validate_calibration_items

    try:
        ws = uuid.UUID(args.workspace_id)
    except ValueError:
        print("invalid --workspace-id", file=sys.stderr)
        return 2
    path = Path(args.file).resolve()
    if REPO_ROOT in path.parents:
        print("refusing: the calibration file must live outside the repository", file=sys.stderr)
        return 2
    try:
        items = validate_calibration_items(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, FeedbackError) as exc:
        print(f"cannot read calibration file: {exc}", file=sys.stderr)
        return 2
    week_start = date.fromisoformat(args.week_start) if args.week_start else None

    if args.dry_run:
        print(f"{len(items)} valid calibration items for workspace {ws} (dry run, nothing written)")
        return 0

    from tce.db.session import async_session

    result = await seed_calibration(async_session, ws, items, week_start=week_start)
    print(
        f"workspace {ws}: inserted {result['inserted']}, "
        f"skipped {result['skipped']} (already seeded)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
