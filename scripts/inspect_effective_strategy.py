"""Print which strategy sources and active prompt versions are in effect for a workspace.

Run against production to confirm no stale overrides are shaping content:

    python scripts/inspect_effective_strategy.py --workspace-id <uuid>
    python scripts/inspect_effective_strategy.py --workspace-id <uuid> --json

Read-only. Prints the first 200 characters of each override and active prompt, which
may contain private business context: run it in a private terminal, do not paste the
output into public places.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

PREVIEW = 200


def _preview(text: str | None) -> str:
    return (text or "")[:PREVIEW].replace("\n", " ")


async def inspect(session: AsyncSession, workspace_id: uuid.UUID) -> dict[str, Any]:
    from tce.editorial import packets, selector
    from tce.models.prompt_version import PromptVersion
    from tce.models.workspace_context import (
        WorkspacePortfolio,
        WorkspaceStrategy,
        WorkspaceTrendFocus,
    )
    from tce.services.strategy_loader import load_effective_strategy

    report: dict[str, Any] = {"workspace_id": str(workspace_id)}
    eff = await load_effective_strategy(session, workspace_id)
    report["effective_strategy"] = {
        "chars": len(eff.text),
        "sources": eff.sources,
        "preview": _preview(eff.text),
    }

    overrides: dict[str, Any] = {}
    for label, model in (
        ("strategy", WorkspaceStrategy),
        ("portfolio", WorkspacePortfolio),
        ("trend_focus", WorkspaceTrendFocus),
    ):
        try:
            row = (
                await session.execute(select(model).where(model.workspace_id == workspace_id))
            ).scalar_one_or_none()
        except Exception as exc:
            await session.rollback()
            overrides[label] = {"status": "error", "detail": type(exc).__name__}
            continue
        if row is None:
            overrides[label] = None
            continue
        body = getattr(row, "markdown", None)
        if body is None:
            body = json.dumps(getattr(row, "queries", None))
        overrides[label] = {
            "row_id": str(row.id),
            "label": getattr(row, "label", None),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "chars": len(body or ""),
            "preview": _preview(body),
        }
    report["workspace_overrides"] = overrides

    prompts = []
    try:
        rows = (
            (
                await session.execute(
                    select(PromptVersion)
                    .where(PromptVersion.is_active.is_(True))
                    .order_by(PromptVersion.agent_name, PromptVersion.version.desc())
                )
            )
            .scalars()
            .all()
        )
        for p in rows:
            prompts.append(
                {
                    "agent_name": p.agent_name,
                    "version": p.version,
                    "status": p.status,
                    "workspace_id": str(p.workspace_id) if p.workspace_id else None,
                    "chars": len(p.prompt_text or ""),
                    "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                    "preview": _preview(p.prompt_text),
                }
            )
    except Exception as exc:
        await session.rollback()
        prompts = [{"status": "error", "detail": type(exc).__name__}]
    report["active_prompt_versions"] = prompts
    report["code_prompt_versions"] = [
        {"agent_name": selector.AGENT_NAME, "version": selector.PROMPT_VERSION},
        {"agent_name": packets.AGENT_NAME, "version": packets.PROMPT_VERSION},
    ]
    return report


def print_report(report: dict[str, Any]) -> None:
    print(f"Workspace: {report['workspace_id']}")
    eff = report["effective_strategy"]
    print(f"\nEffective strategy: {eff['chars']} chars")
    for src in eff["sources"]:
        print("  - " + ", ".join(f"{k}={v}" for k, v in src.items()))
    print(f"  preview: {eff['preview']}")
    print("\nWorkspace overrides:")
    for label, info in report["workspace_overrides"].items():
        if info is None:
            print(f"  {label}: none")
        else:
            print(f"  {label}: " + ", ".join(f"{k}={v}" for k, v in info.items()))
    print("\nActive prompt_versions (DB):")
    if not report["active_prompt_versions"]:
        print("  none")
    for p in report["active_prompt_versions"]:
        print("  - " + ", ".join(f"{k}={v}" for k, v in p.items()))
    print("\nCode prompt versions (editorial):")
    for p in report["code_prompt_versions"]:
        print(f"  - {p['agent_name']} {p['version']}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args()
    try:
        ws = uuid.UUID(args.workspace_id)
    except ValueError:
        print("invalid --workspace-id", file=sys.stderr)
        return 2

    from tce.db.session import async_session

    async with async_session() as session:
        report = await inspect(session, ws)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
