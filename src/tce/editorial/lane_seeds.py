"""Evergreen lane evidence, written by a person: curated clips and story seeds.

Modelled on `tce.news.standing`: an ordinary `EvidenceMoment` on a synthetic source,
`extraction_job_id` None (no model wrote it), scanned for public safety when it is
written. One source per item so a candidate's citation names the clip it reacts to.

  curated_clip  a real, published magic or mentalism clip: performer, title, year and
                its URL, plus one line on why it plays. Never any method text.
  story_seed    a prompt from a performer's life that HE fills from his own memory.
                Stored as a question; `claim_type` "inferred", so it can never
                support a stated outcome.

Idempotent: the same list writes nothing; a changed item gets a new revision and its
previous moment goes stale; an item dropped from the list goes stale too.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from tce.editorial.safety import scan_public_text
from tce.evidence.common import stable_hash
from tce.models.editorial import EvidenceMoment, EvidenceSource

LANE_KINDS = ("curated_clip", "story_seed")
CLAIM_TYPES = {"curated_clip": "demonstrated", "story_seed": "inferred"}


class LaneItemRejectedError(ValueError):
    """An item that must not be stored, with a reason a person can act on."""


@dataclass(frozen=True)
class LaneItem:
    kind: str  # curated_clip | story_seed
    key: str  # stable id inside the workspace (a URL or a slug)
    title: str
    lesson: str  # what the selector reads: why it plays / the seed question
    url: str | None = None
    language: str = "he"
    meta: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.kind not in LANE_KINDS:
            raise LaneItemRejectedError(f"kind must be one of {LANE_KINDS}, got {self.kind!r}")
        if not self.key.strip() or not self.title.strip() or not self.lesson.strip():
            raise LaneItemRejectedError(
                f"{self.key or '(no key)'}: key, title and lesson are required"
            )
        if self.kind == "curated_clip" and not (self.url or "").startswith("https://"):
            raise LaneItemRejectedError(f"{self.key}: a clip needs its https URL")
        scan = scan_public_text({"title": self.title, "lesson": self.lesson})
        if scan["status"] != "clean":
            kinds = ", ".join(sorted({i["kind"] for i in scan["issues"]}))
            raise LaneItemRejectedError(f"{self.key}: public-safety scan found {kinds}")


def _payload(item: LaneItem) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "key": item.key,
        "title": item.title,
        "lesson": item.lesson,
        "url": item.url,
        "meta": item.meta,
    }


async def seed_lane_items(
    session: Any,
    workspace_id: uuid.UUID | str,
    items: list[LaneItem],
    *,
    author: str,
    now: datetime | None = None,
    retire_missing: bool = True,
) -> dict[str, Any]:
    """Write the items; returns counts {written, unchanged, revised, retired}."""
    ws = uuid.UUID(str(workspace_id))
    now = now or datetime.now(UTC).replace(tzinfo=None)
    for item in items:
        item.validate()
    keys = [(i.kind, i.key) for i in items]
    if len(set(keys)) != len(keys):
        raise LaneItemRejectedError("the same item twice: " + ", ".join(
            sorted({f"{k}:{v}" for k, v in keys if keys.count((k, v)) > 1})))

    kinds = sorted({i.kind for i in items}) or list(LANE_KINDS)
    existing = {
        (s.source_kind, s.external_id): s
        for s in (
            await session.execute(
                select(EvidenceSource).where(
                    EvidenceSource.workspace_id == ws, EvidenceSource.source_kind.in_(kinds)
                )
            )
        ).scalars()
    }
    counts = {"written": 0, "unchanged": 0, "revised": 0, "retired": 0}

    async def active_moments(source_id: uuid.UUID) -> list[EvidenceMoment]:
        return list(
            (
                await session.execute(
                    select(EvidenceMoment).where(
                        EvidenceMoment.workspace_id == ws,
                        EvidenceMoment.source_id == source_id,
                        EvidenceMoment.status == "active",
                    )
                )
            ).scalars()
        )

    for item in items:
        payload = _payload(item)
        digest = stable_hash(payload)
        source = existing.get((item.kind, item.key))
        if source is not None and source.version_hash == digest and await active_moments(source.id):
            counts["unchanged"] += 1
            continue
        if source is None:
            source = EvidenceSource(
                id=uuid.uuid4(),
                workspace_id=ws,
                source_kind=item.kind,
                external_id=item.key,
                title=item.title[:500],
                occurred_at=now,
                fetched_at=now,
                version_hash=digest,
                revision=1,
                fetch_status="ok",
                payload_private=payload,
                url_private=item.url,
                meta={"written_by": author, "kind": item.kind, **item.meta},
            )
            session.add(source)
            await session.flush()
            counts["written"] += 1
        else:
            for moment in await active_moments(source.id):
                moment.status = "stale"
            source.title = item.title[:500]
            source.payload_private = payload
            source.version_hash = digest
            source.revision = (source.revision or 1) + 1
            source.fetched_at = now
            source.url_private = item.url
            source.meta = {**(source.meta or {}), "written_by": author, **item.meta}
            counts["revised"] += 1
        session.add(
            EvidenceMoment(
                id=uuid.uuid4(),
                workspace_id=ws,
                source_id=source.id,
                source_version_hash=digest,
                excerpt_private=item.lesson,
                context_private=item.title,
                lesson_summary=item.lesson,
                claim_type=CLAIM_TYPES[item.kind],
                speaker=author,
                speaker_confidence="high",
                language=item.language,
                sensitivity_flags=[],
                status="active",
                extraction_job_id=None,
            )
        )

    if retire_missing:
        wanted = set(keys)
        for (kind, key), source in existing.items():
            if (kind, key) in wanted:
                continue
            for moment in await active_moments(source.id):
                moment.status = "stale"
                counts["retired"] += 1
    await session.flush()
    return counts
