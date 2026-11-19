"""Human review receipts belong to the exact delivered render checked by Jennifer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.editorial import RecordingUpload
from tce.models.editorial_workspace import EditingRequest
from tce.models.jennifer import RenderCheck

TRIAL_SIZE = 20


async def record(
    db: AsyncSession,
    ws: uuid.UUID,
    uid: uuid.UUID,
    ref: str | None,
    actor: str,
    outcome: str,
    notes: list[EditingRequest] | None = None,
    *,
    allow_previous: bool = False,
) -> bool:
    upload = (
        await db.execute(
            select(RecordingUpload)
            .where(RecordingUpload.workspace_id == ws, RecordingUpload.id == uid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if (
        upload is None
        or not upload.edited_path
        or not ref
        or (ref != upload.render_ref and not allow_previous)
    ):
        return False
    checks = (
        (
            await db.execute(
                select(RenderCheck)
                .where(
                    RenderCheck.workspace_id == ws,
                    RenderCheck.upload_id == uid,
                    RenderCheck.state.notin_(("fixing", "released")),
                    RenderCheck.render_ref.is_not(None),
                )
                .order_by(RenderCheck.created_at, RenderCheck.id)
            )
        )
        .scalars()
        .all()
    )
    checked = next((check for check in checks if check.render_ref == ref), None)
    if checked is None:
        return False

    result = dict(checked.result or {})
    reviewers = dict(result.get("human_reviews") or {})
    receipt = dict(reviewers.get(actor) or {})
    # Remember the first decision, and any correction to that same version.
    receipt.setdefault("at", datetime.now(UTC).isoformat())
    # Attach every decision on this ref to the same row. The newest actual measurement
    # available when the reviewer first decided supplies its quality evidence.
    known_first_ref = next(
        (
            c.render_ref
            for c in checks
            if any(r.get("first_cut") for r in (c.result or {}).get("human_reviews", {}).values())
        ),
        checks[0].render_ref,
    )
    receipt["first_cut"] = ref == known_first_ref
    latest = next(c for c in reversed(checks) if c.render_ref == ref)
    gates = (latest.result or {}).get("checks") or {}
    captions = gates.get("captions") or {}
    required = ("captions", "audibility", "loudness", "gaps", "asides")
    complete = (
        latest.state in {"passed", "fixed"}
        and all(k in gates for k in required)
        and all(check.get("state") == "pass" for check in gates.values())
        and (gates.get("audibility") or {}).get("listened") is True
        and captions.get("playback_state") == "pass"
        and (captions.get("frames") or {}).get("state") == "pass"
    )
    receipt.setdefault("checks_complete", complete)
    if receipt.get("outcome") != "changes":
        receipt["outcome"] = outcome
    receipt["last_outcome"] = outcome
    notes = [note for note in notes or [] if note.request and note.request.strip()]
    if notes:
        ids = set(receipt.get("notes", []))
        reopened = set(receipt.get("reopened", []))
        previous = (
            (
                await db.execute(
                    select(EditingRequest).where(
                        EditingRequest.workspace_id == ws,
                        EditingRequest.upload_id == uid,
                        EditingRequest.state == "done",
                    )
                )
            )
            .scalars()
            .all()
        )
        for note in notes:
            ids.add(str(note.id))
            if note.request.casefold().startswith("about my earlier note"):
                if any(
                    p.id != note.id
                    and p.request
                    and p.resolved_at
                    and note.created_at
                    and p.resolved_at <= note.created_at
                    and '"' + p.request.strip().casefold() + '"' in note.request.casefold()
                    for p in previous
                ):
                    reopened.add(str(note.id))
        receipt.update(notes=sorted(ids), reopened=sorted(reopened))
    reviewers[actor] = receipt
    checked.result = {**result, "human_reviews": reviewers}
    await db.flush()
    return True


async def summary(db: AsyncSession, ws: uuid.UUID, actor: str) -> dict:
    rows = (
        (
            await db.execute(
                select(RenderCheck).where(
                    RenderCheck.workspace_id == ws,
                    RenderCheck.result["human_reviews"][actor]["at"].as_string().is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    decisions = [(row.upload_id, row.result["human_reviews"][actor]) for row in rows]
    cohort = sorted(
        ((uid, r) for uid, r in decisions if r.get("first_cut")), key=lambda entry: entry[1]["at"]
    )[:TRIAL_SIZE]
    uploads = {uid for uid, _ in cohort}
    repeats = set().union(*(set(r.get("reopened", [])) for uid, r in decisions if uid in uploads))
    return {
        "reviewed": len(cohort),
        "accepted": sum(r.get("outcome") == "accepted" for _, r in cohort),
        "target": TRIAL_SIZE,
        "reopened_after_done": len(repeats),
        "incomplete_checks": sum(not r.get("checks_complete") for _, r in cohort),
    }
