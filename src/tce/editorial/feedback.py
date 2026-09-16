"""Editorial feedback: versioned preferences, summaries for the selector, calibration.

Learning is kept in three separate lanes:

- source-level: "right source" / "wrong source" (was this evidence worth a topic?)
- angle-level: "right source, change the angle"
- wording-level: phrasing corrections that must not change which topics are picked

A single rejection never becomes an exclusion. Summaries are weighted preferences
the selector may weigh against new evidence; there is no hard exclusion list.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial.common import (
    ORIGIN_CALIBRATION,
    SessionSource,
    coerce_uuid,
    current_week_start,
    open_session,
    week_bounds,
)
from tce.models.editorial import FEEDBACK_KINDS, REJECTION_GATES, EditorialFeedback, TopicCandidate

FEEDBACK_RATINGS = ("publish", "change_angle", "not_for_me")


class FeedbackError(ValueError):
    """Invalid feedback payload."""


class CandidateNotFoundError(LookupError):
    """Candidate does not exist in this workspace."""


def validate_feedback(kind: str, rating: str | None, gate: str | None) -> None:
    if kind not in FEEDBACK_KINDS:
        raise FeedbackError(f"kind must be one of {', '.join(FEEDBACK_KINDS)}")
    if rating is not None and rating not in FEEDBACK_RATINGS:
        raise FeedbackError(f"rating must be one of {', '.join(FEEDBACK_RATINGS)}")
    if kind == "gate_reject":
        if gate not in REJECTION_GATES:
            raise FeedbackError(f"gate_reject needs gate in {', '.join(REJECTION_GATES)}")
    elif gate is not None and gate not in REJECTION_GATES:
        raise FeedbackError(f"gate must be one of {', '.join(REJECTION_GATES)}")


async def next_preference_version(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    current = (
        await session.execute(
            select(func.max(EditorialFeedback.preference_version)).where(
                EditorialFeedback.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()
    return int(current or 0) + 1


async def record_feedback(
    session: AsyncSession,
    workspace_id: uuid.UUID | str,
    candidate_id: uuid.UUID | str,
    *,
    kind: str,
    rating: str | None = None,
    gate: str | None = None,
    note: str | None = None,
    created_by: str | None = None,
    commit: bool = True,
) -> EditorialFeedback:
    """Insert one feedback row. The caller's explicit approve/gate_reject moves a
    proposed candidate to selected/rejected; nothing else changes status."""
    ws = coerce_uuid(workspace_id)
    validate_feedback(kind, rating, gate)
    cand = (
        await session.execute(
            select(TopicCandidate).where(
                TopicCandidate.id == coerce_uuid(candidate_id),
                TopicCandidate.workspace_id == ws,
            )
        )
    ).scalar_one_or_none()
    if cand is None:
        raise CandidateNotFoundError(str(candidate_id))

    now = datetime.now(UTC).replace(tzinfo=None)
    row = EditorialFeedback(
        workspace_id=ws,
        candidate_id=cand.id,
        kind=kind,
        rating=rating,
        gate=gate,
        note=(note or None),
        preference_version=await next_preference_version(session, ws),
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    if cand.status == "proposed":
        if kind == "approve" or (kind == "source" and rating == "publish"):
            cand.status = "selected"
        elif kind == "gate_reject" or rating == "not_for_me":
            cand.status = "rejected"
    if commit:
        await session.commit()
    else:
        await session.flush()
    return row


async def list_feedback(
    session: AsyncSession, workspace_id: uuid.UUID | str, candidate_id: uuid.UUID | str
) -> list[EditorialFeedback]:
    return list(
        (
            await session.execute(
                select(EditorialFeedback)
                .where(
                    EditorialFeedback.workspace_id == coerce_uuid(workspace_id),
                    EditorialFeedback.candidate_id == coerce_uuid(candidate_id),
                )
                .order_by(EditorialFeedback.preference_version)
            )
        )
        .scalars()
        .all()
    )


@dataclass
class FeedbackSummary:
    preference_version: int = 0
    source_positive: list[dict[str, Any]] = field(default_factory=list)
    source_negative: list[dict[str, Any]] = field(default_factory=list)
    angle: list[dict[str, Any]] = field(default_factory=list)
    wording: list[dict[str, Any]] = field(default_factory=list)
    gate_weights: dict[str, float] = field(default_factory=dict)
    notes: list[dict[str, Any]] = field(default_factory=list)
    # Always empty by design: feedback is weighted, never a ban list.
    hard_exclusions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "preference_version": self.preference_version,
            "source_positive": self.source_positive,
            "source_negative": self.source_negative,
            "angle": self.angle,
            "wording": self.wording,
            "gate_weights": self.gate_weights,
            "notes": self.notes,
            "hard_exclusions": self.hard_exclusions,
        }

    def to_prompt_text(self) -> str:
        if not (
            self.source_positive
            or self.source_negative
            or self.angle
            or self.wording
            or self.gate_weights
            or self.notes
        ):
            return "No editor feedback yet."

        def fmt(items: list[dict[str, Any]], limit: int = 12) -> str:
            lines = []
            for it in items[:limit]:
                line = f"- {it['title']} (weight {it['weight']:.2f})"
                if it.get("note"):
                    line += f": {it['note']}"
                lines.append(line)
            return "\n".join(lines) if lines else "- none"

        parts = [
            f"EDITOR PREFERENCES (preference version {self.preference_version}). These are "
            "weighted preferences, not rules. One rejection does not rule out a subject; "
            "new, stronger evidence on the same subject can still be proposed.",
            "SOURCE-LEVEL - right source (evidence like this made good topics):\n"
            + fmt(self.source_positive),
            "SOURCE-LEVEL - wrong source (evidence like this was not worth a topic):\n"
            + fmt(self.source_negative),
            "ANGLE-LEVEL - right source, change the angle (keep the evidence, reframe):\n"
            + fmt(self.angle),
            "WORDING-LEVEL - phrasing corrections (apply to wording only; they do not change "
            "which topics to pick):\n" + fmt(self.wording),
        ]
        if self.gate_weights:
            parts.append(
                "GATE SIGNALS (how often the editor cited each gate, recency weighted):\n"
                + "\n".join(f"- {g}: {w:.2f}" for g, w in sorted(self.gate_weights.items()))
            )
        if self.notes:
            parts.append("EDITOR NOTES:\n" + fmt(self.notes, limit=8))
        return "\n\n".join(parts)


def _recency_weight(index_from_newest: int) -> float:
    # newest feedback weighs 1.0, older decays gently and never reaches zero
    return round(max(0.25, 0.9**index_from_newest), 4)


async def summarize_feedback(
    session: AsyncSession, workspace_id: uuid.UUID | str, *, limit: int = 200
) -> FeedbackSummary:
    ws = coerce_uuid(workspace_id)
    rows = (
        await session.execute(
            select(EditorialFeedback, TopicCandidate)
            .join(TopicCandidate, TopicCandidate.id == EditorialFeedback.candidate_id)
            .where(EditorialFeedback.workspace_id == ws, TopicCandidate.workspace_id == ws)
            .order_by(EditorialFeedback.preference_version.desc())
            .limit(limit)
        )
    ).all()
    summary = FeedbackSummary()
    if not rows:
        return summary
    summary.preference_version = max(fb.preference_version for fb, _ in rows)

    def item(fb: EditorialFeedback, cand: TopicCandidate, weight: float) -> dict[str, Any]:
        return {
            "title": cand.title,
            "lesson": cand.lesson,
            "origin": cand.origin,
            "rating": fb.rating,
            "note": fb.note,
            "weight": weight,
        }

    for i, (fb, cand) in enumerate(rows):
        w = _recency_weight(i)
        entry = item(fb, cand, w)
        if fb.kind == "wording":
            summary.wording.append(entry)
            continue
        if fb.kind == "angle" or fb.rating == "change_angle":
            summary.angle.append(entry)
        elif fb.kind == "approve" or fb.rating == "publish":
            summary.source_positive.append(entry)
        elif fb.kind == "gate_reject" or fb.rating == "not_for_me":
            summary.source_negative.append(entry)
        elif fb.kind == "note" and fb.note:
            summary.notes.append(entry)
        elif fb.kind == "source" and fb.note:
            summary.notes.append(entry)
        if fb.gate:
            summary.gate_weights[fb.gate] = round(summary.gate_weights.get(fb.gate, 0.0) + w, 4)
    return summary


# ---------------------------------------------------------------------------
# Calibration seeding (private JSON lives outside the repository)
# ---------------------------------------------------------------------------

CALIBRATION_FIELDS = (
    "title",
    "lesson",
    "public_angle",
    "audience",
    "source_kind",
    "source_ref",
    "span",
    "note",
)


def validate_calibration_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise FeedbackError("calibration file must contain a JSON list")
    out = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise FeedbackError(f"item {i} is not an object")
        for req in ("title", "lesson", "public_angle"):
            if not str(raw.get(req) or "").strip():
                raise FeedbackError(f"item {i} is missing {req}")
        audience = raw.get("audience") or "both"
        if audience not in ("coaches", "event_owners", "both"):
            audience = "both"
        out.append({k: raw.get(k) for k in CALIBRATION_FIELDS} | {"audience": audience})
    return out


async def seed_calibration(
    source: SessionSource,
    workspace_id: uuid.UUID | str,
    items: list[dict[str, Any]],
    *,
    week_start: date | None = None,
    created_by: str = "calibration",
) -> dict[str, int]:
    """Insert calibration candidates (origin calibration, status selected) with a
    publish rating, for this workspace only. Idempotent on (workspace, title)."""
    ws = coerce_uuid(workspace_id)
    items = validate_calibration_items(items)
    start, _ = week_bounds(week_start or current_week_start())
    inserted = skipped = 0
    async with open_session(source) as session:
        existing = set(
            (
                await session.execute(
                    select(TopicCandidate.title).where(
                        TopicCandidate.workspace_id == ws,
                        TopicCandidate.origin == ORIGIN_CALIBRATION,
                    )
                )
            )
            .scalars()
            .all()
        )
        for it in items:
            title = str(it["title"]).strip()[:300]
            if title in existing:
                skipped += 1
                continue
            now = datetime.now(UTC).replace(tzinfo=None)
            cand = TopicCandidate(
                workspace_id=ws,
                week_start=start,
                moment_ids=[],
                title=title,
                lesson=str(it["lesson"]).strip(),
                audience=it["audience"],
                reasons_to_care=[],
                public_angle=str(it["public_angle"]).strip(),
                public_safety_notes=None,
                gates={
                    g: {"pass": True, "reason": "calibration item accepted by the editor"}
                    for g in REJECTION_GATES
                },
                freshness_role="evergreen",
                citations_private=[
                    {
                        "source_kind": it.get("source_kind"),
                        "source_ref": it.get("source_ref"),
                        "span": it.get("span"),
                        "note": it.get("note"),
                    }
                ],
                status="selected",
                origin=ORIGIN_CALIBRATION,
                created_at=now,
                updated_at=now,
            )
            session.add(cand)
            await session.flush()
            await record_feedback(
                session,
                ws,
                cand.id,
                kind="approve",
                rating="publish",
                note=it.get("note"),
                created_by=created_by,
                commit=False,
            )
            existing.add(title)
            inserted += 1
        await session.commit()
    return {"inserted": inserted, "skipped": skipped}
