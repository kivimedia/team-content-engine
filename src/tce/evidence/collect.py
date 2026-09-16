"""Collection runs with a durable coverage ledger.

Every accessible meeting/repo in the window ends in exactly one item state:
processed, unchanged, updated, excluded, failed, unavailable. A run is `complete`
only when pagination finished and no item failed. Reruns reconcile by
(workspace, source_kind, external_id) and never create duplicates.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tce.evidence import fathom as fathom_mod
from tce.evidence import github as github_mod
from tce.evidence.common import EvidenceHTTPError, as_utc, stable_hash, to_db
from tce.models.editorial import EvidenceCollectionRun, EvidenceMoment, EvidenceSource
from tce.settings import settings

logger = structlog.get_logger()

ITEM_STATES = ("processed", "unchanged", "updated", "excluded", "failed", "unavailable")
FATHOM_KIND = "fathom_meeting"
GITHUB_KIND = "github_commit_group"
RUN_KIND_BY_NAME = {"fathom": FATHOM_KIND, "github": GITHUB_KIND}


def _now() -> datetime:
    return datetime.now(UTC)


class RunLedger:
    """In-memory mirror of one EvidenceCollectionRun, flushed on every activity change."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID):
        self.sessionmaker = sessionmaker
        self.run_id = run_id
        self.counts: Counter[str] = Counter()
        self.items: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.activity: str | None = None

    @classmethod
    async def create_run(
        cls,
        sessionmaker: async_sessionmaker[AsyncSession],
        workspace_id: uuid.UUID,
        source_kind: str,
        window_start: datetime,
        window_end: datetime,
    ) -> uuid.UUID:
        async with sessionmaker() as session:
            run = EvidenceCollectionRun(
                workspace_id=workspace_id,
                source_kind=source_kind,
                window_start=to_db(window_start),
                window_end=to_db(window_end),
                status="running",
                counts={},
                items=[],
                errors=[],
                complete=False,
                current_activity="Queued",
                started_at=to_db(_now()),
            )
            session.add(run)
            await session.commit()
            return run.id

    async def flush(self, **extra: Any) -> None:
        async with self.sessionmaker() as session:
            run = await session.get(EvidenceCollectionRun, self.run_id)
            if run is None:
                return
            run.counts = dict(self.counts)
            run.items = list(self.items)
            run.errors = list(self.errors)
            if self.activity is not None:
                run.current_activity = self.activity[:500]
            for key, value in extra.items():
                setattr(run, key, value)
            await session.commit()

    async def set_activity(self, text: str) -> None:
        self.activity = text
        await self.flush()

    def add_item(self, external_id: str, state: str, reason: str | None = None, **kw: Any):
        assert state in ITEM_STATES, state
        self.counts[state] += 1
        self.items.append({"external_id": external_id, "state": state, "reason": reason, **kw})

    def add_error(self, scope: str, reason: str) -> None:
        self.errors.append({"scope": scope, "reason": reason, "at": _now().isoformat()})

    async def finish(self, *, pagination_finished: bool, fatal: str | None = None) -> str:
        failed_items = self.counts.get("failed", 0)
        complete = fatal is None and pagination_finished and failed_items == 0
        if fatal is not None and not self.items:
            status = "failed"
        elif not complete or self.counts.get("unavailable", 0):
            status = "partial"
        else:
            status = "complete"
        summary = ", ".join(f"{self.counts.get(s, 0)} {s}" for s in ITEM_STATES)
        if fatal:
            self.activity = f"Stopped: {fatal}. {summary}"
        else:
            self.activity = f"Finished ({status}): {summary}"
        await self.flush(status=status, complete=complete, finished_at=to_db(_now()))
        return status


async def upsert_source(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    source_kind: str,
    data: dict[str, Any],
    run_id: uuid.UUID,
) -> tuple[str, EvidenceSource]:
    """Reconcile one source. Returns ("processed"|"updated"|"unchanged", row)."""
    row = (
        await session.execute(
            select(EvidenceSource).where(
                EvidenceSource.workspace_id == workspace_id,
                EvidenceSource.source_kind == source_kind,
                EvidenceSource.external_id == data["external_id"],
            )
        )
    ).scalar_one_or_none()
    now = to_db(_now())
    if row is None:
        row = EvidenceSource(
            workspace_id=workspace_id,
            source_kind=source_kind,
            external_id=data["external_id"],
            title=data.get("title"),
            occurred_at=to_db(data.get("occurred_at")),
            fetched_at=now,
            source_updated_at=now,
            version_hash=data["version_hash"],
            revision=1,
            fetch_status=data.get("fetch_status", "ok"),
            fetch_error=data.get("fetch_error"),
            language=data.get("language"),
            url_private=data.get("url_private"),
            payload_private=data["payload"],
            meta=data.get("meta"),
            last_collection_run_id=run_id,
        )
        session.add(row)
        await session.flush()
        return "processed", row

    row.fetched_at = now
    row.last_collection_run_id = run_id
    row.fetch_status = data.get("fetch_status", "ok")
    row.fetch_error = data.get("fetch_error")
    row.title = data.get("title")
    row.occurred_at = to_db(data.get("occurred_at"))
    row.url_private = data.get("url_private")
    if row.version_hash == data["version_hash"]:
        merged = dict(row.meta or {})
        merged.update(data.get("meta") or {})
        merged.pop("superseded", None)
        row.meta = merged
        return "unchanged", row

    row.version_hash = data["version_hash"]
    row.revision = (row.revision or 1) + 1
    row.source_updated_at = now
    row.payload_private = data["payload"]
    row.language = data.get("language")
    row.meta = data.get("meta")
    await mark_moments_stale(session, workspace_id, row.id)
    return "updated", row


async def mark_moments_stale(
    session: AsyncSession, workspace_id: uuid.UUID, source_id: uuid.UUID
) -> None:
    await session.execute(
        update(EvidenceMoment)
        .where(
            EvidenceMoment.workspace_id == workspace_id,
            EvidenceMoment.source_id == source_id,
            EvidenceMoment.status == "active",
        )
        .values(status="stale")
    )


# ---------------------------------------------------------------------------
# Fathom
# ---------------------------------------------------------------------------


async def collect_fathom(
    sessionmaker: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    *,
    client: fathom_mod.FathomClient | None = None,
    run_id: uuid.UUID | None = None,
) -> uuid.UUID:
    window_start, window_end = as_utc(window_start), as_utc(window_end)
    if run_id is None:
        run_id = await RunLedger.create_run(
            sessionmaker, workspace_id, FATHOM_KIND, window_start, window_end
        )
    ledger = RunLedger(sessionmaker, run_id)
    own_client = client is None
    if client is None:
        key = settings.fathom_api_key.get_secret_value()
        if not key:
            ledger.add_error("config", "Fathom API key is not configured")
            await ledger.finish(pagination_finished=False, fatal="Fathom API key not configured")
            return run_id
        client = fathom_mod.FathomClient(key, settings.fathom_api_base)

    async def on_wait(text: str) -> None:
        await ledger.set_activity(f"Fathom: {text}")

    try:
        await ledger.set_activity("Fathom: requesting meeting list page 1")

        async def on_page(page: int, unique: int) -> None:
            ledger.counts["pages"] = page
            await ledger.set_activity(
                f"Fathom page {page}: {unique} meetings listed, requesting next page"
            )

        try:
            listing = await client.list_meetings(
                window_start, window_end, on_page=on_page, on_wait=on_wait
            )
        except EvidenceHTTPError as exc:
            ledger.add_error("listing", f"meeting listing failed: {exc.reason}")
            await ledger.finish(pagination_finished=False, fatal="Fathom listing failed")
            return run_id

        ledger.counts["pages"] = listing.pages
        ledger.counts["listed"] = listing.listed
        ledger.counts["duplicates_skipped"] = listing.duplicates
        if listing.stop_reason:
            ledger.add_error("pagination", listing.stop_reason)
        in_window = [
            m for m in listing.meetings
            if fathom_mod.meeting_in_window(m, window_start, window_end)
        ]
        ledger.counts["in_window"] = len(in_window)
        ledger.counts["outside_window"] = len(listing.meetings) - len(in_window)
        await ledger.set_activity(
            f"Fathom page {listing.pages}: {len(listing.meetings)} meetings listed, "
            f"{len(in_window)} verified inside the window"
        )

        for idx, item in enumerate(in_window, start=1):
            external_id = fathom_mod.meeting_external_id(item)
            try:
                transcript = item.get("transcript")
                reason = None
                if not transcript:
                    await ledger.set_activity(
                        f"Fathom meeting {idx} of {len(in_window)}: fetching transcript"
                    )
                    transcript, reason = await client.get_transcript(external_id, on_wait)
                await ledger.set_activity(
                    f"Fathom meeting {idx} of {len(in_window)}: normalizing "
                    f"{len(transcript or [])} transcript turns"
                )
                payload = fathom_mod.normalize_meeting(item, transcript)
                data = {
                    "external_id": external_id,
                    "title": payload["title"],
                    "occurred_at": fathom_mod.meeting_started_at(item),
                    "version_hash": stable_hash(payload),
                    "fetch_status": "ok" if transcript else "partial",
                    "fetch_error": None if transcript else reason or "transcript unavailable",
                    "language": payload["language"],
                    "url_private": item.get("share_url") or item.get("url"),
                    "payload": payload,
                    "meta": fathom_mod.meeting_meta(item, payload),
                }
                async with sessionmaker() as session:
                    state, _ = await upsert_source(
                        session, workspace_id, FATHOM_KIND, data, run_id
                    )
                    await session.commit()
                if transcript:
                    ledger.add_item(external_id, state)
                else:
                    ledger.add_item(
                        external_id, "unavailable", data["fetch_error"], upsert=state
                    )
            except Exception as exc:  # recorded per item, never dropped
                logger.warning("evidence.fathom.item_failed", error_type=type(exc).__name__)
                ledger.add_item(external_id, "failed", f"{type(exc).__name__}: {exc}"[:300])
                ledger.add_error(f"meeting:{external_id}", type(exc).__name__)
        await ledger.finish(pagination_finished=listing.pagination_finished)
    except Exception as exc:
        ledger.add_error("run", f"{type(exc).__name__}: {exc}"[:300])
        await ledger.finish(pagination_finished=False, fatal=type(exc).__name__)
    finally:
        if own_client:
            await client.aclose()
    return run_id


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


async def _supersede_old_groups(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    full_name: str,
    window_start: datetime,
    window_end: datetime,
    keep_ids: set[str],
) -> int:
    rows = (
        await session.execute(
            select(EvidenceSource).where(
                EvidenceSource.workspace_id == workspace_id,
                EvidenceSource.source_kind == GITHUB_KIND,
                EvidenceSource.occurred_at >= to_db(window_start),
                EvidenceSource.occurred_at < to_db(window_end),
            )
        )
    ).scalars().all()
    n = 0
    for row in rows:
        if not row.external_id.startswith(f"{full_name}@") or row.external_id in keep_ids:
            continue
        if row.fetch_status == "excluded" and (row.meta or {}).get("superseded"):
            continue
        row.fetch_status = "excluded"
        row.fetch_error = "superseded: commits regrouped on a later collection run"
        row.meta = {**(row.meta or {}), "superseded": True, "exclude_reason": "superseded"}
        await mark_moments_stale(session, workspace_id, row.id)
        n += 1
    return n


async def collect_github(
    sessionmaker: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    *,
    client: github_mod.GitHubClient | None = None,
    run_id: uuid.UUID | None = None,
) -> uuid.UUID:
    window_start, window_end = as_utc(window_start), as_utc(window_end)
    if run_id is None:
        run_id = await RunLedger.create_run(
            sessionmaker, workspace_id, GITHUB_KIND, window_start, window_end
        )
    ledger = RunLedger(sessionmaker, run_id)
    own_client = client is None
    if client is None:
        if not settings.github_pat:
            ledger.add_error("config", "GitHub token is not configured")
            await ledger.finish(pagination_finished=False, fatal="GitHub token not configured")
            return run_id
        client = github_mod.GitHubClient(settings.github_pat)

    async def on_wait(text: str) -> None:
        await ledger.set_activity(f"GitHub rate limit: {text}")

    client.on_wait = on_wait
    try:
        await ledger.set_activity("GitHub: listing accessible repositories")
        try:
            repos, inv_errors = await client.inventory()
        except EvidenceHTTPError as exc:
            ledger.add_error("inventory", f"repository inventory failed: {exc.reason}")
            await ledger.finish(pagination_finished=False, fatal="GitHub inventory failed")
            return run_id
        inventory_complete = not inv_errors
        for err in inv_errors:
            ledger.add_error(err["scope"], err["reason"])
        ledger.counts["repos_listed"] = len(repos)

        for r_idx, repo in enumerate(repos, start=1):
            full = repo["full_name"]
            prefix = f"GitHub {full} {r_idx} of {len(repos)}"
            try:
                await ledger.set_activity(f"{prefix}: listing commits in window")
                listed = await client.list_commits(full, window_start, window_end)
                if listed.state == "empty":
                    ledger.add_item(full, "processed", "empty repository", kind="repo")
                    continue
                if listed.state == "unavailable":
                    ledger.add_item(full, "unavailable", listed.reason, kind="repo")
                    continue
                candidates = [
                    c for c in listed.commits
                    if github_mod.commit_in_window(c, window_start, window_end)
                ]
                ledger.counts["commits_outside_window"] += len(listed.commits) - len(candidates)
                merges = [c for c in candidates if github_mod.is_merge(c)]
                ledger.counts["merge_commits_skipped"] += len(merges)
                candidates = [c for c in candidates if not github_mod.is_merge(c)]
                if not candidates:
                    ledger.add_item(full, "processed", "no commits in window", kind="repo")
                    continue
                records = []
                for c_idx, c in enumerate(candidates, start=1):
                    await ledger.set_activity(
                        f"{prefix}: fetching commit {c_idx} of {len(candidates)}"
                    )
                    detail = await client.get_commit(full, c["sha"])
                    records.append(github_mod.build_commit_record(full, detail))
                ledger.counts["commits_in_window"] += len(records)
                records.sort(key=lambda rec: rec["committed_at"] or "")
                github_mod.detect_reversals(records)
                by_sha = {rec["sha"]: rec for rec in records}
                groups = github_mod.group_commits(records)
                await ledger.set_activity(
                    f"{prefix}: saving {len(groups)} commit groups from {len(records)} commits"
                )
                built = [github_mod.build_group_source(full, g, by_sha) for g in groups]
                group_items = []
                async with sessionmaker() as session:
                    for data in built:
                        data["fetch_status"] = "ok"
                        state, _ = await upsert_source(
                            session, workspace_id, GITHUB_KIND, data, run_id
                        )
                        group_items.append((data, state))
                    superseded = await _supersede_old_groups(
                        session, workspace_id, full, window_start, window_end,
                        {d["external_id"] for d in built},
                    )
                    await session.commit()
                ledger.counts["groups_superseded"] += superseded
                ledger.add_item(
                    full, "processed", f"{len(records)} commits in {len(groups)} groups",
                    kind="repo",
                )
                for data, state in group_items:
                    exclude = data["meta"]["exclude_reason"]
                    if exclude:
                        detail_reason = data["meta"].get("low_signal_reason") or exclude
                        ledger.add_item(
                            data["external_id"], "excluded", detail_reason,
                            kind="group", upsert=state, repo=full,
                        )
                    else:
                        ledger.add_item(data["external_id"], state, kind="group", repo=full)
            except EvidenceHTTPError as exc:
                ledger.add_item(full, "failed", exc.reason, kind="repo")
                ledger.add_error(f"repo:{full}", exc.reason)
            except Exception as exc:
                logger.warning("evidence.github.repo_failed", error_type=type(exc).__name__)
                ledger.add_item(full, "failed", f"{type(exc).__name__}: {exc}"[:300], kind="repo")
                ledger.add_error(f"repo:{full}", type(exc).__name__)
        await ledger.finish(pagination_finished=inventory_complete)
    except Exception as exc:
        ledger.add_error("run", f"{type(exc).__name__}: {exc}"[:300])
        await ledger.finish(pagination_finished=False, fatal=type(exc).__name__)
    finally:
        if own_client:
            await client.aclose()
    return run_id


def coverage_summary(run: EvidenceCollectionRun) -> dict[str, Any]:
    """Counts-only view of a run (safe for logs and the CLI)."""
    return {
        "run_id": str(run.id),
        "source_kind": run.source_kind,
        "status": run.status,
        "complete": run.complete,
        "counts": run.counts,
        "error_count": len(run.errors or []),
        "current_activity": run.current_activity,
    }
