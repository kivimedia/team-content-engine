"""Standing facts: the durable things about the business, written by a person.

Ziv's 21-Sep correction widened what counts as a connection: AI is in scope when
it makes sense for the owners he coaches, or when it applies to Kivi Media's
clients or solutions. Both are true statements about the business that belong to
no particular week, and that is exactly why they were not citable before this
module existed.

A candidate has to cite something. A call is citable (a date, a speaker, a claim
type), a commit is citable (a SHA and a path). "We run receptionist lines for
flower shops" is true all year and has no week, so under the original rule those
two routes could never be cited, and the only way to make them work would have
been to let news candidates cite nothing - the failure the whole lane exists to
prevent.

So a standing fact is an ordinary `EvidenceMoment` on a synthetic
`standing_fact` source, with four constraints that are the whole point:

  written by a person      `extraction_job_id` must be None. A model-written
                           standing fact is an opinion wearing a citation id,
                           which is worse than no citation at all.
  categories, never names  "an AI receptionist answering a shop's phone", not a
                           client. The public-safety scan runs at WRITE time, so
                           a name is caught when it is typed rather than three
                           steps later in a draft.
  never in the week pool   they are injected into the news shard as
                           anchor_context only. Twenty standing facts in the
                           ordinary pool would swamp real calls every week.
  capped support           0.6 in `anchor_support` against 0.9 for a
                           demonstrated commit (applied in the selector, phase
                           5). True but undated should make a candidate
                           possible, not comfortable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from tce.editorial.safety import scan_public_text
from tce.evidence.common import stable_hash
from tce.models.editorial import EvidenceMoment, EvidenceSource

SOURCE_KIND = "standing_fact"

# One synthetic source per workspace holds every standing fact, so they version
# together and a rewrite of the list is one revision rather than N sources.
SOURCE_EXTERNAL_ID = "standing-facts"

# A system Kivi Media runs is demonstrated; a problem Ziv hears is paraphrased.
# Neither is ever `measured`: a standing fact can never support an outcome claim,
# which the selector's invented-outcome check already depends on.
KIND_CLAIM_TYPES = {
    "client_solution": "demonstrated",
    "problem_pattern": "paraphrased",
}


class StandingFactRejectedError(ValueError):
    """A fact that must not be stored, with the reason a person can act on."""


@dataclass(frozen=True)
class StandingFact:
    """One durable fact, as Ziv or the team would write it."""

    anchor_kind: str  # client_solution | problem_pattern
    anchor_term: str  # the matchable phrase
    lesson: str  # what it means, one line
    note: str | None = None  # optional context, private

    def validate(self) -> None:
        if self.anchor_kind not in KIND_CLAIM_TYPES:
            raise StandingFactRejectedError(
                f"anchor_kind must be client_solution or problem_pattern, got {self.anchor_kind!r}"
            )
        if not self.anchor_term.strip():
            raise StandingFactRejectedError("anchor_term is empty; there would be nothing to match")
        if not self.lesson.strip():
            raise StandingFactRejectedError("lesson is empty; the card could not explain itself")

        # Written at the point of entry, not at draft time. A client name typed
        # here would otherwise sit in the index for months before anyone looked.
        scan = scan_public_text({"anchor_term": self.anchor_term, "lesson": self.lesson})
        if scan["status"] != "clean":
            kinds = ", ".join(sorted({i["kind"] for i in scan["issues"]}))
            raise StandingFactRejectedError(
                f"standing facts are written in categories, never specifics: found {kinds}. "
                "Say 'an AI receptionist answering a shop's phone', not the shop."
            )


async def seed_standing_facts(
    session: Any,
    workspace_id: uuid.UUID | str,
    facts: list[StandingFact],
    *,
    author: str = "ziv",
    replace: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write the standing facts for a workspace.

    `replace=True` (the default) is how a corrected list lands: the previous
    moments go `stale` rather than being deleted, so an anchor that pointed at
    one keeps a readable history instead of a dangling id.
    """
    ws = uuid.UUID(str(workspace_id))
    now = now or datetime.now(UTC).replace(tzinfo=None)

    for fact in facts:
        fact.validate()

    terms = [f"{f.anchor_kind}:{normalize_term(f.anchor_term)}" for f in facts]
    if len(set(terms)) != len(terms):
        dupes = sorted({t for t in terms if terms.count(t) > 1})
        raise StandingFactRejectedError(f"the same anchor twice: {', '.join(dupes)}")

    payload = {
        "facts": [
            {
                "anchor_kind": f.anchor_kind,
                "anchor_term": f.anchor_term,
                "lesson": f.lesson,
                "note": f.note,
            }
            for f in facts
        ],
        "author": author,
    }
    version_hash = stable_hash(payload)

    source = (
        await session.execute(
            select(EvidenceSource).where(
                EvidenceSource.workspace_id == ws,
                EvidenceSource.source_kind == SOURCE_KIND,
                EvidenceSource.external_id == SOURCE_EXTERNAL_ID,
            )
        )
    ).scalar_one_or_none()

    if source is None:
        source = EvidenceSource(
            id=uuid.uuid4(),
            workspace_id=ws,
            source_kind=SOURCE_KIND,
            external_id=SOURCE_EXTERNAL_ID,
            title="Standing facts about the business",
            occurred_at=now,
            fetched_at=now,
            version_hash=version_hash,
            revision=1,
            fetch_status="ok",
            payload_private=payload,
            meta={"written_by": author, "kind": "standing_fact"},
        )
        session.add(source)
        await session.flush()
        unchanged = False
    elif source.version_hash == version_hash:
        # Same list, same hash. Do nothing rather than churn revisions, which is
        # what makes the nightly rebuild idempotent.
        unchanged = True
    else:
        source.payload_private = payload
        source.version_hash = version_hash
        source.revision = (source.revision or 1) + 1
        source.fetched_at = now
        source.meta = {**(source.meta or {}), "written_by": author}
        unchanged = False

    if unchanged:
        active = (
            await session.execute(
                select(EvidenceMoment).where(
                    EvidenceMoment.workspace_id == ws,
                    EvidenceMoment.source_id == source.id,
                    EvidenceMoment.status == "active",
                )
            )
        ).scalars().all()
        if len(active) == len(facts):
            return {
                "source_id": str(source.id),
                "written": 0,
                "retired": 0,
                "unchanged": True,
                "detail": f"{len(facts)} standing facts already stored, nothing to do",
            }

    retired = 0
    if replace:
        previous = (
            await session.execute(
                select(EvidenceMoment).where(
                    EvidenceMoment.workspace_id == ws,
                    EvidenceMoment.source_id == source.id,
                    EvidenceMoment.status == "active",
                )
            )
        ).scalars().all()
        for moment in previous:
            moment.status = "stale"
            retired += 1

    for index, fact in enumerate(facts):
        session.add(
            EvidenceMoment(
                id=uuid.uuid4(),
                workspace_id=ws,
                source_id=source.id,
                source_version_hash=version_hash,
                excerpt_private=fact.note or fact.lesson,
                context_private=None,
                lesson_summary=fact.lesson,
                claim_type=KIND_CLAIM_TYPES[fact.anchor_kind],
                speaker=author,
                speaker_confidence="high",
                language="en",
                sensitivity_flags=[],
                status="active",
                # The constraint that keeps this honest: a standing fact has no
                # extraction job because no model wrote it.
                extraction_job_id=None,
                news_ref={
                    "anchor_kind": fact.anchor_kind,
                    "anchor_term": fact.anchor_term,
                    "standing": True,
                    "position": index,
                },
            )
        )

    await session.flush()
    return {
        "source_id": str(source.id),
        "written": len(facts),
        "retired": retired,
        "unchanged": False,
        "detail": (
            f"{len(facts)} standing facts written"
            + (f", {retired} previous ones retired" if retired else "")
        ),
    }


def normalize_term(term: str) -> str:
    from tce.news.anchors import normalize

    return normalize(term)


# The N818 suffix is the lint rule; the short name is what reads in a traceback.
StandingFactRejected = StandingFactRejectedError
