"""Re-check the scripts a false positive parked as drafts, and give them back.

28-Sep-2026: three scripts were written and saved as "draft" instead of "ready",
so the week said "0 scripts ready" while he had eight topics waiting. The safety
scan had flagged lines that deny a guarantee ("It's not a guarantee, it's a
starting point.") and took "The" from a client's company name as a person's name.
The scanner is fixed for new scripts. This re-runs the CURRENT scan on the drafts
already stored, the same way the packet writer runs it (same fields, same names
from the idea's evidence), and prints the old flags next to the new verdict.

Only a draft whose rescan is clean changes, and only with --apply: it becomes
ready, and its stored verdict is replaced with the new one, keeping what the old
scan said under "rescanned" so nothing is lost. A draft that still has a real
issue stays a draft. Superseded and exported versions are never touched.

    PYTHONPATH=src python scripts/rescan_packet_safety.py <workspace_id>          # say what
    PYTHONPATH=src python scripts/rescan_packet_safety.py <workspace_id> --apply  # do it
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import async_session
from tce.editorial.packets import scan_packet_safety, status_for_safety, stored_safety_fields
from tce.models.editorial import RecordingPacket, TopicCandidate

SOURCE = "scripts/rescan_packet_safety.py"


def _flags(issues: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {"kind": issue.get("kind"), "field": issue.get("field"), "match": issue.get("match")}
        for issue in issues or []
    ]


async def rescan(db: AsyncSession, workspace_id: uuid.UUID, *, apply: bool) -> list[dict[str, Any]]:
    """One row per current draft: what the old scan said and what the scan says now.

    With `apply`, a draft whose rescan is clean is made ready. Nothing else changes.
    """
    packets = (
        (
            await db.execute(
                select(RecordingPacket)
                .where(
                    RecordingPacket.workspace_id == workspace_id,
                    # "draft" is never superseded or exported, so this is the set of
                    # current versions that are waiting on the scan and nothing else.
                    RecordingPacket.status == "draft",
                )
                .order_by(RecordingPacket.created_at.asc(), RecordingPacket.version.asc())
            )
        )
        .scalars()
        .all()
    )
    titles: dict[uuid.UUID, str] = {}
    if packets:
        rows = await db.execute(
            select(TopicCandidate.id, TopicCandidate.title).where(
                TopicCandidate.workspace_id == workspace_id,
                TopicCandidate.id.in_({p.candidate_id for p in packets}),
            )
        )
        titles = {row.id: row.title for row in rows}

    now = datetime.now(UTC).replace(tzinfo=None)
    report: list[dict[str, Any]] = []
    for packet in packets:
        old = dict(packet.public_safety or {})
        fresh = await scan_packet_safety(
            db,
            workspace_id,
            stored_safety_fields(packet),
            candidate_id=packet.candidate_id,
            citations=packet.citations_private,
        )
        becomes_ready = status_for_safety(fresh) == "ready"
        if not becomes_ready:
            action = "stays draft"
        elif apply:
            action = "flipped to ready"
        else:
            action = "would flip to ready"
        if apply and becomes_ready:
            verdict = dict(fresh)
            # The writer's own self-check describes the same text, so it stays.
            if "model_self_check" in old:
                verdict["model_self_check"] = old["model_self_check"]
            verdict["rescanned"] = {
                "at": now.isoformat(),
                "by": SOURCE,
                "previous_status": old.get("status"),
                "previous_issues": list(old.get("issues") or []),
            }
            # Only while it is still a draft. The app keeps running during the
            # scan: an accepted edit or an export can mark this row superseded or
            # exported in the meantime, and a plain write put "ready" over that
            # (review, 28-Sep-2026).
            flipped = await db.execute(
                update(RecordingPacket)
                .where(
                    RecordingPacket.id == packet.id,
                    RecordingPacket.workspace_id == workspace_id,
                    RecordingPacket.status == "draft",
                )
                .values(public_safety=verdict, status="ready", updated_at=now)
                .execution_options(synchronize_session="fetch")
            )
            if flipped.rowcount == 0:
                action = "changed since read, skipped"
        report.append(
            {
                "packet_id": str(packet.id),
                "candidate_id": str(packet.candidate_id),
                "title": titles.get(packet.candidate_id, "(missing topic)"),
                "version": packet.version,
                "old_status": old.get("status"),
                "old_issues": _flags(old.get("issues")),
                "new_status": fresh.get("status"),
                "new_issues": _flags(fresh.get("issues")),
                "action": action,
            }
        )
    if apply:
        await db.commit()
    return report


def _print(report: list[dict[str, Any]], apply: bool) -> None:
    if not report:
        print("no drafts in this workspace")
        return
    for row in report:
        print(f"\nv{row['version']} {row['title']}  (packet {row['packet_id']})")
        old = "; ".join(f"{i['kind']}: {i['match']}" for i in row["old_issues"]) or "none"
        print(f"  old scan ({row['old_status']}): {old}")
        new = "; ".join(f"{i['kind']}: {i['match']}" for i in row["new_issues"]) or "none"
        print(f"  scan now ({row['new_status']}): {new}")
        print(f"  -> {row['action']}")
    flips = sum(1 for row in report if row["action"] in ("flipped to ready", "would flip to ready"))
    if apply:
        print(f"\n{flips} of {len(report)} drafts are ready now")
    else:
        print(f"\n{flips} of {len(report)} drafts would become ready. Re-run with --apply.")


async def main(workspace_id: uuid.UUID, apply: bool) -> None:
    async with async_session() as db:
        _print(await rescan(db, workspace_id, apply=apply), apply)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(uuid.UUID(args.workspace_id), args.apply))
