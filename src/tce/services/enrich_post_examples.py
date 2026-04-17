"""Layer 1 of the TJ grounding stack: LLM classifier that enriches
PostExample rows with hook_type / body_structure / story_arc /
tension_type / cta_type / topic_cluster.

Input: 269 imported TJ posts have raw hook_text + body_text but NULL on
every structured classification field. Without these fields, layers 2-4
(trend_scout grounding, strategist grounding, writer RAG) have nothing
to retrieve or filter on.

Classifier taxonomy is grounded in TJ's own
corpus/tj_robertson/deliverable_5_deep_analysis.md. The 7 hook formulas
come straight from that file. body_structure / story_arc / tension_type
are coarse buckets that cover TJ's patterns without being so fine-grained
the classifier can't pick one.

Run:
    python -m tce.services.enrich_post_examples \
        --creator "TJ Robertson" \
        --batch 5

Idempotent: skips posts with hook_type already set. Use --force to
re-classify everything. Use --limit N for a sanity-check run before
committing to the full pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import anthropic
import structlog
from sqlalchemy import and_, or_, select

from tce.db.session import async_session
from tce.models.creator_profile import CreatorProfile
from tce.models.post_example import PostExample
from tce.settings import settings

logger = structlog.get_logger()


CLASSIFIER_SYSTEM = """\
You are a content pattern classifier. Given a social media post (caption +
transcript + engagement metrics), tag it across 6 orthogonal dimensions.

The taxonomy is grounded in content analysis of @tjrobertsondigital (TJ
Robertson), who posts AI/tech commentary for business owners. Use these
exact taxonomy values - do not invent new ones.

DIMENSION 1: hook_type (the opening pattern)
- crisis_signal     : "Code red at [company]. [Executive] [action]..."
- massive_number    : "The [industry] just [lost/gained] [$X] in [timeframe]..."
- counterintuitive  : "You should absolutely [thing that sounds wrong]..."
- hidden_process    : "[Platform] is [secretly doing X] to your [asset]..."
- paradigm_reframe  : "Your [familiar thing] isn't just for [old purpose] anymore..."
- authority_confirm : "[Company]'s [executive] just confirmed that..."
- patent_reveal     : "[Company] just filed a [patent/doc] that reveals..."
- news_peg          : Opens with a specific recent announcement or launch
- contrarian_setup  : States a common belief then challenges it
- question_hook     : Opens with a question (usually WEAK - low engagement)
- personal_anecdote : Opens with a personal story (usually WEAK - low engagement)
- other             : Doesn't cleanly fit above

DIMENSION 2: body_structure
- staccato_reframe  : Short. Declarative. Sentences. Like. This.
- numbered_list     : "Here are N things..." / enumerated steps
- proof_stack       : Stat + stat + stat building an argument
- narrative_arc     : Story with setup-conflict-resolution
- tactical_howto    : Step-by-step with a concrete outcome
- opinion_rant      : Pure stance, no structure beyond escalation
- inner_monologue   : Thinking-out-loud first-person reflection
- other

DIMENSION 3: story_arc (the emotional journey)
- problem_agitation_solution : PAS - traditional copywriting arc
- reveal_implication         : "Here's what happened... and here's why it matters to you"
- hot_take                   : Stance first, defend second, no resolution
- case_study                 : Specific example -> generalizable lesson
- trend_reaction             : Breaking news + what it changes
- educational                : Teach a concept or skill
- other

DIMENSION 4: tension_type (the friction the post surfaces)
- competitive_threat : "Your competitor is doing X, you're behind"
- hidden_opportunity : "Most people miss this; you can exploit it"
- urgent_pivot       : "Window closing; act now or lose"
- paradigm_shift     : "The rules have changed; old playbook is dead"
- misconception      : "You're probably wrong about X"
- status_gap         : "Winners do X; losers do Y"
- low_or_none        : Informational, no explicit tension

DIMENSION 5: cta_type (what the post asks for)
- comment_keyword : "Comment GUIDE to get..."
- dm_me           : "DM me to..."
- book_call       : "Book a call / strategy session"
- follow          : "Follow for more..."
- implicit        : No explicit ask - just value
- other

DIMENSION 6: topic_cluster (TJ's 3 proven zones + fallbacks)
- ai_competition_dynamics : OpenAI vs Google vs Anthropic, model releases, benchmarks
- website_for_ai_agents   : How AI agents browse sites, MCP, agent-ready infrastructure
- saas_industry_shift     : Software disruption, $ lost, industry pivots
- seo_and_ai_overviews    : Search behavior changing, AI overview optimization
- ai_for_small_business   : Practical AI use by SMBs and solo founders
- ai_workforce_economics  : Layoffs, agent teams, org design with AI
- ai_tooling_reviews      : Specific tool/product walkthroughs
- other_tech_commentary   : Tech commentary not in above buckets

OUTPUT FORMAT (valid JSON array, exactly one object per input post, preserving order):
[
  {
    "id": "<id_from_input>",
    "hook_type": "...",
    "body_structure": "...",
    "story_arc": "...",
    "tension_type": "...",
    "cta_type": "...",
    "topic_cluster": "..."
  },
  ...
]

Respond ONLY with the JSON array. No markdown fences, no commentary.
"""


async def _classify_batch(
    client: anthropic.AsyncAnthropic,
    model: str,
    posts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Classify a batch of posts via one LLM call."""
    user_msg = "Classify these posts:\n\n" + json.dumps(posts, ensure_ascii=False)
    response = await client.messages.create(
        model=model,
        max_tokens=1500 + 300 * len(posts),  # headroom per post
        system=CLASSIFIER_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.2,
    )
    # Response body is a list of ContentBlocks
    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ).strip()
    # Strip markdown fences if the model decided to add them despite instructions
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("enrich.json_parse_failed", error=str(e), text_head=text[:200])
        return []


async def enrich_creator(
    creator_name: str,
    batch_size: int = 5,
    limit: int | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Run the classifier over every non-enriched post for the named creator."""
    stats = {"total": 0, "classified": 0, "skipped": 0, "errors": 0}

    client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value()
    )
    model = "claude-sonnet-4-20250514"

    async with async_session() as db:
        cr_result = await db.execute(
            select(CreatorProfile).where(CreatorProfile.creator_name == creator_name)
        )
        creator = cr_result.scalar_one_or_none()
        if not creator:
            print(f"ERROR: creator '{creator_name}' not found. Run instaiq_import first.")
            return stats

        query = select(PostExample).where(PostExample.creator_id == creator.id)
        if not force:
            query = query.where(
                or_(
                    PostExample.hook_type.is_(None),
                    PostExample.topic_cluster.is_(None),
                )
            )
        if limit:
            query = query.limit(limit)

        result = await db.execute(query)
        posts = list(result.scalars().all())
        stats["total"] = len(posts)
        if not posts:
            print(f"No posts to enrich for {creator_name} (use --force to re-classify)")
            return stats

        # Process in batches
        for i in range(0, len(posts), batch_size):
            batch = posts[i : i + batch_size]
            batch_input = [
                {
                    "id": str(p.id),
                    "hook": (p.hook_text or "")[:500],
                    "body": (p.body_text or p.post_text_raw or "")[:1500],
                    "engagement_rate": p.raw_score,
                    "views": int(p.final_score or 0),
                }
                for p in batch
            ]
            classifications = await _classify_batch(client, model, batch_input)
            by_id = {c.get("id"): c for c in classifications}

            for post in batch:
                c = by_id.get(str(post.id))
                if not c:
                    stats["errors"] += 1
                    continue
                post.hook_type = (c.get("hook_type") or "")[:100] or None
                post.body_structure = (c.get("body_structure") or "")[:100] or None
                post.story_arc = (c.get("story_arc") or "")[:100] or None
                post.tension_type = (c.get("tension_type") or "")[:100] or None
                post.cta_type = (c.get("cta_type") or "")[:100] or None
                post.topic_cluster = (c.get("topic_cluster") or "")[:100] or None
                stats["classified"] += 1
            await db.commit()
            logger.info(
                "enrich.batch_done",
                creator=creator_name,
                batch=i // batch_size + 1,
                total_batches=(len(posts) + batch_size - 1) // batch_size,
            )

    return stats


async def _amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enrich PostExample rows with hook/body/arc classifications")
    parser.add_argument("--creator", required=True, help="Creator display name")
    parser.add_argument("--batch", type=int, default=5, help="Posts per LLM call")
    parser.add_argument("--limit", type=int, default=None, help="Max posts (for test runs)")
    parser.add_argument("--force", action="store_true", help="Re-classify even if fields already set")
    args = parser.parse_args(argv)

    stats = await enrich_creator(
        creator_name=args.creator,
        batch_size=args.batch,
        limit=args.limit,
        force=args.force,
    )
    print(f"Enrichment complete: {stats}")
    return 0 if stats["errors"] == 0 else 1


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
