"""Run evidence collection (and optionally moment extraction) against the configured DB.

Read-only toward Fathom and GitHub. Keys come from the environment via settings
(TCE_FATHOM_API_KEY, TCE_GITHUB_PAT). Prints a counts-only coverage summary: no
transcript text, no commit content, no secrets.

    python scripts/collect_evidence.py --workspace-id <uuid> \
        --start 2026-09-06T21:00:00Z --end 2026-09-13T21:00:00Z --kinds fathom,github
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _main(args: argparse.Namespace) -> int:
    from tce.db.session import async_session
    from tce.evidence.collect import collect_fathom, collect_github, coverage_summary
    from tce.evidence.moments import extract_moments
    from tce.models.editorial import EvidenceCollectionRun

    ws = uuid.UUID(args.workspace_id)
    start, end = _parse_dt(args.start), _parse_dt(args.end)
    if end <= start:
        print("--end must be after --start", file=sys.stderr)
        return 2
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    run_ids = []
    for kind in kinds:
        if kind == "fathom":
            run_ids.append(await collect_fathom(async_session, ws, start, end))
        elif kind == "github":
            run_ids.append(await collect_github(async_session, ws, start, end))
        else:
            print(f"unknown kind: {kind}", file=sys.stderr)
            return 2
    if args.extract:
        run_ids.append(await extract_moments(async_session, ws, start, end))

    exit_code = 0
    async with async_session() as session:
        for run_id in run_ids:
            run = await session.get(EvidenceCollectionRun, run_id)
            summary = coverage_summary(run)
            summary.pop("current_activity", None)
            print(json.dumps(summary, indent=2))
            if run.status != "complete":
                exit_code = 1
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--start", required=True, help="ISO datetime, UTC if no offset")
    parser.add_argument("--end", required=True, help="ISO datetime (exclusive)")
    parser.add_argument("--kinds", default="fathom,github")
    parser.add_argument("--extract", action="store_true", help="also run moment extraction")
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
