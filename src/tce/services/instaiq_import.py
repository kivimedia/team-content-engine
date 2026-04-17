"""Import InstaIQ deliverable output into TCE as CreatorProfile + PostExample rows.

Run:
    python -m tce.services.instaiq_import \
        --dir corpus/tj_robertson \
        --creator "TJ Robertson" \
        --handle tjrobertsondigital \
        --format walking_monologue

The --dir should be a local copy of an InstaIQ run's output folder containing at
least deliverable_4_chatbot/documents.json. The script is idempotent: re-running
with the same handle updates rows in place (matched by shortcode in
evidence_image_ref) rather than creating duplicates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select

from tce.db.session import async_session
from tce.models.creator_profile import CreatorProfile
from tce.models.post_example import PostExample
from tce.models.source_document import SourceDocument

logger = structlog.get_logger()


def _extract_hook_and_body(doc_text: str) -> tuple[str, str]:
    """Pull the first sentence out of a document as the hook, rest as body.

    InstaIQ documents start with 'Caption:\\n<caption body>\\n...\\nType: ...'.
    We use the caption body as the raw post text and take the first sentence.
    """
    caption_match = re.search(r"Caption:\s*(.+?)(?:\n#|\nType:|\nTopics:|\nSummary:|\Z)", doc_text, re.DOTALL)
    caption = caption_match.group(1).strip() if caption_match else doc_text.strip()
    if not caption:
        return "", ""
    first_sentence_match = re.match(r"(.+?[.!?])(\s|$)", caption, re.DOTALL)
    hook = first_sentence_match.group(1).strip() if first_sentence_match else caption[:200]
    body = caption[len(hook):].strip() if first_sentence_match else caption
    return hook, body


def _confidence_from_engagement(engagement_rate: float | None) -> str:
    """Map InstaIQ engagement % to our A/B/C confidence."""
    if engagement_rate is None:
        return "C"
    if engagement_rate >= 5.0:
        return "A"
    if engagement_rate >= 1.0:
        return "B"
    return "C"


async def import_instaiq_run(
    output_dir: Path,
    creator_name: str,
    handle: str,
    default_format: str,
) -> dict[str, int]:
    """Parse documents.json and upsert CreatorProfile + PostExamples.

    Returns counts: {creator: 0|1, documents: N, inserted: N, updated: N}.
    """
    docs_path = output_dir / "deliverable_4_chatbot" / "documents.json"
    if not docs_path.exists():
        raise FileNotFoundError(f"Missing {docs_path} - is the --dir correct?")

    with docs_path.open(encoding="utf-8") as f:
        payload = json.load(f)

    documents = payload.get("documents") or []
    ids = payload.get("ids") or []
    metadatas = payload.get("metadatas") or []
    if not (len(documents) == len(ids) == len(metadatas)):
        raise ValueError(
            f"Mismatched lengths in documents.json: docs={len(documents)} "
            f"ids={len(ids)} meta={len(metadatas)}"
        )

    counts = {"creator": 0, "documents": len(documents), "inserted": 0, "updated": 0}
    profile_url = f"https://instagram.com/{handle}"
    source_url_tag = f"instaiq:{handle}:{output_dir.name}"

    async with async_session() as db:
        # Upsert CreatorProfile
        result = await db.execute(
            select(CreatorProfile).where(CreatorProfile.creator_name == creator_name)
        )
        creator = result.scalar_one_or_none()
        if creator is None:
            creator = CreatorProfile(
                creator_name=creator_name,
                source_urls=[profile_url],
                style_notes=f"Imported from InstaIQ run {output_dir.name}. See corpus/{output_dir.name}/deliverable_5_deep_analysis.md for hook formulas and style rules.",
                allowed_influence_weight=0.25,
            )
            db.add(creator)
            await db.flush()
            counts["creator"] = 1
            logger.info("instaiq_import.creator_created", id=str(creator.id), name=creator_name)
        else:
            existing_urls = list(creator.source_urls or [])
            if profile_url not in existing_urls:
                existing_urls.append(profile_url)
                creator.source_urls = existing_urls
                await db.flush()

        # One SourceDocument per InstaIQ run (all 269 post_examples link to it)
        result = await db.execute(
            select(SourceDocument).where(SourceDocument.file_name == output_dir.name)
        )
        source_doc = result.scalar_one_or_none()
        if source_doc is None:
            source_doc = SourceDocument(
                file_name=output_dir.name,
                file_type="instaiq",
                language="en",
                notes=f"InstaIQ run for @{handle} -> {counts['documents']} documents.",
                metadata_={"handle": handle, "run_dir": str(output_dir), "source_tag": source_url_tag},
                ingested_at=datetime.utcnow(),
            )
            db.add(source_doc)
            await db.flush()

        # Upsert PostExamples keyed by shortcode (stored in evidence_image_ref)
        for doc_text, doc_id, meta in zip(documents, ids, metadatas):
            shortcode = meta.get("shortcode") or doc_id.replace("post_", "")
            engagement = meta.get("engagement_rate")
            views = meta.get("views") or 0
            video_type = meta.get("video_type")
            hook, body = _extract_hook_and_body(doc_text)
            hook_type = None
            # Rough bucketing: REEL + short hook -> walking_monologue; others default
            fmt = default_format if meta.get("type") == "REEL" else "photo_post"

            result = await db.execute(
                select(PostExample).where(
                    PostExample.creator_id == creator.id,
                    PostExample.evidence_image_ref == shortcode,
                )
            )
            existing = result.scalar_one_or_none()

            fields = dict(
                document_id=source_doc.id,
                creator_id=creator.id,
                post_text_raw=doc_text[:10000],
                hook_text=hook[:2000],
                body_text=body[:8000],
                hook_type=hook_type,
                cta_type=None,
                visual_type="video" if meta.get("type") == "REEL" else "image",
                tone_tags=[video_type] if video_type else None,
                topic_tags=None,
                visible_comments=meta.get("comments") or 0,
                visible_shares=0,
                engagement_confidence=_confidence_from_engagement(engagement),
                evidence_image_ref=shortcode,
                raw_score=float(engagement) if engagement is not None else None,
                final_score=float(views) if views else None,
                template_family=video_type,
                format_label=fmt,
                manual_review_status="auto",
                parser_notes=source_url_tag,
            )

            if existing:
                for key, val in fields.items():
                    setattr(existing, key, val)
                counts["updated"] += 1
            else:
                db.add(PostExample(**fields))
                counts["inserted"] += 1

        await db.commit()

    return counts


async def _amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import InstaIQ run into TCE corpus")
    parser.add_argument("--dir", required=True, help="Path to InstaIQ run directory")
    parser.add_argument("--creator", required=True, help="Creator display name (e.g. 'TJ Robertson')")
    parser.add_argument("--handle", required=True, help="Instagram handle (e.g. 'tjrobertsondigital')")
    parser.add_argument("--format", default="walking_monologue", help="Default format_label for REELs")
    args = parser.parse_args(argv)

    output_dir = Path(args.dir).resolve()
    if not output_dir.exists():
        print(f"ERROR: --dir {output_dir} does not exist")
        return 2

    counts = await import_instaiq_run(
        output_dir=output_dir,
        creator_name=args.creator,
        handle=args.handle,
        default_format=args.format,
    )
    print(f"Import complete: {counts}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
