"""Human review receipts belong to the exact delivered render checked by Jennifer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.models.editorial_workspace import EditingRequest
from tce.models.jennifer import RenderCheck

TRIAL_SIZE = 20
TRIAL_RELEASE = "angel-editing-2026-11-19"


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
    stamp = next(
        (
            (c.result or {}).get("generated_cut")
            for c in checks
            if c.render_ref == ref and (c.result or {}).get("generated_cut")
        ),
        {},
    )
    receipt["first_cut"] = (
        stamp.get("release") == TRIAL_RELEASE
        and stamp.get("first") is True
        and ref == known_first_ref
    )
    if receipt["first_cut"]:
        receipt["trial_release"] = TRIAL_RELEASE
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


NOTE_CLASSES = {"corrective", "creative", "meaning_change", "unclassified"}


async def review_notes(db: AsyncSession, ws: uuid.UUID, uid: uuid.UUID, actor: str) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(RenderCheck)
                .where(
                    RenderCheck.workspace_id == ws,
                    RenderCheck.upload_id == uid,
                    RenderCheck.result["human_reviews"][actor]["at"].as_string().is_not(None),
                )
                .order_by(RenderCheck.created_at, RenderCheck.id)
            )
        )
        .scalars()
        .all()
    )
    classes = _note_classes([(r.result or {})["human_reviews"][actor] for r in rows])
    if not classes:
        return []
    notes = (
        (
            await db.execute(
                select(EditingRequest)
                .where(
                    EditingRequest.workspace_id == ws,
                    EditingRequest.upload_id == uid,
                    EditingRequest.id.in_([uuid.UUID(k) for k in classes]),
                )
                .order_by(EditingRequest.created_at, EditingRequest.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(n.id),
            "request": n.request,
            "classification": classes[str(n.id)],
            "at": n.created_at.isoformat(),
        }
        for n in notes
    ]


def _note_classes(receipts: list[dict]) -> dict[str, str]:
    """One note may appear on more than one receipt. An unlabeled receipt never
    overrides a human classification, including for receipts made before this field existed.
    """
    result = {}
    for receipt in receipts:
        labels = receipt.get("note_classes") or {}
        for key in receipt.get("notes") or []:
            result.setdefault(key, "unclassified")
            if labels.get(key) in NOTE_CLASSES:
                result[key] = labels[key]
    return result


async def classify(
    db: AsyncSession,
    ws: uuid.UUID,
    uid: uuid.UUID,
    actor: str,
    note_id: uuid.UUID,
    classification: str,
) -> bool:
    if classification not in NOTE_CLASSES:
        return False
    # Serialize with record(), including retries and another correction being submitted.
    upload = (
        await db.execute(
            select(RecordingUpload.id)
            .where(RecordingUpload.id == uid, RecordingUpload.workspace_id == ws)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if upload is None:
        return False
    rows = (
        (
            await db.execute(
                select(RenderCheck)
                .where(
                    RenderCheck.workspace_id == ws,
                    RenderCheck.upload_id == uid,
                    RenderCheck.result["human_reviews"][actor]["at"].as_string().is_not(None),
                )
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    key = str(note_id)
    found = False
    for row in rows:
        result = dict(row.result)
        reviewers = dict(result["human_reviews"])
        receipt = dict(reviewers[actor])
        if key not in (receipt.get("notes") or []):
            continue
        found = True
        receipt["note_classes"] = {**(receipt.get("note_classes") or {}), key: classification}
        reviewers[actor] = receipt
        row.result = {**result, "human_reviews": reviewers}
    if found:
        await db.flush()
    return found


def _counts(receipts: list[dict]) -> dict[str, int]:
    values = list(_note_classes(receipts).values())
    severe = values.count("meaning_change")
    return {
        "corrective": values.count("corrective") + severe,
        "creative": values.count("creative"),
        "meaning_changing": severe,
        "unclassified": values.count("unclassified"),
    }


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
    cohort_by_upload = {}
    for uid, receipt in sorted(decisions, key=lambda item: item[1]["at"]):
        if (
            receipt.get("first_cut")
            and receipt.get("trial_release") == TRIAL_RELEASE
            and uid not in cohort_by_upload
            and len(cohort_by_upload) < TRIAL_SIZE
        ):
            cohort_by_upload[uid] = receipt
    titles = {}
    if cohort_by_upload:
        titles = dict(
            (
                await db.execute(
                    select(RecordingUpload.id, TopicCandidate.title)
                    .join(TopicCandidate, TopicCandidate.id == RecordingUpload.candidate_id)
                    .where(
                        RecordingUpload.workspace_id == ws,
                        TopicCandidate.workspace_id == ws,
                        RecordingUpload.id.in_(cohort_by_upload),
                    )
                )
            ).all()
        )
    videos = []
    linked = []
    repeats = set()
    for uid, first in cohort_by_upload.items():
        receipts = [r for key, r in decisions if key == uid]
        linked.extend(receipts)
        for r in receipts:
            repeats.update(r.get("reopened") or [])
        videos.append(
            {
                "upload_id": str(uid),
                "title": titles.get(uid) or "Recording",
                "reviewed_at": first["at"],
                **_counts(receipts),
            }
        )
    totals = _counts(linked)
    unexplained = {
        uid
        for uid, receipt in decisions
        if uid in cohort_by_upload
        and receipt.get("outcome") == "changes"
        and not receipt.get("notes")
    }
    count = len(videos)
    return {
        "reviewed": count,
        "accepted": sum(r.get("outcome") == "accepted" for r in cohort_by_upload.values()),
        "target": TRIAL_SIZE,
        "proposed_acceptances": 18,
        "reopened_after_done": len(repeats),
        "incomplete_checks": sum(not r.get("checks_complete") for r in cohort_by_upload.values()),
        "unexplained_changes": len(unexplained),
        "notes": totals,
        "corrective_per_video": round(totals["corrective"] / count, 2) if count else None,
        "videos": videos,
    }
