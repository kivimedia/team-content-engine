"""Build the corpus of how Ziv talks, out of his own calls.

Reads the diarized turns already stored on every Fathom source, groups his
uninterrupted stretches of speech, judges each one, and writes them to
`voice_samples`. Re-runnable: a run is keyed by (source, first turn), so rebuilding
after a filter change updates in place instead of duplicating.

    python scripts/build_voice_corpus.py <workspace_id>
    python scripts/build_voice_corpus.py <workspace_id> --apply
    python scripts/build_voice_corpus.py <workspace_id> --apply --show 5
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tce.db.session import async_session
from tce.editorial import voice_corpus as vc
from tce.models.editorial import EvidenceSource
from tce.models.voice_sample import VoiceSample


async def main(
    workspace_id: uuid.UUID, apply: bool, show: int, words_band: tuple[int, int] | None = None
) -> None:
    async with async_session() as db:
        sources = (
            (
                await db.execute(
                    select(EvidenceSource).where(
                        EvidenceSource.workspace_id == workspace_id,
                        EvidenceSource.source_kind == "fathom_meeting",
                    )
                )
            )
            .scalars()
            .all()
        )
        print(f"{len(sources)} calls")

        runs: list[vc.Run] = []
        for source in sources:
            turns = (source.payload_private or {}).get("turns") or []
            runs.extend(
                vc.build_runs(
                    turns,
                    source_id=source.id,
                    source_title=source.title,
                    occurred_at=source.occurred_at,
                )
            )
        vc.prepare(runs)

        counts = Counter(r.kind for r in runs)
        keep = [r for r in runs if r.kind == "teaching"]
        words = sum(r.word_count for r in keep)
        print(f"{len(runs)} stretches of his speech")
        for kind, n in counts.most_common():
            print(f"  {kind:<16} {n}")
        print(f"kept: {len(keep)} mini speeches, {words:,} words")

        band = keep
        if words_band:
            low, high = words_band
            band = [r for r in keep if low <= r.word_count <= high]
            print(f"{len(band)} of them between {low} and {high} words")
        for run in sorted(band, key=lambda r: r.word_count, reverse=True)[:show]:
            print(f"\n--- {run.word_count} words, {run.source_title} ---")
            print(f"opening: {run.opening}")
            print(run.text[:600])

        if not apply:
            print("\nnothing written. Re-run with --apply.")
            return

        now = datetime.now(UTC).replace(tzinfo=None)
        written = 0
        for run in runs:
            values = {
                "id": uuid.uuid4(),
                "workspace_id": workspace_id,
                "source_id": run.source_id,
                "source_title": run.source_title,
                "occurred_at": run.occurred_at,
                "first_turn_index": run.first_turn_index,
                "turn_count": run.turn_count,
                "start_s": run.start_s,
                "end_s": run.end_s,
                "language": run.language,
                "text": run.text,
                "word_count": run.word_count,
                "opening": run.opening,
                "kind": run.kind,
                "kind_reason": run.kind_reason,
                "keywords": run.keywords,
                "created_at": now,
                "updated_at": now,
            }
            stmt = pg_insert(VoiceSample).values(**values)
            await db.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_voice_samples_source_turn",
                    set_={
                        k: stmt.excluded[k]
                        for k in (
                            "text",
                            "word_count",
                            "opening",
                            "kind",
                            "kind_reason",
                            "keywords",
                            "turn_count",
                            "end_s",
                            "language",
                            "updated_at",
                        )
                    },
                )
            )
            written += 1
        await db.commit()
        print(f"\nwrote {written} rows ({len(keep)} usable)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--show", type=int, default=3)
    parser.add_argument("--words", help="preview only this band, e.g. 120:400")
    args = parser.parse_args()
    band = None
    if args.words:
        low, high = args.words.split(":")
        band = (int(low), int(high))
    asyncio.run(main(uuid.UUID(args.workspace_id), args.apply, args.show, band))
