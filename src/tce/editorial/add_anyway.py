"""Add anyway: an idea he said, kept on his list although the gates turned it down.

15-Oct-2026, Ziv: "add a add anyway button then", after the four gates rejected an
idea of his twice. The gates still decide every idea the engine finds. This is the
one way past them, and it is narrow on purpose:

- only an idea HE said (a spoken_idea source). A rejection of something the engine
  found in his calls, commits or the news is never offered here;
- it promotes the rejected row the selector already wrote. It never constructs a
  TopicCandidate, so tests/unit/test_no_ungated_topic_source.py still holds;
- the row says so for good: origin owner_override, and the gate's reason is kept
  on it next to who added it and when. No selector run withdraws it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.editorial.common import ORIGIN_OWNER_OVERRIDE, ORIGIN_SELECTOR_REJECTED
from tce.editorial.idea_lane import SPOKEN_KIND
from tce.models.editorial import EvidenceMoment, EvidenceSource, TopicCandidate

TURNED_DOWN_DAYS = 30
SCAN_LIMIT = 300


class AddAnywayError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _moment_uuids(row: TopicCandidate) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for raw in row.moment_ids or []:
        try:
            out.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    return out


async def _spoken_evidence(
    session: AsyncSession, ws: uuid.UUID, moment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[EvidenceMoment, EvidenceSource]]:
    """The moments among these that are his own spoken ideas, with their source."""
    if not moment_ids:
        return {}
    pairs = (
        await session.execute(
            select(EvidenceMoment, EvidenceSource)
            .join(EvidenceSource, EvidenceSource.id == EvidenceMoment.source_id)
            .where(
                EvidenceMoment.workspace_id == ws,
                EvidenceMoment.id.in_(moment_ids),
                EvidenceSource.source_kind == SPOKEN_KIND,
            )
        )
    ).all()
    return {m.id: (m, s) for m, s in pairs}


def _rejection(row: TopicCandidate) -> dict[str, Any]:
    gates = row.gates if isinstance(row.gates, dict) else {}
    rej = gates.get("_rejection")
    return rej if isinstance(rej, dict) else {}


def _gate_words(gate: str | None) -> str:
    gate = str(gate or "").replace("_", " ").strip()
    return "" if gate in ("", "unspecified") else gate


def _idea_of(source: EvidenceSource) -> tuple[str, str | None]:
    payload = source.payload_private if isinstance(source.payload_private, dict) else {}
    idea = str(payload.get("idea") or source.title or "").strip()
    angle = str(payload.get("angle") or "").strip() or None
    return idea, angle


async def turned_down(
    session: AsyncSession, ws: uuid.UUID, *, days: int = TURNED_DOWN_DAYS
) -> list[dict[str, Any]]:
    """His own ideas the gates turned down lately, newest first, one per idea said."""
    since = _now() - timedelta(days=days)
    rows = (
        (
            await session.execute(
                select(TopicCandidate)
                .where(
                    TopicCandidate.workspace_id == ws,
                    TopicCandidate.origin == ORIGIN_SELECTOR_REJECTED,
                    TopicCandidate.status == "rejected",
                    TopicCandidate.created_at >= since,
                )
                .order_by(TopicCandidate.created_at.desc())
                .limit(SCAN_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    ids = [i for r in rows for i in _moment_uuids(r)]
    spoken = await _spoken_evidence(session, ws, ids)
    out: list[dict[str, Any]] = []
    seen_sources: set[uuid.UUID] = set()
    for row in rows:
        pair = next((spoken[i] for i in _moment_uuids(row) if i in spoken), None)
        if pair is None or pair[1].id in seen_sources:
            continue
        seen_sources.add(pair[1].id)
        idea, angle = _idea_of(pair[1])
        rej = _rejection(row)
        out.append(
            {
                "candidate_id": str(row.id),
                "idea": idea,
                "angle": angle,
                "gate": _gate_words(rej.get("gate")),
                "reason": str(rej.get("reason") or row.editor_notes or "").strip(),
                "said_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return out


def _citation(moment: EvidenceMoment, source: EvidenceSource) -> dict[str, Any]:
    # The same shape selector._citation writes, so lists and scripts read it alike.
    return {
        "moment_id": str(moment.id),
        "source_id": str(source.id),
        "source_kind": source.source_kind,
        "source_title": source.title,
        "occurred_at": source.occurred_at.isoformat() if source.occurred_at else None,
        "span_start_s": moment.span_start_s,
        "span_end_s": moment.span_end_s,
        "code_refs": moment.code_refs,
        "url_private": source.url_private,
        "claim_type": moment.claim_type,
        "speaker": moment.speaker,
        "speaker_confidence": moment.speaker_confidence,
        "translation_label": moment.translation_label,
        "language_uncertain": bool(moment.language_uncertain),
        "sensitivity_flags": list(moment.sensitivity_flags or []),
        "excerpt_private": moment.excerpt_private,
    }


async def add_anyway(
    session: AsyncSession, ws: uuid.UUID, candidate_id: uuid.UUID, *, by: str = "ziv"
) -> dict[str, Any]:
    """Put a turned-down idea of his on the Topics list, marked as his override."""
    row = (
        await session.execute(
            select(TopicCandidate).where(
                TopicCandidate.workspace_id == ws, TopicCandidate.id == candidate_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AddAnywayError("not_found", "That idea was not found.", status=404)
    if row.origin == ORIGIN_OWNER_OVERRIDE:
        return {"candidate_id": str(row.id), "title": row.title, "already": True}
    if not (row.origin == ORIGIN_SELECTOR_REJECTED and row.status == "rejected"):
        raise AddAnywayError("not_turned_down", "Only an idea the checks turned down can be added anyway.")
    spoken = await _spoken_evidence(session, ws, _moment_uuids(row))
    pair = next((spoken[i] for i in _moment_uuids(row) if i in spoken), None)
    if pair is None:
        raise AddAnywayError(
            "not_his_idea", "Only an idea you said yourself can be added past the checks."
        )
    moment, source = pair
    idea, angle = _idea_of(source)
    rej = _rejection(row)
    now = _now()
    gates = dict(row.gates) if isinstance(row.gates, dict) else {}
    gates["_override"] = {
        "by": by,
        "at": now.isoformat(),
        "gate": rej.get("gate"),
        "reason": rej.get("reason"),
    }
    gate = _gate_words(rej.get("gate"))
    row.title = idea[:300]
    row.lesson = angle or idea
    row.public_angle = row.public_angle or ""
    row.citations_private = [_citation(moment, source)]
    row.gates = gates
    row.status = "proposed"
    row.origin = ORIGIN_OWNER_OVERRIDE
    row.updated_at = now
    row.editor_notes = (
        f"Added anyway on {now:%d %b %Y}, past the checks."
        + (f" It had not passed the {gate} check: " if gate else " The checks had said: ")
        + str(rej.get("reason") or "").strip()
    )
    await session.commit()
    return {"candidate_id": str(row.id), "title": row.title, "already": False}
